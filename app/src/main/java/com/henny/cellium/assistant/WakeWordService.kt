package com.henny.cellium.assistant

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.henny.cellium.MainActivity
import com.henny.cellium.R
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.PreferencesStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val TAG = "WakeWordService"
private const val CHANNEL_ID = "cellium_wake_word"
private const val NOTIF_ID = 4108
private const val SAMPLE_RATE = 16000
private const val CHUNK_SAMPLES = 1280 // 80ms @ 16kHz

/**
 * Low-CPU foreground openWakeWord ("Okay Cel") service using exact 1760-sample overlapped LiteRT inference.
 * Releases AudioRecord completely whenever pausedForSession OR screen is off (when wakeWordScreenOnOnly=true)
 * so the Android privacy mic indicator turns off whenever not actively needed.
 * Exposes liveScore StateFlow so Settings can render a real-time wake-word test meter.
 */
class WakeWordService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var listenJob: Job? = null
    private var prefsJob: Job? = null
    private var engine: WakeWordEngine? = null

    @Volatile private var pausedForSession = false
    @Volatile private var isScreenOn = true
    @Volatile private var sensitivityThreshold = 0.25f
    @Volatile private var screenOnOnly = true

    private var screenReceiverRegistered = false
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> isScreenOn = false
                Intent.ACTION_SCREEN_ON, Intent.ACTION_USER_PRESENT -> isScreenOn = true
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        val pm = getSystemService(PowerManager::class.java)
        isScreenOn = pm?.isInteractive ?: true
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_OFF)
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_USER_PRESENT)
        }
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                registerReceiver(screenReceiver, filter, RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("UnspecifiedRegisterReceiverFlag")
                registerReceiver(screenReceiver, filter)
            }
            screenReceiverRegistered = true
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_PAUSE_LISTENING -> {
                pausedForSession = true
                return START_STICKY
            }
            ACTION_RESUME_LISTENING -> {
                pausedForSession = false
                return START_STICKY
            }
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            DevLogBuffer.add("WARN", "WakeWord", "RECORD_AUDIO permission not granted; stopping WakeWordService.")
            stopSelf()
            return START_NOT_STICKY
        }

        startForegroundCompat()
        observePrefsLive()
        startListeningLoop()
        return START_STICKY
    }

    private fun observePrefsLive() {
        if (prefsJob != null) return
        val store = PreferencesStore(applicationContext)
        prefsJob = serviceScope.launch {
            store.preferencesFlow.collectLatest { p ->
                sensitivityThreshold = p.wakeWordSensitivity.coerceIn(0.05f, 0.90f)
                screenOnOnly = p.wakeWordScreenOnOnly
            }
        }
    }

    private fun startForegroundCompat() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Okay Cel Wake Word", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Listening for 'Okay Cel' hands-free wake phrase"
                    setShowBadge(false)
                }
            )
        }
        val openIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stopIntent = PendingIntent.getService(
            this, 1,
            Intent(this, WakeWordService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notif: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_cellium_brand)
            .setContentTitle("Okay Cel Active")
            .setContentText("Say \"Okay Cel\" anytime to summon Floating Cel.")
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(openIntent)
            .addAction(0, "Stop", stopIntent)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    private fun openAudioRecorder(minBuf: Int): AudioRecord? {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        fun trySource(source: Int): AudioRecord? = try {
            val r = AudioRecord(
                source,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                minBuf,
            )
            if (r.state == AudioRecord.STATE_INITIALIZED) r else {
                r.release()
                null
            }
        } catch (_: Throwable) {
            null
        }
        return trySource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            ?: trySource(MediaRecorder.AudioSource.MIC)
    }

    private fun startListeningLoop() {
        listenJob?.cancel()
        listenJob = serviceScope.launch {
            _isRunning.value = true
            val initialPrefs = PreferencesStore(applicationContext).preferencesFlow.first()
            sensitivityThreshold = initialPrefs.wakeWordSensitivity.coerceIn(0.05f, 0.90f)
            screenOnOnly = initialPrefs.wakeWordScreenOnOnly

            val wakeEngine = WakeWordEngine(applicationContext, initialPrefs.wakeWordCustomPath)
            engine = wakeEngine
            if (!wakeEngine.initialize()) {
                DevLogBuffer.add("ERROR", "WakeWord", "Could not initialize openWakeWord TFLite models.")
                _isRunning.value = false
                stopSelf()
                return@launch
            }

            val minBuf = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            ).coerceAtLeast(CHUNK_SAMPLES * 4)

            val pcm = ShortArray(CHUNK_SAMPLES)
            var recorder: AudioRecord? = null
            var lastTriggerMs = 0L
            var lastPeakLogMs = 0L

            fun releaseRecorder() {
                recorder?.let { r ->
                    runCatching { r.stop() }
                    runCatching { r.release() }
                }
                recorder = null
                _liveScore.value = 0f
                _micActive.value = false
            }

            try {
                DevLogBuffer.add("INFO", "WakeWord", "Listening for 'Okay Cel' (threshold=${"%.2f".format(sensitivityThreshold)})")
                while (isActive) {
                    val shouldHoldMic = !pausedForSession && (!screenOnOnly || isScreenOn)
                    if (!shouldHoldMic) {
                        if (recorder != null) {
                            releaseRecorder()
                            wakeEngine.resetState()
                        }
                        delay(300L)
                        continue
                    }

                    if (recorder == null) {
                        val opened = openAudioRecorder(minBuf)
                        if (opened == null) {
                            delay(600L)
                            continue
                        }
                        runCatching { opened.startRecording() }
                            .onFailure {
                                runCatching { opened.release() }
                                delay(600L)
                                continue
                            }
                        recorder = opened
                        _micActive.value = true
                        wakeEngine.resetState()
                    }

                    val activeRec = recorder ?: continue
                    var offset = 0
                    while (offset < CHUNK_SAMPLES && isActive) {
                        if (pausedForSession || (screenOnOnly && !isScreenOn)) break
                        val read = activeRec.read(pcm, offset, CHUNK_SAMPLES - offset)
                        if (read <= 0) break
                        offset += read
                    }
                    if (offset < CHUNK_SAMPLES) {
                        delay(30L)
                        continue
                    }

                    // Feed EVERY 80ms frame continuously (no aggressive RMS drop that clips onset!)
                    val score = wakeEngine.processChunk(pcm)
                    _liveScore.value = score
                    val threshold = sensitivityThreshold
                    val now = System.currentTimeMillis()
                    if (score >= 0.12f && now - lastPeakLogMs > 1800L) {
                        lastPeakLogMs = now
                        DevLogBuffer.add("INFO", "WakeWord", "Score=${"%.2f".format(score)} (threshold=${"%.2f".format(threshold)})")
                    }
                    if (score >= threshold && now - lastTriggerMs > 2400L) {
                        lastTriggerMs = now
                        wakeEngine.resetState()
                        DevLogBuffer.add("INFO", "WakeWord", "Detected 'Okay Cel' (score=${"%.2f".format(score)})")
                        // Immediately release mic before Floating Cel opens STT so AudioRecord never conflicts
                        releaseRecorder()
                        pausedForSession = true
                        FloatingCelOverlayService.start(applicationContext, autoListen = true)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "WakeWord loop error", e)
            } finally {
                releaseRecorder()
                wakeEngine.close()
                _isRunning.value = false
            }
        }
    }

    override fun onDestroy() {
        if (screenReceiverRegistered) {
            runCatching { unregisterReceiver(screenReceiver) }
            screenReceiverRegistered = false
        }
        prefsJob?.cancel()
        listenJob?.cancel()
        engine?.close()
        _liveScore.value = 0f
        _micActive.value = false
        _isRunning.value = false
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val ACTION_STOP = "com.henny.cellium.WAKE_STOP"
        private const val ACTION_PAUSE_LISTENING = "com.henny.cellium.WAKE_PAUSE"
        private const val ACTION_RESUME_LISTENING = "com.henny.cellium.WAKE_RESUME"

        private val _liveScore = MutableStateFlow(0f)
        val liveScore: StateFlow<Float> = _liveScore.asStateFlow()

        private val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()

        private val _micActive = MutableStateFlow(false)
        val micActive: StateFlow<Boolean> = _micActive.asStateFlow()

        fun start(context: Context) {
            val intent = Intent(context, WakeWordService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, WakeWordService::class.java))
        }

        fun setPaused(context: Context, paused: Boolean) {
            runCatching {
                val intent = Intent(context, WakeWordService::class.java).setAction(
                    if (paused) ACTION_PAUSE_LISTENING else ACTION_RESUME_LISTENING
                )
                context.startService(intent)
            }
        }
    }
}

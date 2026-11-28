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
private const val LEGACY_CHANNEL_ID = "cellium_wake_word"
private const val CHANNEL_ID = "cellium_wake_word_silent_v2"
private const val NOTIF_ID = 4108
private const val SAMPLE_RATE = 16000
private const val CHUNK_SAMPLES = 1280 // 80ms @ 16kHz

/**
 * Shared low-CPU openWakeWord ("Okay Cel") audio runner.
 * Hosted natively inside CelliumVoiceInteractionService with ZERO notification when Cellium is
 * the Default Digital Assistant (matching Google Gemini), or hosted by WakeWordService as a
 * minimal silent fallback when Cellium is not set as Default Assistant.
 */
internal class WakeWordLoopController(
    private val appContext: Context,
    private val scope: CoroutineScope,
    private val onWakeDetected: () -> Unit,
    private val onFatalStopped: () -> Unit = {},
) {
    private var listenJob: Job? = null
    private var prefsJob: Job? = null
    private var engine: WakeWordEngine? = null

    @Volatile private var isScreenOn = true
    @Volatile private var sensitivityThreshold = 0.25f
    @Volatile private var screenOnOnly = true
    @Volatile private var customModelPath = ""
    @Volatile private var receiverRegistered = false

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                Intent.ACTION_SCREEN_OFF -> isScreenOn = false
                Intent.ACTION_SCREEN_ON, Intent.ACTION_USER_PRESENT -> isScreenOn = true
            }
        }
    }

    fun start() {
        if (listenJob?.isActive == true) return
        val pm = appContext.getSystemService(PowerManager::class.java)
        isScreenOn = pm?.isInteractive ?: true
        if (!receiverRegistered) {
            val filter = IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_OFF)
                addAction(Intent.ACTION_SCREEN_ON)
                addAction(Intent.ACTION_USER_PRESENT)
            }
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    appContext.registerReceiver(screenReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
                } else {
                    @Suppress("UnspecifiedRegisterReceiverFlag")
                    appContext.registerReceiver(screenReceiver, filter)
                }
                receiverRegistered = true
            }
        }
        observePrefsLive()
        startListeningLoop()
    }

    fun stop() {
        prefsJob?.cancel()
        prefsJob = null
        listenJob?.cancel()
        listenJob = null
        runCatching { engine?.close() }
        engine = null
        if (receiverRegistered) {
            runCatching { appContext.unregisterReceiver(screenReceiver) }
            receiverRegistered = false
        }
        WakeWordService.publishState(running = false, micActive = false, score = 0f)
    }

    private fun observePrefsLive() {
        if (prefsJob?.isActive == true) return
        val store = PreferencesStore(appContext)
        prefsJob = scope.launch {
            store.preferencesFlow.collectLatest { p ->
                sensitivityThreshold = p.wakeWordSensitivity.coerceIn(0.05f, 0.90f)
                screenOnOnly = p.wakeWordScreenOnOnly
                customModelPath = p.wakeWordCustomPath
            }
        }
    }

    private fun openAudioRecorder(minBuf: Int): AudioRecord? {
        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
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
        listenJob = scope.launch {
            WakeWordService.publishState(running = true, micActive = false, score = 0f)
            val initialPrefs = PreferencesStore(appContext).preferencesFlow.first()
            sensitivityThreshold = initialPrefs.wakeWordSensitivity.coerceIn(0.05f, 0.90f)
            screenOnOnly = initialPrefs.wakeWordScreenOnOnly
            customModelPath = initialPrefs.wakeWordCustomPath

            val wakeEngine = WakeWordEngine(appContext, customModelPath)
            engine = wakeEngine
            if (!wakeEngine.initialize()) {
                DevLogBuffer.add("ERROR", "WakeWord", "Could not initialize openWakeWord TFLite models.")
                WakeWordService.publishState(running = false, micActive = false, score = 0f)
                onFatalStopped()
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
                WakeWordService.publishState(running = true, micActive = false, score = 0f)
            }

            try {
                DevLogBuffer.add("INFO", "WakeWord", "Listening for 'Okay Cel' (threshold=${"%.2f".format(sensitivityThreshold)})")
                while (isActive) {
                    val shouldHoldMic = !WakeWordService.isExternallyPaused && (!screenOnOnly || isScreenOn)
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
                        WakeWordService.publishState(running = true, micActive = true, score = 0f)
                        wakeEngine.resetState()
                    }

                    val activeRec = recorder ?: continue
                    var offset = 0
                    while (offset < CHUNK_SAMPLES && isActive) {
                        if (WakeWordService.isExternallyPaused || (screenOnOnly && !isScreenOn)) break
                        val read = activeRec.read(pcm, offset, CHUNK_SAMPLES - offset)
                        if (read <= 0) break
                        offset += read
                    }
                    if (offset < CHUNK_SAMPLES) {
                        delay(30L)
                        continue
                    }

                    val score = wakeEngine.processChunk(pcm)
                    WakeWordService.publishScore(score)
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
                        releaseRecorder()
                        WakeWordService.setPaused(appContext, true)
                        onWakeDetected()
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "WakeWord loop error", e)
            } finally {
                releaseRecorder()
                runCatching { wakeEngine.close() }
                if (engine === wakeEngine) engine = null
                WakeWordService.publishState(running = false, micActive = false, score = 0f)
            }
        }
    }
}

/**
 * Fallback foreground openWakeWord ("Okay Cel") service used ONLY when Cellium is not yet active
 * as Android's Default Digital Assistant. Uses IMPORTANCE_MIN silent channel with deferred
 * presentation so there is zero status-bar icon clutter.
 * When Cellium IS active as Default Digital Assistant, CelliumVoiceInteractionService runs the
 * exact same WakeWordLoopController natively with ZERO foreground notification.
 */
class WakeWordService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var controller: WakeWordLoopController? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        // If CelliumVoiceInteractionService is already bound as Default Assistant, hand off to it
        // so ZERO notification appears in the notification shade!
        if (CelliumVoiceInteractionService.isBoundAsDefaultAssistant()) {
            CelliumVoiceInteractionService.syncWakeWordState(applicationContext)
            stopSelf()
            return START_NOT_STICKY
        }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            DevLogBuffer.add("WARN", "WakeWord", "RECORD_AUDIO permission not granted; stopping WakeWordService.")
            stopSelf()
            return START_NOT_STICKY
        }

        if (!startForegroundCompat()) {
            stopSelf()
            return START_NOT_STICKY
        }

        val runner = controller ?: WakeWordLoopController(
            appContext = applicationContext,
            scope = serviceScope,
            onWakeDetected = {
                if (!CelliumVoiceInteractionService.requestShowSession(fromEarpiece = false)) {
                    FloatingCelOverlayService.start(applicationContext, autoListen = true)
                }
            },
            onFatalStopped = { stopSelf() },
        ).also { controller = it }
        runner.start()
        return START_STICKY
    }

    private fun startForegroundCompat(): Boolean {
        val nm = getSystemService(NotificationManager::class.java)
        runCatching { nm.deleteNotificationChannel(LEGACY_CHANNEL_ID) }
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Voice Standby", NotificationManager.IMPORTANCE_MIN).apply {
                    description = "Silent standby for hands-free voice trigger (zero notification when set as Default Assistant)"
                    setShowBadge(false)
                    setSound(null, null)
                    enableVibration(false)
                    enableLights(false)
                    lockscreenVisibility = Notification.VISIBILITY_SECRET
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
            .setContentTitle("Cel Voice Standby")
            .setContentText("Set Cel as Default Assistant to hide this completely.")
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setVisibility(NotificationCompat.VISIBILITY_SECRET)
            .setOngoing(Build.VERSION.SDK_INT < Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            .setSilent(true)
            .setShowWhen(false)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_DEFERRED)
            .setContentIntent(openIntent)
            .addAction(0, "Stop", stopIntent)
            .build()

        return runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIF_ID, notif, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
            } else {
                startForeground(NOTIF_ID, notif)
            }
            true
        }.onFailure { err ->
            DevLogBuffer.add("WARN", "WakeWord", "Foreground start blocked: ${err.localizedMessage}")
        }.getOrDefault(false)
    }

    override fun onDestroy() {
        controller?.stop()
        controller = null
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val ACTION_STOP = "com.henny.cellium.WAKE_STOP"

        @Volatile
        internal var isExternallyPaused: Boolean = false
            private set

        private val _liveScore = MutableStateFlow(0f)
        val liveScore: StateFlow<Float> = _liveScore.asStateFlow()

        private val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()

        private val _micActive = MutableStateFlow(false)
        val micActive: StateFlow<Boolean> = _micActive.asStateFlow()

        internal fun publishState(running: Boolean, micActive: Boolean, score: Float) {
            _isRunning.value = running
            _micActive.value = micActive
            _liveScore.value = score
        }

        internal fun publishScore(score: Float) {
            _liveScore.value = score
        }

        fun start(context: Context) {
            isExternallyPaused = false
            // Zero-notification native mode when Cellium is active as Default Digital Assistant!
            if (CelliumVoiceInteractionService.isBoundAsDefaultAssistant()) {
                runCatching { context.stopService(Intent(context, WakeWordService::class.java)) }
                CelliumVoiceInteractionService.syncWakeWordState(context.applicationContext)
                return
            }
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                return
            }
            runCatching {
                val intent = Intent(context, WakeWordService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            }.onFailure { err ->
                DevLogBuffer.add("WARN", "WakeWord", "Could not start WakeWordService: ${err.localizedMessage}")
            }
        }

        fun stop(context: Context) {
            isExternallyPaused = false
            CelliumVoiceInteractionService.stopNativeWakeWord()
            runCatching { context.stopService(Intent(context, WakeWordService::class.java)) }
        }

        /**
         * Instant zero-IPC pause/resume shared by both CelliumVoiceInteractionService and
         * WakeWordService. Never calls startService() in the background.
         */
        fun setPaused(@Suppress("UNUSED_PARAMETER") context: Context, paused: Boolean) {
            isExternallyPaused = paused
        }
    }
}

package com.henny.cellium.assistant

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
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
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.sqrt

private const val TAG = "WakeWordService"
private const val CHANNEL_ID = "cellium_wake_word"
private const val NOTIF_ID = 4108
private const val SAMPLE_RATE = 16000
private const val CHUNK_SAMPLES = 1280 // 80ms @ 16kHz

/**
 * Low-CPU foreground AudioRecord service running openWakeWord ("Okay Cel") via LiteRT.
 * Uses an RMS silence pre-gate so TFLite inference is skipped during quiet rooms to save battery.
 */
class WakeWordService : Service() {

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var listenJob: Job? = null
    private var engine: WakeWordEngine? = null
    @Volatile private var pausedForSession = false

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
        startListeningLoop()
        return START_STICKY
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

    private fun startListeningLoop() {
        listenJob?.cancel()
        listenJob = serviceScope.launch {
            val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
            val sensitivity = prefs.wakeWordSensitivity.coerceIn(0.15f, 0.90f)
            val wakeEngine = WakeWordEngine(applicationContext, prefs.wakeWordCustomPath)
            engine = wakeEngine
            if (!wakeEngine.initialize()) {
                DevLogBuffer.add("ERROR", "WakeWord", "Could not initialize openWakeWord TFLite models.")
                stopSelf()
                return@launch
            }

            val minBuf = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            ).coerceAtLeast(CHUNK_SAMPLES * 4)

            fun openRecorder(source: Int): AudioRecord? {
                if (ContextCompat.checkSelfPermission(
                        this@WakeWordService,
                        Manifest.permission.RECORD_AUDIO,
                    ) != PackageManager.PERMISSION_GRANTED
                ) {
                    return null
                }
                return try {
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
                } catch (_: SecurityException) {
                    null
                } catch (_: Throwable) {
                    null
                }
            }

            val recorder = openRecorder(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                ?: openRecorder(MediaRecorder.AudioSource.MIC)

            if (recorder == null) {
                DevLogBuffer.add("ERROR", "WakeWord", "AudioRecord failed to initialize on both VOICE_RECOGNITION and MIC.")
                stopSelf()
                return@launch
            }

            val pcm = ShortArray(CHUNK_SAMPLES)
            // Keep 6-chunk (480ms) pre-roll ring buffer so waking from silence NEVER clips "Okay..."!
            val preRollSize = 6
            val preRoll = Array(preRollSize) { ShortArray(CHUNK_SAMPLES) }
            var preRollIdx = 0
            var preRollCount = 0
            var sleeping = false
            var lastTriggerMs = 0L
            var silentChunks = 0
            var lastPeakLogMs = 0L

            try {
                recorder.startRecording()
                DevLogBuffer.add("INFO", "WakeWord", "Listening for 'Okay Cel' (threshold=${"%.2f".format(sensitivity)})")
                while (isActive) {
                    if (pausedForSession) {
                        delay(250L)
                        continue
                    }
                    var offset = 0
                    while (offset < CHUNK_SAMPLES && isActive) {
                        val read = recorder.read(pcm, offset, CHUNK_SAMPLES - offset)
                        if (read <= 0) break
                        offset += read
                    }
                    if (offset < CHUNK_SAMPLES) {
                        delay(40L)
                        continue
                    }

                    // Energy check with generous pre-roll preservation
                    var sumSq = 0.0
                    for (i in 0 until CHUNK_SAMPLES) {
                        val v = pcm[i].toDouble()
                        sumSq += v * v
                    }
                    val rms = sqrt(sumSq / CHUNK_SAMPLES.toDouble())
                    if (rms < 75.0) {
                        silentChunks++
                        if (silentChunks > 30) {
                            // Store into pre-roll ring while sleeping to save CPU
                            System.arraycopy(pcm, 0, preRoll[preRollIdx], 0, CHUNK_SAMPLES)
                            preRollIdx = (preRollIdx + 1) % preRollSize
                            preRollCount = (preRollCount + 1).coerceAtMost(preRollSize)
                            sleeping = true
                            continue
                        }
                    } else {
                        silentChunks = 0
                        if (sleeping && preRollCount > 0) {
                            // Flush the 480ms pre-roll right before the speech onset!
                            val startIdx = (preRollIdx - preRollCount + preRollSize) % preRollSize
                            for (k in 0 until preRollCount) {
                                wakeEngine.processChunk(preRoll[(startIdx + k) % preRollSize])
                            }
                            preRollCount = 0
                            sleeping = false
                        }
                    }

                    val score = wakeEngine.processChunk(pcm)
                    val now = System.currentTimeMillis()
                    if (score >= 0.14f && now - lastPeakLogMs > 1800L) {
                        lastPeakLogMs = now
                        DevLogBuffer.add("INFO", "WakeWord", "Peak score=${"%.2f".format(score)} (threshold=${"%.2f".format(sensitivity)}, rms=${rms.toInt()})")
                    }
                    if (score >= sensitivity && now - lastTriggerMs > 2500L) {
                        lastTriggerMs = now
                        wakeEngine.resetState()
                        DevLogBuffer.add("INFO", "WakeWord", "Detected 'Okay Cel' (score=${"%.2f".format(score)})")
                        FloatingCelOverlayService.start(applicationContext, autoListen = true)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "WakeWord loop error", e)
            } finally {
                runCatching { recorder.stop() }
                runCatching { recorder.release() }
                wakeEngine.close()
            }
        }
    }

    override fun onDestroy() {
        listenJob?.cancel()
        engine?.close()
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val ACTION_STOP = "com.henny.cellium.WAKE_STOP"
        private const val ACTION_PAUSE_LISTENING = "com.henny.cellium.WAKE_PAUSE"
        private const val ACTION_RESUME_LISTENING = "com.henny.cellium.WAKE_RESUME"

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

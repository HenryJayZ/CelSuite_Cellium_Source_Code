package com.henny.cellium.assistant

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.DisplayMetrics
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.app.NotificationCompat
import com.henny.cellium.MainActivity
import com.henny.cellium.R
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.PreferencesStore
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.data.CustomPersona
import com.henny.cellium.data.local.CelliumDatabase
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.SessionEntity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.UUID
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.sin

private const val OVERLAY_CHANNEL_ID = "cellium_floating_cel"
private const val OVERLAY_NOTIF_ID = 4109

/**
 * Animated dark-red Hell Abyss dismissal zone that appears at the bottom of the screen
 * whenever the user drags Floating Cel. Dropping Cel inside cleanly dismisses the overlay.
 */
private class HellAbyssDismissView(context: Context) : View(context) {
    private var hovering = false
    private val startMs = SystemClock.uptimeMillis()
    private var animRunning = false

    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val vortexPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val emberPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val circleFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val circleStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val crossPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        color = Color.WHITE
    }
    private val labelPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
    }

    private val tickRunnable = object : Runnable {
        override fun run() {
            if (!animRunning) return
            invalidate()
            postDelayed(this, 33L)
        }
    }

    fun setHovering(isHovering: Boolean) {
        if (hovering != isHovering) {
            hovering = isHovering
            invalidate()
        }
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animRunning = true
        post(tickRunnable)
    }

    override fun onDetachedFromWindow() {
        animRunning = false
        removeCallbacks(tickRunnable)
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 4f || h <= 4f) return

        val t = (SystemClock.uptimeMillis() - startMs) / 1000f
        val intensity = if (hovering) 1.0f else 0.72f
        val pulse = 0.5f + 0.5f * sin(t * if (hovering) 8.5f else 4.2f)

        // Deep crimson-black abyss rising from the bottom edge
        bgPaint.shader = LinearGradient(
            0f, 0f, 0f, h,
            intArrayOf(
                Color.TRANSPARENT,
                Color.argb((125 * intensity).toInt(), 90, 8, 18),
                Color.argb((225 * intensity).toInt(), 42, 3, 10),
                Color.argb(245, 18, 2, 6),
            ),
            floatArrayOf(0f, 0.35f, 0.72f, 1f),
            Shader.TileMode.CLAMP,
        )
        canvas.drawRect(0f, 0f, w, h, bgPaint)

        val cx = w * 0.5f
        val cy = h * 0.62f

        // Radial hellfire glow underneath the X target
        val glowRadius = min(w * 0.42f, h * (0.72f + 0.14f * pulse)) * if (hovering) 1.18f else 1f
        emberPaint.shader = RadialGradient(
            cx, cy, glowRadius,
            intArrayOf(
                Color.argb(if (hovering) 220 else 150, 220, 38, 38),
                Color.argb(if (hovering) 110 else 60, 127, 29, 29),
                Color.TRANSPARENT,
            ),
            floatArrayOf(0f, 0.55f, 1f),
            Shader.TileMode.CLAMP,
        )
        canvas.drawCircle(cx, cy, glowRadius, emberPaint)
        emberPaint.shader = null

        // Expanding hellish shockwave rings
        for (i in 0..2) {
            val phase = (t * (if (hovering) 1.15f else 0.65f) + i * 0.33f) % 1f
            val r = h * (0.18f + phase * 0.46f)
            val a = ((1f - phase) * (if (hovering) 190f else 120f)).toInt().coerceIn(0, 220)
            vortexPaint.strokeWidth = if (hovering) 4f else 2.5f
            vortexPaint.color = Color.argb(a, 248, 60, 60)
            canvas.drawCircle(cx, cy, r, vortexPaint)
        }

        // Rising hellfire embers
        for (i in 0..13) {
            val seed = i * 1.73f
            val rise = (t * (0.45f + (i % 4) * 0.16f) + seed) % 1f
            val ex = cx + sin(seed * 3.1f + t * 2.2f) * (w * 0.34f)
            val ey = h - rise * h * 0.92f
            val ea = (sin(rise * PI).toFloat() * (if (hovering) 245f else 180f)).toInt().coerceIn(0, 245)
            emberPaint.color = if (i % 3 == 0) Color.argb(ea, 251, 146, 60) else Color.argb(ea, 239, 68, 68)
            canvas.drawCircle(ex, ey, (2.6f + (i % 3) * 1.6f) * if (hovering) 1.25f else 1f, emberPaint)
        }

        // Crisp glowing dismiss circle + bold X
        val targetR = h * (if (hovering) 0.25f else 0.20f)
        circleFillPaint.color = if (hovering) Color.argb(240, 185, 28, 28) else Color.argb(215, 76, 10, 18)
        canvas.drawCircle(cx, cy, targetR, circleFillPaint)

        circleStrokePaint.strokeWidth = if (hovering) 5.5f else 3.8f
        circleStrokePaint.color = if (hovering) Color.parseColor("#FCA5A5") else Color.parseColor("#EF4444")
        canvas.drawCircle(cx, cy, targetR, circleStrokePaint)

        val xArm = targetR * 0.44f
        crossPaint.strokeWidth = if (hovering) 7.5f else 5.5f
        canvas.drawLine(cx - xArm, cy - xArm, cx + xArm, cy + xArm, crossPaint)
        canvas.drawLine(cx + xArm, cy - xArm, cx - xArm, cy + xArm, crossPaint)

        // Clear label above the target
        labelPaint.textSize = (h * 0.095f).coerceIn(24f, 38f)
        labelPaint.color = if (hovering) Color.parseColor("#FEE2E2") else Color.parseColor("#FCA5A5")
        canvas.drawText(
            if (hovering) "RELEASE TO DISMISS CEL" else "DRAG HERE TO CLOSE",
            cx,
            cy - targetR - 18f,
            labelPaint,
        )
    }
}

/**
 * True System-Wide Floating Cel Overlay (WindowManager TYPE_APPLICATION_OVERLAY).
 * Floats over the Home Screen and EVERY Android app!
 * - Smooth movable animated dot-matrix face
 * - Single-tap to talk; double-tap to toggle Hands-Free continuous mode (with first-time tip)
 * - Living personality: gets bored after ~22s idle -> falls asleep with Zzz after ~48s -> wakes up ANGRY if poked/dragged
 * - Animated dark-red Hell Abyss dismiss zone when dragging Cel
 * - Accurate mic readiness: shows "Starting mic..." until onReadyForSpeech triggers "Listening..."
 * - Full Room memory persistence, active persona sync, and auto Screen Vision prompt when asked to view screen
 */
class FloatingCelOverlayService : Service() {

    private lateinit var wm: WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val llmClient = UniversalLlmClient()

    private var faceContainer: FrameLayout? = null
    private var faceView: AssistantDotFaceView? = null
    private var faceParams: WindowManager.LayoutParams? = null

    private var bubbleView: TextView? = null
    private var bubbleParams: WindowManager.LayoutParams? = null

    private var abyssView: HellAbyssDismissView? = null
    private var abyssParams: WindowManager.LayoutParams? = null
    private var abyssVisible = false
    private var inDismissZone = false

    private var barContainer: LinearLayout? = null
    private var barParams: WindowManager.LayoutParams? = null
    private var screenToggleChip: TextView? = null
    private var inputField: EditText? = null
    private var barVisible = false

    private var speechRecognizer: SpeechRecognizer? = null
    private var cloudSttJob: Job? = null
    private lateinit var celliumTts: CelliumTtsEngine
    private lateinit var celliumStt: CelliumSttEngine
    private var isListening = false
    private var isTalking = false
    private var isThinking = false
    private var isDragging = false
    private var handsFreeEnabled = false
    private var consecutiveSilenceErrors = 0

    // Living idle lifecycle state
    private var lastInteractionMs = SystemClock.uptimeMillis()
    private var isBored = false
    private var isAsleep = false
    private var autoHideBubbleRunnable: Runnable? = null

    // Persistent conversation memory for Floating Cel
    private var floatingSessionId: String? = null
    private var lastFloatingMsgId: String? = null
    private var activeAskJob: Job? = null

    // MediaProjection for Live Screen Vision
    private var mediaProjection: MediaProjection? = null
    private var screenVisionEnabled = false
    private var pendingScreenQuestion: String? = null

    private val boredLines = listOf(
        "*yawn*... getting kinda bored over here...",
        "Hello? Anyone home? Just floating around...",
        "Kinda quiet... tap me if you wanna chat!",
    )

    private val angryWakeLines = listOf(
        "Hey!! I was right in the middle of the best nap!!",
        "Grr! Do you mind?! You just woke me up!",
        "Whoa, rude!! I was sleeping! What do you want?",
        "Hmph! Five more minutes... fine, I'm awake!",
    )

    private val idleTickerRunnable = object : Runnable {
        override fun run() {
            val busy = isListening || isThinking || isTalking || isDragging || barVisible || handsFreeEnabled
            if (!busy && faceContainer != null) {
                val idleSec = (SystemClock.uptimeMillis() - lastInteractionMs) / 1000L
                if (idleSec >= 48L && !isAsleep) {
                    isAsleep = true
                    isBored = false
                    faceView?.updateState(newMood = "sleepy")
                    hideSpeechBubble()
                } else if (idleSec >= 22L && !isBored && !isAsleep) {
                    isBored = true
                    faceView?.updateState(newMood = "bored")
                    showSpeechBubble(boredLines.random(), autoHideMs = 4500L)
                }
            }
            mainHandler.postDelayed(this, 1000L)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WindowManager::class.java)
        initTts()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                dismissFloatingCel(updatePreference = true)
                return START_NOT_STICKY
            }
            ACTION_SET_PROJECTION -> {
                val resCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                val data = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(EXTRA_RESULT_DATA)
                }
                if (resCode == Activity.RESULT_OK && data != null) {
                    startForegroundCompat(withMediaProjection = true)
                    val mpm = getSystemService(MediaProjectionManager::class.java)
                    mediaProjection?.stop()
                    mediaProjection = mpm.getMediaProjection(resCode, data)
                    screenVisionEnabled = true
                    updateScreenVisionChip()
                    val pending = pendingScreenQuestion
                    pendingScreenQuestion = null
                    if (!pending.isNullOrBlank()) {
                        showSpeechBubble("Screen Vision ON — looking now!")
                        mainHandler.postDelayed({ askCel(pending) }, 450L)
                    } else {
                        showSpeechBubble("Screen Vision ON — tap me and ask about what's on screen.", autoHideMs = 4500L)
                    }
                } else {
                    pendingScreenQuestion = null
                }
                return START_STICKY
            }
        }

        if (!Settings.canDrawOverlays(this)) {
            DevLogBuffer.add("WARN", "FloatingCel", "SYSTEM_ALERT_WINDOW permission missing.")
            stopSelf()
            return START_NOT_STICKY
        }

        startForegroundCompat(withMediaProjection = mediaProjection != null)
        val firstCreated = faceContainer == null
        ensureOverlayCreated()

        val autoListen = intent?.getBooleanExtra(EXTRA_AUTO_LISTEN, false) == true
        scope.launch {
            val store = PreferencesStore(applicationContext)
            val prefs = store.preferencesFlow.first()
            faceView?.updateState(newGender = prefs.avatarGender)
            if (firstCreated && !prefs.floatingTipsShown) {
                store.markFloatingTipsShown()
                showSpeechBubble(
                    "Tip: Tap me to talk, double-tap my face for Hands-Free mode, long-press to type, or drag me down to close!",
                    autoHideMs = 7500L,
                )
            } else if (autoListen) {
                mainHandler.postDelayed({ startListening() }, 240L)
            }
        }
        return START_STICKY
    }

    private fun markUserInteraction(resetMoodToIdle: Boolean = false) {
        lastInteractionMs = SystemClock.uptimeMillis()
        isBored = false
        isAsleep = false
        if (resetMoodToIdle && !isListening && !isThinking && !isTalking) {
            faceView?.updateState(newMood = "idle")
        }
    }

    private fun wakeUpAngry(andDrag: Boolean = false) {
        isAsleep = false
        isBored = false
        lastInteractionMs = SystemClock.uptimeMillis()
        vibratePulse(45L)
        val line = angryWakeLines.random()
        faceView?.updateState(newMood = "angry")
        showSpeechBubble(line, autoHideMs = 4500L)
        if (!andDrag) {
            scope.launch {
                val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
                speakOut(line, prefs.ttsEngine, prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate)
            }
        }
        mainHandler.postDelayed({
            if (!isListening && !isThinking && !isTalking && !isDragging && !isAsleep) {
                faceView?.updateState(newMood = "idle")
            }
        }, 4600L)
    }

    private fun vibratePulse(durationMs: Long) {
        runCatching {
            val vib = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                getSystemService(VibratorManager::class.java)?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib?.vibrate(VibrationEffect.createOneShot(durationMs, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vib?.vibrate(durationMs)
            }
        }
    }

    private fun dismissFloatingCel(updatePreference: Boolean) {
        if (updatePreference) {
            scope.launch {
                runCatching { PreferencesStore(applicationContext).updateFloatingMiniCel(false) }
                stopSelf()
            }
        } else {
            stopSelf()
        }
    }

    private fun startForegroundCompat(withMediaProjection: Boolean) {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(OVERLAY_CHANNEL_ID) == null) {
            nm.createNotificationChannel(
                NotificationChannel(OVERLAY_CHANNEL_ID, "Floating Cel", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "System-wide floating Cel companion overlay"
                    setShowBadge(false)
                }
            )
        }
        val openIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stopIntent = PendingIntent.getService(
            this, 2, Intent(this, FloatingCelOverlayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notif: Notification = NotificationCompat.Builder(this, OVERLAY_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_cellium_brand)
            .setContentTitle("Floating Cel Active")
            .setContentText("Tap to talk, double-tap for Hands-Free, drag down to dismiss.")
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(openIntent)
            .addAction(0, "Hide", stopIntent)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val fgsType = if (withMediaProjection) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            } else {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            }
            startForeground(OVERLAY_NOTIF_ID, notif, fgsType)
        } else {
            startForeground(OVERLAY_NOTIF_ID, notif)
        }
    }

    private fun dp(value: Float): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, value, resources.displayMetrics
    ).toInt()

    private fun showAbyssDismissZone() {
        if (abyssVisible) return
        val abyss = abyssView ?: HellAbyssDismissView(this).also { abyssView = it }
        val hPx = dp(164f)
        val params = abyssParams ?: WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            hPx,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
        }.also { abyssParams = it }
        abyss.setHovering(false)
        runCatching {
            wm.addView(abyss, params)
            abyssVisible = true
        }
    }

    private fun hideAbyssDismissZone() {
        if (!abyssVisible) return
        abyssView?.let {
            if (it.isAttachedToWindow) runCatching { wm.removeView(it) }
        }
        abyssVisible = false
        inDismissZone = false
    }

    private fun ensureOverlayCreated() {
        if (faceContainer != null) return
        _isRunning.value = true
        lastInteractionMs = SystemClock.uptimeMillis()

        val sizePx = dp(86f)
        val face = AssistantDotFaceView(this)
        faceView = face

        val container = FrameLayout(this).apply {
            addView(face, FrameLayout.LayoutParams(sizePx, sizePx))
        }
        faceContainer = container

        val params = WindowManager.LayoutParams(
            sizePx,
            sizePx,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = resources.displayMetrics.widthPixels - sizePx - dp(16f)
            y = dp(180f)
        }
        faceParams = params

        // Smooth drag + Hell Abyss dismiss + single-tap talk + double-tap Hands-Free + long-press type bar
        var initX = 0
        var initY = 0
        var downRawX = 0f
        var downRawY = 0f
        var moved = false
        var longPressed = false
        var lastTapUpMs = 0L
        var pendingSingleTap: Runnable? = null

        val longPressRunnable = Runnable {
            if (!moved) {
                longPressed = true
                markUserInteraction()
                vibratePulse(25L)
                toggleBottomChatBar()
            }
        }

        container.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initX = params.x
                    initY = params.y
                    downRawX = event.rawX
                    downRawY = event.rawY
                    moved = false
                    longPressed = false
                    mainHandler.postDelayed(longPressRunnable, 460L)
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downRawX).toInt()
                    val dy = (event.rawY - downRawY).toInt()
                    if (!moved && (abs(dx) > dp(6f) || abs(dy) > dp(6f))) {
                        moved = true
                        isDragging = true
                        mainHandler.removeCallbacks(longPressRunnable)
                        pendingSingleTap?.let { mainHandler.removeCallbacks(it) }
                        if (isAsleep) {
                            wakeUpAngry(andDrag = true)
                        } else {
                            markUserInteraction()
                        }
                        showAbyssDismissZone()
                    }
                    if (moved) {
                        val screenW = resources.displayMetrics.widthPixels
                        val screenH = resources.displayMetrics.heightPixels
                        params.x = (initX + dx).coerceIn(0, screenW - sizePx)
                        params.y = (initY + dy).coerceIn(dp(20f), screenH - sizePx - dp(12f))
                        runCatching { wm.updateViewLayout(container, params) }
                        repositionBubbleBesideFace()

                        val faceCenterY = params.y + sizePx / 2
                        val nowInZone = faceCenterY >= screenH - dp(156f)
                        if (nowInZone != inDismissZone) {
                            inDismissZone = nowInZone
                            abyssView?.setHovering(nowInZone)
                            if (nowInZone) {
                                vibratePulse(35L)
                                faceView?.updateState(newMood = "scared")
                            } else {
                                faceView?.updateState(newMood = "idle")
                            }
                        }
                    }
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    mainHandler.removeCallbacks(longPressRunnable)
                    if (moved) {
                        isDragging = false
                        val shouldDismiss = inDismissZone
                        hideAbyssDismissZone()
                        if (shouldDismiss) {
                            vibratePulse(60L)
                            dismissFloatingCel(updatePreference = true)
                        } else {
                            markUserInteraction(resetMoodToIdle = true)
                        }
                    } else if (!longPressed) {
                        if (isAsleep) {
                            wakeUpAngry(andDrag = false)
                        } else {
                            val now = SystemClock.uptimeMillis()
                            if (now - lastTapUpMs <= 270L) {
                                // Double-tap detected -> Toggle Hands-Free Mode
                                pendingSingleTap?.let { mainHandler.removeCallbacks(it) }
                                pendingSingleTap = null
                                lastTapUpMs = 0L
                                toggleHandsFreeMode()
                            } else {
                                lastTapUpMs = now
                                val single = Runnable {
                                    markUserInteraction()
                                    if (isListening) {
                                        stopListening()
                                    } else {
                                        startListening()
                                    }
                                }
                                pendingSingleTap = single
                                mainHandler.postDelayed(single, 275L)
                            }
                        }
                    }
                    true
                }
                else -> false
            }
        }

        wm.addView(container, params)

        // Floating Speech Bubble right beside Cel (tap to hide!)
        val bubble = TextView(this).apply {
            setTextColor(Color.parseColor("#F5F0FF"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(dp(12f), dp(9f), dp(12f), dp(9f))
            maxWidth = dp(224f)
            background = GradientDrawable().apply {
                setColor(Color.argb(235, 16, 12, 30))
                cornerRadius = dp(16f).toFloat()
                setStroke(dp(1f), Color.argb(175, 192, 132, 252))
            }
            visibility = View.GONE
            setOnClickListener { hideSpeechBubble() }
        }
        bubbleView = bubble
        val bParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = dp(16f)
            y = params.y
        }
        bubbleParams = bParams
        wm.addView(bubble, bParams)

        mainHandler.removeCallbacks(idleTickerRunnable)
        mainHandler.postDelayed(idleTickerRunnable, 1000L)
    }

    private fun toggleHandsFreeMode() {
        markUserInteraction()
        handsFreeEnabled = !handsFreeEnabled
        consecutiveSilenceErrors = 0
        vibratePulse(if (handsFreeEnabled) 40L else 22L)
        faceView?.updateState(isHandsFree = handsFreeEnabled)
        if (handsFreeEnabled) {
            showSpeechBubble(
                "Hands-Free ON — I'll keep listening after I reply! Double-tap my face again to stop.",
                autoHideMs = 4500L,
            )
            if (!isListening && !isThinking && !isTalking) {
                mainHandler.postDelayed({ if (handsFreeEnabled) startListening() }, 700L)
            }
        } else {
            stopListening()
            showSpeechBubble("Hands-Free OFF.", autoHideMs = 2600L)
        }
    }

    private fun repositionBubbleBesideFace() {
        val fParams = faceParams ?: return
        val bParams = bubbleParams ?: return
        val bubble = bubbleView ?: return
        val screenW = resources.displayMetrics.widthPixels
        val faceCenterX = fParams.x + fParams.width / 2
        val placeLeft = faceCenterX > screenW / 2
        bParams.x = if (placeLeft) {
            (fParams.x - dp(232f)).coerceAtLeast(dp(10f))
        } else {
            (fParams.x + fParams.width + dp(8f)).coerceAtMost(screenW - dp(234f))
        }
        bParams.y = fParams.y.coerceIn(dp(28f), resources.displayMetrics.heightPixels - dp(128f))
        if (bubble.isAttachedToWindow) {
            runCatching { wm.updateViewLayout(bubble, bParams) }
        }
    }

    private fun showSpeechBubble(text: String, autoHideMs: Long = 0L) {
        mainHandler.post {
            autoHideBubbleRunnable?.let { mainHandler.removeCallbacks(it) }
            autoHideBubbleRunnable = null
            val bubble = bubbleView ?: return@post
            bubble.text = text
            bubble.visibility = View.VISIBLE
            repositionBubbleBesideFace()
            if (autoHideMs > 0L) {
                val r = Runnable { hideSpeechBubble() }
                autoHideBubbleRunnable = r
                mainHandler.postDelayed(r, autoHideMs)
            }
        }
    }

    private fun hideSpeechBubble() {
        mainHandler.post {
            autoHideBubbleRunnable?.let { mainHandler.removeCallbacks(it) }
            autoHideBubbleRunnable = null
            bubbleView?.visibility = View.GONE
        }
    }

    private fun toggleBottomChatBar() {
        if (barVisible) {
            removeBottomChatBar()
            return
        }
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10f), dp(8f), dp(10f), dp(8f))
            background = GradientDrawable().apply {
                setColor(Color.argb(242, 14, 10, 26))
                cornerRadius = dp(24f).toFloat()
                setStroke(dp(1f), Color.argb(180, 192, 132, 252))
            }
        }

        val screenBtn = TextView(this).apply {
            text = if (screenVisionEnabled) "Eye ON" else "Screen"
            setTextColor(if (screenVisionEnabled) Color.parseColor("#C084FC") else Color.parseColor("#B8AFCF"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnClickListener {
                if (screenVisionEnabled) {
                    screenVisionEnabled = false
                    updateScreenVisionChip()
                    showSpeechBubble("Screen Vision OFF", autoHideMs = 2600L)
                } else if (mediaProjection != null) {
                    screenVisionEnabled = true
                    updateScreenVisionChip()
                    showSpeechBubble("Screen Vision ON", autoHideMs = 2600L)
                } else {
                    AssistantConsentActivity.launchScreenVisionConsent(this@FloatingCelOverlayService)
                }
            }
        }
        screenToggleChip = screenBtn

        val edit = EditText(this).apply {
            hint = "Ask Cel..."
            setHintTextColor(Color.parseColor("#8880A0"))
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            background = null
            isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEND
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnEditorActionListener { _, actionId, _ ->
                if (actionId == EditorInfo.IME_ACTION_SEND) {
                    val q = text.toString().trim()
                    if (q.isNotEmpty()) {
                        setText("")
                        removeBottomChatBar()
                        askCel(q)
                    }
                    true
                } else false
            }
        }
        inputField = edit

        val sendBtn = TextView(this).apply {
            text = "Send"
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            setPadding(dp(12f), dp(7f), dp(12f), dp(7f))
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#A855F7"))
                cornerRadius = dp(16f).toFloat()
            }
            setOnClickListener {
                val q = edit.text.toString().trim()
                if (q.isNotEmpty()) {
                    edit.setText("")
                    removeBottomChatBar()
                    askCel(q)
                }
            }
        }

        val closeBtn = TextView(this).apply {
            text = "X"
            setTextColor(Color.parseColor("#F87171"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(dp(10f), dp(6f), dp(6f), dp(6f))
            setOnClickListener {
                removeBottomChatBar()
                dismissFloatingCel(updatePreference = true)
            }
        }

        row.addView(screenBtn)
        row.addView(edit, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        row.addView(sendBtn)
        row.addView(closeBtn)

        val p = WindowManager.LayoutParams(
            resources.displayMetrics.widthPixels - dp(28f),
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(36f)
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }
        barContainer = row
        barParams = p
        barVisible = true
        runCatching { wm.addView(row, p) }
        edit.requestFocus()
    }

    private fun updateScreenVisionChip() {
        mainHandler.post {
            screenToggleChip?.apply {
                text = if (screenVisionEnabled) "Eye ON" else "Screen"
                setTextColor(if (screenVisionEnabled) Color.parseColor("#C084FC") else Color.parseColor("#B8AFCF"))
            }
        }
    }

    private fun removeBottomChatBar() {
        barContainer?.let {
            if (it.isAttachedToWindow) runCatching { wm.removeView(it) }
        }
        barContainer = null
        barVisible = false
    }

    private fun initTts() {
        celliumTts = CelliumTtsEngine(this)
        celliumStt = CelliumSttEngine(this)
    }

    private fun startListening() {
        if (isThinking) return
        markUserInteraction()
        if (::celliumTts.isInitialized) celliumTts.stop()
        cloudSttJob?.cancel()
        WakeWordService.setPaused(this, true)
        isListening = true
        faceView?.updateState(newMood = "listening", isListening = true, isMicReady = false, isTalking = false)
        showSpeechBubble("Starting mic...")

        scope.launch {
            val prefs = PreferencesStore(this@FloatingCelOverlayService).preferencesFlow.first()
            val sttEngineId = prefs.sttEngine
            if (sttEngineId != CelliumSttEngine.ENGINE_DEVICE) {
                val opt = CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == sttEngineId }
                val db = CelliumDatabase.getInstance(this@FloatingCelOverlayService)
                val providers = withContext(Dispatchers.IO) { db.dao().getAllProviders() }
                val apiKey = prefs.sttApiKey.trim().ifBlank {
                    when (sttEngineId) {
                        CelliumSttEngine.ENGINE_GROQ -> providers.firstOrNull { it.id == "groq" || it.baseUrl.contains("groq.com", true) }?.apiKey.orEmpty()
                        CelliumSttEngine.ENGINE_OPENAI -> providers.firstOrNull { it.id == "openai" || it.baseUrl.contains("api.openai.com", true) }?.apiKey.orEmpty()
                        CelliumSttEngine.ENGINE_HUGGINGFACE -> providers.firstOrNull { it.id == "huggingface" || it.baseUrl.contains("huggingface.co", true) }?.apiKey.orEmpty()
                        else -> ""
                    }
                }
                if (opt?.requiresKey == true && apiKey.isBlank()) {
                    // Fallback gracefully to system recognizer if no key configured
                    startDeviceSpeechRecognizer()
                    return@launch
                }
                cloudSttJob = scope.launch {
                    val res = celliumStt.recordAndTranscribe(
                        engineId = sttEngineId,
                        apiKey = apiKey,
                        modelOverride = prefs.sttModel,
                        onReadyForSpeech = {
                            mainHandler.post {
                                if (isListening) {
                                    faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                    showSpeechBubble("Listening (${opt?.label?.substringBefore(" (") ?: sttEngineId})...")
                                }
                            }
                        },
                        onTranscribing = {
                            mainHandler.post {
                                isListening = false
                                faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                                showSpeechBubble("Transcribing...")
                            }
                        },
                    )
                    isListening = false
                    WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                    res.onSuccess { txt ->
                        consecutiveSilenceErrors = 0
                        askCel(txt)
                    }.onFailure { err ->
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                        if (handsFreeEnabled && (err.localizedMessage?.contains("No speech", true) == true)) {
                            consecutiveSilenceErrors++
                            if (consecutiveSilenceErrors <= 2) {
                                mainHandler.postDelayed({
                                    if (handsFreeEnabled && !isThinking && !isListening && !isTalking) startListening()
                                }, 900L)
                            } else {
                                handsFreeEnabled = false
                                faceView?.updateState(isHandsFree = false)
                                showSpeechBubble("Hands-Free paused (no speech detected).", autoHideMs = 3200L)
                            }
                        } else {
                            showSpeechBubble("STT: ${err.localizedMessage ?: "Failed"}", autoHideMs = 3200L)
                        }
                    }
                }
            } else {
                startDeviceSpeechRecognizer()
            }
        }
    }

    private fun startDeviceSpeechRecognizer() {
        mainHandler.post {
            runCatching {
                speechRecognizer?.destroy()
                val sr = SpeechRecognizer.createSpeechRecognizer(this)
                speechRecognizer = sr
                sr.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        mainHandler.post {
                            if (isListening) {
                                faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                showSpeechBubble("Listening...")
                            }
                        }
                    }
                    override fun onBeginningOfSpeech() = Unit
                    override fun onRmsChanged(rmsdB: Float) = Unit
                    override fun onBufferReceived(buffer: ByteArray?) = Unit
                    override fun onEndOfSpeech() {
                        isListening = false
                        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                    }
                    override fun onError(error: Int) {
                        isListening = false
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                        if (handsFreeEnabled && (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT)) {
                            consecutiveSilenceErrors++
                            if (consecutiveSilenceErrors <= 2) {
                                mainHandler.postDelayed({
                                    if (handsFreeEnabled && !isThinking && !isListening && !isTalking) startListening()
                                }, 900L)
                            } else {
                                handsFreeEnabled = false
                                faceView?.updateState(isHandsFree = false)
                                showSpeechBubble("Hands-Free paused (no speech detected).", autoHideMs = 3200L)
                            }
                        } else {
                            hideSpeechBubble()
                        }
                    }
                    override fun onResults(results: Bundle?) {
                        isListening = false
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                        if (text.isNotEmpty()) {
                            consecutiveSilenceErrors = 0
                            askCel(text)
                        } else {
                            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                            hideSpeechBubble()
                        }
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        val partial = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        if (partial.isNotBlank()) showSpeechBubble("\"$partial\"")
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) = Unit
                })
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                }
                sr.startListening(intent)
            }.onFailure {
                isListening = false
                WakeWordService.setPaused(this, false)
                faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                showSpeechBubble("Long-press me to type instead (mic unavailable).", autoHideMs = 4000L)
            }
        }
    }

    private fun stopListening() {
        isListening = false
        if (::celliumStt.isInitialized) celliumStt.requestStopRecording()
        runCatching { speechRecognizer?.stopListening() }
        WakeWordService.setPaused(this, false)
        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
    }

    private fun asksAboutScreen(text: String): Boolean {
        val lower = text.lowercase()
        val regex = Regex("""\b(see|look at|check|read|describe|watch|what'?s on|whats on|on)\s+(my\s+|the\s+)?screen\b|screen\s*vision""")
        return regex.containsMatchIn(lower)
    }

    private fun captureScreenFrameIfEnabled(): Bitmap? {
        if (!screenVisionEnabled) return null
        val mp = mediaProjection ?: return null
        return runCatching {
            val dm: DisplayMetrics = resources.displayMetrics
            val targetW = (dm.widthPixels / 2).coerceAtLeast(360)
            val targetH = (dm.heightPixels / 2).coerceAtLeast(640)
            val reader = ImageReader.newInstance(targetW, targetH, PixelFormat.RGBA_8888, 2)
            var vd: VirtualDisplay? = null
            try {
                vd = mp.createVirtualDisplay(
                    "CelliumVision",
                    targetW,
                    targetH,
                    dm.densityDpi,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
                    reader.surface,
                    null,
                    null,
                )
                Thread.sleep(160L)
                val img = reader.acquireLatestImage() ?: return@runCatching null
                try {
                    val plane = img.planes[0]
                    val buffer = plane.buffer
                    val pixelStride = plane.pixelStride
                    val rowStride = plane.rowStride
                    val rowPadding = rowStride - pixelStride * targetW
                    val rawBmp = Bitmap.createBitmap(
                        targetW + rowPadding / pixelStride,
                        targetH,
                        Bitmap.Config.ARGB_8888,
                    )
                    rawBmp.copyPixelsFromBuffer(buffer)
                    val cropped = Bitmap.createBitmap(rawBmp, 0, 0, targetW, targetH)
                    if (cropped != rawBmp) rawBmp.recycle()
                    cropped
                } finally {
                    img.close()
                }
            } finally {
                vd?.release()
                reader.close()
            }
        }.getOrNull()
    }

    private fun askCel(userText: String) {
        markUserInteraction()

        // If the user asks Cel to look at their screen and Screen Vision isn't active yet, request consent seamlessly
        if (!screenVisionEnabled && asksAboutScreen(userText)) {
            if (mediaProjection != null) {
                screenVisionEnabled = true
                updateScreenVisionChip()
            } else {
                pendingScreenQuestion = userText
                showSpeechBubble("Tap Allow so I can see your screen — I'll answer right after!", autoHideMs = 6000L)
                AssistantConsentActivity.launchScreenVisionConsent(this)
                return
            }
        }

        isThinking = true
        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
        showSpeechBubble("Thinking...")

        activeAskJob?.cancel()
        activeAskJob = scope.launch {
            try {
                val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
                val dao = CelliumDatabase.getInstance(applicationContext).dao()
                val prov = dao.getProvider(prefs.activeProviderId)
                    ?: dao.getAllProviders().firstOrNull { it.protocol != "on_device" }
                    ?: ProviderPresets.defaultProfiles().first()
                val personas = dao.getAllPersonasOnce().map {
                    CustomPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
                }
                val latestNonArena = dao.getAllSessionsOnce().firstOrNull { !it.isArena }
                val personaId = latestNonArena?.personaId?.ifBlank { prefs.defaultPersonaId } ?: prefs.defaultPersonaId
                val persona = BuiltInPersonas.resolve(personaId, personas)
                val memories = dao.getAllMemoriesOnce()
                val screenBmp = withContext(Dispatchers.IO) { captureScreenFrameIfEnabled() }

                val sid = floatingSessionId ?: UUID.randomUUID().toString().also { newSid ->
                    floatingSessionId = newSid
                    dao.upsertSession(
                        SessionEntity(
                            id = newSid,
                            title = "Floating · ${persona.name}",
                            personaId = persona.id,
                            providerId = prov.id,
                            modelName = prov.selectedModel,
                        )
                    )
                }
                val priorHistory = dao.getMessagesForSessionOnce(sid)
                val userMsgId = UUID.randomUUID().toString()
                dao.upsertMessage(
                    MessageEntity(
                        id = userMsgId,
                        sessionId = sid,
                        parentId = lastFloatingMsgId ?: priorHistory.lastOrNull()?.id,
                        role = "user",
                        content = userText,
                        tokenEstimate = ProviderPresets.estimateTokens(userText),
                    )
                )

                val sysPrompt = llmClient.buildSystemPrompt(
                    persona = persona,
                    memories = memories,
                    agentModeEnabled = false,
                    shizukuConnected = false,
                    moodMethod = prefs.moodMethod,
                    contextConfig = ContextModifyConfig(
                        includePersona = true,
                        includeMemories = true,
                        includeIllumeInstructions = false,
                        includeAgentInstructions = false,
                        includeMoodInstructions = prefs.moodMethod == "inline_tag",
                    ),
                    extraInstruction = "[Floating Assistant] Reply naturally in 1 to 3 short spoken sentences with no markdown formatting. Remember earlier turns in this floating conversation.",
                )

                val sb = StringBuilder()
                val maxRetries = prefs.maxAutoRetries.coerceIn(0, 3)
                var attempt = 0
                while (true) {
                    sb.clear()
                    try {
                        llmClient.streamChat(
                            provider = prov,
                            systemPrompt = sysPrompt,
                            history = priorHistory.takeLast(14),
                            userPrompt = userText,
                            imageBitmap = screenBmp,
                        ).collect { chunk ->
                            if (chunk.contentDelta.isNotEmpty()) {
                                sb.append(chunk.contentDelta)
                                val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                                val (tagMood, body) = MoodDetector.extractInlineMoodTag(clean)
                                if (tagMood != null) faceView?.updateState(newMood = tagMood, newGender = prefs.avatarGender)
                                if (body.isNotBlank()) showSpeechBubble(body)
                            }
                        }
                        break
                    } catch (e: Exception) {
                        if (!UniversalLlmClient.isRetryableError(e) || attempt >= maxRetries) throw e
                        attempt++
                        showSpeechBubble("Busy — retrying ($attempt/$maxRetries)...")
                        delay(1200L * attempt)
                    }
                }
                screenBmp?.recycle()

                val (_, cleanFinal) = ProviderPresets.parseThoughts(sb.toString())
                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(cleanFinal)
                val reply = finalBody.ifBlank { cleanFinal.ifBlank { "I'm right here!" } }
                val mood = tagMood ?: MoodDetector.detectMood(reply)

                val assistantMsgId = UUID.randomUUID().toString()
                lastFloatingMsgId = assistantMsgId
                dao.upsertMessage(
                    MessageEntity(
                        id = assistantMsgId,
                        sessionId = sid,
                        parentId = userMsgId,
                        role = "assistant",
                        speakerLabel = persona.name,
                        content = reply,
                        mood = mood,
                        providerName = prov.name,
                        modelName = prov.selectedModel,
                        tokenEstimate = ProviderPresets.estimateTokens(reply),
                    )
                )
                dao.getSession(sid)?.let { s ->
                    val count = dao.getMessagesForSessionOnce(sid).size
                    dao.upsertSession(
                        s.copy(
                            activeLeafId = assistantMsgId,
                            messageCount = count,
                            lastMessagePreview = reply.take(140),
                            updatedAtMs = System.currentTimeMillis(),
                        )
                    )
                }

                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender)
                showSpeechBubble(reply)
                speakOut(reply, prefs.ttsEngine, prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate)
            } catch (e: Exception) {
                faceView?.updateState(newMood = "error")
                showSpeechBubble("Error: ${e.localizedMessage ?: "Couldn't reach AI"}", autoHideMs = 5000L)
            } finally {
                isThinking = false
                lastInteractionMs = SystemClock.uptimeMillis()
            }
        }
    }

    private fun speakOut(text: String, engine: String, voiceName: String, pitch: Float, rate: Float) {
        if (!::celliumTts.isInitialized) return
        celliumTts.speak(
            rawText = text,
            engine = engine,
            voiceName = voiceName,
            pitch = pitch.coerceIn(0.6f, 1.8f),
            speechRate = rate.coerceIn(0.6f, 1.8f),
            onStart = {
                isTalking = true
                mainHandler.post { faceView?.updateState(isTalking = true) }
            },
            onComplete = {
                isTalking = false
                lastInteractionMs = SystemClock.uptimeMillis()
                mainHandler.post {
                    faceView?.updateState(isTalking = false)
                    if (handsFreeEnabled && !isThinking && !isListening && !isDragging) {
                        mainHandler.postDelayed({
                            if (handsFreeEnabled && !isThinking && !isListening && !isDragging) {
                                startListening()
                            }
                        }, 600L)
                    }
                }
            },
        )
    }

    override fun onDestroy() {
        _isRunning.value = false
        mainHandler.removeCallbacks(idleTickerRunnable)
        autoHideBubbleRunnable?.let { mainHandler.removeCallbacks(it) }
        cloudSttJob?.cancel()
        if (::celliumStt.isInitialized) celliumStt.requestStopRecording()
        hideAbyssDismissZone()
        removeBottomChatBar()
        faceContainer?.let { if (it.isAttachedToWindow) runCatching { wm.removeView(it) } }
        bubbleView?.let { if (it.isAttachedToWindow) runCatching { wm.removeView(it) } }
        runCatching { speechRecognizer?.destroy() }
        if (::celliumTts.isInitialized) runCatching { celliumTts.release() }
        runCatching { mediaProjection?.stop() }
        WakeWordService.setPaused(this, false)
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val ACTION_STOP = "com.henny.cellium.FLOAT_STOP"
        private const val ACTION_SET_PROJECTION = "com.henny.cellium.FLOAT_PROJECTION"
        private const val EXTRA_AUTO_LISTEN = "auto_listen"
        private const val EXTRA_RESULT_CODE = "result_code"
        private const val EXTRA_RESULT_DATA = "result_data"

        private val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()

        fun start(context: Context, autoListen: Boolean = false) {
            val intent = Intent(context, FloatingCelOverlayService::class.java).apply {
                putExtra(EXTRA_AUTO_LISTEN, autoListen)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, FloatingCelOverlayService::class.java))
        }

        fun supplyMediaProjection(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, FloatingCelOverlayService::class.java).apply {
                action = ACTION_SET_PROJECTION
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_RESULT_DATA, data)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}

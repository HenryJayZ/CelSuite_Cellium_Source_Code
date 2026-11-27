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
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.app.NotificationCompat
import com.henny.cellium.MainActivity
import com.henny.cellium.R
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.ai.WebToolsClient
import com.henny.cellium.avatar.AvatarStudioLiveBus
import com.henny.cellium.avatar.AvatarStudioLiveEvent
import com.henny.cellium.avatar.ExpressionDirector
import com.henny.cellium.avatar.FLOATING_IDLE_LINES
import com.henny.cellium.avatar.FLOATING_WAKE_UP_LINES
import com.henny.cellium.avatar.HELL_PIT_PANIC_LINES
import com.henny.cellium.avatar.HELL_PIT_RELIEVED_EXPRESSIONS
import com.henny.cellium.avatar.HELL_PIT_RELIEVED_LINES
import com.henny.cellium.avatar.HELL_PIT_SCARED_EXPRESSIONS
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSoundEngine
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
import kotlinx.coroutines.CancellationException
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
import java.io.File
import java.io.FileOutputStream
import java.util.UUID
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sin

private const val OVERLAY_CHANNEL_ID = "cellium_floating_cel"
private const val OVERLAY_NOTIF_ID = 4109

/**
 * Animated dark-red Hell Abyss dismissal zone at the bottom of the screen while dragging Floating Cel.
 */
private class HellAbyssDismissView(context: Context) : View(context) {
    private var hovering = false
    private val startMs = SystemClock.uptimeMillis()
    private var animRunning = false
    private val handler = Handler(Looper.getMainLooper())

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
            handler.postDelayed(this, 33L)
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
        handler.post(tickRunnable)
    }

    override fun onDetachedFromWindow() {
        animRunning = false
        handler.removeCallbacks(tickRunnable)
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

        for (i in 0..2) {
            val phase = (t * (if (hovering) 1.15f else 0.65f) + i * 0.33f) % 1f
            val r = h * (0.18f + phase * 0.46f)
            val a = ((1f - phase) * (if (hovering) 190f else 120f)).toInt().coerceIn(0, 220)
            vortexPaint.strokeWidth = if (hovering) 4f else 2.5f
            vortexPaint.color = Color.argb(a, 248, 60, 60)
            canvas.drawCircle(cx, cy, r, vortexPaint)
        }

        for (i in 0..13) {
            val seed = i * 1.73f
            val rise = (t * (0.45f + (i % 4) * 0.16f) + seed) % 1f
            val ex = cx + sin(seed * 3.1f + t * 2.2f) * (w * 0.34f)
            val ey = h - rise * h * 0.92f
            val ea = (sin(rise * PI).toFloat() * (if (hovering) 245f else 180f)).toInt().coerceIn(0, 245)
            emberPaint.color = if (i % 3 == 0) Color.argb(ea, 251, 146, 60) else Color.argb(ea, 239, 68, 68)
            canvas.drawCircle(ex, ey, (2.6f + (i % 3) * 1.6f) * if (hovering) 1.25f else 1f, emberPaint)
        }

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
 * True System-Wide Floating Cel Overlay (v2611.26.1):
 * - 4j: Stage indicators + holds reply reveal until TTS audio starts (or typewriter reveal for Synth!)
 * - 4k: Saves Screen Vision screenshots into MessageEntity.attachmentPath + filters "." STT noise
 * - 4l: Turning Auto Chat OFF cancels listening cleanly without transcribing/sending
 * - 4m: Quiet AndroidDeviceActions agentic loop (time, apps, alarms, timers, flashlight, volume, etc.)
 * - 4o: Random scared/worried expression in Hell Abyss; random relieved expression on drag-out -> idle after 2s
 * - 4p: Bubble anchors snugly beside Cel on BOTH left (Gravity.END) and right (Gravity.START) sides!
 * - 4q: True always-listening Auto Mode loop (never disables itself after silent timeouts!)
 * - 4r: Active persona support
 * - 4s: Quick "Switch Chat" / "+ New Chat" overlay menu without closing Floating Cel
 * - 4t: Separate Live/Floating voice profile (including Synth typing animation!)
 * - 4v: Preserves failed message with tappable Retry bubble on offline/network errors
 * - 4x: Continuously animated pixel face via upgraded AssistantDotFaceView
 */
class FloatingCelOverlayService : Service() {

    private lateinit var wm: WindowManager
    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val llmClient = UniversalLlmClient()
    private val webTools = WebToolsClient()

    private var faceContainer: FrameLayout? = null
    private var faceView: AssistantDotFaceView? = null
    private var faceParams: WindowManager.LayoutParams? = null

    // #2e: Dual stacked container — reply bubble NEVER gets erased when listening pill appears!
    private var bubbleStackContainer: LinearLayout? = null
    private var bubbleView: TextView? = null
    private var listeningPill: TextView? = null
    private var bubbleParams: WindowManager.LayoutParams? = null

    private var sideMenuContainer: LinearLayout? = null
    private var sideMenuParams: WindowManager.LayoutParams? = null
    private var sideMenuVisible = false

    private var chatPickerContainer: LinearLayout? = null
    private var chatPickerVisible = false

    private var abyssView: HellAbyssDismissView? = null
    private var abyssParams: WindowManager.LayoutParams? = null
    private var abyssVisible = false
    private var inDismissZone = false
    private var wasInDismissZoneThisDrag = false

    private var barContainer: LinearLayout? = null
    private var barParams: WindowManager.LayoutParams? = null
    private var screenToggleChip: TextView? = null
    private var inputField: EditText? = null
    private var barVisible = false

    private var speechRecognizer: SpeechRecognizer? = null
    private var sttLaunchJob: Job? = null
    private var cloudSttJob: Job? = null
    private var rearmAutoListenRunnable: Runnable? = null

    private lateinit var soundEngine: CelliumSoundEngine
    private lateinit var celliumTts: CelliumTtsEngine
    private lateinit var celliumStt: CelliumSttEngine

    private var isListening = false
    private var isTalking = false
    private var isThinking = false
    private var isDragging = false
    private var handsFreeEnabled = false

    // Living idle lifecycle + angry wake-up / Hell Abyss relieved hold guards + #2g idle screen-peek
    private var lastInteractionMs = SystemClock.uptimeMillis()
    private var lastScreenPeekMs = 0L
    private var lastHellPitLineMs = 0L
    private var lastStudioTeaseMs = 0L
    private var lastIdleLine: String? = null
    private var lastWakeLine: String? = null
    private var lastPanicLine: String? = null
    private var lastRelievedLine: String? = null
    private var angryHoldUntilMs = 0L
    private var relievedHoldUntilMs = 0L
    private var replyMoodHoldUntilMs = 0L
    private var calmDownRunnable: Runnable? = null
    private var relievedResetRunnable: Runnable? = null
    private var moodRelaxRunnable: Runnable? = null
    private var isBored = false
    private var isAsleep = false
    private var isDisintegrating = false
    private var autoHideBubbleRunnable: Runnable? = null
    private var studioObserverJob: Job? = null
    private var screenPeekJob: Job? = null

    // Persistent conversation memory + quick chat switcher (#4s)
    private var floatingSessionId: String? = null
    private var floatingSessionTitle: String = "New Chat"
    private var lastFloatingMsgId: String? = null
    private var activeAskJob: Job? = null

    // Retry state for offline / network failure (#4v)
    private var lastFailedPrompt: String? = null
    private var lastFailedScreenBmp: Bitmap? = null
    private var bubbleIsRetryAction = false

    // MediaProjection for Live Screen Vision
    private var mediaProjection: MediaProjection? = null
    private var screenVisionEnabled = false
    private var pendingScreenQuestion: String? = null

    private fun pickNonRepeating(pool: List<String>, last: String?): String {
        val candidates = pool.filter { it != last }
        return (if (candidates.isNotEmpty()) candidates else pool).random()
    }

    private val idleTickerRunnable = object : Runnable {
        override fun run() {
            val busy = isListening || isThinking || isTalking || isDragging || barVisible || handsFreeEnabled || isDisintegrating
            if (!busy && faceContainer != null && !isAngryHeld() && !isRelievedHeld() && !isReplyMoodHeld()) {
                val now = SystemClock.uptimeMillis()
                val idleSec = (now - lastInteractionMs) / 1000L
                // #2f: Strictly wait >= 60s of genuine idle before showing ANY idle message (never right after answering!)
                if (idleSec >= 300L && isAsleep && (now - lastScreenPeekMs) >= 300_000L) {
                    // #2g: After 5+ min genuine idle, optionally peek at screen & tease if enabled + vision ready
                    maybeTriggerIdleScreenPeek(reason = "woke_from_long_idle")
                } else if (idleSec >= 120L && !isAsleep) {
                    isAsleep = true
                    isBored = false
                    faceView?.updateState(newMood = "sleepy", expressionOverride = null)
                    hideSpeechBubble()
                } else if (idleSec >= 60L && !isBored && !isAsleep) {
                    isBored = true
                    val line = pickNonRepeating(FLOATING_IDLE_LINES, lastIdleLine).also { lastIdleLine = it }
                    faceView?.updateState(newMood = "bored", expressionOverride = null)
                    showSpeechBubble(line, autoHideMs = 4500L)
                }
            }
            mainHandler.postDelayed(this, 1000L)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WindowManager::class.java)
        initAudio()
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
                        showSpeechBubble("Screen Vision ON — tap me and ask about what's on screen.", autoHideMs = 4200L)
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
        val enableHandsFree = intent?.getBooleanExtra(EXTRA_HANDS_FREE, false) == true
        val requestScreenVision = intent?.getBooleanExtra(EXTRA_SCREEN_VISION, false) == true
        scope.launch {
            val store = PreferencesStore(applicationContext)
            val prefs = store.preferencesFlow.first()
            soundEngine.enabled = prefs.soundsEnabled
            soundEngine.hapticsEnabled = prefs.hapticsEnabled
            soundEngine.masterVolume = prefs.sfxVolume
            soundEngine.startupSoundId = prefs.startupSoundId
            soundEngine.startupSoundCustomPath = prefs.startupSoundCustomPath
            soundEngine.startupSoundShuffleEnabled = prefs.startupSoundShuffleEnabled
            soundEngine.startupSoundExcludedIds = prefs.startupSoundExcludedIds
            soundEngine.deletedStartupSoundIds = prefs.deletedStartupSoundIds
            faceView?.updateState(newGender = prefs.avatarGender)
            if (enableHandsFree && !handsFreeEnabled) {
                handsFreeEnabled = true
                faceView?.updateState(isHandsFree = true)
            }
            if (requestScreenVision && !screenVisionEnabled) {
                if (mediaProjection != null) {
                    screenVisionEnabled = true
                    updateScreenVisionChip()
                } else {
                    AssistantConsentActivity.launchScreenVisionConsent(this@FloatingCelOverlayService)
                }
            }
            if (firstCreated && !prefs.floatingTipsShown && !enableHandsFree) {
                store.markFloatingTipsShown()
                showSpeechBubble(
                    "Tip: Tap my face for Auto Chat, Talk, Type, Switch Chat, or drag me down to dismiss!",
                    autoHideMs = 6800L,
                )
            } else if (autoListen || enableHandsFree) {
                scheduleAutoListen(320L)
            }
        }
        return START_STICKY
    }

    private fun isAngryHeld(): Boolean = SystemClock.uptimeMillis() < angryHoldUntilMs
    private fun isRelievedHeld(): Boolean = SystemClock.uptimeMillis() < relievedHoldUntilMs
    private fun isReplyMoodHeld(): Boolean = SystemClock.uptimeMillis() < replyMoodHoldUntilMs

    private fun markUserInteraction(resetMoodToIdle: Boolean = false) {
        lastInteractionMs = SystemClock.uptimeMillis()
        isBored = false
        isAsleep = false
        if (resetMoodToIdle && !isListening && !isThinking && !isTalking && !isAngryHeld() && !isRelievedHeld() && !isReplyMoodHeld()) {
            faceView?.updateState(newMood = "idle", expressionOverride = null)
        }
    }

    // #2h: Varied wake-up lines + natural persistent grumpy/angry expression EVEN AFTER text fades!
    private fun wakeUpAngry(andDrag: Boolean = false) {
        isAsleep = false
        isBored = false
        val now = SystemClock.uptimeMillis()
        lastInteractionMs = now
        angryHoldUntilMs = now + 18_000L
        hapticFeedback(VibrationEffect.EFFECT_HEAVY_CLICK, 45L)
        val line = pickNonRepeating(FLOATING_WAKE_UP_LINES, lastWakeLine).also { lastWakeLine = it }
        val wakeMood = listOf("angry", "annoyed", "grumpy", "sulk", "pout").random()
        faceView?.updateState(newMood = wakeMood, expressionOverride = null)
        showSpeechBubble(line, autoHideMs = 4600L)
        if (!andDrag) {
            scope.launch {
                val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
                speakOut(line, prefs.liveTtsEngine, prefs.liveTtsVoiceName, prefs.liveTtsPitch, prefs.liveTtsSpeechRate, revealOnStart = false)
            }
            // #2g: Optionally peek at screen after waking from nap if screen vision is active
            if (mediaProjection != null && (now - lastScreenPeekMs) >= 180_000L) {
                mainHandler.postDelayed({ maybeTriggerIdleScreenPeek(reason = "poked_awake") }, 4800L)
            }
        }
        calmDownRunnable?.let { mainHandler.removeCallbacks(it) }
        val r = Runnable {
            angryHoldUntilMs = 0L
            if (!isListening && !isThinking && !isTalking && !isDragging && !isAsleep && !isRelievedHeld()) {
                faceView?.updateState(newMood = "idle", expressionOverride = null)
            }
        }
        calmDownRunnable = r
        mainHandler.postDelayed(r, 18_200L)
    }

    // #2g: Optional Idle Screen-Peek Teasing (only when enabled in Settings & MediaProjection is already granted)
    private fun maybeTriggerIdleScreenPeek(reason: String) {
        if (isListening || isThinking || isTalking || isDragging || isDisintegrating) return
        if (mediaProjection == null) return
        lastScreenPeekMs = SystemClock.uptimeMillis()
        screenPeekJob?.cancel()
        screenPeekJob = scope.launch {
            val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
            if (!prefs.floatingIdlePeekEnabled) return@launch
            val frame = withContext(Dispatchers.IO) { captureScreenFrameDirect() } ?: return@launch
            try {
                val dao = CelliumDatabase.getInstance(applicationContext).dao()
                val prov = dao.getProvider(prefs.activeProviderId)
                    ?: dao.getAllProviders().firstOrNull { it.protocol != "on_device" }
                    ?: return@launch
                val personas = dao.getAllPersonasOnce().map {
                    CustomPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
                }
                val persona = BuiltInPersonas.resolve(prefs.defaultPersonaId, personas)
                val sys = llmClient.buildSystemPrompt(
                    persona = persona,
                    memories = emptyList(),
                    agentModeEnabled = false,
                    shizukuConnected = false,
                    moodMethod = "inline_tag",
                    contextConfig = ContextModifyConfig(
                        includePersona = true,
                        includeMemories = false,
                        includeIllumeInstructions = false,
                        includeAgentInstructions = false,
                        includeMoodInstructions = true,
                    ),
                    includeDeviceActions = false,
                    extraInstruction = "[Idle Screen-Peek Tease] You just woke up ($reason) and peeked at what the user is doing on their screen. Drop ONE short, witty, playful, persona-matched 1-sentence tease about what you see (no markdown, max 16 words). Start with a mood tag like [MOOD:teasing] or [MOOD:smug].",
                )
                val sb = StringBuilder()
                llmClient.streamChat(
                    provider = prov,
                    systemPrompt = sys,
                    history = emptyList(),
                    userPrompt = "Peek at this screen and drop one quick playful remark.",
                    imageBitmap = frame,
                ).collect { chunk ->
                    if (chunk.contentDelta.isNotEmpty()) sb.append(chunk.contentDelta)
                }
                val (_, cleaned) = ProviderPresets.parseThoughts(sb.toString())
                val (tagMood, body) = MoodDetector.extractInlineMoodTag(cleaned)
                val tease = UniversalLlmClient.sanitizeVisibleReply(body).trim()
                if (tease.isNotBlank() && !isListening && !isThinking && !isDisintegrating) {
                    isAsleep = false
                    isBored = false
                    lastInteractionMs = SystemClock.uptimeMillis()
                    faceView?.updateState(newMood = tagMood ?: "teasing", newGender = prefs.avatarGender, expressionOverride = null)
                    showSpeechBubble(tease, autoHideMs = 6000L)
                    speakOut(tease, prefs.liveTtsEngine, prefs.liveTtsVoiceName, prefs.liveTtsPitch, prefs.liveTtsSpeechRate, revealOnStart = false)
                }
            } catch (_: Exception) {
                // Silent fail for ambient idle peek
            } finally {
                if (!frame.isRecycled) frame.recycle()
            }
        }
    }

    private fun triggerRelievedAfterHellPit() {
        val relievedExpr = HELL_PIT_RELIEVED_EXPRESSIONS.random()
        relievedHoldUntilMs = SystemClock.uptimeMillis() + 3_200L
        faceView?.updateState(newMood = "relieved", expressionOverride = relievedExpr)
        // #8: Varied relieved line when pulled back out of Hell Pit!
        val line = pickNonRepeating(HELL_PIT_RELIEVED_LINES, lastRelievedLine).also { lastRelievedLine = it }
        showSpeechBubble(line, autoHideMs = 3400L)
        speakQuickOverlayLine(line)
        relievedResetRunnable?.let { mainHandler.removeCallbacks(it) }
        val r = Runnable {
            relievedHoldUntilMs = 0L
            if (!isListening && !isThinking && !isTalking && !isDragging && !isAsleep && !isAngryHeld()) {
                faceView?.updateState(newMood = "idle", expressionOverride = null)
            }
        }
        relievedResetRunnable = r
        mainHandler.postDelayed(r, 3_400L)
    }

    private fun speakQuickOverlayLine(line: String) {
        val now = SystemClock.uptimeMillis()
        if (now - lastHellPitLineMs < 1_800L) return
        lastHellPitLineMs = now
        scope.launch {
            val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
            if (::celliumTts.isInitialized && !isTalking) {
                celliumTts.speak(
                    rawText = line,
                    engine = prefs.liveTtsEngine,
                    voiceName = prefs.liveTtsVoiceName,
                    pitch = prefs.liveTtsPitch,
                    speechRate = prefs.liveTtsSpeechRate,
                )
            }
        }
    }

    private fun hapticFeedback(predefinedEffect: Int, fallbackMs: Long) {
        runCatching {
            val vib = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                getSystemService(VibratorManager::class.java)?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
            if (vib == null || !vib.hasVibrator()) return
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                vib.vibrate(VibrationEffect.createPredefined(predefinedEffect))
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vib.vibrate(VibrationEffect.createOneShot(fallbackMs, VibrationEffect.DEFAULT_AMPLITUDE))
            } else {
                @Suppress("DEPRECATION")
                vib.vibrate(fallbackMs)
            }
        }
    }

    private fun dismissFloatingCel(updatePreference: Boolean) {
        cancelListening()
        activeAskJob?.cancel()
        llmClient.cancelActiveRequests()
        hideSideMenu()
        hideChatPicker()
        hideAbyssDismissZone()
        removeBottomChatBar()
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
            .setContentText("Tap Cel for Auto Chat, Talk, Type, or Switch Chat.")
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
        if (abyssVisible && abyssView != null) return
        hideAbyssDismissZone()
        val abyss = HellAbyssDismissView(this).also { abyssView = it }
        val hPx = dp(164f)
        val params = WindowManager.LayoutParams(
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
        }.onFailure {
            abyssView = null
            abyssVisible = false
        }
    }

    private fun hideAbyssDismissZone() {
        val view = abyssView
        abyssView = null
        abyssVisible = false
        inDismissZone = false
        if (view != null) {
            runCatching { wm.removeViewImmediate(view) }
                .onFailure { runCatching { wm.removeView(view) } }
        }
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

        var initX = 0
        var initY = 0
        var downRawX = 0f
        var downRawY = 0f
        var moved = false

        container.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    initX = params.x
                    initY = params.y
                    downRawX = event.rawX
                    downRawY = event.rawY
                    moved = false
                    wasInDismissZoneThisDrag = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downRawX).toInt()
                    val dy = (event.rawY - downRawY).toInt()
                    if (!moved && (abs(dx) > dp(7f) || abs(dy) > dp(7f))) {
                        moved = true
                        isDragging = true
                        hideSideMenu()
                        hideChatPicker()
                        hapticFeedback(VibrationEffect.EFFECT_TICK, 14L)
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
                                // 4o + #8: Random scared expression + varied panicked voice line!
                                wasInDismissZoneThisDrag = true
                                relievedResetRunnable?.let { mainHandler.removeCallbacks(it) }
                                relievedHoldUntilMs = 0L
                                hapticFeedback(VibrationEffect.EFFECT_CLICK, 24L)
                                val scaredExpr = HELL_PIT_SCARED_EXPRESSIONS.random()
                                faceView?.updateState(newMood = "scared", expressionOverride = scaredExpr)
                                val panicLine = pickNonRepeating(HELL_PIT_PANIC_LINES, lastPanicLine).also { lastPanicLine = it }
                                showSpeechBubble(panicLine, autoHideMs = 3200L)
                                speakQuickOverlayLine(panicLine)
                            } else {
                                // 4o + #8: Dragged OUT of Hell Abyss -> random relieved expression + relieved voice line!
                                hapticFeedback(VibrationEffect.EFFECT_TICK, 12L)
                                if (isAngryHeld()) {
                                    faceView?.updateState(newMood = "angry", expressionOverride = null)
                                } else {
                                    triggerRelievedAfterHellPit()
                                }
                            }
                        }
                    }
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL, MotionEvent.ACTION_OUTSIDE -> {
                    val wasMoved = moved
                    val shouldDismiss = inDismissZone
                    isDragging = false
                    hideAbyssDismissZone()
                    if (wasMoved) {
                        if (shouldDismiss) {
                            // #5: Pixel-scatter disintegration animation before dismissing!
                            isDisintegrating = true
                            cancelListening()
                            hideSideMenu()
                            hideChatPicker()
                            hideSpeechBubble()
                            hideListeningPill()
                            hapticFeedback(VibrationEffect.EFFECT_HEAVY_CLICK, 55L)
                            soundEngine.playClick()
                            val fv = faceView
                            if (fv != null) {
                                fv.startDisintegration {
                                    dismissFloatingCel(updatePreference = true)
                                }
                            } else {
                                dismissFloatingCel(updatePreference = true)
                            }
                        } else if (!wasInDismissZoneThisDrag) {
                            markUserInteraction(resetMoodToIdle = true)
                        } else {
                            // Keep the relieved animation running for its window!
                            markUserInteraction(resetMoodToIdle = false)
                        }
                    } else if (event.actionMasked == MotionEvent.ACTION_UP) {
                        if (isAsleep) {
                            wakeUpAngry(andDrag = false)
                        } else {
                            hapticFeedback(VibrationEffect.EFFECT_CLICK, 18L)
                            markUserInteraction()
                            toggleSideMenu()
                        }
                    }
                    true
                }
                else -> false
            }
        }

        wm.addView(container, params)

        // #2e: Dual stacked overlay container — Reply Bubble + separate Listening Pill!
        val stack = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.START
        }
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
            setOnClickListener {
                hapticFeedback(VibrationEffect.EFFECT_TICK, 12L)
                if (bubbleIsRetryAction && !lastFailedPrompt.isNullOrBlank()) {
                    val prompt = lastFailedPrompt!!
                    val bmp = lastFailedScreenBmp
                    bubbleIsRetryAction = false
                    askCel(prompt, retryBitmapOverride = bmp)
                } else {
                    hideSpeechBubble()
                }
            }
        }
        bubbleView = bubble

        val listenPill = TextView(this).apply {
            setTextColor(Color.parseColor("#34D399"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(dp(10f), dp(5f), dp(10f), dp(5f))
            maxWidth = dp(224f)
            background = GradientDrawable().apply {
                setColor(Color.argb(230, 8, 36, 30))
                cornerRadius = dp(99f).toFloat()
                setStroke(dp(1f), Color.argb(185, 52, 211, 153))
            }
            visibility = View.GONE
            setOnClickListener {
                hapticFeedback(VibrationEffect.EFFECT_TICK, 12L)
                if (isListening) stopListeningForSubmit()
            }
        }
        listeningPill = listenPill

        stack.addView(
            bubble,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            )
        )
        stack.addView(
            listenPill,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(5f) }
        )
        bubbleStackContainer = stack

        val bParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(16f)
            y = params.y
        }
        bubbleParams = bParams
        wm.addView(stack, bParams)

        // #7: Live Avatar Studio mirroring collector!
        studioObserverJob?.cancel()
        studioObserverJob = scope.launch {
            AvatarStudioLiveBus.events.collect { ev ->
                if (isDisintegrating) return@collect
                markUserInteraction()
                when (ev.actionType) {
                    "gender" -> {
                        val g = ev.gender
                        if (!g.isNullOrBlank()) {
                            faceView?.updateState(newGender = g, expressionOverride = ev.expressionName)
                        }
                    }
                    "expression", "modifier" -> {
                        val g = ev.gender
                        val m = ev.mood
                        when {
                            !g.isNullOrBlank() && !m.isNullOrBlank() ->
                                faceView?.updateState(newGender = g, newMood = m, expressionOverride = ev.expressionName)
                            !g.isNullOrBlank() ->
                                faceView?.updateState(newGender = g, expressionOverride = ev.expressionName)
                            !m.isNullOrBlank() ->
                                faceView?.updateState(newMood = m, expressionOverride = ev.expressionName)
                            else ->
                                faceView?.updateState(expressionOverride = ev.expressionName)
                        }
                    }
                    "blink" -> faceView?.triggerManualBlink()
                    "pet" -> faceView?.updateState(newMood = "love", expressionOverride = null)
                    else -> {
                        val g = ev.gender
                        val m = ev.mood
                        when {
                            !g.isNullOrBlank() && !m.isNullOrBlank() ->
                                faceView?.updateState(newGender = g, newMood = m, expressionOverride = ev.expressionName)
                            !g.isNullOrBlank() ->
                                faceView?.updateState(newGender = g, expressionOverride = ev.expressionName)
                            !m.isNullOrBlank() ->
                                faceView?.updateState(newMood = m, expressionOverride = ev.expressionName)
                            else ->
                                faceView?.updateState(expressionOverride = ev.expressionName)
                        }
                    }
                }
                val now = SystemClock.uptimeMillis()
                if (now - lastStudioTeaseMs >= 2_400L) {
                    lastStudioTeaseMs = now
                    val tease = AvatarStudioLiveBus.pickStudioReaction(ev)
                    showSpeechBubble(tease, autoHideMs = 3400L)
                }
            }
        }

        mainHandler.removeCallbacks(idleTickerRunnable)
        mainHandler.postDelayed(idleTickerRunnable, 1000L)
    }

    private fun toggleSideMenu() {
        if (sideMenuVisible) {
            hideSideMenu()
        } else {
            hideChatPicker()
            showSideMenu()
        }
    }

    private fun showSideMenu() {
        hideSideMenu()
        hideSpeechBubble()
        val fParams = faceParams ?: return
        val menuW = dp(178f)

        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(8f), dp(8f), dp(8f), dp(8f))
            background = GradientDrawable().apply {
                setColor(Color.argb(244, 12, 9, 24))
                cornerRadius = dp(20f).toFloat()
                setStroke(dp(1.2f), Color.argb(185, 192, 132, 252))
            }
        }

        fun makeMenuBtn(
            label: String,
            accentHex: String = "#F5F0FF",
            bgColor: Int = Color.argb(110, 40, 28, 72),
            onTap: () -> Unit,
        ): TextView = TextView(this).apply {
            text = label
            setTextColor(Color.parseColor(accentHex))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(dp(12f), dp(9f), dp(12f), dp(9f))
            background = GradientDrawable().apply {
                setColor(bgColor)
                cornerRadius = dp(13f).toFloat()
            }
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = dp(5f) }
            setOnClickListener {
                hapticFeedback(VibrationEffect.EFFECT_CLICK, 18L)
                onTap()
            }
        }

        // 1. Auto continuous conversation toggle (#4l & #4q)
        col.addView(
            makeMenuBtn(
                label = if (handsFreeEnabled) "Auto Chat: ON" else "Auto Chat: OFF",
                accentHex = if (handsFreeEnabled) "#38BDF8" else "#E2DCFA",
                bgColor = if (handsFreeEnabled) Color.argb(140, 14, 58, 92) else Color.argb(100, 36, 26, 62),
            ) {
                hideSideMenu()
                toggleHandsFreeMode()
            }
        )

        // 2. Say Something / Cancel Listening
        col.addView(
            makeMenuBtn(
                label = if (isListening) "Stop Listening" else "Say Something",
                accentHex = if (isListening) "#FCA5A5" else "#C084FC",
                bgColor = if (isListening) Color.argb(145, 96, 20, 34) else Color.argb(125, 68, 30, 118),
            ) {
                hideSideMenu()
                if (isListening) stopListeningForSubmit() else startListening()
            }
        )

        // 3. Type message
        col.addView(
            makeMenuBtn(
                label = if (barVisible) "Hide Keyboard Bar" else "Type a Message",
                accentHex = "#F5F0FF",
            ) {
                hideSideMenu()
                toggleBottomChatBar()
            }
        )

        // 4. Switch Chat / New Chat (#4s)
        col.addView(
            makeMenuBtn(
                label = "Chat: ${floatingSessionTitle.take(12)}",
                accentHex = "#93C5FD",
                bgColor = Color.argb(120, 20, 42, 78),
            ) {
                hideSideMenu()
                showChatPickerOverlay()
            }
        )

        // 5. Screen Vision toggle
        col.addView(
            makeMenuBtn(
                label = if (screenVisionEnabled) "Screen Eye: ON" else "Screen Eye: OFF",
                accentHex = if (screenVisionEnabled) "#34D399" else "#C4B5FD",
                bgColor = if (screenVisionEnabled) Color.argb(135, 16, 78, 58) else Color.argb(100, 36, 26, 62),
            ) {
                hideSideMenu()
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
        )

        // 6. Open in Main Chat App (#6)
        col.addView(
            makeMenuBtn(
                label = "Open in Chat",
                accentHex = "#E9D5FF",
                bgColor = Color.argb(135, 58, 28, 102),
            ) {
                hideSideMenu()
                openActiveSessionInMainChat()
            }
        )

        // 7. Dismiss Floating Cel
        col.addView(
            makeMenuBtn(
                label = "Dismiss Cel",
                accentHex = "#FCA5A5",
                bgColor = Color.argb(120, 82, 18, 28),
            ) {
                hapticFeedback(VibrationEffect.EFFECT_HEAVY_CLICK, 40L)
                dismissFloatingCel(updatePreference = true)
            }.apply {
                (layoutParams as LinearLayout.LayoutParams).bottomMargin = 0
            }
        )

        val screenW = resources.displayMetrics.widthPixels
        val screenH = resources.displayMetrics.heightPixels
        val faceCenterX = fParams.x + fParams.width / 2
        val placeLeft = faceCenterX > screenW / 2
        val menuX = if (placeLeft) {
            (fParams.x - menuW - dp(8f)).coerceAtLeast(dp(8f))
        } else {
            (fParams.x + fParams.width + dp(8f)).coerceAtMost(screenW - menuW - dp(8f))
        }
        val menuY = (fParams.y - dp(24f)).coerceIn(dp(28f), screenH - dp(290f))

        val mParams = WindowManager.LayoutParams(
            menuW,
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = menuX
            y = menuY
        }

        col.setOnTouchListener { _, ev ->
            if (ev.action == MotionEvent.ACTION_OUTSIDE) {
                hideSideMenu()
                true
            } else false
        }

        sideMenuContainer = col
        sideMenuParams = mParams
        runCatching {
            wm.addView(col, mParams)
            sideMenuVisible = true
        }.onFailure {
            sideMenuContainer = null
            sideMenuVisible = false
        }
    }

    private fun hideSideMenu() {
        val view = sideMenuContainer
        sideMenuContainer = null
        sideMenuVisible = false
        if (view != null) {
            runCatching { wm.removeViewImmediate(view) }
                .onFailure { runCatching { wm.removeView(view) } }
        }
    }

    /** 4s: Overlay Chat Switcher right over any app without closing Floating Cel! */
    private fun showChatPickerOverlay() {
        hideChatPicker()
        scope.launch {
            val dao = CelliumDatabase.getInstance(applicationContext).dao()
            val sessions = withContext(Dispatchers.IO) {
                dao.getAllSessionsOnce().filter { !it.isArena && !it.isLocked }.take(12)
            }
            val pickerW = dp(248f)
            val rootCol = LinearLayout(this@FloatingCelOverlayService).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(12f), dp(12f), dp(12f), dp(12f))
                background = GradientDrawable().apply {
                    setColor(Color.argb(248, 14, 10, 28))
                    cornerRadius = dp(20f).toFloat()
                    setStroke(dp(1.2f), Color.argb(190, 96, 165, 250))
                }
            }
            rootCol.addView(TextView(this@FloatingCelOverlayService).apply {
                text = "Switch Floating Chat"
                setTextColor(Color.WHITE)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                setPadding(dp(4f), 0, dp(4f), dp(8f))
            })

            val listCol = LinearLayout(this@FloatingCelOverlayService).apply {
                orientation = LinearLayout.VERTICAL
            }

            fun addRow(title: String, sub: String, selected: Boolean, onTap: () -> Unit) {
                listCol.addView(LinearLayout(this@FloatingCelOverlayService).apply {
                    orientation = LinearLayout.VERTICAL
                    setPadding(dp(10f), dp(8f), dp(10f), dp(8f))
                    background = GradientDrawable().apply {
                        setColor(if (selected) Color.argb(145, 76, 38, 138) else Color.argb(105, 34, 24, 58))
                        cornerRadius = dp(12f).toFloat()
                    }
                    layoutParams = LinearLayout.LayoutParams(
                        LinearLayout.LayoutParams.MATCH_PARENT,
                        LinearLayout.LayoutParams.WRAP_CONTENT,
                    ).apply { bottomMargin = dp(5f) }
                    addView(TextView(this@FloatingCelOverlayService).apply {
                        text = title
                        setTextColor(Color.WHITE)
                        setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
                        typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                        maxLines = 1
                    })
                    if (sub.isNotBlank()) {
                        addView(TextView(this@FloatingCelOverlayService).apply {
                            text = sub
                            setTextColor(Color.parseColor("#B5AACD"))
                            setTextSize(TypedValue.COMPLEX_UNIT_SP, 10.5f)
                            maxLines = 1
                        })
                    }
                    setOnClickListener {
                        hapticFeedback(VibrationEffect.EFFECT_CLICK, 16L)
                        onTap()
                        hideChatPicker()
                    }
                })
            }

            addRow("+ New Chat", "Start a fresh conversation", floatingSessionId == null) {
                floatingSessionId = null
                floatingSessionTitle = "New Chat"
                lastFloatingMsgId = null
                showSpeechBubble("Switched to a fresh chat!", autoHideMs = 2600L)
            }
            sessions.forEach { s ->
                addRow(
                    title = s.title.ifBlank { "Untitled Chat" },
                    sub = s.lastMessagePreview.take(44).ifBlank { "${s.messageCount} msgs" },
                    selected = floatingSessionId == s.id,
                ) {
                    floatingSessionId = s.id
                    floatingSessionTitle = s.title.ifBlank { "Chat" }
                    lastFloatingMsgId = s.activeLeafId
                    showSpeechBubble("Reading chat: ${s.title.take(26)}", autoHideMs = 2800L)
                }
            }

            val scroller = ScrollView(this@FloatingCelOverlayService).apply {
                addView(listCol)
            }
            rootCol.addView(scroller, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(250f)))

            val pParams = WindowManager.LayoutParams(
                pickerW,
                WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH,
                PixelFormat.TRANSLUCENT,
            ).apply {
                gravity = Gravity.CENTER
            }
            rootCol.setOnTouchListener { _, ev ->
                if (ev.action == MotionEvent.ACTION_OUTSIDE) {
                    hideChatPicker()
                    true
                } else false
            }

            chatPickerContainer = rootCol
            runCatching {
                wm.addView(rootCol, pParams)
                chatPickerVisible = true
            }.onFailure {
                chatPickerContainer = null
                chatPickerVisible = false
            }
        }
    }

    private fun hideChatPicker() {
        val view = chatPickerContainer
        chatPickerContainer = null
        chatPickerVisible = false
        if (view != null) {
            runCatching { wm.removeViewImmediate(view) }
                .onFailure { runCatching { wm.removeView(view) } }
        }
    }

    private fun toggleHandsFreeMode() {
        markUserInteraction()
        handsFreeEnabled = !handsFreeEnabled
        hapticFeedback(
            if (handsFreeEnabled) VibrationEffect.EFFECT_DOUBLE_CLICK else VibrationEffect.EFFECT_CLICK,
            if (handsFreeEnabled) 38L else 20L,
        )
        faceView?.updateState(isHandsFree = handsFreeEnabled)
        if (handsFreeEnabled) {
            showSpeechBubble("Auto Chat ON — always listening!", autoHideMs = 3000L)
            if (!isListening && !isThinking && !isTalking) {
                scheduleAutoListen(550L)
            }
        } else {
            // 4l: Turning Auto Chat OFF MUST cancel listening cleanly without transcribing/sending!
            cancelListening()
            showSpeechBubble("Auto Chat OFF.", autoHideMs = 2200L)
        }
    }

    private fun scheduleAutoListen(delayMs: Long = 550L) {
        rearmAutoListenRunnable?.let { mainHandler.removeCallbacks(it) }
        val r = Runnable {
            if (handsFreeEnabled && !isThinking && !isListening && !isTalking && !isDragging && !barVisible) {
                startListening()
            }
        }
        rearmAutoListenRunnable = r
        mainHandler.postDelayed(r, delayMs)
    }

    private fun openActiveSessionInMainChat() {
        val sid = floatingSessionId
        runCatching {
            val intent = Intent(applicationContext, MainActivity::class.java).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP
                )
                putExtra(MainActivity.EXTRA_OPEN_CHAT_TAB, true)
                if (!sid.isNullOrBlank()) {
                    putExtra(MainActivity.EXTRA_OPEN_SESSION_ID, sid)
                }
            }
            startActivity(intent)
        }
    }

    /**
     * 4p + #2e: Anchors the stacked bubble + listening pill snugly 8dp beside Cel's face on BOTH sides!
     * On the left of Cel, uses Gravity.END so the stack's RIGHT edge always hugs Cel regardless of text width.
     */
    private fun repositionBubbleBesideFace() {
        val fParams = faceParams ?: return
        val bParams = bubbleParams ?: return
        val stack = bubbleStackContainer ?: return
        val screenW = resources.displayMetrics.widthPixels
        val faceCenterX = fParams.x + fParams.width / 2
        val placeLeft = faceCenterX > screenW / 2
        stack.gravity = if (placeLeft) Gravity.END else Gravity.START
        if (placeLeft) {
            bParams.gravity = Gravity.TOP or Gravity.END
            bParams.x = (screenW - fParams.x + dp(8f)).coerceAtLeast(dp(8f))
        } else {
            bParams.gravity = Gravity.TOP or Gravity.START
            bParams.x = (fParams.x + fParams.width + dp(8f)).coerceAtMost(screenW - dp(80f))
        }
        bParams.y = fParams.y.coerceIn(dp(28f), resources.displayMetrics.heightPixels - dp(128f))
        if (stack.isAttachedToWindow) {
            runCatching { wm.updateViewLayout(stack, bParams) }
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

    // #2e: Separate stacked listening indicator pill so listening NEVER erases Cel's last reply!
    private fun showListeningPill(text: String) {
        mainHandler.post {
            val pill = listeningPill ?: return@post
            pill.text = text
            pill.visibility = View.VISIBLE
            repositionBubbleBesideFace()
        }
    }

    private fun hideListeningPill() {
        mainHandler.post {
            listeningPill?.visibility = View.GONE
        }
    }

    private fun toggleBottomChatBar() {
        if (barVisible) {
            removeBottomChatBar()
            return
        }
        cancelListening()
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
                hapticFeedback(VibrationEffect.EFFECT_TICK, 14L)
                removeBottomChatBar()
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
        if (handsFreeEnabled && !isListening && !isThinking && !isTalking) {
            scheduleAutoListen(500L)
        }
    }

    private fun initAudio() {
        soundEngine = CelliumSoundEngine(this)
        celliumTts = CelliumTtsEngine(this, sharedSoundEngine = soundEngine)
        celliumStt = CelliumSttEngine(this)
    }

    private fun startListening() {
        if (isThinking || isTalking || isDragging || barVisible) return
        markUserInteraction()
        if (::celliumTts.isInitialized) celliumTts.stop()
        rearmAutoListenRunnable?.let { mainHandler.removeCallbacks(it) }
        sttLaunchJob?.cancel()
        cloudSttJob?.cancel()
        WakeWordService.setPaused(this, true)
        isListening = true
        bubbleIsRetryAction = false
        faceView?.updateState(newMood = "listening", isListening = true, isMicReady = false, isTalking = false, expressionOverride = null)
        // #2e: Show stacked Listening pill without erasing Cel's reply bubble!
        showListeningPill("Starting mic...")

        sttLaunchJob = scope.launch {
            val prefs = PreferencesStore(this@FloatingCelOverlayService).preferencesFlow.first()
            if (!isListening) return@launch
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
                    startDeviceSpeechRecognizer()
                    return@launch
                }
                cloudSttJob = scope.launch {
                    val res = celliumStt.recordAndTranscribe(
                        engineId = sttEngineId,
                        apiKey = apiKey,
                        modelOverride = prefs.sttModel,
                        preSpeechTimeoutMs = 45_000L,
                        silenceAutoStopMs = 2_800L,
                        onReadyForSpeech = {
                            mainHandler.post {
                                if (isListening) {
                                    faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                    showListeningPill("Listening...")
                                }
                            }
                        },
                        onTranscribing = {
                            mainHandler.post {
                                isListening = false
                                faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                                showListeningPill("Transcribing...")
                            }
                        },
                    )
                    isListening = false
                    WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                    res.onSuccess { rawTxt ->
                        val cleaned = CelliumSttEngine.sanitizeTranscript(rawTxt)
                        if (cleaned.isNotBlank()) {
                            hideListeningPill()
                            askCel(cleaned)
                        } else {
                            hideListeningPill()
                            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                            if (handsFreeEnabled) {
                                // 4q: ALWAYS keep listening while Auto Mode is ON!
                                scheduleAutoListen(450L)
                            }
                        }
                    }.onFailure { err ->
                        hideListeningPill()
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                        if (handsFreeEnabled) {
                            // 4q: Never turn off Auto Chat on silence/timeout — re-arm calmly!
                            scheduleAutoListen(750L)
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
            if (!isListening) return@post
            runCatching {
                speechRecognizer?.destroy()
                val sr = SpeechRecognizer.createSpeechRecognizer(this)
                speechRecognizer = sr
                sr.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        mainHandler.post {
                            if (isListening) {
                                faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                showListeningPill("Listening...")
                            }
                        }
                    }
                    override fun onBeginningOfSpeech() = Unit
                    override fun onRmsChanged(rmsdB: Float) = Unit
                    override fun onBufferReceived(buffer: ByteArray?) = Unit
                    override fun onEndOfSpeech() {
                        isListening = false
                        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                        showListeningPill("Transcribing...")
                    }
                    override fun onError(error: Int) {
                        isListening = false
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        hideListeningPill()
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                        if (handsFreeEnabled) {
                            // 4q: True always-listening loop — never disables Auto Mode on silence/timeout!
                            scheduleAutoListen(600L)
                        }
                    }
                    override fun onResults(results: Bundle?) {
                        isListening = false
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        hideListeningPill()
                        val raw = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        val cleaned = CelliumSttEngine.sanitizeTranscript(raw)
                        if (cleaned.isNotEmpty()) {
                            askCel(cleaned)
                        } else {
                            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                            if (handsFreeEnabled) {
                                scheduleAutoListen(450L)
                            }
                        }
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        if (!isListening) return
                        val partial = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        if (partial.isNotBlank()) showListeningPill("\"$partial\"")
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) = Unit
                })
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2800L)
                    putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 2800L)
                    putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 45000L)
                }
                sr.startListening(intent)
            }.onFailure {
                isListening = false
                WakeWordService.setPaused(this, false)
                hideListeningPill()
                faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                showSpeechBubble("Mic unavailable — tap me to type instead.", autoHideMs = 4000L)
            }
        }
    }

    /** 4l: Cancels listening cleanly WITHOUT transcribing or sending partial audio! */
    private fun cancelListening() {
        rearmAutoListenRunnable?.let { mainHandler.removeCallbacks(it) }
        rearmAutoListenRunnable = null
        isListening = false
        sttLaunchJob?.cancel()
        sttLaunchJob = null
        cloudSttJob?.cancel()
        cloudSttJob = null
        if (::celliumStt.isInitialized) celliumStt.cancelRecording()
        mainHandler.post {
            runCatching { speechRecognizer?.cancel() }
            WakeWordService.setPaused(this, false)
            hideListeningPill()
            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
        }
    }

    /** Stops recording intentionally to transcribe & send what user just spoke. */
    private fun stopListeningForSubmit() {
        isListening = false
        if (::celliumStt.isInitialized) celliumStt.requestStopRecording()
        mainHandler.post {
            runCatching { speechRecognizer?.stopListening() }
            WakeWordService.setPaused(this, false)
            faceView?.updateState(isListening = false, isMicReady = false)
        }
    }

    private fun asksAboutScreen(text: String): Boolean {
        val lower = text.lowercase()
        val regex = Regex("""\b(see|look at|check|read|describe|watch|what'?s on|whats on|on)\s+(my\s+|the\s+)?screen\b|screen\s*vision""")
        return regex.containsMatchIn(lower)
    }

    private fun captureScreenFrameIfEnabled(): Bitmap? {
        if (!screenVisionEnabled) return null
        return captureScreenFrameDirect()
    }

    private fun captureScreenFrameDirect(): Bitmap? {
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

    private fun saveScreenshotToAttachment(bmp: Bitmap?): String {
        if (bmp == null || bmp.isRecycled) return ""
        val dir = File(applicationContext.filesDir, "attachments").apply { mkdirs() }
        val file = File(dir, "float_screen_${System.currentTimeMillis()}.jpg")
        return runCatching {
            FileOutputStream(file).use { fos -> bmp.compress(Bitmap.CompressFormat.JPEG, 86, fos) }
            file.absolutePath
        }.getOrDefault("")
    }

    private fun askCel(userText: String, retryBitmapOverride: Bitmap? = null) {
        val cleanedText = userText.trim()
        if (cleanedText.isEmpty()) return
        markUserInteraction()
        bubbleIsRetryAction = false

        if (!screenVisionEnabled && retryBitmapOverride == null && asksAboutScreen(cleanedText)) {
            if (mediaProjection != null) {
                screenVisionEnabled = true
                updateScreenVisionChip()
            } else {
                pendingScreenQuestion = cleanedText
                showSpeechBubble("Tap Allow so I can see your screen — I'll answer right after!", autoHideMs = 6000L)
                AssistantConsentActivity.launchScreenVisionConsent(this)
                return
            }
        }

        isThinking = true
        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false, expressionOverride = null)
        showSpeechBubble("Thinking...")

        activeAskJob?.cancel()
        activeAskJob = scope.launch {
            var screenBmp: Bitmap? = null
            try {
                val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
                val dao = CelliumDatabase.getInstance(applicationContext).dao()
                val prov = dao.getProvider(prefs.activeProviderId)
                    ?: dao.getAllProviders().firstOrNull { it.protocol != "on_device" }
                    ?: ProviderPresets.defaultProfiles().first()
                val personas = dao.getAllPersonasOnce().map {
                    CustomPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
                }
                // #9: Always respect active floating session persona or user's currently selected default persona!
                val chosenSession = floatingSessionId?.let { dao.getSession(it) }
                val personaId = chosenSession?.personaId?.ifBlank { prefs.defaultPersonaId } ?: prefs.defaultPersonaId
                val persona = BuiltInPersonas.resolve(personaId, personas)
                val memories = dao.getAllMemoriesOnce()
                screenBmp = retryBitmapOverride ?: withContext(Dispatchers.IO) { captureScreenFrameIfEnabled() }

                val sid = floatingSessionId ?: UUID.randomUUID().toString().also { newSid ->
                    floatingSessionId = newSid
                    floatingSessionTitle = "Floating · ${persona.name}"
                    dao.upsertSession(
                        SessionEntity(
                            id = newSid,
                            title = floatingSessionTitle,
                            personaId = persona.id,
                            providerId = prov.id,
                            modelName = prov.selectedModel,
                        )
                    )
                }
                val savedAttachmentPath = withContext(Dispatchers.IO) { saveScreenshotToAttachment(screenBmp) }
                val priorHistory = dao.getMessagesForSessionOnce(sid)
                val userMsgId = UUID.randomUUID().toString()
                dao.upsertMessage(
                    MessageEntity(
                        id = userMsgId,
                        sessionId = sid,
                        parentId = lastFloatingMsgId ?: priorHistory.lastOrNull()?.id,
                        role = "user",
                        content = cleanedText,
                        attachmentPath = savedAttachmentPath,
                        tokenEstimate = ProviderPresets.estimateTokens(cleanedText),
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
                    includeDeviceActions = true,
                    extraInstruction = "[Floating Assistant] Reply naturally in 1 to 3 short spoken sentences with no markdown formatting. Remember earlier turns in this floating conversation.",
                )

                // 4m: Quiet agentic execution loop before speaking final reply!
                val workingHistory = priorHistory.takeLast(14).toMutableList()
                var currentPrompt = cleanedText
                var currentBmp = screenBmp
                var finalRaw = ""

                for (step in 0..2) {
                    val sb = StringBuilder()
                    val maxRetries = prefs.maxAutoRetries.coerceIn(0, 3)
                    var attempt = 0
                    while (true) {
                        sb.clear()
                        try {
                            llmClient.streamChat(
                                provider = prov,
                                systemPrompt = sysPrompt,
                                history = workingHistory,
                                userPrompt = currentPrompt,
                                imageBitmap = currentBmp,
                            ).collect { chunk ->
                                if (chunk.contentDelta.isNotEmpty()) {
                                    sb.append(chunk.contentDelta)
                                    val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                                    val (tagMood, _) = MoodDetector.extractInlineMoodTag(clean)
                                    if (tagMood != null) {
                                        faceView?.updateState(newMood = tagMood, newGender = prefs.avatarGender)
                                    }
                                }
                            }
                            break
                        } catch (ce: CancellationException) {
                            throw ce
                        } catch (e: Exception) {
                            if (!UniversalLlmClient.isRetryableError(e) || attempt >= maxRetries) throw e
                            attempt++
                            showSpeechBubble("Busy — retrying ($attempt/$maxRetries)...")
                            delay(1200L * attempt)
                        }
                    }

                    val (_, cleanStep) = ProviderPresets.parseThoughts(sb.toString())
                    val actions = AndroidDeviceActions.extractActionPayloads(cleanStep)
                    val (webQuery, _) = UniversalLlmClient.extractWebSearchQuery(cleanStep)
                    if ((actions.isNotEmpty() || !webQuery.isNullOrBlank()) && step < 2) {
                        val resultBlock = buildString {
                            if (actions.isNotEmpty()) {
                                showSpeechBubble("Running action...")
                                faceView?.updateState(newMood = "working", newGender = prefs.avatarGender)
                                for (payload in actions.take(3)) {
                                    val res = AndroidDeviceActions.executePayload(applicationContext, payload, webTools)
                                    appendLine("[DEVICE_ACTION_RESULT (${res.action}, success=${res.success})]: ${res.output}")
                                }
                            }
                            if (!webQuery.isNullOrBlank()) {
                                showSpeechBubble("Searching web...")
                                faceView?.updateState(newMood = "curious", newGender = prefs.avatarGender)
                                val searchRes = webTools.searchWeb(webQuery, maxResults = 4)
                                val block = searchRes.fold(
                                    onSuccess = { items ->
                                        if (items.isEmpty()) "No web results for $webQuery."
                                        else items.joinToString("\n") { "${it.title}: ${it.snippet}" }
                                    },
                                    onFailure = { "Web search error: ${it.localizedMessage}" },
                                )
                                appendLine("[WEB_SEARCH_RESULT \"$webQuery\"]:\n$block")
                            }
                        }.trim()
                        workingHistory.add(
                            MessageEntity(
                                id = UUID.randomUUID().toString(),
                                sessionId = sid,
                                role = "user",
                                content = currentPrompt,
                            )
                        )
                        workingHistory.add(
                            MessageEntity(
                                id = UUID.randomUUID().toString(),
                                sessionId = sid,
                                role = "assistant",
                                content = cleanStep,
                            )
                        )
                        currentPrompt = "$resultBlock\nNow give your concise natural spoken answer. Do NOT emit another [DEVICE_ACTION] or [WEB_SEARCH] tag."
                        currentBmp = null
                        showSpeechBubble("Thinking...")
                    } else {
                        finalRaw = UniversalLlmClient.sanitizeVisibleReply(cleanStep)
                        break
                    }
                }

                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(finalRaw)
                val reply = UniversalLlmClient.sanitizeVisibleReply(finalBody.ifBlank { finalRaw }).ifBlank { "I'm right here!" }
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

                if (screenBmp != null && screenBmp !== lastFailedScreenBmp) {
                    screenBmp.recycle()
                }
                lastFailedPrompt = null
                lastFailedScreenBmp = null

                val holdMs = ExpressionDirector.holdDurationMsForMood(mood)
                replyMoodHoldUntilMs = SystemClock.uptimeMillis() + holdMs
                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender, expressionOverride = null)
                moodRelaxRunnable?.let { mainHandler.removeCallbacks(it) }
                val relax = Runnable {
                    replyMoodHoldUntilMs = 0L
                    if (!isListening && !isThinking && !isTalking && !isDragging && !isAsleep && !isAngryHeld() && !isRelievedHeld()) {
                        faceView?.updateState(newMood = "idle", expressionOverride = null)
                    }
                }
                moodRelaxRunnable = relax
                mainHandler.postDelayed(relax, holdMs + 3_000L)

                // 4j & 4t: Hold text reveal until voice audio starts (or animated typewriter for Synth!)
                speakOut(
                    text = reply,
                    engine = prefs.liveTtsEngine,
                    voiceName = prefs.liveTtsVoiceName,
                    pitch = prefs.liveTtsPitch,
                    rate = prefs.liveTtsSpeechRate,
                    revealOnStart = true,
                )
            } catch (ce: CancellationException) {
                // Cancelled cleanly
            } catch (e: Exception) {
                // 4v: Preserve prompt & screenshot with tappable Retry bubble so message is never lost!
                lastFailedPrompt = cleanedText
                lastFailedScreenBmp = screenBmp
                bubbleIsRetryAction = true
                faceView?.updateState(newMood = "error", expressionOverride = null)
                showSpeechBubble("Offline/Error: ${e.localizedMessage?.take(80) ?: "Couldn't reach AI"}\nTap to Retry")
            } finally {
                isThinking = false
                lastInteractionMs = SystemClock.uptimeMillis()
            }
        }
    }

    private fun speakOut(
        text: String,
        engine: String,
        voiceName: String,
        pitch: Float,
        rate: Float,
        revealOnStart: Boolean,
    ) {
        if (!::celliumTts.isInitialized) {
            if (revealOnStart) showSpeechBubble(text)
            return
        }
        val isSynth = engine.equals(CelliumTtsEngine.ENGINE_SYNTH, ignoreCase = true)
        if (revealOnStart) {
            if (!isSynth) showSpeechBubble("Preparing voice...") else showSpeechBubble("")
        }
        celliumTts.speak(
            rawText = text,
            engine = engine,
            voiceName = voiceName,
            pitch = pitch.coerceIn(0.25f, 2.50f),
            speechRate = rate.coerceIn(0.50f, 2.20f),
            onStart = {
                isTalking = true
                mainHandler.post {
                    faceView?.updateState(isTalking = true)
                    if (revealOnStart && !isSynth) {
                        showSpeechBubble(text)
                    }
                }
            },
            onSynthCharProgress = if (isSynth && revealOnStart) { count ->
                showSpeechBubble(text.take(count))
            } else null,
            onComplete = {
                isTalking = false
                lastInteractionMs = SystemClock.uptimeMillis()
                mainHandler.post {
                    faceView?.updateState(isTalking = false)
                    if (revealOnStart) showSpeechBubble(text)
                    if (handsFreeEnabled && !isThinking && !isListening && !isDragging && !barVisible) {
                        scheduleAutoListen(550L)
                    }
                }
            },
        )
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        hideSideMenu()
        hideChatPicker()
        hideAbyssDismissZone()
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        _isRunning.value = false
        mainHandler.removeCallbacks(idleTickerRunnable)
        autoHideBubbleRunnable?.let { mainHandler.removeCallbacks(it) }
        calmDownRunnable?.let { mainHandler.removeCallbacks(it) }
        relievedResetRunnable?.let { mainHandler.removeCallbacks(it) }
        moodRelaxRunnable?.let { mainHandler.removeCallbacks(it) }
        rearmAutoListenRunnable?.let { mainHandler.removeCallbacks(it) }
        studioObserverJob?.cancel()
        screenPeekJob?.cancel()
        cancelListening()
        activeAskJob?.cancel()
        llmClient.cancelActiveRequests()
        hideSideMenu()
        hideChatPicker()
        hideAbyssDismissZone()
        removeBottomChatBar()
        faceContainer?.let { runCatching { wm.removeViewImmediate(it) }.onFailure { _ -> runCatching { wm.removeView(it) } } }
        bubbleStackContainer?.let { runCatching { wm.removeViewImmediate(it) }.onFailure { _ -> runCatching { wm.removeView(it) } } }
        runCatching { speechRecognizer?.destroy() }
        if (::celliumTts.isInitialized) runCatching { celliumTts.release() }
        if (::soundEngine.isInitialized) runCatching { soundEngine.release() }
        runCatching { mediaProjection?.stop() }
        WakeWordService.setPaused(this, false)
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val ACTION_STOP = "com.henny.cellium.FLOAT_STOP"
        private const val ACTION_SET_PROJECTION = "com.henny.cellium.FLOAT_PROJECTION"
        private const val EXTRA_AUTO_LISTEN = "auto_listen"
        private const val EXTRA_HANDS_FREE = "hands_free"
        private const val EXTRA_SCREEN_VISION = "screen_vision"
        private const val EXTRA_RESULT_CODE = "result_code"
        private const val EXTRA_RESULT_DATA = "result_data"

        private val _isRunning = MutableStateFlow(false)
        val isRunning: StateFlow<Boolean> = _isRunning.asStateFlow()

        fun start(
            context: Context,
            autoListen: Boolean = false,
            enableHandsFree: Boolean = false,
            requestScreenVision: Boolean = false,
        ) {
            val intent = Intent(context, FloatingCelOverlayService::class.java).apply {
                putExtra(EXTRA_AUTO_LISTEN, autoListen)
                putExtra(EXTRA_HANDS_FREE, enableHandsFree)
                putExtra(EXTRA_SCREEN_VISION, requestScreenVision)
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

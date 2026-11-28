package com.henny.cellium.assistant

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.ColorDrawable
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.util.TypedValue
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.henny.cellium.MainActivity
import com.henny.cellium.R
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.ai.WebToolsClient
import com.henny.cellium.avatar.ExpressionDirector
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
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import java.util.UUID
import kotlin.math.abs

/**
 * Required companion RecognitionService declared in voice_interaction_service.xml so Android 14/15/16
 * VoiceInteractionManagerService keeps Cellium locked as the Default Digital Assistant instead of
 * resetting to "None".
 */
class CelliumRecognitionService : RecognitionService() {
    override fun onStartListening(recognizerIntent: Intent?, listener: Callback?) {
        runCatching { listener?.error(SpeechRecognizer.ERROR_CLIENT) }
    }

    override fun onCancel(listener: Callback?) = Unit

    override fun onStopListening(listener: Callback?) = Unit
}

/**
 * Default Digital Assistant Service for Android (Gemini replacement).
 * Registered via Settings -> Apps -> Default Apps -> Digital Assistant App -> Cellium.
 * Also hosts openWakeWord ("Okay Cel") natively with ZERO foreground notification whenever active.
 */
class CelliumVoiceInteractionService : VoiceInteractionService() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var prefsJob: Job? = null
    private var wakeController: WakeWordLoopController? = null

    override fun onReady() {
        super.onReady()
        activeServiceRef = java.lang.ref.WeakReference(this)
        _isBoundAsDefaultAssistant.value = true
        DevLogBuffer.add("INFO", "Assistant", "CelliumVoiceInteractionService ready (bound as Default Assistant).")
        // Stop any redundant foreground WakeWordService notification since we are system-bound!
        runCatching { stopService(Intent(this, WakeWordService::class.java)) }
        observeWakeWordPref()
    }

    private fun observeWakeWordPref() {
        prefsJob?.cancel()
        prefsJob = serviceScope.launch {
            PreferencesStore(applicationContext).preferencesFlow.collectLatest { p ->
                val hasMic = ContextCompat.checkSelfPermission(
                    applicationContext,
                    Manifest.permission.RECORD_AUDIO,
                ) == PackageManager.PERMISSION_GRANTED
                if (p.wakeWordEnabled && hasMic) {
                    startNativeWakeWordInternal()
                } else {
                    stopNativeWakeWordInternal()
                }
            }
        }
    }

    internal fun startNativeWakeWordInternal() {
        val hasMic = ContextCompat.checkSelfPermission(
            applicationContext,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
        if (!hasMic) return
        val runner = wakeController ?: WakeWordLoopController(
            appContext = applicationContext,
            scope = serviceScope,
            onWakeDetected = {
                val showed = runCatching {
                    showSession(
                        Bundle().apply { putBoolean("from_wake_word", true) },
                        VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT,
                    )
                    true
                }.getOrDefault(false)
                if (!showed) {
                    FloatingCelOverlayService.start(applicationContext, autoListen = true)
                }
            },
        ).also { wakeController = it }
        runner.start()
    }

    internal fun stopNativeWakeWordInternal() {
        wakeController?.stop()
        wakeController = null
    }

    override fun onShutdown() {
        prefsJob?.cancel()
        prefsJob = null
        stopNativeWakeWordInternal()
        if (activeServiceRef?.get() === this) {
            activeServiceRef = null
            _isBoundAsDefaultAssistant.value = false
        }
        serviceScope.cancel()
        super.onShutdown()
    }

    override fun onLaunchVoiceAssistFromKeyguard() {
        runCatching {
            showSession(
                Bundle().apply { putBoolean("from_keyguard", true) },
                VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT,
            )
        }
    }

    companion object {
        @Volatile
        private var activeServiceRef: java.lang.ref.WeakReference<CelliumVoiceInteractionService>? = null

        private val _isBoundAsDefaultAssistant = MutableStateFlow(false)
        val isBoundFlow: StateFlow<Boolean> = _isBoundAsDefaultAssistant.asStateFlow()

        fun isBoundAsDefaultAssistant(): Boolean = activeServiceRef?.get() != null

        fun syncWakeWordState(context: Context) {
            val svc = activeServiceRef?.get() ?: return
            svc.serviceScope.launch {
                val p = PreferencesStore(context.applicationContext).preferencesFlow.first()
                if (p.wakeWordEnabled) svc.startNativeWakeWordInternal() else svc.stopNativeWakeWordInternal()
            }
        }

        fun stopNativeWakeWord() {
            activeServiceRef?.get()?.stopNativeWakeWordInternal()
        }

        fun requestShowSession(fromEarpiece: Boolean = false): Boolean {
            val svc = activeServiceRef?.get() ?: return false
            return runCatching {
                val args = Bundle().apply { putBoolean("from_earpiece", fromEarpiece) }
                svc.showSession(
                    args,
                    VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT,
                )
                true
            }.onFailure { err ->
                DevLogBuffer.add("WARN", "Assistant", "showSession failed: ${err.localizedMessage}")
            }.getOrDefault(false)
        }
    }
}

class CelliumVoiceInteractionSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession {
        DevLogBuffer.add("INFO", "Assistant", "CelliumVoiceInteractionSessionService creating new session.")
        return CelliumVoiceInteractionSession(this)
    }
}

/**
 * Always-on Gemini-style multi-region circle-to-crop overlay:
 * - Drawing is ALWAYS active when a screenshot is captured (no Circle toggle button needed).
 * - Each stroke crops that exact region from the screenshot (never triggers STT or auto-send!).
 * - Supports multiple circled regions with persistent glowing selection boxes on screen.
 */
private class ScreenCropOverlayView(
    context: Context,
    private val onDrawingStarted: () -> Unit,
    private val onRegionCropped: (RectF) -> Unit,
    private val onBackgroundTapped: () -> Unit,
) : View(context) {

    var drawEnabled: Boolean = false
        set(value) {
            field = value
            invalidate()
        }

    // Normalized crop rectangles (0..1) corresponding to each circled area
    private val committedRegions = ArrayList<RectF>()
    private var activeStroke: ArrayList<Pair<Float, Float>>? = null
    private var downRawX = 0f
    private var downRawY = 0f
    private var movedBeyondTap = false
    private val drawPath = Path()
    private val boxRect = RectF()

    private val outerGlowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Color.argb(120, 168, 85, 247)
    }
    private val midGlowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Color.argb(215, 56, 189, 248)
    }
    private val corePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Color.argb(245, 248, 244, 255)
    }
    private val regionFillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(38, 56, 189, 248)
    }
    private val regionStrokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 5f
        color = Color.argb(215, 125, 211, 252)
    }
    private val badgeBgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(225, 168, 85, 247)
    }
    private val badgeTextPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.WHITE
        textSize = 28f
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
        textAlign = Paint.Align.CENTER
    }

    fun setRegions(regions: List<RectF>) {
        committedRegions.clear()
        committedRegions.addAll(regions)
        invalidate()
    }

    fun clearAll() {
        committedRegions.clear()
        activeStroke = null
        invalidate()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        val w = width.toFloat().coerceAtLeast(1f)
        val h = height.toFloat().coerceAtLeast(1f)
        val nx = (event.x / w).coerceIn(0f, 1f)
        val ny = (event.y / h).coerceIn(0f, 1f)

        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downRawX = event.x
                downRawY = event.y
                movedBeyondTap = false
                if (drawEnabled) {
                    activeStroke = ArrayList<Pair<Float, Float>>(32).apply { add(nx to ny) }
                    invalidate()
                }
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (!movedBeyondTap && (abs(event.x - downRawX) > 18f || abs(event.y - downRawY) > 18f)) {
                    movedBeyondTap = true
                    if (drawEnabled) onDrawingStarted()
                }
                if (drawEnabled && movedBeyondTap) {
                    activeStroke?.add(nx to ny)
                    invalidate()
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                val stroke = activeStroke
                activeStroke = null
                if (!movedBeyondTap) {
                    onBackgroundTapped()
                } else if (drawEnabled && stroke != null && stroke.size >= 3) {
                    var minX = 1f
                    var minY = 1f
                    var maxX = 0f
                    var maxY = 0f
                    for ((px, py) in stroke) {
                        if (px < minX) minX = px
                        if (py < minY) minY = py
                        if (px > maxX) maxX = px
                        if (py > maxY) maxY = py
                    }
                    // Add gentle 2.5% padding so cropped content isn't cut tight at the edges
                    val padX = 0.025f
                    val padY = 0.018f
                    val left = (minX - padX).coerceIn(0f, 0.96f)
                    val top = (minY - padY).coerceIn(0f, 0.96f)
                    val right = (maxX + padX).coerceIn(left + 0.04f, 1f)
                    val bottom = (maxY + padY).coerceIn(top + 0.04f, 1f)
                    if ((right - left) * w >= 32f && (bottom - top) * h >= 32f) {
                        onRegionCropped(RectF(left, top, right, bottom))
                    }
                }
                invalidate()
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                activeStroke = null
                invalidate()
                return true
            }
        }
        return false
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 4f || h <= 4f) return

        // Draw committed cropped regions with numbered badges
        committedRegions.forEachIndexed { idx, r ->
            boxRect.set(r.left * w, r.top * h, r.right * w, r.bottom * h)
            canvas.drawRoundRect(boxRect, 22f, 22f, regionFillPaint)
            canvas.drawRoundRect(boxRect, 22f, 22f, regionStrokePaint)
            val badgeCx = (boxRect.left + 22f).coerceIn(22f, w - 22f)
            val badgeCy = (boxRect.top + 22f).coerceIn(22f, h - 22f)
            canvas.drawCircle(badgeCx, badgeCy, 18f, badgeBgPaint)
            canvas.drawText("${idx + 1}", badgeCx, badgeCy + 10f, badgeTextPaint)
        }

        // Draw active freehand glowing stroke
        val pts = activeStroke ?: return
        if (pts.isEmpty()) return
        val baseStroke = (minOf(w, h) * 0.011f).coerceIn(6f, 14f)
        outerGlowPaint.strokeWidth = baseStroke * 2.5f
        midGlowPaint.strokeWidth = baseStroke * 1.35f
        corePaint.strokeWidth = baseStroke * 0.50f

        drawPath.reset()
        drawPath.moveTo(pts[0].first * w, pts[0].second * h)
        if (pts.size == 1) {
            drawPath.lineTo(pts[0].first * w + 1f, pts[0].second * h + 1f)
        } else {
            for (i in 1 until pts.size) {
                val prev = pts[i - 1]
                val curr = pts[i]
                drawPath.quadTo(
                    prev.first * w,
                    prev.second * h,
                    (prev.first + curr.first) * 0.5f * w,
                    (prev.second + curr.second) * 0.5f * h,
                )
            }
            val last = pts.last()
            drawPath.lineTo(last.first * w, last.second * h)
        }
        canvas.drawPath(drawPath, outerGlowPaint)
        canvas.drawPath(drawPath, midGlowPaint)
        canvas.drawPath(drawPath, corePaint)
    }
}

private data class CroppedSelection(
    val id: String = UUID.randomUUID().toString(),
    val normRect: RectF,
    val bitmap: Bitmap,
)

/**
 * Gemini-style transparent Assistant overlay right over the current app (v2611.26.1):
 * - 4a–4f: Drawing ALWAYS ON (no Circle button); drawing cancels STT, crops cleanly to multi-crop
 *   thumbnail strip above input box, unselects full screenshot by default, NEVER auto-sends.
 * - 4g: Plays user's selected/custom start-up sound (22 presets + custom audio).
 * - 4h/4n: Cancels ALL in-flight generation, STT & TTS immediately on close/hide/Go Live.
 * - 4i: Typing in input bar immediately cancels listening and shows Send button; hands-free hides Send.
 * - 4j: Clear stage labels + holds reply text reveal until voice audio is ready (or typewriter for Synth).
 * - 4k: Saves attached screenshots/crops to disk in MessageEntity.attachmentPath + filters "." STT noise.
 * - 4m: Quiet AndroidDeviceActions agentic loop (time, apps, alarm, timer, flashlight, volume, etc.).
 * - 4r/4s/4t/4v: Active persona, quick chat switcher, Live/Floating voice profile (incl. Synth), and Retry on error.
 */
class CelliumVoiceInteractionSession(context: Context) : VoiceInteractionSession(context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val llmClient = UniversalLlmClient()
    private val webTools = WebToolsClient()
    private var moodRelaxRunnable: Runnable? = null

    // Themed context prevents EditText/Material crashes when VoiceInteractionSession passes a raw Service context
    private val uiContext: Context by lazy {
        ContextThemeWrapper(context, R.style.Theme_Cellium_AssistantSession)
    }
    private var rootContainer: FrameLayout? = null

    private var faceView: AssistantDotFaceView? = null
    private var speechBubble: TextView? = null
    private var screenChip: TextView? = null
    private var clearCropsChip: TextView? = null
    private var chatSwitchChip: TextView? = null
    private var sendBtnView: TextView? = null
    private var drawOverlay: ScreenCropOverlayView? = null
    private var previewStripScroll: HorizontalScrollView? = null
    private var previewStripRow: LinearLayout? = null
    private var chatPickerOverlay: FrameLayout? = null
    private var inputEdit: EditText? = null

    private var capturedScreenshot: Bitmap? = null
    private var includeScreenVision = true
    private val croppedRegions = ArrayList<CroppedSelection>()

    private var speechRecognizer: SpeechRecognizer? = null
    private var showListenRunnable: Runnable? = null
    private var deviceSilenceFlushJob: Job? = null
    private val deviceSpeechBuffer = StringBuilder()
    private var sttLaunchJob: Job? = null
    private var cloudSttJob: Job? = null
    private var askJob: Job? = null

    private lateinit var soundEngine: CelliumSoundEngine
    private lateinit var celliumTts: CelliumTtsEngine
    private lateinit var celliumStt: CelliumSttEngine

    private var isListening = false
    private var isTypingMode = false
    private var isVisible = false
    private var assistSessionId: String? = null
    private var lastMessageId: String? = null

    // Retry state for offline / network failures (#4v)
    private var lastFailedPrompt: String? = null
    private var lastFailedImages: List<Bitmap> = emptyList()
    private var bubbleIsRetryAction = false

    private fun dp(v: Float): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, uiContext.resources.displayMetrics
    ).toInt()

    override fun onCreate() {
        super.onCreate()
        runCatching { setTheme(R.style.Theme_Cellium_AssistantSession) }
        runCatching {
            soundEngine = CelliumSoundEngine(context.applicationContext)
            celliumTts = CelliumTtsEngine(context.applicationContext, sharedSoundEngine = soundEngine)
            celliumStt = CelliumSttEngine(context.applicationContext)
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "Assistant", "Session audio init error: ${err.localizedMessage}")
        }
    }

    override fun onPrepareShow(args: Bundle?, showFlags: Int) {
        super.onPrepareShow(args, showFlags)
        setUiEnabled(true)
        setKeepAwake(true)
    }

    override fun onComputeInsets(outInsets: Insets) {
        super.onComputeInsets(outInsets)
        outInsets.contentInsets.set(0, 0, 0, 0)
        outInsets.touchableInsets = Insets.TOUCHABLE_INSETS_FRAME
    }

    override fun onHandleScreenshot(screenshot: Bitmap?) {
        super.onHandleScreenshot(screenshot)
        capturedScreenshot = screenshot
        mainHandler.post {
            drawOverlay?.drawEnabled = screenshot != null
            screenChip?.apply {
                visibility = if (screenshot != null) View.VISIBLE else View.GONE
                updateScreenChipAppearance()
            }
            rebuildAttachmentPreviewStrip()
        }
    }

    private fun configureSessionWindow() {
        runCatching {
            window?.window?.apply {
                setLayout(WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT)
                setBackgroundDrawable(ColorDrawable(Color.TRANSPARENT))
                setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
            }
        }
    }

    override fun onCreateContentView(): View {
        configureSessionWindow()
        val root = FrameLayout(uiContext).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
            setBackgroundColor(Color.argb(95, 4, 3, 10))
        }
        rootContainer = root

        // Always-on Gemini-style multi-region circle-to-crop overlay
        val overlay = ScreenCropOverlayView(
            context = uiContext,
            onDrawingStarted = {
                // 4b: Drawing NEVER transcribes — immediately cancel any active/pending STT
                cancelListeningQuietly()
            },
            onRegionCropped = { normRect ->
                handleNewCircledCrop(normRect)
            },
            onBackgroundTapped = {
                if (chatPickerOverlay?.visibility == View.VISIBLE) {
                    chatPickerOverlay?.visibility = View.GONE
                } else {
                    hide()
                }
            },
        )
        drawOverlay = overlay
        root.addView(
            overlay,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        )

        val celRow = LinearLayout(uiContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setOnClickListener { /* consume */ }
        }

        val faceSize = dp(92f)
        val face = AssistantDotFaceView(uiContext).apply {
            layoutParams = LinearLayout.LayoutParams(faceSize, faceSize)
        }
        faceView = face

        val bubble = TextView(uiContext).apply {
            text = "Circle anything on screen, speak, or type below."
            setTextColor(Color.parseColor("#F5F0FF"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
            setPadding(dp(14f), dp(10f), dp(14f), dp(10f))
            maxWidth = dp(242f)
            background = GradientDrawable().apply {
                setColor(Color.argb(238, 16, 12, 30))
                cornerRadius = dp(18f).toFloat()
                setStroke(dp(1f), Color.argb(185, 192, 132, 252))
            }
            setOnClickListener {
                if (bubbleIsRetryAction && !lastFailedPrompt.isNullOrBlank()) {
                    val retryPrompt = lastFailedPrompt!!
                    val retryImgs = lastFailedImages
                    bubbleIsRetryAction = false
                    askCel(retryPrompt, explicitBitmaps = retryImgs)
                } else {
                    visibility = View.GONE
                }
            }
        }
        speechBubble = bubble

        celRow.addView(face)
        celRow.addView(
            bubble,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { leftMargin = dp(10f) }
        )

        val baseCelBottomMargin = dp(186f)
        val celLp = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.START
            leftMargin = dp(16f)
            bottomMargin = baseCelBottomMargin
        }

        var downX = 0f
        var downY = 0f
        var startTx = 0f
        var startTy = 0f
        var dragged = false
        face.setOnTouchListener { _, ev ->
            when (ev.action) {
                MotionEvent.ACTION_DOWN -> {
                    downX = ev.rawX
                    downY = ev.rawY
                    startTx = celRow.translationX
                    startTy = celRow.translationY
                    dragged = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = ev.rawX - downX
                    val dy = ev.rawY - downY
                    if (abs(dx) > dp(6f) || abs(dy) > dp(6f)) dragged = true
                    celRow.translationX = startTx + dx
                    celRow.translationY = startTy + dy
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!dragged) {
                        if (isListening) stopListeningForSubmit() else startListening()
                    }
                    true
                }
                else -> false
            }
        }
        root.addView(celRow, celLp)

        val baseBottomPad = dp(18f)
        val bottomCol = LinearLayout(uiContext).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14f), dp(6f), dp(14f), baseBottomPad)
            setOnClickListener { /* consume */ }
        }

        // #6: Gemini-style swipe-up handle -> opens exact active conversation in main Chat tab!
        var handleDownY = 0f
        var handleTriggered = false
        val swipeHandleRow = LinearLayout(uiContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, dp(4f), 0, dp(6f))
            addView(
                View(uiContext).apply {
                    background = GradientDrawable().apply {
                        setColor(Color.argb(175, 192, 132, 252))
                        cornerRadius = dp(3f).toFloat()
                    }
                    layoutParams = LinearLayout.LayoutParams(dp(44f), dp(4.5f))
                }
            )
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playOpen()
                openActiveSessionInMainChat()
            }
            setOnTouchListener { _, ev ->
                when (ev.actionMasked) {
                    MotionEvent.ACTION_DOWN -> {
                        handleDownY = ev.rawY
                        handleTriggered = false
                        true
                    }
                    MotionEvent.ACTION_MOVE -> {
                        if (!handleTriggered && (handleDownY - ev.rawY) > dp(44f)) {
                            handleTriggered = true
                            if (::soundEngine.isInitialized) soundEngine.playOpen()
                            openActiveSessionInMainChat()
                        }
                        true
                    }
                    MotionEvent.ACTION_UP -> {
                        if (!handleTriggered && abs(handleDownY - ev.rawY) < dp(12f)) {
                            if (::soundEngine.isInitialized) soundEngine.playOpen()
                            openActiveSessionInMainChat()
                        }
                        true
                    }
                    else -> false
                }
            }
        }
        bottomCol.addView(
            swipeHandleRow,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            )
        )

        // 4e & 4f: Cropped / Screenshot Thumbnail Preview Strip above chat box!
        val stripRow = LinearLayout(uiContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        previewStripRow = stripRow
        val stripScroll = HorizontalScrollView(uiContext).apply {
            isHorizontalScrollBarEnabled = false
            visibility = View.GONE
            addView(stripRow)
        }
        previewStripScroll = stripScroll
        bottomCol.addView(
            stripScroll,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = dp(8f) }
        )

        val chipRow = LinearLayout(uiContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
        }

        fun chipBg(fill: Int, stroke: Int): GradientDrawable = GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(14f).toFloat()
            setStroke(dp(1f), stroke)
        }

        val sChip = TextView(uiContext).apply {
            text = "Full Screen: ON"
            setTextColor(Color.parseColor("#D8B4FE"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = chipBg(Color.argb(215, 28, 18, 48), Color.argb(165, 192, 132, 252))
            visibility = if (capturedScreenshot != null) View.VISIBLE else View.GONE
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playClick()
                includeScreenVision = !includeScreenVision
                updateScreenChipAppearance()
                rebuildAttachmentPreviewStrip()
            }
        }
        screenChip = sChip

        val clrChip = TextView(uiContext).apply {
            text = "Clear Crops"
            setTextColor(Color.parseColor("#FCA5A5"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(9f), dp(6f), dp(9f), dp(6f))
            background = chipBg(Color.argb(215, 56, 16, 24), Color.argb(175, 248, 113, 113))
            visibility = View.GONE
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playClick()
                clearAllCrops()
            }
        }
        clearCropsChip = clrChip

        // 4s: Quick chat switcher chip
        val chatChip = TextView(uiContext).apply {
            text = "Chat: New"
            setTextColor(Color.parseColor("#93C5FD"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = chipBg(Color.argb(215, 16, 30, 56), Color.argb(175, 96, 165, 250))
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playClick()
                cancelListeningQuietly()
                openChatPickerOverlay()
            }
        }
        chatSwitchChip = chatChip

        val liveChip = TextView(uiContext).apply {
            text = "Go Live"
            setTextColor(Color.parseColor("#34D399"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(11f), dp(6f), dp(11f), dp(6f))
            background = chipBg(Color.argb(220, 10, 46, 36), Color.argb(185, 52, 211, 153))
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playOpen()
                // 4n: Immediately abort all pop-up work BEFORE launching Floating Cel!
                cancelAllActiveWork()
                if (Settings.canDrawOverlays(context)) {
                    FloatingCelOverlayService.start(
                        context = context.applicationContext,
                        autoListen = false,
                        enableHandsFree = true,
                        requestScreenVision = includeScreenVision,
                    )
                    hide()
                } else {
                    showBubble("Grant 'Display over other apps' so Cel can float live!")
                    val permIntent = Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:${context.packageName}"),
                    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    runCatching { startAssistantActivity(permIntent) }.onFailure {
                        runCatching { context.startActivity(permIntent) }
                    }
                }
            }
        }

        val openChatChip = TextView(uiContext).apply {
            text = "Open Chat"
            setTextColor(Color.parseColor("#E9D5FF"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = chipBg(Color.argb(220, 44, 22, 74), Color.argb(185, 192, 132, 252))
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playOpen()
                openActiveSessionInMainChat()
            }
        }

        val chipLp = {
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { rightMargin = dp(7f) }
        }
        chipRow.addView(sChip, chipLp())
        chipRow.addView(clrChip, chipLp())
        chipRow.addView(chatChip, chipLp())
        chipRow.addView(openChatChip, chipLp())
        chipRow.addView(liveChip, chipLp())

        val chipScroll = HorizontalScrollView(uiContext).apply {
            isHorizontalScrollBarEnabled = false
            addView(chipRow)
        }
        bottomCol.addView(
            chipScroll,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = dp(8f) }
        )

        val pill = LinearLayout(uiContext).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(12f), dp(8f), dp(10f), dp(8f))
            background = GradientDrawable().apply {
                setColor(Color.argb(242, 14, 10, 26))
                cornerRadius = dp(26f).toFloat()
                setStroke(dp(1.2f), Color.argb(190, 192, 132, 252))
            }
        }

        val micBtn = TextView(uiContext).apply {
            text = "Mic"
            setTextColor(Color.parseColor("#C084FC"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playClick()
                isTypingMode = false
                if (isListening) stopListeningForSubmit() else startListening()
            }
        }

        val sendBtn = TextView(uiContext).apply {
            text = "Send"
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            setPadding(dp(14f), dp(7f), dp(14f), dp(7f))
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#A855F7"))
                cornerRadius = dp(18f).toFloat()
            }
            visibility = View.GONE
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playSend()
                val q = inputEdit?.text?.toString()?.trim().orEmpty()
                if (q.isNotEmpty()) {
                    inputEdit?.setText("")
                    isTypingMode = false
                    visibility = View.GONE
                    askCel(q)
                }
            }
        }
        sendBtnView = sendBtn

        val edit = EditText(uiContext).apply {
            hint = "Circle screen, speak, or type..."
            setHintTextColor(Color.parseColor("#8A80A4"))
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f)
            background = null
            // #2b: Multiline paragraphs + normal keyboard Enter/New-Line (Send button sends!)
            isSingleLine = false
            maxLines = 4
            inputType = InputType.TYPE_CLASS_TEXT or
                InputType.TYPE_TEXT_FLAG_MULTI_LINE or
                InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
            imeOptions = EditorInfo.IME_FLAG_NO_EXTRACT_UI
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnFocusChangeListener { _, hasFocus ->
                if (hasFocus) {
                    // 4i: Focusing the text box immediately cancels hands-free listening!
                    isTypingMode = true
                    cancelListeningQuietly()
                    sendBtnView?.visibility = View.VISIBLE
                }
            }
            addTextChangedListener(object : TextWatcher {
                override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
                override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                    val hasText = !s.isNullOrBlank()
                    if (hasText) {
                        // 4i: Typing cancels voice listening and waits for explicit Send
                        isTypingMode = true
                        cancelListeningQuietly()
                        sendBtnView?.visibility = View.VISIBLE
                    } else if (!isFocused) {
                        sendBtnView?.visibility = View.GONE
                    }
                }
                override fun afterTextChanged(s: Editable?) = Unit
            })
        }
        inputEdit = edit

        pill.addView(micBtn)
        pill.addView(edit, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        pill.addView(sendBtn)
        bottomCol.addView(pill)

        root.addView(
            bottomCol,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            )
        )

        // Overlay chat picker container (#4s)
        val pickerHost = FrameLayout(uiContext).apply {
            setBackgroundColor(Color.argb(180, 6, 4, 14))
            visibility = View.GONE
            setOnClickListener { visibility = View.GONE }
        }
        chatPickerOverlay = pickerHost
        root.addView(
            pickerHost,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        )

        // WindowInsets listener: sits cleanly above 3-button nav bar & rises with IME
        root.setOnApplyWindowInsetsListener { _, insets ->
            val bottomInset = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                val nav = insets.getInsets(WindowInsets.Type.systemBars()).bottom
                val ime = insets.getInsets(WindowInsets.Type.ime()).bottom
                maxOf(nav, ime)
            } else {
                @Suppress("DEPRECATION")
                insets.systemWindowInsetBottom
            }
            bottomCol.setPadding(dp(14f), dp(8f), dp(14f), baseBottomPad + bottomInset)
            (celRow.layoutParams as? FrameLayout.LayoutParams)?.let { lp ->
                lp.bottomMargin = baseCelBottomMargin + bottomInset
                celRow.layoutParams = lp
            }
            insets
        }
        root.requestApplyInsets()

        return root
    }

    private fun updateScreenChipAppearance() {
        screenChip?.apply {
            text = if (includeScreenVision) "Full Screen: ON" else "Full Screen: OFF"
            setTextColor(if (includeScreenVision) Color.parseColor("#D8B4FE") else Color.parseColor("#9A90B0"))
        }
    }

    private fun openActiveSessionInMainChat() {
        val sid = assistSessionId
        cancelAllActiveWork()
        val intent = Intent(context.applicationContext, MainActivity::class.java).apply {
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
        // Use startAssistantActivity first so Android 14/15/16 BAL restrictions never block opening Cel!
        runCatching { startAssistantActivity(intent) }.onFailure {
            runCatching { context.startActivity(intent) }
        }
        hide()
    }

    private fun handleNewCircledCrop(normRect: RectF) {
        val src = capturedScreenshot ?: return
        val x = (normRect.left * src.width).toInt().coerceIn(0, (src.width - 2).coerceAtLeast(0))
        val y = (normRect.top * src.height).toInt().coerceIn(0, (src.height - 2).coerceAtLeast(0))
        val w = ((normRect.width()) * src.width).toInt().coerceIn(2, src.width - x)
        val h = ((normRect.height()) * src.height).toInt().coerceIn(2, src.height - y)
        val cropped = runCatching { Bitmap.createBitmap(src, x, y, w, h) }.getOrNull() ?: return

        soundEngine.playPop()
        // 4c: First circled crop automatically unselects full screenshot so ONLY crops upload unless re-enabled
        if (croppedRegions.isEmpty()) {
            includeScreenVision = false
            updateScreenChipAppearance()
        }
        if (croppedRegions.size >= 5) {
            val removed = croppedRegions.removeAt(0)
            if (!removed.bitmap.isRecycled) removed.bitmap.recycle()
        }
        croppedRegions.add(CroppedSelection(normRect = normRect, bitmap = cropped))
        drawOverlay?.setRegions(croppedRegions.map { it.normRect })
        clearCropsChip?.visibility = View.VISIBLE
        rebuildAttachmentPreviewStrip()
        // 4d: NEVER auto-send! Inform user cleanly and wait for voice or text.
        showBubble("Cropped ${croppedRegions.size} spot${if (croppedRegions.size > 1) "s" else ""}. Circle more, tap Mic, or type!")
    }

    private fun clearAllCrops() {
        croppedRegions.forEach { if (!it.bitmap.isRecycled) it.bitmap.recycle() }
        croppedRegions.clear()
        drawOverlay?.clearAll()
        clearCropsChip?.visibility = View.GONE
        rebuildAttachmentPreviewStrip()
    }

    private fun rebuildAttachmentPreviewStrip() {
        mainHandler.post {
            val row = previewStripRow ?: return@post
            val scroll = previewStripScroll ?: return@post
            row.removeAllViews()

            val fullBmp = if (includeScreenVision) capturedScreenshot else null
            if (fullBmp != null && !fullBmp.isRecycled) {
                row.addView(
                    buildThumbCard(
                        bitmap = fullBmp,
                        label = "Full Screen",
                        accentColor = Color.parseColor("#C084FC"),
                        onRemove = {
                            includeScreenVision = false
                            updateScreenChipAppearance()
                            rebuildAttachmentPreviewStrip()
                        },
                    )
                )
            }
            croppedRegions.forEachIndexed { idx, sel ->
                if (!sel.bitmap.isRecycled) {
                    row.addView(
                        buildThumbCard(
                            bitmap = sel.bitmap,
                            label = "Crop #${idx + 1}",
                            accentColor = Color.parseColor("#38BDF8"),
                            onRemove = {
                                val target = croppedRegions.removeAt(idx)
                                if (!target.bitmap.isRecycled) target.bitmap.recycle()
                                drawOverlay?.setRegions(croppedRegions.map { it.normRect })
                                clearCropsChip?.visibility = if (croppedRegions.isNotEmpty()) View.VISIBLE else View.GONE
                                rebuildAttachmentPreviewStrip()
                            },
                        )
                    )
                }
            }
            scroll.visibility = if (row.childCount > 0) View.VISIBLE else View.GONE
        }
    }

    private fun buildThumbCard(
        bitmap: Bitmap,
        label: String,
        accentColor: Int,
        onRemove: () -> Unit,
    ): View {
        val card = FrameLayout(uiContext).apply {
            background = GradientDrawable().apply {
                setColor(Color.argb(235, 16, 12, 30))
                cornerRadius = dp(12f).toFloat()
                setStroke(dp(1.2f), accentColor)
            }
            layoutParams = LinearLayout.LayoutParams(dp(74f), dp(74f)).apply {
                rightMargin = dp(8f)
            }
            setPadding(dp(2f), dp(2f), dp(2f), dp(2f))
        }
        val img = ImageView(uiContext).apply {
            setImageBitmap(bitmap)
            scaleType = ImageView.ScaleType.CENTER_CROP
        }
        card.addView(img, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))

        val tag = TextView(uiContext).apply {
            text = label
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 9.5f)
            setBackgroundColor(Color.argb(180, 10, 8, 20))
            setPadding(dp(4f), dp(1f), dp(4f), dp(1f))
            gravity = Gravity.CENTER
        }
        card.addView(
            tag,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.BOTTOM,
            )
        )

        val closeX = TextView(uiContext).apply {
            text = "×"
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12f)
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            background = GradientDrawable().apply {
                setColor(Color.argb(225, 220, 38, 38))
                shape = GradientDrawable.OVAL
            }
            setOnClickListener {
                if (::soundEngine.isInitialized) soundEngine.playClick()
                onRemove()
            }
        }
        card.addView(
            closeX,
            FrameLayout.LayoutParams(dp(20f), dp(20f), Gravity.TOP or Gravity.END).apply {
                topMargin = dp(2f)
                rightMargin = dp(2f)
            }
        )
        return card
    }

    private fun openChatPickerOverlay() {
        val host = chatPickerOverlay ?: return
        scope.launch {
            val dao = CelliumDatabase.getInstance(context.applicationContext).dao()
            val sessions = withContext(Dispatchers.IO) {
                dao.getAllSessionsOnce().filter { !it.isArena && !it.isLocked }.take(12)
            }
            host.removeAllViews()
            val card = LinearLayout(uiContext).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(16f), dp(16f), dp(16f), dp(16f))
                background = GradientDrawable().apply {
                    setColor(Color.argb(248, 16, 12, 30))
                    cornerRadius = dp(22f).toFloat()
                    setStroke(dp(1.2f), Color.argb(190, 192, 132, 252))
                }
                setOnClickListener { /* consume */ }
            }
            card.addView(TextView(uiContext).apply {
                text = "Switch Active Chat"
                setTextColor(Color.WHITE)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
                typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                setPadding(0, 0, 0, dp(10f))
            })

            fun makeRow(label: String, sub: String, selected: Boolean, onTap: () -> Unit): View = LinearLayout(uiContext).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(12f), dp(10f), dp(12f), dp(10f))
                background = GradientDrawable().apply {
                    setColor(if (selected) Color.argb(135, 92, 42, 160) else Color.argb(110, 34, 24, 58))
                    cornerRadius = dp(12f).toFloat()
                }
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ).apply { bottomMargin = dp(6f) }
                addView(TextView(uiContext).apply {
                    text = label
                    setTextColor(Color.WHITE)
                    setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
                    typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
                    maxLines = 1
                })
                if (sub.isNotBlank()) {
                    addView(TextView(uiContext).apply {
                        text = sub
                        setTextColor(Color.parseColor("#B8AED0"))
                        setTextSize(TypedValue.COMPLEX_UNIT_SP, 11f)
                        maxLines = 1
                    })
                }
                setOnClickListener {
                    if (::soundEngine.isInitialized) soundEngine.playClick()
                    onTap()
                    host.visibility = View.GONE
                }
            }

            val listCol = LinearLayout(uiContext).apply { orientation = LinearLayout.VERTICAL }
            listCol.addView(
                makeRow("+ New Assistant Chat", "Start a fresh thread", assistSessionId == null) {
                    assistSessionId = null
                    lastMessageId = null
                    chatSwitchChip?.text = "Chat: New"
                }
            )
            sessions.forEach { s ->
                listCol.addView(
                    makeRow(
                        label = s.title.ifBlank { "Untitled Chat" },
                        sub = s.lastMessagePreview.take(48).ifBlank { "${s.messageCount} messages" },
                        selected = assistSessionId == s.id,
                    ) {
                        assistSessionId = s.id
                        lastMessageId = s.activeLeafId
                        chatSwitchChip?.text = "Chat: ${s.title.take(12)}"
                    }
                )
            }
            val scroller = ScrollView(uiContext).apply {
                addView(listCol)
            }
            card.addView(scroller, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(300f)))
            host.addView(
                card,
                FrameLayout.LayoutParams(dp(300f), FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER)
            )
            host.visibility = View.VISIBLE
        }
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        DevLogBuffer.add("INFO", "Assistant", "CelliumVoiceInteractionSession onShow (flags=$showFlags)")
        configureSessionWindow()
        rootContainer?.visibility = View.VISIBLE
        rootContainer?.requestLayout()
        WakeWordService.setPaused(context.applicationContext, true)
        isVisible = true
        isTypingMode = false
        bubbleIsRetryAction = false
        includeScreenVision = true
        clearAllCrops()
        drawOverlay?.drawEnabled = capturedScreenshot != null
        sendBtnView?.visibility = View.GONE
        inputEdit?.setText("")
        updateScreenChipAppearance()
        rebuildAttachmentPreviewStrip()

        scope.launch {
            runCatching {
                val prefs = PreferencesStore(context.applicationContext).preferencesFlow.first()
                if (::soundEngine.isInitialized) {
                    soundEngine.enabled = prefs.soundsEnabled
                    soundEngine.hapticsEnabled = prefs.hapticsEnabled
                    soundEngine.masterVolume = prefs.sfxVolume
                    soundEngine.startupSoundId = prefs.startupSoundId
                    soundEngine.startupSoundCustomPath = prefs.startupSoundCustomPath
                    soundEngine.startupSoundShuffleEnabled = prefs.startupSoundShuffleEnabled
                    soundEngine.startupSoundExcludedIds = prefs.startupSoundExcludedIds
                    soundEngine.deletedStartupSoundIds = prefs.deletedStartupSoundIds
                    soundEngine.playAssistantSummon()
                }
                faceView?.updateState(newGender = prefs.avatarGender, newMood = "happy")
            }
        }

        showListenRunnable?.let { mainHandler.removeCallbacks(it) }
        val r = Runnable {
            if (isVisible && !isTypingMode && croppedRegions.isEmpty()) {
                startListening()
            }
        }
        showListenRunnable = r
        mainHandler.postDelayed(r, 420L)
    }

    private fun cancelAllActiveWork() {
        showListenRunnable?.let { mainHandler.removeCallbacks(it) }
        showListenRunnable = null
        moodRelaxRunnable?.let { mainHandler.removeCallbacks(it) }
        moodRelaxRunnable = null
        cancelListeningQuietly()
        askJob?.cancel()
        askJob = null
        llmClient.cancelActiveRequests()
        if (::celliumTts.isInitialized) celliumTts.stop()
        faceView?.updateState(isListening = false, isMicReady = false, isTalking = false)
    }

    override fun onHide() {
        isVisible = false
        rootContainer?.visibility = View.GONE
        // 4h: Closing Cel IMMEDIATELY aborts any background LLM / STT / TTS work!
        cancelAllActiveWork()
        WakeWordService.setPaused(context.applicationContext, false)
        super.onHide()
    }

    override fun onDestroy() {
        isVisible = false
        cancelAllActiveWork()
        WakeWordService.setPaused(context.applicationContext, false)
        clearAllCrops()
        runCatching { speechRecognizer?.destroy() }
        if (::celliumTts.isInitialized) runCatching { celliumTts.release() }
        if (::soundEngine.isInitialized) runCatching { soundEngine.release() }
        scope.cancel()
        super.onDestroy()
    }

    private fun cancelListeningQuietly() {
        showListenRunnable?.let { mainHandler.removeCallbacks(it) }
        showListenRunnable = null
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = null
        deviceSpeechBuffer.clear()
        isListening = false
        sttLaunchJob?.cancel()
        sttLaunchJob = null
        cloudSttJob?.cancel()
        cloudSttJob = null
        if (::celliumStt.isInitialized) celliumStt.cancelRecording()
        mainHandler.post {
            runCatching { speechRecognizer?.cancel() }
            faceView?.updateState(isListening = false, isMicReady = false)
        }
    }

    private fun stopListeningForSubmit() {
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = null
        val buffered = deviceSpeechBuffer.toString().trim()
        if (buffered.isNotEmpty()) {
            deviceSpeechBuffer.clear()
            isListening = false
            mainHandler.post {
                runCatching { speechRecognizer?.cancel() }
                faceView?.updateState(isListening = false, isMicReady = false)
            }
            askCel(buffered)
            return
        }
        isListening = false
        if (::celliumStt.isInitialized) celliumStt.requestStopRecording()
        mainHandler.post {
            runCatching { speechRecognizer?.stopListening() }
            faceView?.updateState(isListening = false, isMicReady = false)
        }
    }

    private fun startListening() {
        if (!isVisible) return
        if (ContextCompat.checkSelfPermission(context.applicationContext, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            showBubble("Grant Microphone permission in Cel to speak, or type below.")
            return
        }
        if (::celliumTts.isInitialized) celliumTts.stop()
        cancelListeningQuietly()
        isListening = true
        bubbleIsRetryAction = false
        faceView?.updateState(newMood = "listening", isListening = true, isMicReady = false)
        showBubble("Starting mic...")

        sttLaunchJob = scope.launch {
            val appCtx = context.applicationContext
            val prefs = PreferencesStore(appCtx).preferencesFlow.first()
            if (!isListening || !isVisible || isTypingMode) return@launch
            val sttEngineId = prefs.sttEngine
            if (sttEngineId != CelliumSttEngine.ENGINE_DEVICE) {
                val opt = CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == sttEngineId }
                val providers = withContext(Dispatchers.IO) { CelliumDatabase.getInstance(appCtx).dao().getAllProviders() }
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
                        preSpeechTimeoutMs = 60_000L,
                        silenceAutoStopMs = 2_400L,
                        onReadyForSpeech = {
                            mainHandler.post {
                                if (isListening && isVisible && !isTypingMode) {
                                    faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                    showBubble("Listening...")
                                }
                            }
                        },
                        onTranscribing = {
                            mainHandler.post {
                                if (isVisible && !isTypingMode) {
                                    isListening = false
                                    faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                                    showBubble("Transcribing...")
                                }
                            }
                        },
                    )
                    isListening = false
                    if (!isVisible || isTypingMode) return@launch
                    res.onSuccess { rawTxt ->
                        val cleaned = CelliumSttEngine.sanitizeTranscript(rawTxt)
                        if (cleaned.isNotBlank()) {
                            askCel(cleaned)
                        } else {
                            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                            showBubble("Didn't catch that — tap Mic or type!")
                        }
                    }.onFailure {
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                        showBubble("Mic idle — tap Mic or type!")
                    }
                }
            } else {
                startDeviceSpeechRecognizer()
            }
        }
    }

    private fun buildDeviceSpeechIntent(): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2_500L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 2_500L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 60_000L)
    }

    private fun scheduleDeviceUtteranceFlush() {
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = scope.launch {
            delay(2_200L)
            if (!isVisible || isTypingMode) return@launch
            val combined = deviceSpeechBuffer.toString().trim()
            deviceSpeechBuffer.clear()
            isListening = false
            runCatching { speechRecognizer?.cancel() }
            if (combined.isNotEmpty()) {
                askCel(combined)
            } else {
                faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                showBubble("Didn't catch that — tap Mic or type!")
            }
        }
    }

    private fun startDeviceSpeechRecognizer() {
        mainHandler.post {
            if (!isVisible || isTypingMode) return@post
            runCatching {
                speechRecognizer?.destroy()
                val sr = CelliumSttEngine.createBestDeviceSpeechRecognizer(uiContext)
                    ?: throw IllegalStateException("No speech recognition service available")
                speechRecognizer = sr
                sr.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        mainHandler.post {
                            if (isListening && isVisible && !isTypingMode) {
                                faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                if (deviceSpeechBuffer.isEmpty()) showBubble("Listening...")
                            }
                        }
                    }
                    override fun onBeginningOfSpeech() {
                        // User resumed speaking during the 2.2s breath grace window — cancel pending flush!
                        deviceSilenceFlushJob?.cancel()
                        deviceSilenceFlushJob = null
                    }
                    override fun onRmsChanged(rmsdB: Float) {
                        if (rmsdB > 4.5f && deviceSilenceFlushJob != null && deviceSpeechBuffer.isNotEmpty()) {
                            scheduleDeviceUtteranceFlush()
                        }
                    }
                    override fun onBufferReceived(buffer: ByteArray?) = Unit
                    override fun onEndOfSpeech() {
                        if (isVisible && !isTypingMode && deviceSpeechBuffer.isEmpty()) {
                            faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                        }
                    }
                    override fun onError(error: Int) {
                        if (!isVisible || isTypingMode || !isListening) return
                        if (deviceSpeechBuffer.isNotEmpty()) {
                            // Still in 2.2s breath grace window — let flush timer finish sending!
                            if (deviceSilenceFlushJob?.isActive != true) scheduleDeviceUtteranceFlush()
                            return
                        }
                        isListening = false
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                    }
                    override fun onResults(results: Bundle?) {
                        if (!isVisible || isTypingMode || !isListening) return
                        val raw = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        val cleaned = CelliumSttEngine.sanitizeTranscript(raw)
                        if (cleaned.isNotEmpty()) {
                            if (deviceSpeechBuffer.isNotEmpty()) deviceSpeechBuffer.append(' ')
                            deviceSpeechBuffer.append(cleaned)
                            showBubble("\"${deviceSpeechBuffer}\"")
                            // Re-arm silently and wait 2.2s of true silence so catching breath never cuts off speech
                            scheduleDeviceUtteranceFlush()
                            mainHandler.postDelayed({
                                if (isVisible && !isTypingMode && isListening) {
                                    runCatching { speechRecognizer?.startListening(buildDeviceSpeechIntent()) }
                                }
                            }, 90L)
                        } else if (deviceSpeechBuffer.isNotEmpty()) {
                            if (deviceSilenceFlushJob?.isActive != true) scheduleDeviceUtteranceFlush()
                        } else {
                            isListening = false
                            faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                            showBubble("Didn't catch that — tap Mic or type!")
                        }
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        if (!isListening || !isVisible || isTypingMode) return
                        val p = CelliumSttEngine.sanitizeTranscript(
                            partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        )
                        if (p.isNotBlank()) {
                            if (deviceSilenceFlushJob != null) {
                                deviceSilenceFlushJob?.cancel()
                                deviceSilenceFlushJob = null
                            }
                            val preview = if (deviceSpeechBuffer.isNotEmpty()) "${deviceSpeechBuffer} $p" else p
                            showBubble("\"$preview\"")
                        }
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) = Unit
                })
                sr.startListening(buildDeviceSpeechIntent())
            }.onFailure {
                isListening = false
                faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                showBubble("Mic unavailable — type below or switch STT in Settings.")
            }
        }
    }

    private fun showBubble(text: String) {
        mainHandler.post {
            speechBubble?.apply {
                this.text = text
                visibility = View.VISIBLE
            }
        }
    }

    private fun saveBitmapsToAttachments(bitmaps: List<Bitmap>): String {
        if (bitmaps.isEmpty()) return ""
        val dir = File(context.applicationContext.filesDir, "attachments").apply { mkdirs() }
        val saved = ArrayList<String>(bitmaps.size)
        bitmaps.forEachIndexed { idx, bmp ->
            if (!bmp.isRecycled) {
                val outFile = File(dir, "assist_${System.currentTimeMillis()}_$idx.jpg")
                runCatching {
                    FileOutputStream(outFile).use { fos ->
                        bmp.compress(Bitmap.CompressFormat.JPEG, 88, fos)
                    }
                    saved.add(outFile.absolutePath)
                }
            }
        }
        return saved.joinToString("\n")
    }

    private fun askCel(userText: String, explicitBitmaps: List<Bitmap>? = null) {
        val cleanedUserText = userText.trim()
        if (cleanedUserText.isEmpty()) return
        cancelListeningQuietly()
        bubbleIsRetryAction = false
        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
        showBubble("Thinking...")

        val usedFullScreenThisTurn = explicitBitmaps == null && includeScreenVision &&
            capturedScreenshot != null && !capturedScreenshot!!.isRecycled
        val bitmapsToSend: List<Bitmap> = explicitBitmaps ?: buildList {
            val rawShot = capturedScreenshot
            if (includeScreenVision && rawShot != null && !rawShot.isRecycled) {
                add(rawShot)
            }
            croppedRegions.forEach { sel ->
                if (!sel.bitmap.isRecycled) {
                    sel.bitmap.copy(Bitmap.Config.ARGB_8888, false)?.let { add(it) }
                }
            }
        }
        val cropCount = croppedRegions.size
        if (explicitBitmaps == null && croppedRegions.isNotEmpty()) {
            clearAllCrops()
        }
        // #2a: After sending 1st message with a screenshot, auto-switch Full Screen OFF so follow-ups don't re-upload it
        if (usedFullScreenThisTurn) {
            includeScreenVision = false
            mainHandler.post {
                updateScreenChipAppearance()
                rebuildAttachmentPreviewStrip()
            }
        }

        val effectivePrompt = when {
            cropCount > 0 && usedFullScreenThisTurn ->
                "[User attached full screen + $cropCount circled cropped region(s). Focus closely on the cropped regions!] $cleanedUserText"
            cropCount > 0 ->
                "[User circled and cropped $cropCount specific region(s) from their screen — answer specifically about these cropped image(s)!] $cleanedUserText"
            else -> cleanedUserText
        }

        askJob?.cancel()
        askJob = scope.launch {
            try {
                val appCtx = context.applicationContext
                val prefs = PreferencesStore(appCtx).preferencesFlow.first()
                val dao = CelliumDatabase.getInstance(appCtx).dao()
                val prov = dao.getProvider(prefs.activeProviderId)
                    ?: dao.getAllProviders().firstOrNull { it.protocol != "on_device" }
                    ?: ProviderPresets.defaultProfiles().first()
                val personas = dao.getAllPersonasOnce().map {
                    CustomPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
                }
                // #9: Always respect active session persona or user's currently selected default persona!
                val activeSession = assistSessionId?.let { dao.getSession(it) }
                val personaId = activeSession?.personaId?.ifBlank { prefs.defaultPersonaId } ?: prefs.defaultPersonaId
                val persona = BuiltInPersonas.resolve(personaId, personas)
                val memories = dao.getAllMemoriesOnce()

                val sid = assistSessionId ?: UUID.randomUUID().toString().also { newSid ->
                    assistSessionId = newSid
                    dao.upsertSession(
                        SessionEntity(
                            id = newSid,
                            title = "Assistant · ${cleanedUserText.take(28)}",
                            personaId = persona.id,
                            providerId = prov.id,
                            modelName = prov.selectedModel,
                        )
                    )
                    mainHandler.post { chatSwitchChip?.text = "Chat: ${cleanedUserText.take(10)}" }
                }

                // 4k: Persist attached screenshots & crops to disk so they appear in Chat!
                val savedAttachmentPaths = withContext(Dispatchers.IO) {
                    saveBitmapsToAttachments(bitmapsToSend)
                }

                val priorHistory = dao.getMessagesForSessionOnce(sid)
                val userMsgId = UUID.randomUUID().toString()
                dao.upsertMessage(
                    MessageEntity(
                        id = userMsgId,
                        sessionId = sid,
                        parentId = lastMessageId ?: priorHistory.lastOrNull()?.id,
                        role = "user",
                        content = cleanedUserText,
                        attachmentPath = savedAttachmentPaths,
                        tokenEstimate = ProviderPresets.estimateTokens(cleanedUserText),
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
                    extraInstruction = "[Default Android Assistant] Answer crisply in 1 to 3 spoken sentences without markdown symbols.",
                )

                // 4m: Quiet agentic loop (up to 3 device action steps before final spoken answer)
                var currentHistory = priorHistory.takeLast(14).toMutableList()
                var currentPrompt = effectivePrompt
                var currentImages = bitmapsToSend
                var finalRawReply = ""

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
                                history = currentHistory,
                                userPrompt = currentPrompt,
                                imageBitmaps = currentImages,
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
                            showBubble("Busy — retrying ($attempt/$maxRetries)...")
                            delay(1200L * attempt)
                        }
                    }

                    val (_, cleanStep) = ProviderPresets.parseThoughts(sb.toString())
                    val actions = AndroidDeviceActions.extractActionPayloads(cleanStep)
                    val (webQuery, _) = UniversalLlmClient.extractWebSearchQuery(cleanStep)
                    if ((actions.isNotEmpty() || !webQuery.isNullOrBlank()) && step < 2) {
                        val resultsText = buildString {
                            if (actions.isNotEmpty()) {
                                showBubble("Running action...")
                                faceView?.updateState(newMood = "working", newGender = prefs.avatarGender)
                                for (payload in actions.take(3)) {
                                    val res = AndroidDeviceActions.executePayload(appCtx, payload, webTools)
                                    appendLine("[DEVICE_ACTION_RESULT (${res.action}, success=${res.success})]: ${res.output}")
                                }
                            }
                            if (!webQuery.isNullOrBlank()) {
                                showBubble("Searching web...")
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
                        currentHistory.add(
                            MessageEntity(
                                id = UUID.randomUUID().toString(),
                                sessionId = sid,
                                role = "user",
                                content = currentPrompt,
                            )
                        )
                        currentHistory.add(
                            MessageEntity(
                                id = UUID.randomUUID().toString(),
                                sessionId = sid,
                                role = "assistant",
                                content = cleanStep,
                            )
                        )
                        currentPrompt = "$resultsText\nNow give your concise natural spoken answer to the user. Do NOT emit another [DEVICE_ACTION] or [WEB_SEARCH] tag."
                        currentImages = emptyList()
                        showBubble("Thinking...")
                    } else {
                        finalRawReply = UniversalLlmClient.sanitizeVisibleReply(cleanStep)
                        break
                    }
                }

                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(finalRawReply)
                val reply = UniversalLlmClient.sanitizeVisibleReply(finalBody.ifBlank { finalRawReply }).ifBlank { "All set!" }
                val mood = tagMood ?: MoodDetector.detectMood(reply)

                val assistantMsgId = UUID.randomUUID().toString()
                lastMessageId = assistantMsgId
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

                lastFailedPrompt = null
                lastFailedImages = emptyList()

                if (!isVisible) return@launch
                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender)

                // 4j & 4t: Hold text reveal until voice audio starts playing (or typewriter for Synth!)
                val voiceEngine = prefs.liveTtsEngine
                val voiceName = prefs.liveTtsVoiceName
                val voicePitch = prefs.liveTtsPitch
                val voiceRate = prefs.liveTtsSpeechRate
                val isSynth = voiceEngine.equals(CelliumTtsEngine.ENGINE_SYNTH, ignoreCase = true)

                if (!isSynth) {
                    showBubble("Preparing voice...")
                } else {
                    showBubble("")
                }

                if (::celliumTts.isInitialized) {
                    celliumTts.speak(
                        rawText = reply,
                        engine = voiceEngine,
                        voiceName = voiceName,
                        pitch = voicePitch,
                        speechRate = voiceRate,
                        onStart = {
                            mainHandler.post {
                                if (!isVisible) return@post
                                faceView?.updateState(isTalking = true)
                                if (!isSynth) showBubble(reply)
                            }
                        },
                        onSynthCharProgress = if (isSynth) { count ->
                            if (isVisible) showBubble(reply.take(count))
                        } else null,
                        onComplete = {
                            mainHandler.post {
                                faceView?.updateState(isTalking = false)
                                if (isVisible) showBubble(reply)
                                // #2d: Hold emotional expression naturally before relaxing back to idle
                                moodRelaxRunnable?.let { mainHandler.removeCallbacks(it) }
                                val r = Runnable {
                                    if (isVisible && !isListening) {
                                        faceView?.updateState(newMood = "idle")
                                    }
                                }
                                moodRelaxRunnable = r
                                mainHandler.postDelayed(r, ExpressionDirector.holdDurationMsForMood(mood))
                            }
                        },
                    )
                } else {
                    showBubble(reply)
                }
            } catch (ce: CancellationException) {
                // Aborted cleanly on close/hide
            } catch (e: Exception) {
                // 4v: Preserve prompt + images so user can tap bubble to retry when back online!
                lastFailedPrompt = cleanedUserText
                lastFailedImages = bitmapsToSend
                bubbleIsRetryAction = true
                faceView?.updateState(newMood = "error")
                showBubble("Offline/Error: ${e.localizedMessage?.take(90) ?: "Request failed"}\nTap here to Retry")
            }
        }
    }
}

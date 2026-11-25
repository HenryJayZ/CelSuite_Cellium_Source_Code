package com.henny.cellium.assistant

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
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
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.core.ContextModifyConfig
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
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
 */
class CelliumVoiceInteractionService : VoiceInteractionService() {
    override fun onReady() {
        super.onReady()
    }

    override fun onLaunchVoiceAssistFromKeyguard() {
        showSession(
            Bundle(),
            VoiceInteractionSession.SHOW_WITH_ASSIST or VoiceInteractionSession.SHOW_WITH_SCREENSHOT,
        )
    }
}

class CelliumVoiceInteractionSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession =
        CelliumVoiceInteractionSession(this)
}

/**
 * Full-screen transparent freehand neon drawing canvas (Gemini Circle/Draw-to-Focus style)
 * allowing the user to circle or underline anything on screen to tell Cel exactly where to look.
 */
private class ScreenHighlightOverlayView(
    context: Context,
    private val onStrokesChanged: (Boolean) -> Unit,
) : View(context) {

    var drawEnabled: Boolean = false
        set(value) {
            field = value
            invalidate()
        }

    // Store normalized strokes (pairs of x/w, y/h) so compositing onto any screenshot resolution is pixel-accurate!
    private val strokes = ArrayList<ArrayList<Pair<Float, Float>>>()
    private var currentStroke: ArrayList<Pair<Float, Float>>? = null
    private val drawPath = Path()

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
    private val frameBorderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 8f
        color = Color.argb(150, 192, 132, 252)
    }

    fun hasStrokes(): Boolean = strokes.isNotEmpty()

    fun clearStrokes() {
        strokes.clear()
        currentStroke = null
        onStrokesChanged(false)
        invalidate()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!drawEnabled) return false
        val w = width.toFloat().coerceAtLeast(1f)
        val h = height.toFloat().coerceAtLeast(1f)
        val nx = (event.x / w).coerceIn(0f, 1f)
        val ny = (event.y / h).coerceIn(0f, 1f)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                val stroke = ArrayList<Pair<Float, Float>>(32)
                stroke.add(nx to ny)
                strokes.add(stroke)
                currentStroke = stroke
                onStrokesChanged(true)
                invalidate()
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                currentStroke?.add(nx to ny)
                invalidate()
                return true
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                currentStroke = null
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
        if (drawEnabled) {
            canvas.drawRect(4f, 4f, w - 4f, h - 4f, frameBorderPaint)
        }
        drawAllStrokes(canvas, w, h)
    }

    private fun drawAllStrokes(canvas: Canvas, w: Float, h: Float) {
        val baseStroke = (minOf(w, h) * 0.012f).coerceIn(7f, 16f)
        outerGlowPaint.strokeWidth = baseStroke * 2.6f
        midGlowPaint.strokeWidth = baseStroke * 1.4f
        corePaint.strokeWidth = baseStroke * 0.52f

        for (pts in strokes) {
            if (pts.isEmpty()) continue
            drawPath.reset()
            val first = pts[0]
            drawPath.moveTo(first.first * w, first.second * h)
            if (pts.size == 1) {
                drawPath.lineTo(first.first * w + 1f, first.second * h + 1f)
            } else {
                for (i in 1 until pts.size) {
                    val prev = pts[i - 1]
                    val curr = pts[i]
                    val mx = (prev.first + curr.first) * 0.5f * w
                    val my = (prev.second + curr.second) * 0.5f * h
                    drawPath.quadTo(prev.first * w, prev.second * h, mx, my)
                }
                val last = pts.last()
                drawPath.lineTo(last.first * w, last.second * h)
            }
            canvas.drawPath(drawPath, outerGlowPaint)
            canvas.drawPath(drawPath, midGlowPaint)
            canvas.drawPath(drawPath, corePaint)
        }
    }

    /**
     * Composites the user's drawn glowing highlights onto a mutable copy of [source] screenshot.
     */
    fun compositeOntoScreenshot(source: Bitmap): Bitmap {
        if (strokes.isEmpty()) return source
        val maxSide = 1080
        val scale = minOf(maxSide.toFloat() / source.width, maxSide.toFloat() / source.height, 1f)
        val outW = (source.width * scale).toInt().coerceAtLeast(1)
        val outH = (source.height * scale).toInt().coerceAtLeast(1)
        val scaled = if (scale < 1f) Bitmap.createScaledBitmap(source, outW, outH, true) else source
        val mutable = scaled.copy(Bitmap.Config.ARGB_8888, true)
        if (scaled !== source) scaled.recycle()
        val canvas = Canvas(mutable)
        drawAllStrokes(canvas, mutable.width.toFloat(), mutable.height.toFloat())
        return mutable
    }
}

/**
 * Gemini-style transparent Assistant overlay right over the current app:
 * - WindowInsets-aware bottom input bar (never overlaps 3-button Android navigation bars!)
 * - Plays shimmering heavenly summon chime on open
 * - Interactive Gemini-style Draw / Circle on Screen highlight mode composited onto the screenshot
 * - "Go Live" chip jumps straight into Floating Cel hands-free live mode
 * - Uses user's selected Edge Neural / Google / System TTS (emoji-free) & Cloud/Device STT
 */
class CelliumVoiceInteractionSession(context: Context) : VoiceInteractionSession(context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val llmClient = UniversalLlmClient()

    private var faceView: AssistantDotFaceView? = null
    private var speechBubble: TextView? = null
    private var screenChip: TextView? = null
    private var drawChip: TextView? = null
    private var clearDrawChip: TextView? = null
    private var drawOverlay: ScreenHighlightOverlayView? = null
    private var inputEdit: EditText? = null
    private var capturedScreenshot: Bitmap? = null
    private var includeScreenVision = true
    private var drawModeActive = false

    private var speechRecognizer: SpeechRecognizer? = null
    private var cloudSttJob: Job? = null
    private lateinit var soundEngine: CelliumSoundEngine
    private lateinit var celliumTts: CelliumTtsEngine
    private lateinit var celliumStt: CelliumSttEngine
    private var isListening = false
    private var assistSessionId: String? = null
    private var lastMessageId: String? = null

    private fun dp(v: Float): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, context.resources.displayMetrics
    ).toInt()

    override fun onCreate() {
        super.onCreate()
        soundEngine = CelliumSoundEngine(context)
        celliumTts = CelliumTtsEngine(context)
        celliumStt = CelliumSttEngine(context)
    }

    override fun onHandleScreenshot(screenshot: Bitmap?) {
        super.onHandleScreenshot(screenshot)
        capturedScreenshot = screenshot
        mainHandler.post {
            screenChip?.apply {
                visibility = if (screenshot != null) View.VISIBLE else View.GONE
                text = if (includeScreenVision) "Screen Attached" else "Screen Off"
            }
            drawChip?.visibility = if (screenshot != null) View.VISIBLE else View.GONE
        }
    }

    override fun onCreateContentView(): View {
        val root = FrameLayout(context).apply {
            setBackgroundColor(Color.argb(95, 4, 3, 10))
            setOnClickListener {
                if (!drawModeActive) hide()
            }
        }

        // Full-screen Gemini-style Draw/Circle canvas behind controls
        val overlay = ScreenHighlightOverlayView(context) { hasStrokes ->
            clearDrawChip?.visibility = if (hasStrokes) View.VISIBLE else View.GONE
            if (hasStrokes) {
                includeScreenVision = true
                screenChip?.text = "Screen Attached"
                screenChip?.setTextColor(Color.parseColor("#D8B4FE"))
            }
        }
        drawOverlay = overlay
        root.addView(
            overlay,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        )

        val celRow = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setOnClickListener { /* consume */ }
        }

        val faceSize = dp(92f)
        val face = AssistantDotFaceView(context).apply {
            layoutParams = LinearLayout.LayoutParams(faceSize, faceSize)
        }
        faceView = face

        val bubble = TextView(context).apply {
            text = "Hey! Ask me anything, circle on screen, or tap to speak."
            setTextColor(Color.parseColor("#F5F0FF"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
            setPadding(dp(14f), dp(10f), dp(14f), dp(10f))
            maxWidth = dp(235f)
            background = GradientDrawable().apply {
                setColor(Color.argb(235, 16, 12, 30))
                cornerRadius = dp(18f).toFloat()
                setStroke(dp(1f), Color.argb(180, 192, 132, 252))
            }
            setOnClickListener { visibility = View.GONE }
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

        val baseCelBottomMargin = dp(122f)
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
                        if (isListening) stopListening() else startListening()
                    }
                    true
                }
                else -> false
            }
        }
        root.addView(celRow, celLp)

        val baseBottomPad = dp(18f)
        val bottomCol = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14f), dp(8f), dp(14f), baseBottomPad)
            setOnClickListener { /* consume */ }
        }

        val chipRow = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
        }

        fun chipBg(fill: Int, stroke: Int): GradientDrawable = GradientDrawable().apply {
            setColor(fill)
            cornerRadius = dp(14f).toFloat()
            setStroke(dp(1f), stroke)
        }

        val sChip = TextView(context).apply {
            text = "Screen Attached"
            setTextColor(Color.parseColor("#D8B4FE"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = chipBg(Color.argb(215, 28, 18, 48), Color.argb(165, 192, 132, 252))
            visibility = if (capturedScreenshot != null) View.VISIBLE else View.GONE
            setOnClickListener {
                soundEngine.playClick()
                includeScreenVision = !includeScreenVision
                text = if (includeScreenVision) "Screen Attached" else "Screen Off"
                setTextColor(if (includeScreenVision) Color.parseColor("#D8B4FE") else Color.parseColor("#9A90B0"))
            }
        }
        screenChip = sChip

        val dChip = TextView(context).apply {
            text = "Circle"
            setTextColor(Color.parseColor("#38BDF8"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = chipBg(Color.argb(215, 14, 34, 52), Color.argb(175, 56, 189, 248))
            visibility = if (capturedScreenshot != null) View.VISIBLE else View.GONE
            setOnClickListener {
                soundEngine.playClick()
                drawModeActive = !drawModeActive
                drawOverlay?.drawEnabled = drawModeActive
                text = if (drawModeActive) "Drawing ON" else "Circle"
                background = if (drawModeActive) {
                    chipBg(Color.argb(235, 34, 88, 128), Color.argb(240, 125, 211, 252))
                } else {
                    chipBg(Color.argb(215, 14, 34, 52), Color.argb(175, 56, 189, 248))
                }
                if (drawModeActive) {
                    includeScreenVision = true
                    screenChip?.text = "Screen Attached"
                    showBubble("Draw or circle what you want me to look at, then ask!")
                }
            }
        }
        drawChip = dChip

        val clrChip = TextView(context).apply {
            text = "Clear"
            setTextColor(Color.parseColor("#FCA5A5"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(9f), dp(6f), dp(9f), dp(6f))
            background = chipBg(Color.argb(215, 56, 16, 24), Color.argb(175, 248, 113, 113))
            visibility = View.GONE
            setOnClickListener {
                soundEngine.playClick()
                drawOverlay?.clearStrokes()
            }
        }
        clearDrawChip = clrChip

        val liveChip = TextView(context).apply {
            text = "Go Live"
            setTextColor(Color.parseColor("#34D399"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(11f), dp(6f), dp(11f), dp(6f))
            background = chipBg(Color.argb(220, 10, 46, 36), Color.argb(185, 52, 211, 153))
            setOnClickListener {
                soundEngine.playOpen()
                if (Settings.canDrawOverlays(context)) {
                    FloatingCelOverlayService.start(
                        context = context.applicationContext,
                        autoListen = true,
                        enableHandsFree = true,
                        requestScreenVision = includeScreenVision,
                    )
                    hide()
                } else {
                    showBubble("Grant 'Display over other apps' so Cel can float live!")
                    runCatching {
                        context.startActivity(
                            Intent(
                                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:${context.packageName}"),
                            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                    }
                }
            }
        }

        val chipLp = {
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { rightMargin = dp(7f) }
        }
        chipRow.addView(sChip, chipLp())
        chipRow.addView(dChip, chipLp())
        chipRow.addView(clrChip, chipLp())
        chipRow.addView(liveChip, chipLp())

        bottomCol.addView(
            chipRow,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { bottomMargin = dp(8f) }
        )

        val pill = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(12f), dp(8f), dp(10f), dp(8f))
            background = GradientDrawable().apply {
                setColor(Color.argb(242, 14, 10, 26))
                cornerRadius = dp(26f).toFloat()
                setStroke(dp(1.2f), Color.argb(190, 192, 132, 252))
            }
        }

        val micBtn = TextView(context).apply {
            text = "Mic"
            setTextColor(Color.parseColor("#C084FC"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnClickListener {
                soundEngine.playClick()
                if (isListening) stopListening() else startListening()
            }
        }

        val edit = EditText(context).apply {
            hint = "Ask Cel about this screen..."
            setHintTextColor(Color.parseColor("#8A80A4"))
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f)
            background = null
            isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEND
            setPadding(dp(8f), dp(6f), dp(8f), dp(6f))
            setOnEditorActionListener { _, actionId, _ ->
                if (actionId == EditorInfo.IME_ACTION_SEND) {
                    val q = text.toString().trim()
                    if (q.isNotEmpty()) {
                        setText("")
                        askCel(q)
                    }
                    true
                } else false
            }
        }
        inputEdit = edit

        val sendBtn = TextView(context).apply {
            text = "Ask"
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
            setPadding(dp(14f), dp(7f), dp(14f), dp(7f))
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#A855F7"))
                cornerRadius = dp(18f).toFloat()
            }
            setOnClickListener {
                soundEngine.playSend()
                val q = edit.text.toString().trim()
                if (q.isNotEmpty()) {
                    edit.setText("")
                    askCel(q)
                }
            }
        }

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

        // WindowInsets listener: guarantees chat bar sits cleanly ABOVE 3-button nav bar & rises with IME!
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

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        drawModeActive = false
        drawOverlay?.drawEnabled = false
        drawOverlay?.clearStrokes()
        drawChip?.text = "Circle"
        scope.launch {
            val prefs = PreferencesStore(context.applicationContext).preferencesFlow.first()
            soundEngine.enabled = prefs.soundsEnabled
            soundEngine.hapticsEnabled = prefs.hapticsEnabled
            soundEngine.masterVolume = prefs.sfxVolume
            soundEngine.playAssistantSummon()
            faceView?.updateState(newGender = prefs.avatarGender, newMood = "happy")
        }
        mainHandler.postDelayed({ startListening() }, 360L)
    }

    override fun onHide() {
        stopListening()
        if (::celliumTts.isInitialized) celliumTts.stop()
        super.onHide()
    }

    override fun onDestroy() {
        stopListening()
        cloudSttJob?.cancel()
        runCatching { speechRecognizer?.destroy() }
        if (::celliumTts.isInitialized) runCatching { celliumTts.release() }
        if (::soundEngine.isInitialized) runCatching { soundEngine.release() }
        scope.cancel()
        super.onDestroy()
    }

    private fun startListening() {
        if (::celliumTts.isInitialized) celliumTts.stop()
        cloudSttJob?.cancel()
        isListening = true
        faceView?.updateState(newMood = "listening", isListening = true, isMicReady = false)
        showBubble("Starting mic...")

        scope.launch {
            val appCtx = context.applicationContext
            val prefs = PreferencesStore(appCtx).preferencesFlow.first()
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
                        silenceAutoStopMs = 3_500L,
                        onReadyForSpeech = {
                            mainHandler.post {
                                if (isListening) {
                                    faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                                    showBubble("Listening...")
                                }
                            }
                        },
                        onTranscribing = {
                            mainHandler.post {
                                isListening = false
                                faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
                                showBubble("Transcribing...")
                            }
                        },
                    )
                    isListening = false
                    res.onSuccess { txt ->
                        if (txt.isNotBlank()) askCel(txt) else faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                    }.onFailure {
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
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
                val sr = SpeechRecognizer.createSpeechRecognizer(context)
                speechRecognizer = sr
                sr.setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        mainHandler.post {
                            faceView?.updateState(newMood = "listening", isListening = true, isMicReady = true)
                            showBubble("Listening...")
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
                        faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                    }
                    override fun onResults(results: Bundle?) {
                        isListening = false
                        val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                        if (text.isNotEmpty()) askCel(text) else faceView?.updateState(newMood = "idle", isListening = false, isMicReady = false)
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        val p = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        if (p.isNotBlank()) showBubble("\"$p\"")
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) = Unit
                })
                sr.startListening(
                    Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3500L)
                        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 3500L)
                    }
                )
            }
        }
    }

    private fun stopListening() {
        isListening = false
        if (::celliumStt.isInitialized) celliumStt.requestStopRecording()
        runCatching { speechRecognizer?.stopListening() }
        faceView?.updateState(isListening = false, isMicReady = false)
    }

    private fun showBubble(text: String) {
        mainHandler.post {
            speechBubble?.apply {
                this.text = text
                visibility = View.VISIBLE
            }
        }
    }

    private fun askCel(userText: String) {
        faceView?.updateState(newMood = "thinking", isListening = false, isMicReady = false)
        showBubble("Thinking...")

        val hadHighlights = drawOverlay?.hasStrokes() == true
        val rawScreenshot = capturedScreenshot
        val bmpToSend: Bitmap? = when {
            !includeScreenVision || rawScreenshot == null -> null
            hadHighlights -> drawOverlay?.compositeOntoScreenshot(rawScreenshot)
            else -> rawScreenshot
        }
        if (hadHighlights) {
            drawOverlay?.clearStrokes()
            drawModeActive = false
            drawOverlay?.drawEnabled = false
            drawChip?.text = "Circle"
        }

        val effectivePrompt = if (hadHighlights && bmpToSend != null) {
            "[The user circled/highlighted a specific region on this screen in glowing violet/cyan — focus ONLY on what they highlighted!] $userText"
        } else {
            userText
        }

        scope.launch {
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
                val latestNonArena = dao.getAllSessionsOnce().firstOrNull { !it.isArena && !it.isLocked }
                val personaId = latestNonArena?.personaId?.ifBlank { prefs.defaultPersonaId } ?: prefs.defaultPersonaId
                val persona = BuiltInPersonas.resolve(personaId, personas)
                val memories = dao.getAllMemoriesOnce()

                val sid = assistSessionId ?: UUID.randomUUID().toString().also { newSid ->
                    assistSessionId = newSid
                    dao.upsertSession(
                        SessionEntity(
                            id = newSid,
                            title = "Assistant · ${userText.take(32)}",
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
                        parentId = lastMessageId ?: priorHistory.lastOrNull()?.id,
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
                    extraInstruction = "[Default Android Assistant] Answer crisply in 1 to 3 spoken sentences without markdown symbols.",
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
                            userPrompt = effectivePrompt,
                            imageBitmap = bmpToSend,
                        ).collect { chunk ->
                            if (chunk.contentDelta.isNotEmpty()) {
                                sb.append(chunk.contentDelta)
                                val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                                val (tagMood, body) = MoodDetector.extractInlineMoodTag(clean)
                                if (tagMood != null) faceView?.updateState(newMood = tagMood, newGender = prefs.avatarGender)
                                if (body.isNotBlank()) showBubble(body)
                            }
                        }
                        break
                    } catch (e: Exception) {
                        if (!UniversalLlmClient.isRetryableError(e) || attempt >= maxRetries) throw e
                        attempt++
                        showBubble("Busy — retrying ($attempt/$maxRetries)...")
                        delay(1200L * attempt)
                    }
                }
                if (bmpToSend != null && bmpToSend !== rawScreenshot) {
                    bmpToSend.recycle()
                }

                val (_, cleanFinal) = ProviderPresets.parseThoughts(sb.toString())
                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(cleanFinal)
                val reply = finalBody.ifBlank { cleanFinal.ifBlank { "All set!" } }
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

                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender)
                showBubble(reply)
                if (::celliumTts.isInitialized) {
                    celliumTts.speak(
                        rawText = reply,
                        engine = prefs.ttsEngine,
                        voiceName = prefs.ttsVoiceName,
                        pitch = prefs.ttsPitch,
                        speechRate = prefs.ttsSpeechRate,
                        onStart = { mainHandler.post { faceView?.updateState(isTalking = true) } },
                        onComplete = { mainHandler.post { faceView?.updateState(isTalking = false) } },
                    )
                }
            } catch (e: Exception) {
                faceView?.updateState(newMood = "error")
                showBubble("Error: ${e.localizedMessage ?: "Assistant failed"}")
            }
        }
    }
}

package com.henny.cellium.assistant

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.PreferencesStore
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.data.CustomPersona
import com.henny.cellium.data.local.CelliumDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.abs

/**
 * Default Digital Assistant Service for Android (Gemini replacement).
 * Registered via Settings -> Apps -> Default Apps -> Digital Assistant App -> Cellium.
 */
class CelliumVoiceInteractionService : VoiceInteractionService() {
    override fun onReady() {
        super.onReady()
    }
}

class CelliumVoiceInteractionSessionService : VoiceInteractionSessionService() {
    override fun onNewSession(args: Bundle?): VoiceInteractionSession =
        CelliumVoiceInteractionSession(this)
}

/**
 * Gemini-style transparent Assistant overlay right over the current app:
 * - Movable animated Cel dot-matrix face with tap-to-hide speech bubble right beside her
 * - Captures current screen via Android onHandleScreenshot() with toggleable Screen Vision chip
 * - Sleek bottom pill bar for typing, mic toggle, screen vision toggle, and dismiss
 */
class CelliumVoiceInteractionSession(context: Context) : VoiceInteractionSession(context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val llmClient = UniversalLlmClient()

    private var faceView: AssistantDotFaceView? = null
    private var speechBubble: TextView? = null
    private var screenChip: TextView? = null
    private var inputEdit: EditText? = null
    private var capturedScreenshot: Bitmap? = null
    private var includeScreenVision = true

    private var speechRecognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var isListening = false

    private fun dp(v: Float): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, context.resources.displayMetrics
    ).toInt()

    override fun onCreate() {
        super.onCreate()
        tts = TextToSpeech(context) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) {
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {
                        mainHandler.post { faceView?.updateState(isTalking = true) }
                    }
                    override fun onDone(utteranceId: String?) {
                        mainHandler.post { faceView?.updateState(isTalking = false) }
                    }
                    @Deprecated("Deprecated in Java")
                    override fun onError(utteranceId: String?) {
                        mainHandler.post { faceView?.updateState(isTalking = false) }
                    }
                })
            }
        }
    }

    override fun onHandleScreenshot(screenshot: Bitmap?) {
        super.onHandleScreenshot(screenshot)
        capturedScreenshot = screenshot
        mainHandler.post {
            screenChip?.apply {
                visibility = if (screenshot != null) View.VISIBLE else View.GONE
                text = if (includeScreenVision) "Screen Attached" else "Screen Off"
            }
        }
    }

    override fun onCreateContentView(): View {
        val root = FrameLayout(context).apply {
            setBackgroundColor(Color.argb(90, 4, 3, 10))
            setOnClickListener { hide() }
        }

        // Movable Cel floating face + adjacent tap-to-hide speech bubble
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
            text = "Hey! Ask me anything or tap to speak."
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

        val celLp = FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.START
            leftMargin = dp(16f)
            bottomMargin = dp(112f)
        }

        // Make Cel row smoothly draggable anywhere on screen
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

        // Bottom Gemini-style pill composer
        val bottomCol = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14f), dp(8f), dp(14f), dp(22f))
            setOnClickListener { /* consume */ }
        }

        val chipRow = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.START
        }
        val sChip = TextView(context).apply {
            text = "Screen Attached"
            setTextColor(Color.parseColor("#D8B4FE"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            setPadding(dp(10f), dp(5f), dp(10f), dp(5f))
            background = GradientDrawable().apply {
                setColor(Color.argb(215, 28, 18, 48))
                cornerRadius = dp(14f).toFloat()
                setStroke(dp(1f), Color.argb(160, 192, 132, 252))
            }
            visibility = if (capturedScreenshot != null) View.VISIBLE else View.GONE
            setOnClickListener {
                includeScreenVision = !includeScreenVision
                text = if (includeScreenVision) "Screen Attached" else "Screen Off"
                setTextColor(if (includeScreenVision) Color.parseColor("#D8B4FE") else Color.parseColor("#9A90B0"))
            }
        }
        screenChip = sChip
        chipRow.addView(sChip)
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
            setOnClickListener { if (isListening) stopListening() else startListening() }
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

        return root
    }

    override fun onShow(args: Bundle?, showFlags: Int) {
        super.onShow(args, showFlags)
        scope.launch {
            val prefs = PreferencesStore(context.applicationContext).preferencesFlow.first()
            faceView?.updateState(newGender = prefs.avatarGender, newMood = "happy")
        }
        mainHandler.postDelayed({ startListening() }, 280L)
    }

    override fun onHide() {
        stopListening()
        tts?.stop()
        super.onHide()
    }

    override fun onDestroy() {
        stopListening()
        runCatching { speechRecognizer?.destroy() }
        runCatching { tts?.stop(); tts?.shutdown() }
        scope.cancel()
        super.onDestroy()
    }

    private fun startListening() {
        tts?.stop()
        isListening = true
        faceView?.updateState(newMood = "listening", isListening = true)
        showBubble("Listening...")
        runCatching {
            speechRecognizer?.destroy()
            val sr = SpeechRecognizer.createSpeechRecognizer(context)
            speechRecognizer = sr
            sr.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() {
                    isListening = false
                    faceView?.updateState(newMood = "thinking", isListening = false)
                }
                override fun onError(error: Int) {
                    isListening = false
                    faceView?.updateState(newMood = "idle", isListening = false)
                }
                override fun onResults(results: Bundle?) {
                    isListening = false
                    val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                    if (text.isNotEmpty()) askCel(text) else faceView?.updateState(newMood = "idle", isListening = false)
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
                }
            )
        }
    }

    private fun stopListening() {
        isListening = false
        runCatching { speechRecognizer?.stopListening() }
        faceView?.updateState(isListening = false)
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
        faceView?.updateState(newMood = "thinking", isListening = false)
        showBubble("Thinking...")
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
                val persona = BuiltInPersonas.resolve(prefs.defaultPersonaId, personas)
                val memories = dao.getAllMemoriesOnce()
                val bmp = if (includeScreenVision) capturedScreenshot else null

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
                llmClient.streamChat(
                    provider = prov,
                    systemPrompt = sysPrompt,
                    history = emptyList(),
                    userPrompt = userText,
                    imageBitmap = bmp,
                ).collect { chunk ->
                    if (chunk.contentDelta.isNotEmpty()) {
                        sb.append(chunk.contentDelta)
                        val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                        val (tagMood, body) = MoodDetector.extractInlineMoodTag(clean)
                        if (tagMood != null) faceView?.updateState(newMood = tagMood, newGender = prefs.avatarGender)
                        if (body.isNotBlank()) showBubble(body)
                    }
                }
                val (_, cleanFinal) = ProviderPresets.parseThoughts(sb.toString())
                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(cleanFinal)
                val reply = finalBody.ifBlank { cleanFinal.ifBlank { "All set!" } }
                val mood = tagMood ?: MoodDetector.detectMood(reply)
                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender)
                showBubble(reply)
                if (ttsReady) {
                    tts?.apply {
                        language = Locale.getDefault()
                        if (prefs.ttsVoiceName.isNotBlank()) {
                            voices?.firstOrNull { it.name == prefs.ttsVoiceName }?.let { voice = it }
                        }
                        setPitch(prefs.ttsPitch.coerceIn(0.6f, 1.8f))
                        setSpeechRate(prefs.ttsSpeechRate.coerceIn(0.6f, 1.8f))
                        speak(reply, TextToSpeech.QUEUE_FLUSH, null, "cel_assist_${System.currentTimeMillis()}")
                    }
                }
            } catch (e: Exception) {
                faceView?.updateState(newMood = "error")
                showBubble("Error: ${e.localizedMessage ?: "Assistant failed"}")
            }
        }
    }
}

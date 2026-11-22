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
import android.graphics.Color
import android.graphics.PixelFormat
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
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
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
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.DevLogBuffer
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
import kotlinx.coroutines.withContext
import java.util.Locale
import kotlin.math.abs

private const val OVERLAY_CHANNEL_ID = "cellium_floating_cel"
private const val OVERLAY_NOTIF_ID = 4109

/**
 * True System-Wide Floating Cel Overlay (WindowManager TYPE_APPLICATION_OVERLAY).
 * Floats over the Home Screen and EVERY Android app!
 * - Movable animated dot-matrix face (no "Mini-Cel" label!)
 * - Tap face to start/stop listening; replies via TTS + tap-to-hide floating speech bubble right beside Cel
 * - Optional Live Screen Vision toggle using MediaProjection single-frame screenshot grab
 * - Compact expandable bottom chat bar for typing without opening Cellium
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

    private var barContainer: LinearLayout? = null
    private var barParams: WindowManager.LayoutParams? = null
    private var screenToggleChip: TextView? = null
    private var inputField: EditText? = null
    private var barVisible = false

    private var speechRecognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var isListening = false
    private var isTalking = false
    private var isThinking = false

    // MediaProjection for Live Screen Vision
    private var mediaProjection: MediaProjection? = null
    private var screenVisionEnabled = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        wm = getSystemService(WindowManager::class.java)
        initTts()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopSelf()
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
                    showSpeechBubble("Screen Vision ON — tap me and ask about what's on screen.")
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
        ensureOverlayCreated()

        val autoListen = intent?.getBooleanExtra(EXTRA_AUTO_LISTEN, false) == true
        if (autoListen) {
            mainHandler.postDelayed({ startListening() }, 240L)
        }
        return START_STICKY
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
            .setContentText("Tap Cel anywhere to talk, drag to move, long-press to type.")
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

    private fun ensureOverlayCreated() {
        if (faceContainer != null) return

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

        // Smooth drag + tap-to-talk + long-press-to-open-chat-bar
        var initX = 0
        var initY = 0
        var downRawX = 0f
        var downRawY = 0f
        var moved = false
        var longPressed = false
        val longPressRunnable = Runnable {
            if (!moved) {
                longPressed = true
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
                    mainHandler.postDelayed(longPressRunnable, 420L)
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (event.rawX - downRawX).toInt()
                    val dy = (event.rawY - downRawY).toInt()
                    if (abs(dx) > dp(6f) || abs(dy) > dp(6f)) {
                        moved = true
                        mainHandler.removeCallbacks(longPressRunnable)
                    }
                    params.x = (initX + dx).coerceIn(0, resources.displayMetrics.widthPixels - sizePx)
                    params.y = (initY + dy).coerceIn(dp(24f), resources.displayMetrics.heightPixels - sizePx - dp(24f))
                    runCatching { wm.updateViewLayout(container, params) }
                    repositionBubbleBesideFace()
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    mainHandler.removeCallbacks(longPressRunnable)
                    if (!moved && !longPressed) {
                        if (isListening) stopListening() else startListening()
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
            maxWidth = dp(220f)
            background = GradientDrawable().apply {
                setColor(Color.argb(232, 16, 12, 30))
                cornerRadius = dp(16f).toFloat()
                setStroke(dp(1f), Color.argb(170, 192, 132, 252))
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

        // Sync initial avatar gender
        scope.launch {
            val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
            faceView?.updateState(newGender = prefs.avatarGender)
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
            (fParams.x - dp(228f)).coerceAtLeast(dp(10f))
        } else {
            (fParams.x + fParams.width + dp(8f)).coerceAtMost(screenW - dp(230f))
        }
        bParams.y = fParams.y.coerceIn(dp(28f), resources.displayMetrics.heightPixels - dp(120f))
        if (bubble.isAttachedToWindow) {
            runCatching { wm.updateViewLayout(bubble, bParams) }
        }
    }

    private fun showSpeechBubble(text: String) {
        mainHandler.post {
            val bubble = bubbleView ?: return@post
            bubble.text = text
            bubble.visibility = View.VISIBLE
            repositionBubbleBesideFace()
        }
    }

    private fun hideSpeechBubble() {
        mainHandler.post {
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
                    showSpeechBubble("Screen Vision OFF")
                } else if (mediaProjection != null) {
                    screenVisionEnabled = true
                    updateScreenVisionChip()
                    showSpeechBubble("Screen Vision ON")
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
                stopSelf()
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
        tts = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) {
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {
                        isTalking = true
                        mainHandler.post { faceView?.updateState(isTalking = true) }
                    }
                    override fun onDone(utteranceId: String?) {
                        isTalking = false
                        mainHandler.post { faceView?.updateState(isTalking = false) }
                    }
                    @Deprecated("Deprecated in Java")
                    override fun onError(utteranceId: String?) {
                        isTalking = false
                        mainHandler.post { faceView?.updateState(isTalking = false) }
                    }
                })
            }
        }
    }

    private fun startListening() {
        if (isThinking) return
        tts?.stop()
        WakeWordService.setPaused(this, true)
        isListening = true
        faceView?.updateState(newMood = "listening", isListening = true, isTalking = false)
        showSpeechBubble("Listening...")

        mainHandler.post {
            runCatching {
                speechRecognizer?.destroy()
                val sr = SpeechRecognizer.createSpeechRecognizer(this)
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
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        faceView?.updateState(newMood = "idle", isListening = false)
                        hideSpeechBubble()
                    }
                    override fun onResults(results: Bundle?) {
                        isListening = false
                        WakeWordService.setPaused(this@FloatingCelOverlayService, false)
                        val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                        if (text.isNotEmpty()) {
                            askCel(text)
                        } else {
                            faceView?.updateState(newMood = "idle", isListening = false)
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
                showSpeechBubble("Tap long-press to type instead (mic unavailable).")
            }
        }
    }

    private fun stopListening() {
        isListening = false
        runCatching { speechRecognizer?.stopListening() }
        WakeWordService.setPaused(this, false)
        faceView?.updateState(newMood = "idle", isListening = false)
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
        isThinking = true
        faceView?.updateState(newMood = "thinking", isListening = false)
        showSpeechBubble("Thinking...")

        scope.launch {
            try {
                val prefs = PreferencesStore(applicationContext).preferencesFlow.first()
                val dao = CelliumDatabase.getInstance(applicationContext).dao()
                val prov = dao.getProvider(prefs.activeProviderId)
                    ?: dao.getAllProviders().firstOrNull { it.protocol != "on_device" }
                    ?: ProviderPresets.defaultProfiles().first()
                val personas = dao.getAllPersonasOnce().map {
                    CustomPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
                }
                val persona = BuiltInPersonas.resolve(prefs.defaultPersonaId, personas)
                val memories = dao.getAllMemoriesOnce()
                val screenBmp = withContext(Dispatchers.IO) { captureScreenFrameIfEnabled() }

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
                    extraInstruction = "[Floating Assistant] Reply naturally in 1 to 3 short spoken sentences with no markdown formatting.",
                )

                val sb = StringBuilder()
                llmClient.streamChat(
                    provider = prov,
                    systemPrompt = sysPrompt,
                    history = emptyList(),
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
                screenBmp?.recycle()

                val (_, cleanFinal) = ProviderPresets.parseThoughts(sb.toString())
                val (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(cleanFinal)
                val reply = finalBody.ifBlank { cleanFinal.ifBlank { "I'm right here!" } }
                val mood = tagMood ?: MoodDetector.detectMood(reply)
                faceView?.updateState(newMood = mood, newGender = prefs.avatarGender)
                showSpeechBubble(reply)
                speakOut(reply, prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate)
            } catch (e: Exception) {
                faceView?.updateState(newMood = "error")
                showSpeechBubble("Error: ${e.localizedMessage ?: "Couldn't reach AI"}")
            } finally {
                isThinking = false
            }
        }
    }

    private fun speakOut(text: String, voiceName: String, pitch: Float, rate: Float) {
        if (!ttsReady) return
        val engine = tts ?: return
        engine.language = Locale.getDefault()
        if (voiceName.isNotBlank()) {
            engine.voices?.firstOrNull { it.name == voiceName }?.let { engine.voice = it }
        }
        engine.setPitch(pitch.coerceIn(0.6f, 1.8f))
        engine.setSpeechRate(rate.coerceIn(0.6f, 1.8f))
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "cel_float_${System.currentTimeMillis()}")
    }

    override fun onDestroy() {
        removeBottomChatBar()
        faceContainer?.let { if (it.isAttachedToWindow) runCatching { wm.removeView(it) } }
        bubbleView?.let { if (it.isAttachedToWindow) runCatching { wm.removeView(it) } }
        runCatching { speechRecognizer?.destroy() }
        runCatching { tts?.stop(); tts?.shutdown() }
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

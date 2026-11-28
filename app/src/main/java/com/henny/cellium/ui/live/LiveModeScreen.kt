package com.henny.cellium.ui.live

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.RectF
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.view.Surface
import android.view.TextureView
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.CallEnd
import androidx.compose.material.icons.rounded.Cameraswitch
import androidx.compose.material.icons.rounded.ChatBubbleOutline
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Keyboard
import androidx.compose.material.icons.rounded.Loop
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.MicOff
import androidx.compose.material.icons.rounded.PictureInPictureAlt
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Videocam
import androidx.compose.material.icons.rounded.VideocamOff
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import android.app.Activity
import android.content.ContextWrapper
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.avatar.ExpressionDirector
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.chat.PersonaPickerSheet
import com.henny.cellium.ui.components.CelliumIcons
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.GlassPill
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import kotlin.math.sin

private enum class LivePhase {
    IDLE,
    PREPARING_MIC,
    LISTENING,
    TRANSCRIBING,
    THINKING,
    RUNNING_ACTION,
    PREPARING_VOICE,
    SPEAKING,
}

/**
 * Lightweight Camera2 controller for Gemini-Live style real-world camera sharing (front or back).
 * Runs camera callbacks on a dedicated HandlerThread and grabs fast downscaled bitmaps on demand.
 */
private class LiveCameraController(
    private val context: Context,
) {
    private val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
    private var cameraThread: HandlerThread? = null
    private var cameraHandler: Handler? = null
    private var cameraDevice: CameraDevice? = null
    private var captureSession: CameraCaptureSession? = null
    private var textureView: TextureView? = null
    private var useFrontCamera: Boolean = false
    private var isStarted: Boolean = false

    fun attach(tv: TextureView, front: Boolean) {
        textureView = tv
        useFrontCamera = front
        isStarted = true
        if (tv.isAvailable) {
            openCameraInternal(tv, front)
        } else {
            tv.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
                override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) {
                    if (isStarted) openCameraInternal(tv, useFrontCamera)
                }
                override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) {
                    configurePreviewTransform(tv, width, height)
                }
                override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                    closeCameraOnly()
                    return true
                }
                override fun onSurfaceTextureUpdated(surface: SurfaceTexture) {}
            }
        }
    }

    fun switchLens(front: Boolean) {
        if (useFrontCamera == front && cameraDevice != null) return
        useFrontCamera = front
        val tv = textureView ?: return
        closeCameraOnly()
        if (isStarted && tv.isAvailable) {
            openCameraInternal(tv, front)
        }
    }

    fun captureFrameBitmap(maxDim: Int = 768): Bitmap? {
        val tv = textureView ?: return null
        if (!tv.isAvailable || tv.width <= 0 || tv.height <= 0) return null
        val raw = runCatching { tv.bitmap }.getOrNull() ?: return null
        val w = raw.width
        val h = raw.height
        if (w <= maxDim && h <= maxDim) return raw
        val scale = maxDim.toFloat() / maxOf(w, h).toFloat()
        val dstW = (w * scale).toInt().coerceAtLeast(1)
        val dstH = (h * scale).toInt().coerceAtLeast(1)
        val scaled = runCatching { Bitmap.createScaledBitmap(raw, dstW, dstH, true) }.getOrNull()
        if (scaled != null && scaled !== raw) {
            raw.recycle()
            return scaled
        }
        return raw
    }

    private fun ensureThread(): Handler {
        val existing = cameraHandler
        if (existing != null && cameraThread?.isAlive == true) return existing
        val t = HandlerThread("cel-live-camera").apply { start() }
        cameraThread = t
        return Handler(t.looper).also { cameraHandler = it }
    }

    private fun resolveCameraId(front: Boolean): String? {
        val mgr = cameraManager ?: return null
        val targetFacing = if (front) CameraCharacteristics.LENS_FACING_FRONT else CameraCharacteristics.LENS_FACING_BACK
        val ids = runCatching { mgr.cameraIdList }.getOrDefault(emptyArray())
        return ids.firstOrNull { id ->
            runCatching {
                mgr.getCameraCharacteristics(id).get(CameraCharacteristics.LENS_FACING) == targetFacing
            }.getOrDefault(false)
        } ?: ids.firstOrNull()
    }

    private fun configurePreviewTransform(tv: TextureView, viewWidth: Int, viewHeight: Int) {
        if (viewWidth <= 0 || viewHeight <= 0) return
        val matrix = Matrix()
        val viewRect = RectF(0f, 0f, viewWidth.toFloat(), viewHeight.toFloat())
        val bufferRect = RectF(0f, 0f, 480f, 640f)
        val centerX = viewRect.centerX()
        val centerY = viewRect.centerY()
        bufferRect.offset(centerX - bufferRect.centerX(), centerY - bufferRect.centerY())
        matrix.setRectToRect(viewRect, bufferRect, Matrix.ScaleToFit.FILL)
        val scale = maxOf(viewHeight.toFloat() / 640f, viewWidth.toFloat() / 480f)
        matrix.postScale(scale, scale, centerX, centerY)
        tv.setTransform(matrix)
    }

    @SuppressLint("MissingPermission")
    private fun openCameraInternal(tv: TextureView, front: Boolean) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            return
        }
        val mgr = cameraManager ?: return
        val camId = resolveCameraId(front) ?: return
        val handler = ensureThread()

        runCatching {
            mgr.openCamera(
                camId,
                object : CameraDevice.StateCallback() {
                    override fun onOpened(camera: CameraDevice) {
                        if (!isStarted) {
                            runCatching { camera.close() }
                            return
                        }
                        cameraDevice = camera
                        startPreviewSession(camera, tv, handler)
                    }
                    override fun onDisconnected(camera: CameraDevice) {
                        runCatching { camera.close() }
                        if (cameraDevice === camera) cameraDevice = null
                    }
                    override fun onError(camera: CameraDevice, error: Int) {
                        runCatching { camera.close() }
                        if (cameraDevice === camera) cameraDevice = null
                    }
                },
                handler,
            )
        }
    }

    @Suppress("DEPRECATION")
    private fun startPreviewSession(camera: CameraDevice, tv: TextureView, handler: Handler) {
        val st = tv.surfaceTexture ?: return
        st.setDefaultBufferSize(640, 480)
        val surface = Surface(st)
        runCatching {
            val reqBuilder = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
                addTarget(surface)
                set(CaptureRequest.CONTROL_AF_MODE, CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE)
            }
            camera.createCaptureSession(
                listOf(surface),
                object : CameraCaptureSession.StateCallback() {
                    override fun onConfigured(session: CameraCaptureSession) {
                        if (!isStarted || cameraDevice == null) {
                            runCatching { session.close() }
                            return
                        }
                        captureSession = session
                        runCatching { session.setRepeatingRequest(reqBuilder.build(), null, handler) }
                    }
                    override fun onConfigureFailed(session: CameraCaptureSession) {}
                },
                handler,
            )
        }
    }

    private fun closeCameraOnly() {
        runCatching { captureSession?.close() }
        captureSession = null
        runCatching { cameraDevice?.close() }
        cameraDevice = null
    }

    fun release() {
        isStarted = false
        closeCameraOnly()
        textureView = null
        runCatching { cameraThread?.quitSafely() }
        cameraThread = null
        cameraHandler = null
    }
}

@Composable
fun LiveModeScreen(
    viewModel: CelliumViewModel,
    onClose: () -> Unit,
    onOpenVoiceSettings: () -> Unit = {},
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val keyboardController = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val isFloating by FloatingCelOverlayService.isRunning.collectAsStateWithLifecycle()

    // Cinematic intro / outro transition animators
    val introAnim = remember { Animatable(0f) }
    val outroAnim = remember { Animatable(0f) }
    var isExiting by remember { mutableStateOf(false) }
    var pendingEndCall by remember { mutableStateOf(false) }

    // Immersive OLED Eye toggle
    var guiHidden by remember { mutableStateOf(false) }
    var eyeVisible by remember { mutableStateOf(true) }
    var eyePokeNonce by remember { mutableIntStateOf(0) }

    var phase by remember { mutableStateOf(LivePhase.IDLE) }
    var stageLabel by remember { mutableStateOf("") }
    var mood by remember { mutableStateOf("idle") }
    var moodHoldJob by remember { mutableStateOf<Job?>(null) }
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    var userTranscript by remember { mutableStateOf("") }
    var celReply by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var mouthOpenness by remember { mutableFloatStateOf(0.05f) }

    fun findHostActivity(ctx: Context): Activity? {
        var cur: Context? = ctx
        while (cur is ContextWrapper) {
            if (cur is Activity) return cur
            cur = cur.baseContext
        }
        return null
    }

    // True Android edge-to-edge immersive fullscreen when Hide Eye is ON (restores bars on toggle or exit)
    DisposableEffect(guiHidden) {
        val activity = findHostActivity(context)
        val controller = activity?.let { WindowCompat.getInsetsController(it.window, it.window.decorView) }
        if (controller != null) {
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            if (guiHidden) {
                controller.hide(WindowInsetsCompat.Type.systemBars())
            } else {
                controller.show(WindowInsetsCompat.Type.systemBars())
            }
        }
        onDispose {
            controller?.show(WindowInsetsCompat.Type.systemBars())
        }
    }

    // Retry preservation on offline / network failure
    var failedPrompt by remember { mutableStateOf<String?>(null) }
    var failedBitmap by remember { mutableStateOf<Bitmap?>(null) }

    // In-place Pickers
    var showPersonaPicker by remember { mutableStateOf(false) }
    var showChatSwitcher by remember { mutableStateOf(false) }

    val isSynthLive = prefs.liveTtsEngine == CelliumTtsEngine.ENGINE_SYNTH

    // Live Typing Input — Synth starts with input ready, and Keyboard button ALWAYS toggles ON/OFF + summons IME!
    var showTypingInput by remember(isSynthLive) { mutableStateOf(isSynthLive) }
    var typingFocusNonce by remember { mutableIntStateOf(0) }
    val typingFocusRequester = remember { FocusRequester() }
    var typedInput by remember { mutableStateOf("") }

    LaunchedEffect(showTypingInput, typingFocusNonce) {
        if (showTypingInput && typingFocusNonce > 0) {
            delay(80L)
            runCatching { typingFocusRequester.requestFocus() }
            keyboardController?.show()
        }
    }

    // Gemini-Live Style Camera Sharing
    var cameraEnabled by remember { mutableStateOf(false) }
    var useFrontCamera by remember { mutableStateOf(false) }
    var hasCameraPerm by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        )
    }
    val cameraController = remember(context) { LiveCameraController(context) }

    var listenStartedAtMs by remember { mutableLongStateOf(0L) }
    var userStoppedDeviceStt by remember { mutableStateOf(false) }
    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var cloudSttJob by remember { mutableStateOf<Job?>(null) }
    val deviceSpeechBuffer = remember { StringBuilder() }
    var deviceSilenceFlushJob by remember { mutableStateOf<Job?>(null) }
    var deviceRearmJob by remember { mutableStateOf<Job?>(null) }
    var deviceHasDetectedSpeech by remember { mutableStateOf(false) }

    fun clearDeviceSpeechAccumulator() {
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = null
        deviceRearmJob?.cancel()
        deviceRearmJob = null
        deviceSpeechBuffer.setLength(0)
        deviceHasDetectedSpeech = false
    }

    fun cancelAllListeningWithoutSending() {
        userStoppedDeviceStt = true
        clearDeviceSpeechAccumulator()
        cloudSttJob?.cancel()
        cloudSttJob = null
        viewModel.sttEngine.cancelRecording()
        runCatching { recognizer?.cancel() }
        if (phase == LivePhase.PREPARING_MIC || phase == LivePhase.LISTENING || phase == LivePhase.TRANSCRIBING) {
            phase = LivePhase.IDLE
            stageLabel = ""
            mouthOpenness = 0.05f
        }
    }

    fun triggerExit(afterExit: () -> Unit = onClose) {
        if (isExiting) return
        isExiting = true
        pendingEndCall = false
        keyboardController?.hide()
        cancelAllListeningWithoutSending()
        viewModel.cancelLiveStream()
        viewModel.ttsEngine.stop()
        cameraEnabled = false
        cameraController.release()
        scope.launch {
            outroAnim.animateTo(1f, tween(durationMillis = 320, easing = FastOutLinearInEasing))
            afterExit()
        }
    }

    BackHandler { triggerExit() }

    LaunchedEffect(guiHidden, eyePokeNonce) {
        if (!guiHidden) {
            eyeVisible = true
        } else {
            eyeVisible = true
            delay(1_200L)
            eyeVisible = false
        }
    }

    LaunchedEffect(context) {
        avatarLibrary = withContext(Dispatchers.IO) { AvatarLibrary.load(context) }
    }

    var hasAudioPerm by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        )
    }

    fun buildDeviceSpeechIntent(): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3_200L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 3_200L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 60_000L)
    }

    lateinit var startListening: () -> Unit

    fun sendLivePrompt(rawText: String, explicitBitmap: Bitmap? = null, isRetry: Boolean = false) {
        if (isExiting) return
        val spoken = rawText.trim()
        if (spoken.isBlank()) {
            phase = LivePhase.IDLE
            stageLabel = ""
            mouthOpenness = 0.05f
            return
        }
        val frameBitmap = explicitBitmap ?: if (cameraEnabled) cameraController.captureFrameBitmap() else null
        pendingEndCall = false
        userTranscript = spoken
        celReply = ""
        errorMsg = null
        failedPrompt = null
        failedBitmap = null
        phase = LivePhase.THINKING
        stageLabel = if (frameBitmap != null) "Looking through camera..." else "Thinking..."
        mood = "thinking"

        viewModel.streamLiveReply(
            transcript = spoken,
            screenBitmap = frameBitmap,
            isRetry = isRetry,
            onStageChanged = { st ->
                scope.launch(Dispatchers.Main) {
                    if (isExiting) return@launch
                    stageLabel = st
                    phase = if (st.contains("action", ignoreCase = true) || st.contains("web", ignoreCase = true)) {
                        LivePhase.RUNNING_ACTION
                    } else {
                        LivePhase.THINKING
                    }
                }
            },
            onDelta = { _ ->
                // Hold celReply hidden until TTS voice actually starts
            },
            onMoodChanged = { detected ->
                scope.launch(Dispatchers.Main) { mood = detected }
            },
            onEndCallRequested = {
                scope.launch(Dispatchers.Main) { pendingEndCall = true }
            },
            onComplete = { finalReply ->
                scope.launch(Dispatchers.Main) {
                    if (isExiting) return@launch
                    val liveEngine = viewModel.preferences.value.liveTtsEngine
                    phase = LivePhase.PREPARING_VOICE
                    stageLabel = if (liveEngine == CelliumTtsEngine.ENGINE_SYNTH) {
                        "Starting Synth voice..."
                    } else {
                        "Preparing ${CelliumTtsEngine.engineLabel(liveEngine)} voice..."
                    }
                    viewModel.speakLiveText(
                        text = finalReply,
                        onStart = {
                            scope.launch(Dispatchers.Main) {
                                if (isExiting) return@launch
                                phase = LivePhase.SPEAKING
                                stageLabel = ""
                                if (liveEngine != CelliumTtsEngine.ENGINE_SYNTH) {
                                    celReply = finalReply
                                }
                            }
                        },
                        onSynthCharProgress = { charIdx ->
                            scope.launch(Dispatchers.Main) {
                                if (isExiting) return@launch
                                phase = LivePhase.SPEAKING
                                stageLabel = ""
                                celReply = finalReply.take(charIdx.coerceIn(0, finalReply.length))
                            }
                        },
                        onComplete = {
                            scope.launch(Dispatchers.Main) {
                                if (isExiting) return@launch
                                celReply = finalReply
                                phase = LivePhase.IDLE
                                stageLabel = ""
                                mouthOpenness = 0.05f
                                if (pendingEndCall) {
                                    pendingEndCall = false
                                    delay(380L)
                                    triggerExit()
                                    return@launch
                                }
                                // Hold emotional expression naturally before relaxing back to idle
                                moodHoldJob?.cancel()
                                val holdMs = ExpressionDirector.holdDurationMsForMood(mood)
                                moodHoldJob = scope.launch {
                                    delay(holdMs)
                                    if (!isExiting && phase == LivePhase.IDLE) {
                                        mood = "idle"
                                    }
                                }
                                if (viewModel.preferences.value.liveHandsFreeLoop && hasAudioPerm && typedInput.isBlank()) {
                                    delay(360L)
                                    if (!isExiting && viewModel.preferences.value.liveHandsFreeLoop && typedInput.isBlank()) {
                                        startListening()
                                    }
                                }
                            }
                        },
                    )
                }
            },
            onError = { err ->
                scope.launch(Dispatchers.Main) {
                    if (isExiting) return@launch
                    pendingEndCall = false
                    errorMsg = err
                    failedPrompt = spoken
                    failedBitmap = frameBitmap
                    mood = "error"
                    phase = LivePhase.IDLE
                    stageLabel = ""
                }
            },
        )
    }

    fun handleSttTranscript(rawSpoken: String) {
        if (isExiting) return
        val cleaned = CelliumSttEngine.sanitizeTranscript(rawSpoken)
        if (cleaned.isBlank()) {
            // Ignore empty / "." noise bursts and seamlessly re-listen if Auto Mode is ON (#4k, #4q)
            phase = LivePhase.IDLE
            stageLabel = ""
            mouthOpenness = 0.05f
            if (viewModel.preferences.value.liveHandsFreeLoop && hasAudioPerm && typedInput.isBlank()) {
                scope.launch(Dispatchers.Main) {
                    delay(260L)
                    if (!isExiting && viewModel.preferences.value.liveHandsFreeLoop && phase == LivePhase.IDLE && typedInput.isBlank()) {
                        startListening()
                    }
                }
            }
            return
        }
        sendLivePrompt(cleaned)
    }

    fun flushDeviceSpeechAccumulator() {
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = null
        deviceRearmJob?.cancel()
        deviceRearmJob = null
        val combined = deviceSpeechBuffer.toString().trim()
        deviceSpeechBuffer.setLength(0)
        deviceHasDetectedSpeech = false
        userStoppedDeviceStt = true
        runCatching { recognizer?.cancel() }
        handleSttTranscript(combined)
    }

    fun scheduleDeviceSilenceFlush(delayMs: Long = 2_200L) {
        deviceSilenceFlushJob?.cancel()
        deviceSilenceFlushJob = scope.launch(Dispatchers.Main) {
            delay(delayMs)
            if (!isExiting && !userStoppedDeviceStt && deviceSpeechBuffer.isNotEmpty()) {
                flushDeviceSpeechAccumulator()
            }
        }
    }

    startListening = {
        if (hasAudioPerm && !isExiting) {
            errorMsg = null
            viewModel.ttsEngine.stop()
            clearDeviceSpeechAccumulator()
            cloudSttJob?.cancel()
            phase = LivePhase.PREPARING_MIC
            stageLabel = "Starting mic..."
            mood = "listening"
            listenStartedAtMs = System.currentTimeMillis()
            userStoppedDeviceStt = false

            val sttEngineId = viewModel.preferences.value.sttEngine
            if (sttEngineId == CelliumSttEngine.ENGINE_DEVICE) {
                val sr = recognizer
                if (sr == null) {
                    phase = LivePhase.IDLE
                    stageLabel = ""
                    errorMsg = "Device speech recognition unavailable. Switch STT engine in Settings -> Voice."
                } else {
                    runCatching { sr.startListening(buildDeviceSpeechIntent()) }
                        .onFailure {
                            phase = LivePhase.IDLE
                            stageLabel = ""
                            errorMsg = "Device speech recognition unavailable. Switch STT engine in Settings -> Voice."
                        }
                }
            } else {
                val opt = CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == sttEngineId }
                val apiKey = viewModel.resolveSttApiKey(sttEngineId)
                if (opt?.requiresKey == true && apiKey.isBlank()) {
                    phase = LivePhase.IDLE
                    stageLabel = ""
                    errorMsg = "Missing API key for ${opt.label}. Add your key in Settings -> Voice & Audio."
                } else {
                    cloudSttJob = scope.launch {
                        val res = viewModel.sttEngine.recordAndTranscribe(
                            engineId = sttEngineId,
                            apiKey = apiKey,
                            modelOverride = viewModel.preferences.value.sttModel,
                            maxDurationMs = 180_000L,
                            preSpeechTimeoutMs = 60_000L,
                            silenceAutoStopMs = 2_400L,
                            manualStopOnly = false,
                            onReadyForSpeech = {
                                scope.launch(Dispatchers.Main) {
                                    phase = LivePhase.LISTENING
                                    stageLabel = "Listening..."
                                }
                            },
                            onRmsLevel = { lvl ->
                                if (phase == LivePhase.LISTENING) {
                                    mouthOpenness = (0.08f + lvl * 0.72f).coerceIn(0.08f, 0.80f)
                                }
                            },
                            onTranscribing = {
                                scope.launch(Dispatchers.Main) {
                                    phase = LivePhase.TRANSCRIBING
                                    stageLabel = "Transcribing..."
                                    mouthOpenness = 0.05f
                                }
                            },
                            onModelAutoSelected = { picked ->
                                viewModel.persistAutoSelectedSttModel(sttEngineId, picked)
                            },
                        )
                        if (!isExiting) {
                            res.onSuccess { txt ->
                                handleSttTranscript(txt)
                            }.onFailure { err ->
                                phase = LivePhase.IDLE
                                stageLabel = ""
                                mouthOpenness = 0.05f
                                val msg = err.localizedMessage.orEmpty()
                                val isTimeoutOrNoise = msg.contains("No speech", ignoreCase = true) ||
                                    msg.contains("timed out", ignoreCase = true) ||
                                    msg.contains("short", ignoreCase = true)
                                if (msg.contains("cancelled", ignoreCase = true)) {
                                    // User cancelled cleanly (e.g. turned Auto OFF or started typing)
                                } else if (isTimeoutOrNoise && viewModel.preferences.value.liveHandsFreeLoop && typedInput.isBlank()) {
                                    // True always-listening Auto Mode (#4q)
                                    delay(250L)
                                    if (!isExiting && viewModel.preferences.value.liveHandsFreeLoop && phase == LivePhase.IDLE && typedInput.isBlank()) {
                                        startListening()
                                    }
                                } else {
                                    errorMsg = msg.ifBlank { "Speech transcription failed." }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    val audioPermLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasAudioPerm = granted
        if (granted) startListening()
        else errorMsg = "Microphone permission is required for Live Mode."
    }

    val cameraPermLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasCameraPerm = granted
        if (granted) {
            cameraEnabled = true
        } else {
            errorMsg = "Camera permission is required for Live Camera vision."
        }
    }

    LaunchedEffect(Unit) {
        viewModel.soundEngine.playAssistantSummon()
        introAnim.animateTo(1f, tween(durationMillis = 560, easing = FastOutSlowInEasing))
        if (!isExiting && viewModel.preferences.value.liveHandsFreeLoop && hasAudioPerm && phase == LivePhase.IDLE) {
            startListening()
        }
    }

    DisposableEffect(context) {
        val sr = CelliumSttEngine.createBestDeviceSpeechRecognizer(context)?.apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    if (!userStoppedDeviceStt) {
                        phase = LivePhase.LISTENING
                        stageLabel = "Listening..."
                    }
                }
                override fun onBeginningOfSpeech() {
                    deviceHasDetectedSpeech = true
                    deviceSilenceFlushJob?.cancel()
                    deviceSilenceFlushJob = null
                }
                override fun onRmsChanged(rmsdB: Float) {
                    if (phase == LivePhase.LISTENING) {
                        mouthOpenness = ((rmsdB + 2f) / 14f).coerceIn(0.08f, 0.75f)
                        if (deviceSpeechBuffer.isNotEmpty() && rmsdB > 4.5f) {
                            // User is continuing to speak — reset the 2.2s breath grace timer
                            scheduleDeviceSilenceFlush(2_200L)
                        }
                    }
                }
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {
                    // Stay in LISTENING during the 2.2s breath grace window instead of jarring to Transcribing
                    if (!userStoppedDeviceStt && deviceSpeechBuffer.isEmpty()) {
                        stageLabel = "Listening..."
                    }
                }
                override fun onError(error: Int) {
                    if (isExiting || userStoppedDeviceStt) return
                    val retryable = error == SpeechRecognizer.ERROR_NO_MATCH ||
                        error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ||
                        error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY
                    // If we already captured speech in the buffer, NEVER drop it — let the 2.2s grace timer finish!
                    if (deviceSpeechBuffer.isNotEmpty()) {
                        if (error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY) {
                            deviceRearmJob?.cancel()
                            deviceRearmJob = scope.launch(Dispatchers.Main) {
                                delay(160L)
                                if (!isExiting && !userStoppedDeviceStt && typedInput.isBlank()) {
                                    runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                                }
                            }
                        } else if (deviceSilenceFlushJob?.isActive != true) {
                            scheduleDeviceSilenceFlush(650L)
                        }
                        return
                    }
                    val autoOn = viewModel.preferences.value.liveHandsFreeLoop
                    val elapsed = System.currentTimeMillis() - listenStartedAtMs
                    if (retryable && (autoOn || elapsed < 60_000L)) {
                        deviceRearmJob?.cancel()
                        deviceRearmJob = scope.launch(Dispatchers.Main) {
                            delay(220L)
                            if (!isExiting && !userStoppedDeviceStt && typedInput.isBlank()) {
                                runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                            }
                        }
                    } else {
                        phase = LivePhase.IDLE
                        stageLabel = ""
                        mouthOpenness = 0.05f
                    }
                }
                override fun onPartialResults(partialResults: Bundle?) {
                    if (userStoppedDeviceStt) return
                    val txt = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                    val cleaned = CelliumSttEngine.sanitizeTranscript(txt.orEmpty())
                    if (cleaned.isNotBlank()) {
                        deviceHasDetectedSpeech = true
                        deviceSilenceFlushJob?.cancel()
                        deviceSilenceFlushJob = null
                        val prefix = deviceSpeechBuffer.toString().trim()
                        userTranscript = if (prefix.isBlank()) cleaned else "$prefix $cleaned"
                    }
                }
                override fun onResults(results: Bundle?) {
                    if (isExiting || userStoppedDeviceStt) return
                    val raw = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                    val segment = CelliumSttEngine.sanitizeTranscript(raw)
                    if (segment.isNotBlank()) {
                        deviceHasDetectedSpeech = true
                        if (deviceSpeechBuffer.isNotEmpty()) deviceSpeechBuffer.append(' ')
                        deviceSpeechBuffer.append(segment)
                        userTranscript = deviceSpeechBuffer.toString()
                        phase = LivePhase.LISTENING
                        stageLabel = "Listening..."
                        // Hold for 2.2s of true silence so catching a breath NEVER cuts off the user!
                        scheduleDeviceSilenceFlush(2_200L)
                        deviceRearmJob?.cancel()
                        deviceRearmJob = scope.launch(Dispatchers.Main) {
                            delay(90L)
                            if (!isExiting && !userStoppedDeviceStt && typedInput.isBlank() && deviceSpeechBuffer.isNotEmpty()) {
                                runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                            }
                        }
                    } else if (deviceSpeechBuffer.isNotEmpty()) {
                        if (deviceSilenceFlushJob?.isActive != true) {
                            scheduleDeviceSilenceFlush(1_200L)
                        }
                    } else {
                        handleSttTranscript("")
                    }
                }
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }
        recognizer = sr

        onDispose {
            clearDeviceSpeechAccumulator()
            cloudSttJob?.cancel()
            viewModel.sttEngine.cancelRecording()
            viewModel.cancelLiveStream()
            runCatching { sr?.destroy() }
            viewModel.ttsEngine.stop()
            cameraController.release()
        }
    }

    LaunchedEffect(phase) {
        if (phase != LivePhase.SPEAKING) {
            if (phase != LivePhase.LISTENING) mouthOpenness = 0.05f
            return@LaunchedEffect
        }
        var t = 0f
        while (phase == LivePhase.SPEAKING) {
            t += 0.35f
            mouthOpenness = (0.35f + 0.35f * sin(t)).coerceIn(0.10f, 0.85f)
            delay(55L)
        }
    }

    val activeProv = uiState.activeProvider
    val provIconKey = activeProv?.badge ?: "sparkle"
    val persona = uiState.resolvedPersona
    val activeSessionTitle = uiState.activeSession?.title?.ifBlank { "New Chat" } ?: "New Chat"
    val sttLabel = remember(prefs.sttEngine) {
        CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == prefs.sttEngine }?.label?.substringBefore(" (") ?: "System"
    }

    val introP = introAnim.value
    val outroP = outroAnim.value
    val avatarScale = ((0.52f + 0.48f * introP) * (1f - 0.45f * outroP)).coerceAtLeast(0.1f)
    val contentAlpha = (introP * (1f - outroP)).coerceIn(0f, 1f)

    // Full-bleed Pure OLED Black immersive stage
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .imePadding()
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
            ) {
                if (guiHidden) {
                    eyePokeNonce++
                }
            },
    ) {
        // Harmonic intro / outro energy rings rendered directly on pure black
        Canvas(modifier = Modifier.fillMaxSize()) {
            val center = Offset(size.width * 0.5f, size.height * 0.44f)
            val maxR = size.minDimension * 0.56f
            if (introP < 0.99f) {
                val ringAlpha = (1f - introP).coerceIn(0f, 1f) * 0.65f
                drawCircle(
                    color = visuals.primary.copy(alpha = ringAlpha),
                    radius = maxR * (0.18f + 0.85f * introP),
                    center = center,
                    style = Stroke(width = 3.dp.toPx() * (1.2f - 0.7f * introP)),
                )
                drawCircle(
                    color = visuals.secondary.copy(alpha = ringAlpha * 0.75f),
                    radius = maxR * (0.08f + 0.62f * introP),
                    center = center,
                    style = Stroke(width = 2.dp.toPx()),
                )
            }
            if (outroP > 0.01f) {
                val collapseAlpha = (1f - outroP * 0.6f).coerceIn(0f, 1f) * 0.75f
                drawCircle(
                    color = visuals.primary.copy(alpha = collapseAlpha),
                    radius = maxR * (1f - outroP).coerceAtLeast(0.02f),
                    center = center,
                    style = Stroke(width = 2.5.dp.toPx()),
                )
            }
        }

        // Resolve active Dot-Matrix expression (anti-repetition ExpressionDirector)
        val liveExpr = remember(avatarLibrary, prefs.avatarGender, mood) {
            val picked = ExpressionDirector.pickExpressionForMood(mood)
            avatarLibrary?.get(prefs.avatarGender, picked, "Base")
                ?: avatarLibrary?.getForMood(prefs.avatarGender, mood)
                ?: avatarLibrary?.get(prefs.avatarGender, MoodDetector.moodToExpressionName(mood), "Base")
        }
        val activeAnimDisplayName = remember(liveExpr, mood) {
            liveExpr?.name?.takeIf { it.isNotBlank() } ?: MoodDetector.moodToExpressionName(mood)
        }
        val topLeftStatusText = when {
            stageLabel.isNotBlank() && phase != LivePhase.SPEAKING -> stageLabel
            phase == LivePhase.PREPARING_MIC -> "Starting mic..."
            phase == LivePhase.LISTENING -> if (cameraEnabled) "Listening · Cam ON" else "Listening..."
            phase == LivePhase.TRANSCRIBING -> "Transcribing..."
            phase == LivePhase.THINKING -> "Thinking..."
            phase == LivePhase.RUNNING_ACTION -> "Running action..."
            phase == LivePhase.PREPARING_VOICE -> "Preparing voice..."
            phase == LivePhase.SPEAKING -> "Speaking..."
            else -> ""
        }
        val statusDotColor = when (phase) {
            LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING, LivePhase.PREPARING_VOICE -> CelAmber
            LivePhase.LISTENING -> CelEmeraldThought
            LivePhase.SPEAKING -> visuals.secondary
            LivePhase.THINKING, LivePhase.RUNNING_ACTION -> visuals.primary
            LivePhase.IDLE -> CelTextSecondary
        }

        // Foreground layout — Cel's dot-matrix face lives inside weight(1f) ABOVE the chat bubble so
        // the chat bubble NEVER covers Cel's face, gracefully framing around her!
        Column(
            modifier = Modifier
                .fillMaxSize()
                .then(if (guiHidden) Modifier else Modifier.statusBarsPadding().navigationBarsPadding())
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .graphicsLayer { alpha = contentAlpha },
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Top Status Bar (hidden when Hide Eye is ON; leaves room for Voice Settings + Eye buttons at top-right)
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(240)) + slideInVertically(tween(260)) { -it / 2 },
                exit = fadeOut(tween(220)) + slideOutVertically(tween(220)) { -it / 2 },
                modifier = Modifier.fillMaxWidth().padding(end = 94.dp),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Model & Live Status Pill
                    GlassPill(onClick = {}) {
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(statusDotColor)
                        )
                        Icon(
                            imageVector = CelliumIcons.resolve(provIconKey),
                            contentDescription = null,
                            tint = visuals.primary,
                            modifier = Modifier.size(14.dp),
                        )
                        Text(
                            text = buildAnnotatedString {
                                val rawModel = activeProv?.selectedModel
                                    ?.removePrefix("models/")
                                    ?.substringAfterLast('/')
                                    ?.ifBlank { activeProv.name }
                                    ?: "Pollinations"
                                val shortProv = activeProv?.name?.substringBefore(" (")?.replace(" AI", "")?.trim().orEmpty()
                                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = CelTextPrimary)) {
                                    append(rawModel.take(16))
                                }
                                if (shortProv.isNotBlank()) {
                                    withStyle(SpanStyle(color = CelLavender.copy(alpha = 0.8f), fontFamily = JetBrainsMono, fontSize = 10.sp)) {
                                        append(" · $shortProv")
                                    }
                                }
                            },
                            style = MaterialTheme.typography.labelMedium,
                            maxLines = 1,
                            softWrap = false,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }

                    // Quick Chat Switcher Pill
                    GlassPill(onClick = { showChatSwitcher = true }) {
                        Icon(
                            imageVector = Icons.Rounded.ChatBubbleOutline,
                            contentDescription = "Switch Chat",
                            tint = visuals.secondary,
                            modifier = Modifier.size(14.dp),
                        )
                        Text(
                            text = activeSessionTitle.take(16),
                            style = MaterialTheme.typography.labelMedium,
                            color = CelTextPrimary,
                            maxLines = 1,
                            softWrap = false,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }

                    // Active Persona Pill
                    GlassPill(onClick = { showPersonaPicker = true }) {
                        Icon(
                            imageVector = CelliumIcons.resolve(persona.iconKey),
                            contentDescription = "Persona",
                            tint = CelLavender,
                            modifier = Modifier.size(14.dp),
                        )
                        Text(
                            text = persona.name,
                            style = MaterialTheme.typography.labelMedium,
                            color = CelTextPrimary,
                            maxLines = 1,
                            softWrap = false,
                        )
                    }

                    // Float over apps Pill
                    GlassPill(
                        selected = isFloating,
                        onClick = {
                            if (isFloating) {
                                FloatingCelOverlayService.stop(context)
                                scope.launch { viewModel.prefsStore.updateFloatingMiniCel(false) }
                                viewModel.showBanner("Floating Cel turned OFF.")
                            } else if (Settings.canDrawOverlays(context)) {
                                scope.launch { viewModel.prefsStore.updateFloatingMiniCel(true) }
                                FloatingCelOverlayService.start(context, autoListen = false)
                                viewModel.showBanner("Floating Cel launched over all apps.")
                            } else {
                                runCatching {
                                    val intent = Intent(
                                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                        Uri.parse("package:${context.packageName}"),
                                    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                    context.startActivity(intent)
                                }
                            }
                        },
                    ) {
                        Icon(
                            Icons.Rounded.PictureInPictureAlt,
                            contentDescription = "Float over apps",
                            modifier = Modifier.size(15.dp),
                            tint = if (isFloating) CelEmeraldThought else CelLavender,
                        )
                        Text(
                            if (isFloating) "Float ON" else "Float",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextPrimary,
                            maxLines = 1,
                            softWrap = false,
                        )
                    }

                    // Auto / Manual Mode Toggle
                    GlassPill(
                        onClick = {
                            val nextAuto = !prefs.liveHandsFreeLoop
                            if (!nextAuto) {
                                cancelAllListeningWithoutSending()
                            }
                            scope.launch {
                                viewModel.prefsStore.updateVoiceSettings(
                                    prefs.ttsVoiceName,
                                    prefs.ttsPitch,
                                    prefs.ttsSpeechRate,
                                    prefs.autoReadReplies,
                                    nextAuto,
                                    prefs.ttsEngine,
                                )
                                viewModel.notifyPrefsChangedForSync()
                                if (nextAuto && hasAudioPerm && phase == LivePhase.IDLE && typedInput.isBlank()) {
                                    startListening()
                                }
                            }
                        },
                        selected = prefs.liveHandsFreeLoop,
                        modifier = Modifier.testTag("live_handsfree_toggle"),
                    ) {
                        Icon(Icons.Rounded.Loop, contentDescription = "Hands-free loop", modifier = Modifier.size(15.dp), tint = CelTextPrimary)
                        Text(
                            text = if (prefs.liveHandsFreeLoop) "Auto" else "Manual",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextPrimary,
                            maxLines = 1,
                            softWrap = false,
                        )
                    }
                }
            }

            // Cel's Dedicated Unobstructed Dot-Matrix Face Stage (auto-fits cleanly above the chat bubble!)
            BoxWithConstraints(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .graphicsLayer {
                        scaleX = avatarScale
                        scaleY = avatarScale
                    },
                contentAlignment = Alignment.Center,
            ) {
                val maxAvailable = minOf(maxWidth, maxHeight)
                val faceSize = (maxAvailable * if (guiHidden && !isSynthLive) 0.90f else 0.88f)
                    .coerceIn(136.dp, 400.dp)
                Box(
                    modifier = Modifier
                        .size(faceSize)
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                        ) {
                            if (guiHidden) {
                                eyePokeNonce++
                            }
                            if (phase == LivePhase.SPEAKING) {
                                viewModel.ttsEngine.stop()
                                startListening()
                            } else if (phase == LivePhase.IDLE && guiHidden) {
                                if (!hasAudioPerm) {
                                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                } else {
                                    startListening()
                                }
                            } else {
                                viewModel.soundEngine.playAnimalesePurr()
                                mood = "happy"
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    DotMatrixAvatarCanvas(
                        expression = liveExpr,
                        scale = if (guiHidden && !isSynthLive) 1.24f else 1.12f,
                        mouthOpenness = mouthOpenness,
                        highFps = prefs.highFpsMode,
                        onPetted = {
                            viewModel.soundEngine.playAnimalesePurr()
                            mood = "love"
                        },
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }

            // Synth Hide-Eye Minimal Bubble + Typing Box: ONLY shown during guiHidden if user picked Synth voice!
            // For all non-Synth voices, Hide Eye hides EVERY HUD element including the chat bubble!
            if (guiHidden && isSynthLive) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (userTranscript.isNotBlank() || celReply.isNotBlank() || errorMsg != null) {
                        LiveSmartChatBubble(
                            userTranscript = userTranscript,
                            celReply = celReply,
                            errorMsg = errorMsg,
                            failedPrompt = failedPrompt,
                            isActivePhase = phase != LivePhase.IDLE,
                            isSpeaking = phase == LivePhase.SPEAKING,
                            maxBubbleHeight = 165.dp,
                            idleHint = "",
                            accent = visuals.primary,
                            onRetry = {
                                val retryText = failedPrompt ?: return@LiveSmartChatBubble
                                val retryBmp = failedBitmap?.takeUnless { it.isRecycled }
                                sendLivePrompt(retryText, explicitBitmap = retryBmp, isRetry = true)
                            },
                        )
                    }

                    LiveTypingBar(
                        value = typedInput,
                        onValueChange = { next ->
                            if (next.isNotEmpty() && (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC)) {
                                cancelAllListeningWithoutSending()
                            }
                            typedInput = next
                        },
                        onSend = {
                            val toSend = typedInput.trim()
                            if (toSend.isNotEmpty()) {
                                typedInput = ""
                                cancelAllListeningWithoutSending()
                                sendLivePrompt(toSend)
                            }
                        },
                        accent = visuals.primary,
                        focusRequester = typingFocusRequester,
                    )
                }
            }

            // Full Bottom Smart Chat Bubble, Typing Bar & Liquid Glass Controls (hidden completely when Hide Eye is ON)
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(240)) + slideInVertically(tween(260)) { it / 2 },
                exit = fadeOut(tween(220)) + slideOutVertically(tween(220)) { it / 2 },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    LiveSmartChatBubble(
                        userTranscript = userTranscript,
                        celReply = celReply,
                        errorMsg = errorMsg,
                        failedPrompt = failedPrompt,
                        isActivePhase = phase != LivePhase.IDLE,
                        isSpeaking = phase == LivePhase.SPEAKING,
                        maxBubbleHeight = if (showTypingInput) 155.dp else 210.dp,
                        idleHint = "Tap mic to talk to ${persona.name} · ${CelliumTtsEngine.engineLabel(prefs.liveTtsEngine)}",
                        accent = visuals.primary,
                        onRetry = {
                            viewModel.soundEngine.playClick()
                            val retryText = failedPrompt ?: return@LiveSmartChatBubble
                            val retryBmp = failedBitmap?.takeUnless { it.isRecycled }
                            sendLivePrompt(retryText, explicitBitmap = retryBmp, isRetry = true)
                        },
                    )

                    if (showTypingInput) {
                        LiveTypingBar(
                            value = typedInput,
                            onValueChange = { next ->
                                if (next.isNotEmpty() && (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC)) {
                                    cancelAllListeningWithoutSending()
                                }
                                typedInput = next
                            },
                            onSend = {
                                val toSend = typedInput.trim()
                                if (toSend.isNotEmpty()) {
                                    typedInput = ""
                                    cancelAllListeningWithoutSending()
                                    sendLivePrompt(toSend)
                                }
                            },
                            accent = visuals.primary,
                            focusRequester = typingFocusRequester,
                        )
                    }

                    // Liquid Glass Control Dock
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Camera Sharing Toggle (Liquid Glass)
                        LiquidGlassCircleButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                if (cameraEnabled) {
                                    cameraEnabled = false
                                    cameraController.release()
                                } else if (hasCameraPerm) {
                                    cameraEnabled = true
                                } else {
                                    cameraPermLauncher.launch(Manifest.permission.CAMERA)
                                }
                            },
                            icon = if (cameraEnabled) Icons.Rounded.Videocam else Icons.Rounded.VideocamOff,
                            contentDescription = if (cameraEnabled) "Stop camera sharing" else "Share camera with Cel",
                            tint = if (cameraEnabled) CelEmeraldThought else Color(0xFF9E8CFF),
                            active = cameraEnabled,
                            size = 54.dp,
                            iconSize = 23.dp,
                            modifier = Modifier.testTag("live_camera_button"),
                        )

                        // Primary Mic Button (Liquid Glass)
                        val micTint = when (phase) {
                            LivePhase.LISTENING -> CelEmeraldThought
                            LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING, LivePhase.PREPARING_VOICE -> CelAmber
                            else -> visuals.primary
                        }
                        LiquidGlassCircleButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                if (!hasAudioPerm) {
                                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                } else if (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC) {
                                    if (prefs.sttEngine == CelliumSttEngine.ENGINE_DEVICE) {
                                        if (deviceSpeechBuffer.isNotEmpty()) {
                                            // User tapped mic to finish early — submit accumulated utterance immediately!
                                            flushDeviceSpeechAccumulator()
                                        } else {
                                            userStoppedDeviceStt = true
                                            clearDeviceSpeechAccumulator()
                                            runCatching { recognizer?.cancel() }
                                            phase = LivePhase.IDLE
                                            stageLabel = ""
                                            mouthOpenness = 0.05f
                                        }
                                    } else {
                                        viewModel.sttEngine.requestStopRecording()
                                    }
                                } else {
                                    startListening()
                                }
                            },
                            icon = if (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC) Icons.Rounded.MicOff else Icons.Rounded.Mic,
                            contentDescription = "Toggle microphone",
                            tint = micTint,
                            active = true,
                            size = 66.dp,
                            iconSize = 30.dp,
                            modifier = Modifier.testTag("live_mic_button"),
                        )

                        // Keyboard / Type Bar Toggle (Liquid Glass — now toggles & pops up IME reliably!)
                        LiquidGlassCircleButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                val next = !showTypingInput
                                showTypingInput = next
                                if (next) {
                                    typingFocusNonce++
                                } else {
                                    keyboardController?.hide()
                                    focusManager.clearFocus()
                                }
                            },
                            icon = Icons.Rounded.Keyboard,
                            contentDescription = "Type in Live Mode",
                            tint = if (showTypingInput) visuals.secondary else Color(0xFF9E8CFF),
                            active = showTypingInput,
                            size = 54.dp,
                            iconSize = 22.dp,
                            modifier = Modifier.testTag("live_keyboard_button"),
                        )

                        // Hang Up (Liquid Glass Red)
                        LiquidGlassCircleButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                triggerExit()
                            },
                            icon = Icons.Rounded.CallEnd,
                            contentDescription = "End Live Mode",
                            tint = CelDangerRed,
                            active = true,
                            size = 60.dp,
                            iconSize = 26.dp,
                            modifier = Modifier.testTag("live_hangup_button"),
                        )
                    }
                }
            }
        }

        // Independent Top-Left Live Status Bubble ("Listening...", "Transcribing...", "Thinking...", etc.)
        // Completely decoupled from the chat bubble so status transitions NEVER jump or resize the chat bubble!
        Box(
            modifier = Modifier
                .align(Alignment.TopStart)
                .statusBarsPadding()
                .padding(top = 60.dp, start = 16.dp)
                .graphicsLayer { alpha = contentAlpha },
        ) {
            AnimatedVisibility(
                visible = !guiHidden && topLeftStatusText.isNotBlank(),
                enter = fadeIn(tween(180)) + slideInVertically(tween(200)) { -it / 2 },
                exit = fadeOut(tween(180)),
            ) {
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(99.dp))
                        .background(
                            Brush.verticalGradient(
                                listOf(
                                    statusDotColor.copy(alpha = 0.24f),
                                    Color(0xCC0D0A1A),
                                )
                            )
                        )
                        .border(
                            width = 1.dp,
                            brush = Brush.verticalGradient(
                                listOf(
                                    Color.White.copy(alpha = 0.42f),
                                    statusDotColor.copy(alpha = 0.45f),
                                )
                            ),
                            shape = RoundedCornerShape(99.dp),
                        )
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                        .testTag("live_status_pill"),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    Box(
                        modifier = Modifier
                            .size(7.dp)
                            .clip(CircleShape)
                            .background(statusDotColor)
                    )
                    Text(
                        text = topLeftStatusText,
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextPrimary,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        softWrap = false,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }

        // Optional Top-Right Cel Face Animation Name HUD Badge (toggled next to Dev Logs)
        if (prefs.showAvatarAnimName && !guiHidden) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .statusBarsPadding()
                    .padding(
                        top = 60.dp,
                        end = if (cameraEnabled && hasCameraPerm) 134.dp else 14.dp,
                    )
                    .graphicsLayer { alpha = contentAlpha }
                    .clip(RoundedCornerShape(99.dp))
                    .background(
                        Brush.verticalGradient(
                            listOf(
                                visuals.primary.copy(alpha = 0.22f),
                                Color(0xCC0C0918),
                            )
                        )
                    )
                    .border(1.dp, visuals.primary.copy(alpha = 0.45f), RoundedCornerShape(99.dp))
                    .padding(horizontal = 10.dp, vertical = 5.dp)
                    .testTag("live_anim_name_badge"),
            ) {
                Text(
                    text = "${prefs.avatarGender} · $activeAnimDisplayName",
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = CelLavender,
                    maxLines = 1,
                    softWrap = false,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        // Live Camera PiP Preview (Gemini-Live style, top-right below top controls)
        if (cameraEnabled && hasCameraPerm && !guiHidden) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .statusBarsPadding()
                    .padding(top = 60.dp, end = 14.dp)
                    .size(width = 112.dp, height = 152.dp)
                    .clip(RoundedCornerShape(18.dp))
                    .background(Color(0xFF0A0812))
                    .border(1.5.dp, visuals.primary.copy(alpha = 0.75f), RoundedCornerShape(18.dp)),
            ) {
                AndroidView(
                    factory = { ctx ->
                        TextureView(ctx).also { tv ->
                            cameraController.attach(tv, useFrontCamera)
                        }
                    },
                    update = {
                        cameraController.switchLens(useFrontCamera)
                    },
                    modifier = Modifier.fillMaxSize(),
                )
                Row(
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(6.dp)
                        .clip(RoundedCornerShape(99.dp))
                        .background(Color(0xB8000000))
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(CelEmeraldThought))
                    Text("CAM", fontSize = 9.sp, fontWeight = FontWeight.Bold, color = Color.White)
                }
                IconButton(
                    onClick = {
                        viewModel.soundEngine.playClick()
                        useFrontCamera = !useFrontCamera
                    },
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(4.dp)
                        .size(30.dp)
                        .clip(CircleShape)
                        .background(Color(0xB8000000)),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Cameraswitch,
                        contentDescription = "Flip Camera",
                        tint = Color.White,
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
        }

        // Top-End Liquid Glass Controls: Voice Settings Shortcut + Immersive Hide Eye Toggle
        Row(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .statusBarsPadding()
                .padding(top = 12.dp, end = 14.dp)
                .graphicsLayer { alpha = contentAlpha },
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(180)),
                exit = fadeOut(tween(180)),
            ) {
                LiquidGlassCircleButton(
                    onClick = {
                        viewModel.soundEngine.playClick()
                        triggerExit(afterExit = onOpenVoiceSettings)
                    },
                    icon = Icons.Rounded.Settings,
                    contentDescription = "Voice Settings",
                    tint = visuals.primary,
                    active = false,
                    size = 40.dp,
                    iconSize = 19.dp,
                    modifier = Modifier.testTag("live_voice_settings_button"),
                )
            }

            AnimatedVisibility(
                visible = eyeVisible,
                enter = fadeIn(tween(180)),
                exit = fadeOut(tween(260)),
            ) {
                LiquidGlassCircleButton(
                    onClick = {
                        viewModel.soundEngine.playClick()
                        guiHidden = !guiHidden
                    },
                    icon = if (guiHidden) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                    contentDescription = if (guiHidden) "Show Live GUI" else "Hide Live GUI",
                    tint = if (guiHidden) CelLavender else visuals.primary,
                    active = guiHidden,
                    size = 40.dp,
                    iconSize = 20.dp,
                    modifier = Modifier.testTag("live_eye_toggle"),
                )
            }
        }
    }

    // Persona Picker Sheet (#4r)
    if (showPersonaPicker) {
        PersonaPickerSheet(
            activePersonaId = uiState.activePersonaId,
            customPersonas = uiState.customPersonas,
            onSelect = { viewModel.selectPersona(it) },
            onDismiss = { showPersonaPicker = false },
        )
    }

    // Quick In-Live Chat Switcher Dialog (#4s)
    if (showChatSwitcher) {
        val availableChats = remember(uiState.sessions) {
            uiState.sessions.filter { !it.isLocked && !it.isArena }
                .sortedByDescending { it.updatedAtMs }
                .take(30)
        }
        AlertDialog(
            onDismissRequest = { showChatSwitcher = false },
            containerColor = Color(0xFF120E1D),
            title = {
                Text("Switch Live Chat", color = CelTextPrimary, style = MaterialTheme.typography.titleMedium)
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = visuals.primary.copy(alpha = 0.22f),
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .clickable {
                                showChatSwitcher = false
                                viewModel.startNewSession("Live · ${persona.name}")
                                userTranscript = ""
                                celReply = ""
                                errorMsg = null
                                failedPrompt = null
                                failedBitmap = null
                            },
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(Icons.Rounded.Add, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(18.dp))
                            Text("Create New Chat", style = MaterialTheme.typography.labelLarge, color = CelTextPrimary)
                        }
                    }

                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().heightIn(max = 280.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(availableChats, key = { it.id }) { sess ->
                            val isActive = sess.id == uiState.activeSessionId
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (isActive) visuals.primary.copy(alpha = 0.20f) else CelTerminalBg)
                                    .clickable {
                                        showChatSwitcher = false
                                        viewModel.selectSession(sess.id)
                                        userTranscript = ""
                                        celReply = ""
                                        errorMsg = null
                                        failedPrompt = null
                                        failedBitmap = null
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = sess.title.ifBlank { "Untitled Chat" },
                                        style = MaterialTheme.typography.labelMedium,
                                        color = CelTextPrimary,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        text = "${sess.messageCount} msgs · ${sess.lastMessagePreview.ifBlank { "Empty" }}",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = CelTextSecondary,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                if (isActive) {
                                    Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                                }
                            }
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showChatSwitcher = false }) {
                    Text("Close", color = CelLavender)
                }
            },
        )
    }
}

@Composable
private fun LiveSmartChatBubble(
    userTranscript: String,
    celReply: String,
    errorMsg: String?,
    failedPrompt: String?,
    isActivePhase: Boolean,
    isSpeaking: Boolean,
    maxBubbleHeight: Dp,
    idleHint: String,
    accent: Color,
    onRetry: () -> Unit,
) {
    val scrollState = rememberScrollState()
    val hasContent = userTranscript.isNotBlank() || celReply.isNotBlank() || errorMsg != null

    // Keep the newest spoken lines anchored cleanly at the bottom while Cel speaks/types;
    // older lines gracefully slide up behind the top "..." ellipsis fade until Cel finishes!
    LaunchedEffect(celReply, userTranscript, errorMsg, isSpeaking) {
        if (scrollState.maxValue > 0) {
            scrollState.scrollTo(scrollState.maxValue)
        }
    }

    if (!hasContent && idleHint.isBlank()) return

    val bubbleShape = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp, bottomStart = 20.dp, bottomEnd = 20.dp)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(bubbleShape)
            .background(
                Brush.verticalGradient(
                    listOf(
                        Color(0xD8140E24),
                        Color(0xE80A0714),
                    )
                )
            )
            .border(
                width = if (isActivePhase) 1.35.dp else 1.dp,
                brush = Brush.verticalGradient(
                    listOf(
                        if (isActivePhase) accent.copy(alpha = 0.80f) else Color.White.copy(alpha = 0.28f),
                        accent.copy(alpha = 0.30f),
                    )
                ),
                shape = bubbleShape,
            ),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .heightIn(max = maxBubbleHeight)
                .verticalScroll(scrollState)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            if (!hasContent) {
                Text(
                    text = idleHint,
                    style = MaterialTheme.typography.labelMedium,
                    color = CelTextSecondary,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                if (userTranscript.isNotBlank()) {
                    Text(
                        text = "\"$userTranscript\"",
                        style = MaterialTheme.typography.labelMedium,
                        color = CelTextSecondary,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                if (celReply.isNotBlank()) {
                    Text(
                        text = celReply,
                        style = MaterialTheme.typography.bodyMedium,
                        color = CelLavender,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                if (errorMsg != null) {
                    Text(
                        text = errorMsg,
                        style = MaterialTheme.typography.bodySmall,
                        color = CelDangerRed,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (failedPrompt != null) {
                        Spacer(Modifier.height(2.dp))
                        Button(
                            onClick = onRetry,
                            colors = ButtonDefaults.buttonColors(containerColor = accent),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.testTag("live_retry_button"),
                        ) {
                            Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text("Retry Message", maxLines = 1, softWrap = false)
                        }
                    }
                }
            }
        }

        // Top ellipsis fade mask whenever older text has scrolled past the top edge
        if (scrollState.value > 6) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .height(34.dp)
                    .background(
                        Brush.verticalGradient(
                            listOf(
                                Color(0xF5120C21),
                                Color(0xAA120C21),
                                Color.Transparent,
                            )
                        )
                    ),
                contentAlignment = Alignment.TopCenter,
            ) {
                Box(
                    modifier = Modifier
                        .padding(top = 3.dp)
                        .clip(RoundedCornerShape(99.dp))
                        .background(Color(0xD81B1330))
                        .border(0.8.dp, accent.copy(alpha = 0.45f), RoundedCornerShape(99.dp))
                        .padding(horizontal = 10.dp, vertical = 1.dp),
                ) {
                    Text(
                        text = "...",
                        style = MaterialTheme.typography.labelSmall.copy(fontWeight = FontWeight.Bold),
                        color = CelLavender,
                        maxLines = 1,
                    )
                }
            }
        }
    }
}

@Composable
private fun LiquidGlassCircleButton(
    onClick: () -> Unit,
    icon: ImageVector,
    contentDescription: String,
    tint: Color,
    active: Boolean,
    size: Dp,
    iconSize: Dp,
    modifier: Modifier = Modifier,
) {
    val fillBrush = remember(tint, active) {
        if (active) {
            Brush.verticalGradient(
                listOf(
                    Color.White.copy(alpha = 0.30f),
                    tint.copy(alpha = 0.62f),
                    tint.copy(alpha = 0.36f),
                )
            )
        } else {
            Brush.verticalGradient(
                listOf(
                    Color.White.copy(alpha = 0.16f),
                    tint.copy(alpha = 0.18f),
                    Color(0x99110D1E),
                )
            )
        }
    }
    val rimBrush = remember(tint, active) {
        Brush.verticalGradient(
            listOf(
                Color.White.copy(alpha = if (active) 0.72f else 0.48f),
                tint.copy(alpha = if (active) 0.65f else 0.32f),
                Color.White.copy(alpha = 0.14f),
            )
        )
    }
    Box(
        modifier = modifier
            .size(size)
            .clip(CircleShape)
            .background(fillBrush)
            .border(1.35.dp, rimBrush, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        // Specular optical glass dome sheen along the top curve
        Canvas(modifier = Modifier.fillMaxSize()) {
            val w = this.size.width
            val h = this.size.height
            drawOval(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color.White.copy(alpha = if (active) 0.34f else 0.22f),
                        Color.Transparent,
                    ),
                    startY = 0f,
                    endY = h * 0.52f,
                ),
                topLeft = Offset(w * 0.14f, h * 0.05f),
                size = Size(w * 0.72f, h * 0.44f),
            )
        }
        Icon(
            imageVector = icon,
            contentDescription = contentDescription,
            tint = Color.White,
            modifier = Modifier.size(iconSize),
        )
    }
}

@Composable
private fun LiveTypingBar(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    accent: Color,
    focusRequester: FocusRequester,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = { Text("Type to Cel...", color = CelTextSecondary, style = MaterialTheme.typography.bodySmall) },
            singleLine = true,
            shape = RoundedCornerShape(18.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = Color(0xCC110D1B),
                unfocusedContainerColor = Color(0xAA110D1B),
                focusedBorderColor = accent,
                unfocusedBorderColor = accent.copy(alpha = 0.35f),
                focusedTextColor = CelTextPrimary,
                unfocusedTextColor = CelTextPrimary,
            ),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
            keyboardActions = KeyboardActions(onSend = { onSend() }),
            modifier = Modifier
                .weight(1f)
                .focusRequester(focusRequester),
        )
        if (value.isNotBlank()) {
            LiquidGlassCircleButton(
                onClick = onSend,
                icon = Icons.AutoMirrored.Rounded.Send,
                contentDescription = "Send typed prompt",
                tint = accent,
                active = true,
                size = 46.dp,
                iconSize = 20.dp,
            )
        }
    }
}

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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
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
        return runCatching { Bitmap.createScaledBitmap(raw, dstW, dstH, true) }.getOrDefault(raw)
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
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val isFloating by FloatingCelOverlayService.isRunning.collectAsStateWithLifecycle()

    // Cinematic intro / outro transition animators
    val introAnim = remember { Animatable(0f) }
    val outroAnim = remember { Animatable(0f) }
    var isExiting by remember { mutableStateOf(false) }

    // Immersive OLED Eye toggle
    var guiHidden by remember { mutableStateOf(false) }
    var eyeVisible by remember { mutableStateOf(true) }
    var eyePokeNonce by remember { mutableIntStateOf(0) }

    var phase by remember { mutableStateOf(LivePhase.IDLE) }
    var stageLabel by remember { mutableStateOf("") }
    var mood by remember { mutableStateOf("idle") }
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    var userTranscript by remember { mutableStateOf("") }
    var celReply by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var mouthOpenness by remember { mutableFloatStateOf(0.05f) }

    // Retry preservation on offline / network failure (#4v)
    var failedPrompt by remember { mutableStateOf<String?>(null) }
    var failedBitmap by remember { mutableStateOf<Bitmap?>(null) }

    // In-place Pickers (#4r, #4s)
    var showPersonaPicker by remember { mutableStateOf(false) }
    var showChatSwitcher by remember { mutableStateOf(false) }

    // Live Typing Input (#4t)
    var showTypingInput by remember { mutableStateOf(false) }
    var typedInput by remember { mutableStateOf("") }

    // Gemini-Live Style Camera Sharing (#4u)
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

    val isSynthLive = prefs.liveTtsEngine == CelliumTtsEngine.ENGINE_SYNTH

    fun cancelAllListeningWithoutSending() {
        userStoppedDeviceStt = true
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

    fun triggerExit() {
        if (isExiting) return
        isExiting = true
        cancelAllListeningWithoutSending()
        viewModel.cancelLiveStream()
        viewModel.ttsEngine.stop()
        cameraEnabled = false
        cameraController.release()
        scope.launch {
            outroAnim.animateTo(1f, tween(durationMillis = 320, easing = FastOutLinearInEasing))
            onClose()
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
                // Hold celReply hidden until TTS voice actually starts (#4j)
            },
            onMoodChanged = { detected ->
                scope.launch(Dispatchers.Main) { mood = detected }
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

    startListening = {
        if (hasAudioPerm && !isExiting) {
            errorMsg = null
            viewModel.ttsEngine.stop()
            cloudSttJob?.cancel()
            phase = LivePhase.PREPARING_MIC
            stageLabel = "Starting mic..."
            mood = "listening"
            listenStartedAtMs = System.currentTimeMillis()
            userStoppedDeviceStt = false

            val sttEngineId = viewModel.preferences.value.sttEngine
            if (sttEngineId == CelliumSttEngine.ENGINE_DEVICE) {
                runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                    .onFailure {
                        phase = LivePhase.IDLE
                        stageLabel = ""
                        errorMsg = "Device speech recognition unavailable. Switch STT engine in Settings -> Voice."
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
                            silenceAutoStopMs = 3_200L,
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
        val sr = if (SpeechRecognizer.isRecognitionAvailable(context)) {
            SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        phase = LivePhase.LISTENING
                        stageLabel = "Listening..."
                    }
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {
                        if (phase == LivePhase.LISTENING) {
                            mouthOpenness = ((rmsdB + 2f) / 14f).coerceIn(0.08f, 0.75f)
                        }
                    }
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {
                        if (!userStoppedDeviceStt) {
                            phase = LivePhase.TRANSCRIBING
                            stageLabel = "Transcribing..."
                        }
                    }
                    override fun onError(error: Int) {
                        val retryable = error == SpeechRecognizer.ERROR_NO_MATCH ||
                            error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT ||
                            error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY
                        val autoOn = viewModel.preferences.value.liveHandsFreeLoop
                        val elapsed = System.currentTimeMillis() - listenStartedAtMs
                        if (!isExiting && !userStoppedDeviceStt && retryable && (autoOn || elapsed < 60_000L)) {
                            scope.launch(Dispatchers.Main) {
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
                        val txt = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                        val cleaned = CelliumSttEngine.sanitizeTranscript(txt.orEmpty())
                        if (cleaned.isNotBlank()) userTranscript = cleaned
                    }
                    override fun onResults(results: Bundle?) {
                        if (userStoppedDeviceStt) return
                        val spoken = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        handleSttTranscript(spoken)
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }
        } else null
        recognizer = sr

        onDispose {
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

        // Centered Dot-Matrix Avatar (always visible even when GUI is hidden!)
        val liveExpr = remember(avatarLibrary, prefs.avatarGender, mood) {
            avatarLibrary?.getForMood(prefs.avatarGender, mood)
                ?: avatarLibrary?.get(prefs.avatarGender, MoodDetector.moodToExpressionName(mood), "Base")
        }
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .graphicsLayer {
                    scaleX = avatarScale
                    scaleY = avatarScale
                    alpha = contentAlpha
                },
            contentAlignment = Alignment.Center,
        ) {
            val faceSize = (minOf(maxWidth, maxHeight) * if (guiHidden && !isSynthLive) 0.88f else 0.72f).coerceIn(210.dp, 420.dp)
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

        // Live Camera PiP Preview (Gemini-Live style, top-right below Eye toggle) (#4u)
        if (cameraEnabled && hasCameraPerm) {
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
                // LIVE CAM indicator badge
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
                // Flip lens button overlaid on PiP
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

        // Foreground HUD overlay
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding()
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .graphicsLayer { alpha = contentAlpha },
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // Top Status Bar (hidden when Hide Eye is ON)
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(240)) + slideInVertically(tween(260)) { -it / 2 },
                exit = fadeOut(tween(220)) + slideOutVertically(tween(220)) { -it / 2 },
                modifier = Modifier.fillMaxWidth().padding(end = 48.dp),
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
                                .background(
                                    when (phase) {
                                        LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING, LivePhase.PREPARING_VOICE -> CelAmber
                                        LivePhase.LISTENING -> CelEmeraldThought
                                        LivePhase.SPEAKING -> visuals.secondary
                                        LivePhase.THINKING, LivePhase.RUNNING_ACTION -> visuals.primary
                                        LivePhase.IDLE -> CelTextSecondary
                                    }
                                )
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

                    // Quick Chat Switcher Pill (#4s)
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

                    // Active Persona Pill (#4r)
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

                    // Auto / Manual Mode Toggle (#4l, #4q)
                    GlassPill(
                        onClick = {
                            val nextAuto = !prefs.liveHandsFreeLoop
                            if (!nextAuto) {
                                // Turning Auto OFF cancels recording without sending! (#4l)
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

            Spacer(Modifier.weight(1f))

            // Synth Hide-Eye Minimal Bubbles + Typing Box (#4t): stays visible on OLED black when Synth voice is active!
            if (guiHidden && isSynthLive) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (userTranscript.isNotBlank() || celReply.isNotBlank() || stageLabel.isNotBlank() || errorMsg != null) {
                        GlassCard(
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(18.dp),
                            highlighted = phase != LivePhase.IDLE,
                        ) {
                            if (userTranscript.isNotBlank()) {
                                Text(
                                    text = "You: $userTranscript",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = CelTextSecondary,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                            if (stageLabel.isNotBlank() && celReply.isBlank()) {
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    text = stageLabel,
                                    style = MaterialTheme.typography.labelSmall,
                                    color = CelAmber,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                            if (celReply.isNotBlank()) {
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    text = celReply,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = CelTextPrimary,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                            if (errorMsg != null) {
                                Spacer(Modifier.height(6.dp))
                                Text(
                                    text = errorMsg!!,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = CelDangerRed,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                if (failedPrompt != null) {
                                    Spacer(Modifier.height(6.dp))
                                    Button(
                                        onClick = {
                                            val retryText = failedPrompt ?: return@Button
                                            val retryBmp = failedBitmap
                                            sendLivePrompt(retryText, explicitBitmap = retryBmp, isRetry = true)
                                        },
                                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                                        shape = RoundedCornerShape(12.dp),
                                    ) {
                                        Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("Retry", maxLines = 1, softWrap = false)
                                    }
                                }
                            }
                        }
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
                    )
                }
            }

            // Full Bottom Transcript, Retry, Typing Bar & Camera/Mic/Hangup Controls (visible when GUI is NOT hidden)
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(240)) + slideInVertically(tween(260)) { it / 2 },
                exit = fadeOut(tween(220)) + slideOutVertically(tween(220)) { it / 2 },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    GlassCard(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(20.dp),
                        highlighted = phase != LivePhase.IDLE,
                    ) {
                        val headerText = when {
                            stageLabel.isNotBlank() && phase != LivePhase.SPEAKING -> stageLabel
                            phase == LivePhase.PREPARING_MIC -> "Starting mic ($sttLabel)..."
                            phase == LivePhase.LISTENING && userTranscript.isBlank() ->
                                if (cameraEnabled) "Listening ($sttLabel) · Camera Vision ON" else "Listening ($sttLabel)... take your time"
                            phase == LivePhase.TRANSCRIBING -> "Transcribing via $sttLabel..."
                            userTranscript.isNotBlank() -> "\"$userTranscript\""
                            else -> "Tap mic to talk to ${persona.name} · Voice: ${CelliumTtsEngine.engineLabel(prefs.liveTtsEngine)}"
                        }
                        Text(
                            text = headerText,
                            style = MaterialTheme.typography.titleSmall,
                            color = if (phase == LivePhase.PREPARING_VOICE || phase == LivePhase.RUNNING_ACTION) CelAmber else CelTextPrimary,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        if (celReply.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                            Text(
                                text = celReply,
                                style = MaterialTheme.typography.bodySmall,
                                color = CelLavender,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        if (errorMsg != null) {
                            Spacer(Modifier.height(6.dp))
                            Text(
                                text = errorMsg!!,
                                style = MaterialTheme.typography.bodySmall,
                                color = CelDangerRed,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            if (failedPrompt != null) {
                                Spacer(Modifier.height(8.dp))
                                Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                                    Button(
                                        onClick = {
                                            viewModel.soundEngine.playClick()
                                            val retryText = failedPrompt ?: return@Button
                                            val retryBmp = failedBitmap
                                            sendLivePrompt(retryText, explicitBitmap = retryBmp, isRetry = true)
                                        },
                                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
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

                    if (showTypingInput || isSynthLive) {
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
                        )
                    }

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        // Camera Sharing Toggle (#4u)
                        IconButton(
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
                            modifier = Modifier
                                .size(52.dp)
                                .clip(CircleShape)
                                .background(if (cameraEnabled) CelEmeraldThought else Color(0xFF1A1426))
                                .border(1.5.dp, Color.White.copy(alpha = 0.2f), CircleShape)
                                .testTag("live_camera_button"),
                        ) {
                            Icon(
                                imageVector = if (cameraEnabled) Icons.Rounded.Videocam else Icons.Rounded.VideocamOff,
                                contentDescription = if (cameraEnabled) "Stop camera sharing" else "Share camera with Cel",
                                tint = Color.White,
                                modifier = Modifier.size(24.dp),
                            )
                        }

                        // Primary Mic Button
                        IconButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                if (!hasAudioPerm) {
                                    audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                } else if (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC) {
                                    if (prefs.sttEngine == CelliumSttEngine.ENGINE_DEVICE) {
                                        userStoppedDeviceStt = true
                                        recognizer?.stopListening()
                                        phase = LivePhase.IDLE
                                        stageLabel = ""
                                    } else {
                                        viewModel.sttEngine.requestStopRecording()
                                    }
                                } else {
                                    startListening()
                                }
                            },
                            modifier = Modifier
                                .size(66.dp)
                                .clip(CircleShape)
                                .background(
                                    when (phase) {
                                        LivePhase.LISTENING -> CelEmeraldThought
                                        LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING, LivePhase.PREPARING_VOICE -> CelAmber
                                        else -> visuals.primary
                                    }
                                )
                                .border(2.dp, Color.White.copy(alpha = 0.25f), CircleShape)
                                .testTag("live_mic_button"),
                        ) {
                            Icon(
                                imageVector = if (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC) Icons.Rounded.MicOff else Icons.Rounded.Mic,
                                contentDescription = "Toggle microphone",
                                tint = Color.White,
                                modifier = Modifier.size(30.dp),
                            )
                        }

                        // Keyboard / Type Bar Toggle
                        IconButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                showTypingInput = !showTypingInput
                            },
                            modifier = Modifier
                                .size(52.dp)
                                .clip(CircleShape)
                                .background(if (showTypingInput || isSynthLive) visuals.secondary else Color(0xFF1A1426))
                                .border(1.5.dp, Color.White.copy(alpha = 0.2f), CircleShape),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.Keyboard,
                                contentDescription = "Type in Live Mode",
                                tint = Color.White,
                                modifier = Modifier.size(22.dp),
                            )
                        }

                        // Hang Up
                        IconButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                triggerExit()
                            },
                            modifier = Modifier
                                .size(60.dp)
                                .clip(CircleShape)
                                .background(CelDangerRed)
                                .testTag("live_hangup_button"),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.CallEnd,
                                contentDescription = "End Live Mode",
                                tint = Color.White,
                                modifier = Modifier.size(26.dp),
                            )
                        }
                    }
                }
            }
        }

        // Top-End Immersive Eye Toggle (fades out after hiding GUI; wakes on screen tap)
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .statusBarsPadding()
                .padding(top = 12.dp, end = 14.dp)
                .graphicsLayer { alpha = contentAlpha },
        ) {
            AnimatedVisibility(
                visible = eyeVisible,
                enter = fadeIn(tween(180)),
                exit = fadeOut(tween(260)),
            ) {
                IconButton(
                    onClick = {
                        viewModel.soundEngine.playClick()
                        guiHidden = !guiHidden
                    },
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(Color(0xB80E0A1C))
                        .border(1.dp, visuals.primary.copy(alpha = 0.55f), CircleShape)
                        .testTag("live_eye_toggle"),
                ) {
                    Icon(
                        imageVector = if (guiHidden) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                        contentDescription = if (guiHidden) "Show Live GUI" else "Hide Live GUI",
                        tint = if (guiHidden) CelLavender else Color.White,
                        modifier = Modifier.size(20.dp),
                    )
                }
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
private fun LiveTypingBar(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    accent: Color,
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
            modifier = Modifier.weight(1f),
        )
        if (value.isNotBlank()) {
            IconButton(
                onClick = onSend,
                modifier = Modifier
                    .size(46.dp)
                    .clip(CircleShape)
                    .background(accent),
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Rounded.Send,
                    contentDescription = "Send typed prompt",
                    tint = Color.White,
                    modifier = Modifier.size(20.dp),
                )
            }
        }
    }
}

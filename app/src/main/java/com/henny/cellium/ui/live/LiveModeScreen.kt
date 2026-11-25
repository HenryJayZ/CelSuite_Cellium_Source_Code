package com.henny.cellium.ui.live

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CallEnd
import androidx.compose.material.icons.rounded.Loop
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.MicOff
import androidx.compose.material.icons.rounded.PictureInPictureAlt
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.chat.PersonaPickerSheet
import com.henny.cellium.ui.components.CelliumIcons
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.GlassPill
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
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

private enum class LivePhase { IDLE, PREPARING_MIC, LISTENING, TRANSCRIBING, THINKING, SPEAKING }

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

    // Immersive OLED Eye toggle: hide all GUI; when hidden, eye fades out after 1s and returns for 1s on screen tap
    var guiHidden by remember { mutableStateOf(false) }
    var eyeVisible by remember { mutableStateOf(true) }
    var eyePokeNonce by remember { mutableIntStateOf(0) }

    var phase by remember { mutableStateOf(LivePhase.IDLE) }
    var mood by remember { mutableStateOf("idle") }
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    var userTranscript by remember { mutableStateOf("") }
    var celReply by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var mouthOpenness by remember { mutableFloatStateOf(0.05f) }
    var showPersonaPicker by remember { mutableStateOf(false) }

    var listenStartedAtMs by remember { mutableLongStateOf(0L) }
    var userStoppedDeviceStt by remember { mutableStateOf(false) }

    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var cloudSttJob by remember { mutableStateOf<Job?>(null) }

    fun triggerExit() {
        if (isExiting) return
        isExiting = true
        userStoppedDeviceStt = true
        cloudSttJob?.cancel()
        viewModel.sttEngine.cancelRecording()
        viewModel.ttsEngine.stop()
        runCatching { recognizer?.stopListening() }
        scope.launch {
            outroAnim.animateTo(1f, tween(durationMillis = 340, easing = FastOutLinearInEasing))
            onClose()
        }
    }

    BackHandler { triggerExit() }

    LaunchedEffect(Unit) {
        viewModel.soundEngine.playAssistantSummon()
        introAnim.animateTo(1f, tween(durationMillis = 620, easing = FastOutSlowInEasing))
    }

    LaunchedEffect(guiHidden, eyePokeNonce) {
        if (!guiHidden) {
            eyeVisible = true
        } else {
            eyeVisible = true
            delay(1_000L)
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
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 3_500L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 3_500L)
        putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 60_000L)
    }

    lateinit var startListening: () -> Unit

    fun handleTranscript(spoken: String) {
        if (isExiting) return
        if (spoken.isBlank()) {
            phase = LivePhase.IDLE
            mouthOpenness = 0.05f
            return
        }
        userTranscript = spoken
        phase = LivePhase.THINKING
        mood = "thinking"
        celReply = ""
        errorMsg = null
        viewModel.streamLiveReply(
            transcript = spoken,
            onDelta = { partial -> celReply = partial },
            onMoodChanged = { detected -> mood = detected },
            onComplete = { finalReply ->
                if (isExiting) return@streamLiveReply
                celReply = finalReply
                phase = LivePhase.SPEAKING
                viewModel.speakText(
                    text = finalReply,
                    onStart = {
                        scope.launch(Dispatchers.Main) { phase = LivePhase.SPEAKING }
                    },
                    onComplete = {
                        scope.launch(Dispatchers.Main) {
                            phase = LivePhase.IDLE
                            mouthOpenness = 0.05f
                            if (!isExiting && viewModel.preferences.value.liveHandsFreeLoop && hasAudioPerm) {
                                delay(450)
                                startListening()
                            }
                        }
                    },
                )
            },
            onError = { err ->
                errorMsg = err
                mood = "error"
                phase = LivePhase.IDLE
            },
        )
    }

    startListening = {
        if (hasAudioPerm && !isExiting) {
            errorMsg = null
            viewModel.ttsEngine.stop()
            cloudSttJob?.cancel()
            phase = LivePhase.PREPARING_MIC
            mood = "listening"
            listenStartedAtMs = System.currentTimeMillis()
            userStoppedDeviceStt = false

            val sttEngineId = viewModel.preferences.value.sttEngine
            if (sttEngineId == CelliumSttEngine.ENGINE_DEVICE) {
                runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                    .onFailure {
                        phase = LivePhase.IDLE
                        errorMsg = "Device speech recognition unavailable. Switch STT engine in Settings -> Voice."
                    }
            } else {
                val opt = CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == sttEngineId }
                val apiKey = viewModel.resolveSttApiKey(sttEngineId)
                if (opt?.requiresKey == true && apiKey.isBlank()) {
                    phase = LivePhase.IDLE
                    errorMsg = "Missing API key for ${opt.label}. Add your key in Settings -> Voice & Audio."
                } else {
                    cloudSttJob = scope.launch {
                        val res = viewModel.sttEngine.recordAndTranscribe(
                            engineId = sttEngineId,
                            apiKey = apiKey,
                            modelOverride = viewModel.preferences.value.sttModel,
                            maxDurationMs = 180_000L,
                            preSpeechTimeoutMs = 60_000L,
                            silenceAutoStopMs = 3_500L,
                            manualStopOnly = false,
                            onReadyForSpeech = {
                                scope.launch(Dispatchers.Main) { phase = LivePhase.LISTENING }
                            },
                            onRmsLevel = { lvl ->
                                if (phase == LivePhase.LISTENING) {
                                    mouthOpenness = (0.08f + lvl * 0.72f).coerceIn(0.08f, 0.80f)
                                }
                            },
                            onTranscribing = {
                                scope.launch(Dispatchers.Main) {
                                    phase = LivePhase.TRANSCRIBING
                                    mouthOpenness = 0.05f
                                }
                            },
                            onModelAutoSelected = { picked ->
                                viewModel.persistAutoSelectedSttModel(sttEngineId, picked)
                            },
                        )
                        if (!isExiting) {
                            res.onSuccess { txt ->
                                handleTranscript(txt)
                            }.onFailure { err ->
                                phase = LivePhase.IDLE
                                mouthOpenness = 0.05f
                                val msg = err.localizedMessage.orEmpty()
                                if (!msg.contains("cancelled", ignoreCase = true)) {
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

    DisposableEffect(context) {
        val sr = if (SpeechRecognizer.isRecognitionAvailable(context)) {
            SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        phase = LivePhase.LISTENING
                    }
                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {
                        if (phase == LivePhase.LISTENING) {
                            mouthOpenness = ((rmsdB + 2f) / 14f).coerceIn(0.08f, 0.75f)
                        }
                    }
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}
                    override fun onError(error: Int) {
                        val elapsed = System.currentTimeMillis() - listenStartedAtMs
                        val retryable = error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                        if (!isExiting && !userStoppedDeviceStt && retryable && elapsed < 60_000L) {
                            scope.launch(Dispatchers.Main) {
                                delay(120L)
                                if (!isExiting && !userStoppedDeviceStt) {
                                    runCatching { recognizer?.startListening(buildDeviceSpeechIntent()) }
                                }
                            }
                        } else {
                            phase = LivePhase.IDLE
                            mouthOpenness = 0.05f
                        }
                    }
                    override fun onPartialResults(partialResults: Bundle?) {
                        val txt = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                        if (!txt.isNullOrBlank()) userTranscript = txt
                    }
                    override fun onResults(results: Bundle?) {
                        val spoken = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                        handleTranscript(spoken)
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }
        } else null
        recognizer = sr

        onDispose {
            cloudSttJob?.cancel()
            viewModel.sttEngine.cancelRecording()
            runCatching { sr?.destroy() }
            viewModel.ttsEngine.stop()
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
            val center = Offset(size.width * 0.5f, size.height * 0.48f)
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
            val faceSize = (minOf(maxWidth, maxHeight) * if (guiHidden) 0.88f else 0.78f).coerceIn(220.dp, 440.dp)
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
                    scale = if (guiHidden) 1.24f else 1.15f,
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

        // Foreground HUD overlay (smoothly hidden when user toggles Eye icon)
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
            // Top Status Bar (leaves right clearance for Eye toggle)
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
                    GlassPill(onClick = {}) {
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(
                                    when (phase) {
                                        LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING -> Color(0xFFFBBF24)
                                        LivePhase.LISTENING -> CelEmeraldThought
                                        LivePhase.SPEAKING -> visuals.secondary
                                        LivePhase.THINKING -> visuals.primary
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
                                    append(rawModel.take(18))
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

                    GlassPill(
                        onClick = {
                            scope.launch {
                                viewModel.prefsStore.updateVoiceSettings(
                                    prefs.ttsVoiceName,
                                    prefs.ttsPitch,
                                    prefs.ttsSpeechRate,
                                    prefs.autoReadReplies,
                                    !prefs.liveHandsFreeLoop,
                                    prefs.ttsEngine,
                                )
                                viewModel.notifyPrefsChangedForSync()
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

            // Bottom Transcript & Mic/Hangup Controls
            AnimatedVisibility(
                visible = !guiHidden,
                enter = fadeIn(tween(240)) + slideInVertically(tween(260)) { it / 2 },
                exit = fadeOut(tween(220)) + slideOutVertically(tween(220)) { it / 2 },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    GlassCard(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(20.dp),
                        highlighted = phase != LivePhase.IDLE,
                    ) {
                        Text(
                            text = when {
                                phase == LivePhase.PREPARING_MIC -> "Starting mic ($sttLabel)..."
                                phase == LivePhase.LISTENING && userTranscript.isBlank() -> "Listening ($sttLabel)... take your time"
                                phase == LivePhase.TRANSCRIBING -> "Transcribing via $sttLabel..."
                                userTranscript.isNotBlank() -> "\"$userTranscript\""
                                else -> "Tap mic to talk to ${persona.name} · STT: $sttLabel"
                            },
                            style = MaterialTheme.typography.titleSmall,
                            color = CelTextPrimary,
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
                        }
                    }

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(24.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
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
                                        LivePhase.PREPARING_MIC, LivePhase.TRANSCRIBING -> Color(0xFFF59E0B)
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

                        IconButton(
                            onClick = {
                                viewModel.soundEngine.playClick()
                                triggerExit()
                            },
                            modifier = Modifier
                                .size(66.dp)
                                .clip(CircleShape)
                                .background(CelDangerRed)
                                .testTag("live_hangup_button"),
                        ) {
                            Icon(
                                imageVector = Icons.Rounded.CallEnd,
                                contentDescription = "End Live Mode",
                                tint = Color.White,
                                modifier = Modifier.size(28.dp),
                            )
                        }
                    }
                }
            }
        }

        // Top-End Immersive Eye Toggle (fades out 1s after hiding GUI; wakes for 1s on screen tap)
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

    if (showPersonaPicker) {
        PersonaPickerSheet(
            activePersonaId = uiState.activePersonaId,
            customPersonas = uiState.customPersonas,
            onSelect = { viewModel.selectPersona(it) },
            onDismiss = { showPersonaPicker = false },
        )
    }
}

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
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CallEnd
import androidx.compose.material.icons.rounded.Loop
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.MicOff
import androidx.compose.material.icons.rounded.PictureInPictureAlt
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
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
    BackHandler {
        viewModel.ttsEngine.stop()
        viewModel.sttEngine.requestStopRecording()
        onClose()
    }

    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val isFloating by FloatingCelOverlayService.isRunning.collectAsStateWithLifecycle()

    var phase by remember { mutableStateOf(LivePhase.IDLE) }
    var mood by remember { mutableStateOf("idle") }
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    var userTranscript by remember { mutableStateOf("") }
    var celReply by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var mouthOpenness by remember { mutableFloatStateOf(0.05f) }
    var showPersonaPicker by remember { mutableStateOf(false) }

    LaunchedEffect(context) {
        avatarLibrary = withContext(Dispatchers.IO) { AvatarLibrary.load(context) }
    }
    var hasAudioPerm by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        )
    }

    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }
    var cloudSttJob by remember { mutableStateOf<Job?>(null) }

    lateinit var startListening: () -> Unit

    fun handleTranscript(spoken: String) {
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
                            if (viewModel.preferences.value.liveHandsFreeLoop && hasAudioPerm) {
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
        if (hasAudioPerm) {
            errorMsg = null
            viewModel.ttsEngine.stop()
            cloudSttJob?.cancel()
            phase = LivePhase.PREPARING_MIC
            mood = "listening"

            val sttEngineId = viewModel.preferences.value.sttEngine
            if (sttEngineId == CelliumSttEngine.ENGINE_DEVICE) {
                val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
                }
                runCatching { recognizer?.startListening(intent) }
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
                        )
                        res.onSuccess { txt ->
                            handleTranscript(txt)
                        }.onFailure { err ->
                            phase = LivePhase.IDLE
                            mouthOpenness = 0.05f
                            errorMsg = err.localizedMessage ?: "Speech transcription failed."
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
                        phase = LivePhase.IDLE
                        mouthOpenness = 0.05f
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
            viewModel.sttEngine.requestStopRecording()
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

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // Top Status Bar (Model-First Provider, Persona Switcher, Float Over Apps, Auto Loop)
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
                                    append(" ✦ $shortProv")
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

            // Large Centered Dot-Matrix Avatar
            val liveExpr = remember(avatarLibrary, prefs.avatarGender, mood) {
                avatarLibrary?.getForMood(prefs.avatarGender, mood)
                    ?: avatarLibrary?.get(prefs.avatarGender, MoodDetector.moodToExpressionName(mood), "Base")
            }
            BoxWithConstraints(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .clickable {
                        if (phase == LivePhase.SPEAKING) {
                            viewModel.ttsEngine.stop()
                            startListening()
                        } else {
                            viewModel.soundEngine.playAnimalesePurr()
                            mood = "happy"
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                val faceSize = (minOf(maxWidth, maxHeight) * 0.82f).coerceIn(220.dp, 420.dp)
                DotMatrixAvatarCanvas(
                    expression = liveExpr,
                    scale = 1.15f,
                    mouthOpenness = mouthOpenness,
                    highFps = prefs.highFpsMode,
                    onPetted = {
                        viewModel.soundEngine.playAnimalesePurr()
                        mood = "love"
                    },
                    modifier = Modifier.size(faceSize),
                )
            }

            // Transcript & Controls
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
                            phase == LivePhase.LISTENING && userTranscript.isBlank() -> "Listening ($sttLabel)... tap mic when done"
                            phase == LivePhase.TRANSCRIBING -> "Transcribing via $sttLabel..."
                            userTranscript.isNotBlank() -> "“$userTranscript”"
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
                            if (!hasAudioPerm) {
                                audioPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                            } else if (phase == LivePhase.LISTENING || phase == LivePhase.PREPARING_MIC) {
                                if (prefs.sttEngine == CelliumSttEngine.ENGINE_DEVICE) {
                                    recognizer?.stopListening()
                                    phase = LivePhase.IDLE
                                } else {
                                    // Trigger immediate transcription of what was recorded so far!
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
                            cloudSttJob?.cancel()
                            viewModel.sttEngine.requestStopRecording()
                            viewModel.ttsEngine.stop()
                            recognizer?.stopListening()
                            onClose()
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

    if (showPersonaPicker) {
        PersonaPickerSheet(
            activePersonaId = uiState.activePersonaId,
            customPersonas = uiState.customPersonas,
            onSelect = { viewModel.selectPersona(it) },
            onDismiss = { showPersonaPicker = false },
        )
    }
}

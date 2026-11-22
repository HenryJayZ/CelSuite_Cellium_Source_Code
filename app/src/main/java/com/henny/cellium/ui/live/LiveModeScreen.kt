package com.henny.cellium.ui.live

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.CallEnd
import androidx.compose.material.icons.rounded.Loop
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.MicOff
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.GlassPill
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale
import kotlin.math.sin

private enum class LivePhase { IDLE, LISTENING, THINKING, SPEAKING }

@Composable
fun LiveModeScreen(
    viewModel: CelliumViewModel,
    onClose: () -> Unit,
) {
    BackHandler { onClose() }

    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()

    var phase by remember { mutableStateOf(LivePhase.IDLE) }
    var mood by remember { mutableStateOf("idle") }
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    var userTranscript by remember { mutableStateOf("") }
    var celReply by remember { mutableStateOf("") }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var mouthOpenness by remember { mutableFloatStateOf(0.05f) }

    LaunchedEffect(context) {
        avatarLibrary = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { AvatarLibrary.load(context) }
    }
    var hasAudioPerm by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        )
    }

    var tts by remember { mutableStateOf<TextToSpeech?>(null) }
    var recognizer by remember { mutableStateOf<SpeechRecognizer?>(null) }

    fun startListening() {
        if (!hasAudioPerm) return
        errorMsg = null
        tts?.stop()
        phase = LivePhase.LISTENING
        mood = "excited"
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault())
        }
        runCatching { recognizer?.startListening(intent) }
            .onFailure {
                phase = LivePhase.IDLE
                errorMsg = "Speech recognition unavailable on this device."
            }
    }

    fun speakReply(text: String) {
        val engine = tts
        if (engine == null) {
            phase = LivePhase.IDLE
            return
        }
        engine.setPitch(prefs.ttsPitch)
        engine.setSpeechRate(prefs.ttsSpeechRate)
        if (prefs.ttsVoiceName.isNotBlank()) {
            engine.voices?.firstOrNull { it.name == prefs.ttsVoiceName }?.let { engine.voice = it }
        }
        phase = LivePhase.SPEAKING
        val clean = text.replace(Regex("[`*_#>]"), "").take(900)
        engine.speak(clean, TextToSpeech.QUEUE_FLUSH, null, "cel_live_utt")
    }

    val audioPermLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasAudioPerm = granted
        if (granted) startListening()
        else errorMsg = "Microphone permission is required for CelAS Live Mode."
    }

    DisposableEffect(context) {
        var localTts: TextToSpeech? = null
        localTts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                localTts?.language = Locale.US
                localTts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) {}
                    override fun onDone(utteranceId: String?) {
                        scope.launch {
                            phase = LivePhase.IDLE
                            mouthOpenness = 0.05f
                            if (prefs.liveHandsFreeLoop && hasAudioPerm) {
                                delay(450)
                                startListening()
                            }
                        }
                    }
                    @Deprecated("Deprecated in Java")
                    override fun onError(utteranceId: String?) {
                        scope.launch { phase = LivePhase.IDLE; mouthOpenness = 0.05f }
                    }
                })
            }
        }
        tts = localTts

        val sr = if (SpeechRecognizer.isRecognitionAvailable(context)) {
            SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {}
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
                        if (spoken.isBlank()) {
                            phase = LivePhase.IDLE
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
                            onComplete = { finalReply ->
                                celReply = finalReply
                                mood = MoodDetector.detectMood(finalReply)
                                speakReply(finalReply)
                            },
                            onError = { err ->
                                errorMsg = err
                                mood = "error"
                                phase = LivePhase.IDLE
                            },
                        )
                    }
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }
        } else null
        recognizer = sr

        onDispose {
            runCatching { sr?.destroy() }
            runCatching { localTts?.stop(); localTts?.shutdown() }
        }
    }

    // Animate mouth while speaking
    LaunchedEffect(phase) {
        if (phase != LivePhase.SPEAKING) {
            mouthOpenness = 0.05f
            return@LaunchedEffect
        }
        var t = 0f
        while (phase == LivePhase.SPEAKING) {
            t += 0.35f
            mouthOpenness = (0.35f + 0.35f * sin(t)).coerceIn(0.10f, 0.85f)
            delay(55L)
        }
    }

    val provName = uiState.activeProvider?.name ?: "Pollinations Free"
    val provIconKey = uiState.activeProvider?.badge ?: "sparkle"

    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 18.dp, vertical = 14.dp),
    ) {
        Column(
            modifier = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween,
        ) {
            // Top Status Bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                GlassPill(onClick = {}) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(
                                when (phase) {
                                    LivePhase.LISTENING -> CelEmeraldThought
                                    LivePhase.SPEAKING -> visuals.secondary
                                    LivePhase.THINKING -> visuals.primary
                                    LivePhase.IDLE -> CelTextSecondary
                                }
                            )
                    )
                    Icon(
                        imageVector = com.henny.cellium.ui.components.CelliumIcons.resolve(provIconKey),
                        contentDescription = null,
                        tint = visuals.primary,
                        modifier = Modifier.size(14.dp),
                    )
                    Text(
                        text = "Live · ${provName.take(18)}",
                        style = MaterialTheme.typography.labelMedium,
                        color = CelTextPrimary,
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
                            )
                        }
                    },
                    selected = prefs.liveHandsFreeLoop,
                    modifier = Modifier.testTag("live_handsfree_toggle"),
                ) {
                    Icon(Icons.Rounded.Loop, contentDescription = "Hands-free loop", modifier = Modifier.size(15.dp), tint = CelTextPrimary)
                    Text(if (prefs.liveHandsFreeLoop) "Auto" else "Manual", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary)
                }
            }

            // Center Interactive Dot-Matrix Avatar (Tap to barge-in / headpat)
            val liveExpr = remember(avatarLibrary, prefs.avatarGender, mood) {
                avatarLibrary?.get(prefs.avatarGender, MoodDetector.moodToExpressionName(mood), "Base")
            }
            Box(
                modifier = Modifier
                    .size(260.dp)
                    .clickable {
                        if (phase == LivePhase.SPEAKING) {
                            tts?.stop()
                            startListening()
                        } else {
                            viewModel.soundEngine.playAnimalesePurr()
                            mood = "happy"
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                DotMatrixAvatarCanvas(
                    expression = liveExpr,
                    mouthOpenness = mouthOpenness,
                    highFps = prefs.highFpsMode,
                    onPetted = {
                        viewModel.soundEngine.playAnimalesePurr()
                        mood = "love"
                    },
                    modifier = Modifier.size(230.dp),
                )
            }

            // Transcript & Controls
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                GlassCard(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(20.dp),
                    highlighted = phase != LivePhase.IDLE,
                ) {
                    Text(
                        text = when {
                            userTranscript.isNotBlank() -> "“$userTranscript”"
                            phase == LivePhase.LISTENING -> "Listening…"
                            else -> "Tap mic to talk to ${uiState.resolvedPersona.name}"
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
                            } else if (phase == LivePhase.LISTENING) {
                                recognizer?.stopListening()
                                phase = LivePhase.IDLE
                            } else {
                                startListening()
                            }
                        },
                        modifier = Modifier
                            .size(66.dp)
                            .clip(CircleShape)
                            .background(if (phase == LivePhase.LISTENING) CelEmeraldThought else visuals.primary)
                            .border(2.dp, Color.White.copy(alpha = 0.25f), CircleShape)
                            .testTag("live_mic_button"),
                    ) {
                        Icon(
                            imageVector = if (phase == LivePhase.LISTENING) Icons.Rounded.MicOff else Icons.Rounded.Mic,
                            contentDescription = "Toggle microphone",
                            tint = Color.White,
                            modifier = Modifier.size(30.dp),
                        )
                    }

                    IconButton(
                        onClick = {
                            tts?.stop()
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
}

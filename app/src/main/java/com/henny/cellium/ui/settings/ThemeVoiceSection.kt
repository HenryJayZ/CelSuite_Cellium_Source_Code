package com.henny.cellium.ui.settings

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import android.speech.tts.TextToSpeech
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Assistant
import androidx.compose.material.icons.rounded.AudioFile
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Hearing
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Restore
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material.icons.rounded.Wallpaper
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.assistant.WakeWordService
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.CelliumThemePresets
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.Locale

private val TYPING_SPEED_OPTIONS = listOf(
    "super_slow" to "Super Slow",
    "slow" to "Slow",
    "medium" to "Medium",
    "fast" to "Fast",
    "very_fast" to "Very Fast",
    "instant" to "Instant (Live Stream)",
)

private val VOICE_PREVIEW_LINES = listOf(
    "Hey bestie! Ready to build something iconic today?",
    "Cel dot Cellium voice check, crystal clear and cozy.",
    "Ooooh, how does this voice feel to your ears?",
    "Hello from inside your pocket! Let us cook something awesome.",
    "Testing one, two, three! Smooth as velvet on midnight glass.",
    "Hey! Pick me if you want late-night chats that sound warm.",
    "Good vibes only! Every syllable calibrated just for you.",
    "System check complete! Ready whenever you say Okay Cel.",
    "Hi there! Ask me anything, from tiny questions to giant ideas.",
    "Ooh, nice choice! Let us see if this cadence matches your mood.",
    "Live voice ready! Tell me what is on your mind right now.",
    "Testing the studio acoustics. Zero static, maximum personality.",
    "Hey friend! Want to brainstorm, vent, or write some code?",
    "Sound check! Pitch, pace, and sparkle are all locked in.",
    "Ready on standby! Tap any voice and I will switch on the fly.",
    "Voice sample live! Dial the pitch or speed however you like.",
    "All systems humming! Let us turn a small spark into magic.",
    "Hi bestie! I promise never to read emojis out loud like a robot.",
    "Fresh line coming through! Do I pass the vibe check?",
    "Spotlight on! Pick your favorite voice and let us roll.",
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ThemeWallpaperStudioCard(
    prefs: CelliumPreferences,
    viewModel: CelliumViewModel,
) {
    val context = LocalContext.current
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    var customHex by remember(prefs.customPrimaryHex) { mutableStateOf(prefs.customPrimaryHex) }

    var dimDraft by remember(prefs.wallpaperDim) { mutableFloatStateOf(prefs.wallpaperDim) }
    var glassDraft by remember(prefs.glassOpacity) { mutableFloatStateOf(prefs.glassOpacity) }
    var glowDraft by remember(prefs.borderGlow) { mutableFloatStateOf(prefs.borderGlow) }
    var particleDraft by remember(prefs.particleDensity) { mutableFloatStateOf(prefs.particleDensity.toFloat()) }

    val wallpaperPicker = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) {
            scope.launch { viewModel.prefsStore.updateCustomWallpaperUri(uri.toString()) }
        }
    }

    GlassCard(shape = RoundedCornerShape(22.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(Icons.Rounded.Palette, contentDescription = null, tint = visuals.primary)
            Column {
                Text("Theme, Wallpaper & Liquid Glass", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                Text("6 presets + custom accent hex + glass controls", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            }
        }

        Spacer(Modifier.height(10.dp))

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            CelliumThemePresets.ALL.forEach { preset ->
                FilterChip(
                    selected = prefs.themePresetId == preset.id,
                    onClick = { scope.launch { viewModel.prefsStore.updateThemePreset(preset.id) } },
                    leadingIcon = {
                        Box(modifier = Modifier.size(10.dp).clip(CircleShape).background(preset.primary))
                    },
                    label = { Text(preset.name, maxLines = 1, softWrap = false) },
                )
            }
            FilterChip(
                selected = prefs.themePresetId == "custom",
                onClick = { scope.launch { viewModel.prefsStore.updateThemePreset("custom") } },
                label = { Text("Custom Hex", maxLines = 1, softWrap = false) },
            )
        }

        if (prefs.themePresetId == "custom") {
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = customHex,
                    onValueChange = {
                        customHex = it
                        scope.launch { viewModel.prefsStore.updateCustomPrimaryHex(it) }
                    },
                    label = { Text("Accent Hex (#A855F7)") },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(12.dp),
                )
                Box(
                    modifier = Modifier
                        .size(38.dp)
                        .clip(CircleShape)
                        .background(CelliumThemePresets.parseHexColor(customHex))
                        .border(1.dp, visuals.activeBorder, CircleShape)
                )
            }
        }

        Spacer(Modifier.height(10.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(
                onClick = { wallpaperPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.weight(1f).testTag("pick_wallpaper_button"),
            ) {
                Icon(Icons.Rounded.Wallpaper, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Custom Wallpaper", maxLines = 1, softWrap = false)
            }
            if (prefs.customWallpaperUri.isNotBlank()) {
                TextButton(onClick = { scope.launch { viewModel.prefsStore.updateCustomWallpaperUri("") } }) {
                    Text("Reset", maxLines = 1, softWrap = false)
                }
            }
        }

        Spacer(Modifier.height(8.dp))
        Text("Wallpaper Dim: ${(dimDraft * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = dimDraft,
            onValueChange = { dimDraft = it },
            onValueChangeFinished = {
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(dimDraft, glassDraft, glowDraft, particleDraft.toInt(), prefs.fontScale)
                }
            },
            valueRange = 0.15f..0.88f,
        )

        Text("Glass Opacity: ${(glassDraft * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = glassDraft,
            onValueChange = { glassDraft = it },
            onValueChangeFinished = {
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(dimDraft, glassDraft, glowDraft, particleDraft.toInt(), prefs.fontScale)
                }
            },
            valueRange = 0.35f..0.96f,
        )

        Text("Border Glow: ${(glowDraft * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = glowDraft,
            onValueChange = { glowDraft = it },
            onValueChangeFinished = {
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(dimDraft, glassDraft, glowDraft, particleDraft.toInt(), prefs.fontScale)
                }
            },
            valueRange = 0.15f..1.0f,
        )

        Text("Ambient Particles: ${particleDraft.toInt()}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = particleDraft,
            onValueChange = { particleDraft = it },
            onValueChangeFinished = {
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(dimDraft, glassDraft, glowDraft, particleDraft.toInt(), prefs.fontScale)
                }
            },
            valueRange = 0f..48f,
        )

        SettingSwitchRow("60 FPS High-Smoothness Mode", prefs.highFpsMode) {
            scope.launch { viewModel.prefsStore.updateHighFpsMode(it) }
        }
        SettingSwitchRow("Wrap Long Lines in Code Blocks (Default ON)", prefs.codeWordWrap) {
            scope.launch { viewModel.prefsStore.updateCodeWordWrap(it) }
        }
        SettingSwitchRow("System Floating Cel Overlay (Over All Apps)", prefs.floatingMiniCel) { enabled ->
            if (enabled && !Settings.canDrawOverlays(context)) {
                val intent = Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:${context.packageName}"),
                )
                runCatching { context.startActivity(intent) }
                viewModel.showBanner("Grant 'Display over other apps' permission, then toggle Floating Cel ON.")
            } else {
                scope.launch { viewModel.prefsStore.updateFloatingMiniCel(enabled) }
                if (enabled) {
                    FloatingCelOverlayService.start(context, autoListen = false)
                } else {
                    FloatingCelOverlayService.stop(context)
                }
            }
        }
    }
}

private data class SystemVoiceItem(
    val rawName: String,
    val shortLabel: String,
    val languageGroup: String,
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun VoiceAndAudioLabCard(
    prefs: CelliumPreferences,
    viewModel: CelliumViewModel,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // Split Voice Profile Tab: false = Normal Chat (Speaker), true = Live & Floating (#4t)
    var editingLiveProfile by remember { mutableStateOf(false) }

    val selectedEngine = (if (editingLiveProfile) prefs.liveTtsEngine else prefs.ttsEngine)
        .ifBlank { CelliumTtsEngine.ENGINE_SYNTH }
    val selectedVoiceId = if (editingLiveProfile) prefs.liveTtsVoiceName else prefs.ttsVoiceName
    val persistedPitch = if (editingLiveProfile) prefs.liveTtsPitch else prefs.ttsPitch
    val persistedRate = if (editingLiveProfile) prefs.liveTtsSpeechRate else prefs.ttsSpeechRate

    var systemVoices by remember { mutableStateOf<List<SystemVoiceItem>>(emptyList()) }
    var expandedGroups by remember { mutableStateOf<Set<String>>(emptySet()) }
    var voiceSearch by remember { mutableStateOf("") }

    // Smooth slider drafts (widened pitch 0.25..2.50 & rate 0.50..2.20 per #1)
    var pitchDraft by remember(editingLiveProfile, persistedPitch) { mutableFloatStateOf(persistedPitch.coerceIn(0.25f, 2.50f)) }
    var rateDraft by remember(editingLiveProfile, persistedRate) { mutableFloatStateOf(persistedRate.coerceIn(0.50f, 2.20f)) }
    var sfxVolDraft by remember(prefs.sfxVolume) { mutableFloatStateOf(prefs.sfxVolume) }
    var chirpPitchDraft by remember(prefs.typingSoundPitch) { mutableFloatStateOf(prefs.typingSoundPitch.coerceIn(0.25f, 2.50f)) }
    var wakeSensDraft by remember(prefs.wakeWordSensitivity) { mutableFloatStateOf(prefs.wakeWordSensitivity.coerceIn(0.05f, 0.90f)) }
    var lastPreviewIdx by remember { mutableIntStateOf(-1) }
    var startupCacheBytes by remember(prefs.deletedStartupSoundIds, prefs.startupSoundId) {
        mutableStateOf(viewModel.soundEngine.getStartupCacheBytes())
    }

    val liveWakeScore by WakeWordService.liveScore.collectAsStateWithLifecycle()
    val wakeRunning by WakeWordService.isRunning.collectAsStateWithLifecycle()
    val wakeMicActive by WakeWordService.micActive.collectAsStateWithLifecycle()

    fun nextUniquePreviewLine(): String {
        val candidates = VOICE_PREVIEW_LINES.indices.filter { it != lastPreviewIdx }
        val picked = candidates.random()
        lastPreviewIdx = picked
        return VOICE_PREVIEW_LINES[picked]
    }

    fun persistProfileVoice(engine: String, voiceId: String, pitch: Float, rate: Float) {
        scope.launch {
            if (editingLiveProfile) {
                viewModel.prefsStore.updateLiveVoiceSettings(engine, voiceId, pitch, rate)
            } else {
                viewModel.prefsStore.updateVoiceSettings(
                    voice = voiceId,
                    pitch = pitch,
                    rate = rate,
                    autoRead = prefs.autoReadReplies,
                    handsFree = prefs.liveHandsFreeLoop,
                    ttsEngine = engine,
                )
            }
            viewModel.notifyPrefsChangedForSync()
        }
    }

    var sttKeyDraft by remember(prefs.sttApiKey) { mutableStateOf(prefs.sttApiKey) }
    var sttModelDraft by remember(prefs.sttModel) { mutableStateOf(prefs.sttModel) }

    val wakeMicLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            scope.launch { viewModel.prefsStore.updateWakeWordSettings(enabled = true) }
            WakeWordService.start(context)
            viewModel.showSettingsFeedback("Okay Cel wake word listening active.")
        } else {
            viewModel.showSettingsFeedback("Microphone permission required for Okay Cel wake word.", isError = true)
        }
    }

    val customTflitePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            scope.launch {
                val savedPath = withContext(Dispatchers.IO) {
                    runCatching {
                        val dest = File(context.filesDir, "wakeword_custom.tflite")
                        context.contentResolver.openInputStream(uri)?.use { input ->
                            FileOutputStream(dest).use { output -> input.copyTo(output) }
                        }
                        dest.absolutePath
                    }.getOrNull()
                }
                if (savedPath != null) {
                    viewModel.prefsStore.updateWakeWordSettings(enabled = prefs.wakeWordEnabled, customPath = savedPath)
                    if (prefs.wakeWordEnabled) {
                        WakeWordService.stop(context)
                        WakeWordService.start(context)
                    }
                    viewModel.showSettingsFeedback("Custom wake word .tflite imported.")
                } else {
                    viewModel.showSettingsFeedback("Failed to import custom .tflite file.", isError = true)
                }
            }
        }
    }

    // Custom Start-up Sound Audio Uploader (#4g)
    val customStartupAudioPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            scope.launch {
                val savedPath = withContext(Dispatchers.IO) {
                    runCatching {
                        val dest = File(context.filesDir, "custom_startup_audio")
                        context.contentResolver.openInputStream(uri)?.use { input ->
                            FileOutputStream(dest).use { output -> input.copyTo(output) }
                        }
                        dest.absolutePath
                    }.getOrNull()
                }
                if (savedPath != null) {
                    viewModel.prefsStore.updateStartupSound("custom", customPath = savedPath)
                    viewModel.soundEngine.startupSoundId = "custom"
                    viewModel.soundEngine.startupSoundCustomPath = savedPath
                    viewModel.soundEngine.playAssistantSummon("custom", savedPath)
                    viewModel.showSettingsFeedback("Custom Start-up sound uploaded & selected.")
                } else {
                    viewModel.showSettingsFeedback("Could not import custom audio file.", isError = true)
                }
            }
        }
    }

    DisposableEffect(context, selectedEngine) {
        if (selectedEngine != CelliumTtsEngine.ENGINE_SYSTEM || systemVoices.isNotEmpty()) {
            return@DisposableEffect onDispose {}
        }
        var engine: TextToSpeech? = null
        engine = TextToSpeech(context) { st ->
            if (st == TextToSpeech.SUCCESS) {
                engine?.language = Locale.US
                val all = engine?.voices
                    ?.filter { !it.isNetworkConnectionRequired }
                    ?.sortedWith(
                        compareByDescending<android.speech.tts.Voice> { it.locale.language == "en" }
                            .thenBy { it.locale.displayLanguage }
                            .thenBy { it.locale.displayCountry }
                            .thenBy { it.name }
                    )
                    ?.map { v ->
                        val shortCode = v.name.substringAfterLast('#').substringAfterLast('-').take(18)
                        val region = v.locale.displayCountry.ifBlank { v.locale.country.uppercase() }
                        val group = if (region.isNotBlank()) "${v.locale.displayLanguage} ($region)" else v.locale.displayLanguage
                        SystemVoiceItem(
                            rawName = v.name,
                            shortLabel = shortCode.ifBlank { v.name.take(18) },
                            languageGroup = group,
                        )
                    }
                    .orEmpty()
                systemVoices = all
                all.firstOrNull { it.languageGroup.startsWith("English (United States)") }?.let {
                    expandedGroups = setOf(it.languageGroup)
                }
            }
        }
        onDispose {
            engine?.stop()
            engine?.shutdown()
        }
    }

    val filteredSynthVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.SYNTH_VOICES
        else CelliumTtsEngine.SYNTH_VOICES.filter {
            it.label.lowercase().contains(q) || it.accent.lowercase().contains(q) || it.gender.lowercase().contains(q)
        }
    }

    val filteredEdgeVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.EDGE_VOICES
        else CelliumTtsEngine.EDGE_VOICES.filter {
            it.label.lowercase().contains(q) || it.accent.lowercase().contains(q) || it.gender.lowercase().contains(q) || it.id.lowercase().contains(q)
        }
    }

    val filteredPollyVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.POLLY_VOICES
        else CelliumTtsEngine.POLLY_VOICES.filter {
            it.label.lowercase().contains(q) || it.accent.lowercase().contains(q) || it.gender.lowercase().contains(q) || it.id.lowercase().contains(q)
        }
    }

    val filteredTikTokVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.TIKTOK_VOICES
        else CelliumTtsEngine.TIKTOK_VOICES.filter {
            it.label.lowercase().contains(q) || it.accent.lowercase().contains(q) || it.gender.lowercase().contains(q) || it.id.lowercase().contains(q)
        }
    }

    val filteredGoogleVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.GOOGLE_VOICES
        else CelliumTtsEngine.GOOGLE_VOICES.filter {
            it.label.lowercase().contains(q) || it.accent.lowercase().contains(q) || it.gender.lowercase().contains(q)
        }
    }

    val groupedSystemVoices = remember(systemVoices, voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        val list = if (q.isEmpty()) systemVoices else systemVoices.filter {
            it.languageGroup.lowercase().contains(q) || it.shortLabel.lowercase().contains(q) || it.rawName.lowercase().contains(q)
        }
        list.groupBy { it.languageGroup }
    }

    val chatVoiceSummary = "${CelliumTtsEngine.engineLabel(prefs.ttsEngine)} · ${CelliumTtsEngine.resolveVoiceLabel(prefs.ttsEngine, prefs.ttsVoiceName)}"
    val liveVoiceSummary = "${CelliumTtsEngine.engineLabel(prefs.liveTtsEngine)} · ${CelliumTtsEngine.resolveVoiceLabel(prefs.liveTtsEngine, prefs.liveTtsVoiceName)}"

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // 0. Currently Selected Voices Banner (#6)
        GlassCard(highlighted = true, shape = RoundedCornerShape(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.VolumeUp, contentDescription = null, tint = visuals.primary)
                Text("Currently Selected Voices", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
            }
            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(CelTerminalBg)
                    .clickable { editingLiveProfile = false }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Normal Chat Voice (Speaker)", style = MaterialTheme.typography.labelSmall, color = CelLavender)
                    Text(chatVoiceSummary, style = MaterialTheme.typography.labelLarge, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text(
                    text = "${"%.2f".format(prefs.ttsPitch)}x · ${"%.2f".format(prefs.ttsSpeechRate)}x",
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = CelTextSecondary,
                )
            }
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(CelTerminalBg)
                    .clickable { editingLiveProfile = true }
                    .padding(horizontal = 10.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Live, Floating & Assistant Voice", style = MaterialTheme.typography.labelSmall, color = CelEmeraldThought)
                    Text(liveVoiceSummary, style = MaterialTheme.typography.labelLarge, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text(
                    text = "${"%.2f".format(prefs.liveTtsPitch)}x · ${"%.2f".format(prefs.liveTtsSpeechRate)}x",
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = CelTextSecondary,
                )
            }
        }

        // 1. Split Text-to-Speech Voice Lab (Normal Chat vs Live & Floating + Synth Engine!) (#1, #4t)
        GlassCard(shape = RoundedCornerShape(22.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.RecordVoiceOver, contentDescription = null, tint = visuals.secondary)
                    Column {
                        Text("Text-to-Speech Voice Lab", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                        val subtitle = when (selectedEngine) {
                            CelliumTtsEngine.ENGINE_SYNTH -> "Synth Voices (Offline Instant) · Typewriter bubble mode"
                            CelliumTtsEngine.ENGINE_EDGE -> "Edge Neural v2 · ${CelliumTtsEngine.EDGE_VOICES.size} HD studio voices"
                            CelliumTtsEngine.ENGINE_POLLY -> "Polly Studio (Free) · ${CelliumTtsEngine.POLLY_VOICES.size} warm voices"
                            CelliumTtsEngine.ENGINE_TIKTOK -> "TikTok Voices (Free) · ${CelliumTtsEngine.TIKTOK_VOICES.size} expressive voices"
                            CelliumTtsEngine.ENGINE_GOOGLE -> "Google TTS · ${CelliumTtsEngine.GOOGLE_VOICES.size} crisp accents"
                            else -> "System Offline TTS · ${groupedSystemVoices.size} languages (${systemVoices.size})"
                        }
                        Text(subtitle, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    }
                }
                OutlinedButton(
                    onClick = {
                        viewModel.speakPreviewWithVoice(
                            engine = selectedEngine,
                            voiceId = selectedVoiceId,
                            pitch = pitchDraft,
                            rate = rateDraft,
                            text = nextUniquePreviewLine(),
                        )
                    },
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Icon(Icons.Rounded.VolumeUp, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Test", maxLines = 1, softWrap = false)
                }
            }

            Spacer(Modifier.height(10.dp))

            // Profile Switcher Tabs: Normal Chat vs Live & Floating (#4t)
            Text("Editing Voice Profile For", style = MaterialTheme.typography.labelSmall, color = CelLavender)
            Spacer(Modifier.height(4.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                FilterChip(
                    selected = !editingLiveProfile,
                    onClick = { editingLiveProfile = false },
                    label = { Text("Normal Chat", maxLines = 1, softWrap = false) },
                    modifier = Modifier.weight(1f),
                )
                FilterChip(
                    selected = editingLiveProfile,
                    onClick = { editingLiveProfile = true },
                    label = { Text("Live & Floating", maxLines = 1, softWrap = false) },
                    modifier = Modifier.weight(1f),
                )
            }

            Spacer(Modifier.height(8.dp))

            // TTS Engine Chips (including Synth Default!)
            Text("TTS Engine", style = MaterialTheme.typography.labelSmall, color = CelLavender)
            Spacer(Modifier.height(4.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_SYNTH,
                    onClick = {
                        val defaultVoice = if (selectedVoiceId.startsWith("synth:")) selectedVoiceId else CelliumTtsEngine.SYNTH_VOICES.first().id
                        persistProfileVoice(CelliumTtsEngine.ENGINE_SYNTH, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("Synth (Default)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_EDGE,
                    onClick = {
                        val defaultVoice = if (selectedVoiceId.endsWith("Neural", true)) selectedVoiceId else CelliumTtsEngine.EDGE_VOICES.first().id
                        persistProfileVoice(CelliumTtsEngine.ENGINE_EDGE, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("Edge Neural", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_POLLY,
                    onClick = {
                        val defaultVoice = if (selectedVoiceId.startsWith("polly:")) selectedVoiceId else CelliumTtsEngine.POLLY_VOICES.first().id
                        persistProfileVoice(CelliumTtsEngine.ENGINE_POLLY, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("Polly Studio", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_TIKTOK,
                    onClick = {
                        val defaultVoice = if (selectedVoiceId.startsWith("tiktok:")) selectedVoiceId else CelliumTtsEngine.TIKTOK_VOICES.first().id
                        persistProfileVoice(CelliumTtsEngine.ENGINE_TIKTOK, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("TikTok", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_GOOGLE,
                    onClick = {
                        val defaultVoice = if (selectedVoiceId.startsWith("google:")) selectedVoiceId else CelliumTtsEngine.GOOGLE_VOICES.first().id
                        persistProfileVoice(CelliumTtsEngine.ENGINE_GOOGLE, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("Google TTS", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_SYSTEM,
                    onClick = {
                        val defaultVoice = if (
                            selectedVoiceId.startsWith("synth:") ||
                            selectedVoiceId.startsWith("google:") ||
                            selectedVoiceId.startsWith("polly:") ||
                            selectedVoiceId.startsWith("tiktok:") ||
                            selectedVoiceId.endsWith("Neural", true)
                        ) "" else selectedVoiceId
                        persistProfileVoice(CelliumTtsEngine.ENGINE_SYSTEM, defaultVoice, pitchDraft, rateDraft)
                    },
                    label = { Text("System Offline", maxLines = 1, softWrap = false) },
                )
            }

            Spacer(Modifier.height(8.dp))

            OutlinedTextField(
                value = voiceSearch,
                onValueChange = { voiceSearch = it },
                placeholder = {
                    Text(
                        when (selectedEngine) {
                            CelliumTtsEngine.ENGINE_SYNTH -> "Search Synth voices (Groove Synth, Cozy Chatter, Crystal Bell...)"
                            CelliumTtsEngine.ENGINE_EDGE -> "Search Edge Neural voices (Emma, Ava, Aria, Sonia...)"
                            CelliumTtsEngine.ENGINE_POLLY -> "Search Polly voices (Joanna, Amy, Brian, Matthew...)"
                            CelliumTtsEngine.ENGINE_TIKTOK -> "Search TikTok voices (Jessie, Sakura, Ghostface...)"
                            CelliumTtsEngine.ENGINE_GOOGLE -> "Search Google TTS accents..."
                            else -> "Search system voices or language..."
                        }
                    )
                },
                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
            )
            Spacer(Modifier.height(6.dp))

            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                when (selectedEngine) {
                    CelliumTtsEngine.ENGINE_SYNTH -> {
                        items(filteredSynthVoices, key = { it.id }) { v ->
                            val sel = selectedVoiceId == v.id || (selectedVoiceId.isBlank() && v.id == "synth:groove_synth")
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_SYNTH,
                                            voiceId = v.id,
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_SYNTH, v.id, pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text("${v.label} · ${v.accent}", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(v.gender, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                                }
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    CelliumTtsEngine.ENGINE_EDGE -> {
                        items(filteredEdgeVoices, key = { it.id }) { v ->
                            val sel = selectedVoiceId == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_EDGE,
                                            voiceId = v.id,
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_EDGE, v.id, pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text("${v.label} · ${v.accent}", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(v.gender, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                                }
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    CelliumTtsEngine.ENGINE_POLLY -> {
                        items(filteredPollyVoices, key = { it.id }) { v ->
                            val sel = selectedVoiceId == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_POLLY,
                                            voiceId = v.id,
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_POLLY, v.id, pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text("${v.label} · ${v.accent}", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(v.gender, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                                }
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    CelliumTtsEngine.ENGINE_TIKTOK -> {
                        items(filteredTikTokVoices, key = { it.id }) { v ->
                            val sel = selectedVoiceId == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_TIKTOK,
                                            voiceId = v.id,
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_TIKTOK, v.id, pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text("${v.label} · ${v.accent}", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(v.gender, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                                }
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    CelliumTtsEngine.ENGINE_GOOGLE -> {
                        items(filteredGoogleVoices, key = { it.id }) { v ->
                            val sel = selectedVoiceId == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_GOOGLE,
                                            voiceId = v.id,
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_GOOGLE, v.id, pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(v.label, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text("${v.accent} · ${v.gender}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                                }
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            }
                        }
                    }

                    else -> {
                        item(key = "sys_default_voice") {
                            val sel = selectedVoiceId.isBlank()
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        viewModel.speakPreviewWithVoice(
                                            engine = CelliumTtsEngine.ENGINE_SYSTEM,
                                            voiceId = "",
                                            pitch = pitchDraft,
                                            rate = rateDraft,
                                            text = nextUniquePreviewLine(),
                                        )
                                        persistProfileVoice(CelliumTtsEngine.ENGINE_SYSTEM, "", pitchDraft, rateDraft)
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text("System Default Voice", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary)
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(15.dp))
                            }
                        }

                        groupedSystemVoices.forEach { (groupName, itemsInGroup) ->
                            val isSearching = voiceSearch.isNotBlank()
                            val isExpanded = isSearching || groupName in expandedGroups
                            item(key = "hdr_$groupName") {
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(visuals.primary.copy(alpha = 0.12f))
                                        .clickable {
                                            expandedGroups = if (groupName in expandedGroups) expandedGroups - groupName else expandedGroups + groupName
                                        }
                                        .padding(horizontal = 10.dp, vertical = 7.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                ) {
                                    Text(
                                        text = "$groupName (${itemsInGroup.size})",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = CelLavender,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f),
                                    )
                                    Icon(
                                        imageVector = if (isExpanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                                        contentDescription = null,
                                        tint = CelLavender,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            }
                            if (isExpanded) {
                                items(itemsInGroup, key = { it.rawName }) { item ->
                                    val sel = selectedVoiceId == item.rawName
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(start = 10.dp)
                                            .clip(RoundedCornerShape(10.dp))
                                            .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                            .clickable {
                                                viewModel.speakPreviewWithVoice(
                                                    engine = CelliumTtsEngine.ENGINE_SYSTEM,
                                                    voiceId = item.rawName,
                                                    pitch = pitchDraft,
                                                    rate = rateDraft,
                                                    text = nextUniquePreviewLine(),
                                                )
                                                persistProfileVoice(CelliumTtsEngine.ENGINE_SYSTEM, item.rawName, pitchDraft, rateDraft)
                                            }
                                            .padding(horizontal = 10.dp, vertical = 7.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                    ) {
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(item.shortLabel, style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                            Text(item.rawName, style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono), color = CelTextMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                        }
                                        if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(15.dp))
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(8.dp))

            // Widened Pitch & Rate Sliders (#1)
            Text(
                text = "Voice Pitch: ${String.format(Locale.US, "%.2f", pitchDraft)}x (Deep 0.25x <-> High 2.50x)",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = pitchDraft,
                onValueChange = { pitchDraft = it },
                onValueChangeFinished = {
                    persistProfileVoice(selectedEngine, selectedVoiceId, pitchDraft, rateDraft)
                },
                valueRange = 0.25f..2.50f,
            )

            Text(
                text = "Speech Rate: ${String.format(Locale.US, "%.2f", rateDraft)}x",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = rateDraft,
                onValueChange = { rateDraft = it },
                onValueChangeFinished = {
                    persistProfileVoice(selectedEngine, selectedVoiceId, pitchDraft, rateDraft)
                },
                valueRange = 0.50f..2.20f,
            )
        }

        // 2. Cel Start-up Sound Studio (22 Gentle Presets + Shuffle + Custom Audio + Delete Presets to Save Storage) (#4g)
        GlassCard(shape = RoundedCornerShape(22.dp)) {
            val visiblePresets = remember(prefs.deletedStartupSoundIds) {
                CelliumSoundEngine.STARTUP_SOUND_PRESETS.filter { it.id !in prefs.deletedStartupSoundIds }
            }
            val activeStartupLabel = if (prefs.startupSoundId == "custom" && prefs.startupSoundCustomPath.isNotBlank()) {
                "Custom Audio File"
            } else {
                CelliumSoundEngine.findStartupPreset(prefs.startupSoundId).label
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.MusicNote, contentDescription = null, tint = visuals.primary)
                    Column {
                        Text("Cel Start-up Sound Studio", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                        Text(
                            text = "Active: $activeStartupLabel · ${visiblePresets.size}/22 presets · ${"%.1f".format(startupCacheBytes / 1024f)} KB cache",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                }
            }

            Spacer(Modifier.height(10.dp))

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                OutlinedButton(
                    onClick = {
                        val pool = visiblePresets.filter { it.id != prefs.startupSoundId }.ifEmpty { visiblePresets }
                        val picked = pool.randomOrNull() ?: return@OutlinedButton
                        viewModel.soundEngine.startupSoundId = picked.id
                        viewModel.soundEngine.playAssistantSummon(picked.id)
                        scope.launch {
                            viewModel.prefsStore.updateStartupSound(picked.id)
                            viewModel.notifyPrefsChangedForSync()
                            startupCacheBytes = viewModel.soundEngine.getStartupCacheBytes()
                            viewModel.showSettingsFeedback("Shuffled start-up sound: ${picked.label}")
                        }
                    },
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.Shuffle, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Shuffle", maxLines = 1, softWrap = false)
                }
                OutlinedButton(
                    onClick = { customStartupAudioPicker.launch(arrayOf("audio/*")) },
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.AudioFile, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Upload Audio", maxLines = 1, softWrap = false)
                }
            }

            if (prefs.deletedStartupSoundIds.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                TextButton(
                    onClick = {
                        scope.launch {
                            viewModel.prefsStore.updateDeletedStartupSounds(emptySet())
                            viewModel.showSettingsFeedback("Restored all 22 start-up sound presets.")
                        }
                    },
                ) {
                    Icon(Icons.Rounded.Restore, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Restore All 22 Presets (${prefs.deletedStartupSoundIds.size} deleted)")
                }
            }

            Spacer(Modifier.height(6.dp))

            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 210.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                if (prefs.startupSoundCustomPath.isNotBlank() && File(prefs.startupSoundCustomPath).exists()) {
                    item(key = "startup_custom") {
                        val sel = prefs.startupSoundId == "custom"
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                .clickable {
                                    viewModel.soundEngine.startupSoundId = "custom"
                                    viewModel.soundEngine.startupSoundCustomPath = prefs.startupSoundCustomPath
                                    viewModel.soundEngine.playAssistantSummon("custom", prefs.startupSoundCustomPath)
                                    scope.launch { viewModel.prefsStore.updateStartupSound("custom", prefs.startupSoundCustomPath) }
                                }
                                .padding(horizontal = 10.dp, vertical = 7.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("Custom Uploaded Audio", style = MaterialTheme.typography.labelMedium, color = CelEmeraldThought)
                                Text("Saved locally in app storage", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                            }
                            if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            IconButton(
                                onClick = {
                                    runCatching { File(prefs.startupSoundCustomPath).delete() }
                                    val fallback = visiblePresets.firstOrNull()?.id ?: "soft_celesta"
                                    scope.launch {
                                        viewModel.prefsStore.updateStartupSound(fallback, customPath = "")
                                        viewModel.showSettingsFeedback("Deleted custom start-up audio.")
                                    }
                                },
                                modifier = Modifier.size(30.dp),
                            ) {
                                Icon(Icons.Rounded.Delete, contentDescription = "Delete custom audio", tint = CelDangerRed, modifier = Modifier.size(16.dp))
                            }
                        }
                    }
                }

                items(visiblePresets, key = { it.id }) { preset ->
                    val sel = prefs.startupSoundId == preset.id
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(10.dp))
                            .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                            .clickable {
                                viewModel.soundEngine.startupSoundId = preset.id
                                viewModel.soundEngine.playAssistantSummon(preset.id)
                                scope.launch {
                                    viewModel.prefsStore.updateStartupSound(preset.id)
                                    viewModel.notifyPrefsChangedForSync()
                                    startupCacheBytes = viewModel.soundEngine.getStartupCacheBytes()
                                }
                            }
                            .padding(horizontal = 10.dp, vertical = 7.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(preset.label, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(preset.vibe, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1)
                        }
                        if (sel) {
                            Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(4.dp))
                        }
                        if (visiblePresets.size > 1) {
                            IconButton(
                                onClick = {
                                    val freed = viewModel.soundEngine.deleteStartupPresetCache(preset.id)
                                    val nextDeleted = prefs.deletedStartupSoundIds + preset.id
                                    scope.launch {
                                        viewModel.prefsStore.updateDeletedStartupSounds(nextDeleted)
                                        if (prefs.startupSoundId == preset.id) {
                                            val nextFallback = visiblePresets.firstOrNull { it.id != preset.id }?.id ?: "soft_celesta"
                                            viewModel.prefsStore.updateStartupSound(nextFallback)
                                        }
                                        startupCacheBytes = viewModel.soundEngine.getStartupCacheBytes()
                                        val freedKb = "%.1f".format(freed / 1024f)
                                        viewModel.showSettingsFeedback("Deleted '${preset.label}' (freed $freedKb KB).")
                                    }
                                },
                                modifier = Modifier.size(30.dp),
                            ) {
                                Icon(Icons.Rounded.Delete, contentDescription = "Delete preset", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                            }
                        }
                    }
                }
            }
        }

        // 3. Speech-to-Text (STT) Engine Selector
        GlassCard(shape = RoundedCornerShape(22.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Hearing, contentDescription = null, tint = CelEmeraldThought)
                Column {
                    Text("Speech-to-Text (STT) Engine", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("Upgrade voice recognition accuracy in Live, Chat & Floating Cel", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                }
            }
            Spacer(Modifier.height(10.dp))

            val activeStt = CelliumSttEngine.ALL_ENGINES.firstOrNull { it.id == prefs.sttEngine }
                ?: CelliumSttEngine.ALL_ENGINES.first()

            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                CelliumSttEngine.ALL_ENGINES.forEach { opt ->
                    FilterChip(
                        selected = prefs.sttEngine == opt.id,
                        onClick = {
                            scope.launch {
                                viewModel.prefsStore.updateSttSettings(
                                    engine = opt.id,
                                    apiKey = sttKeyDraft,
                                    model = "",
                                )
                                viewModel.notifyPrefsChangedForSync()
                                viewModel.showSettingsFeedback("STT engine set to ${opt.label}.")
                            }
                            sttModelDraft = ""
                        },
                        label = { Text(opt.label, maxLines = 1, softWrap = false) },
                    )
                }
            }

            Spacer(Modifier.height(6.dp))
            Text(activeStt.subtitle, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)

            if (activeStt.requiresKey) {
                val resolvedKey = sttKeyDraft.trim().ifBlank { viewModel.resolveSttApiKey(activeStt.id) }
                val keyReady = resolvedKey.isNotBlank()
                var discoveredSttModels by remember(activeStt.id) { mutableStateOf<List<String>>(emptyList()) }
                var isPingingStt by remember(activeStt.id) { mutableStateOf(false) }
                var sttPingError by remember(activeStt.id) { mutableStateOf<String?>(null) }
                var sttDropdownExpanded by remember(activeStt.id) { mutableStateOf(false) }

                val knownPresets = remember(activeStt.id) {
                    CelliumSttEngine.KNOWN_MODELS_BY_ENGINE[activeStt.id].orEmpty()
                }
                val dropdownModels = remember(discoveredSttModels, knownPresets) {
                    if (discoveredSttModels.isNotEmpty()) {
                        (discoveredSttModels + knownPresets).distinct()
                    } else {
                        knownPresets
                    }
                }

                fun runPingDiscovery(showToast: Boolean) {
                    if (resolvedKey.isBlank()) {
                        if (showToast) {
                            viewModel.showSettingsFeedback("Add an API key first to ping ${activeStt.label}.", isError = true)
                        }
                        return
                    }
                    scope.launch {
                        isPingingStt = true
                        sttPingError = null
                        val res = viewModel.discoverSttModels(
                            engineId = activeStt.id,
                            explicitKeyOverride = sttKeyDraft,
                            forceRefresh = true,
                        )
                        isPingingStt = false
                        res.onSuccess { liveList ->
                            discoveredSttModels = liveList
                            if (liveList.isNotEmpty()) {
                                val currentValid = sttModelDraft.isNotBlank() &&
                                    liveList.any { it.equals(sttModelDraft.trim(), ignoreCase = true) }
                                if (!currentValid) {
                                    val autoPicked = liveList.first()
                                    sttModelDraft = autoPicked
                                    viewModel.prefsStore.updateSttSettings(
                                        engine = activeStt.id,
                                        apiKey = sttKeyDraft,
                                        model = autoPicked,
                                    )
                                    viewModel.notifyPrefsChangedForSync()
                                    if (showToast) {
                                        viewModel.showSettingsFeedback("Found ${liveList.size} voice model(s) on your key · Selected $autoPicked.")
                                    }
                                } else if (showToast) {
                                    viewModel.showSettingsFeedback("Key verified · ${liveList.size} voice model(s) available.")
                                }
                            } else {
                                sttPingError = "Key works, but no Whisper/STT models were listed. Pick from presets or enter a custom model."
                                if (showToast) {
                                    viewModel.showSettingsFeedback(sttPingError!!, isError = true)
                                }
                            }
                        }.onFailure { err ->
                            sttPingError = err.localizedMessage ?: "Failed to ping key."
                            if (showToast) {
                                viewModel.showSettingsFeedback("Key ping failed: $sttPingError", isError = true)
                            }
                        }
                    }
                }

                LaunchedEffect(activeStt.id, resolvedKey) {
                    if (resolvedKey.isNotBlank() && discoveredSttModels.isEmpty()) {
                        runPingDiscovery(showToast = false)
                    }
                }

                Spacer(Modifier.height(8.dp))
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = (if (keyReady) CelEmeraldThought else CelAmber).copy(alpha = 0.14f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        text = if (keyReady && prefs.sttApiKey.isBlank()) {
                            "API Key Ready — auto-using your saved provider key!"
                        } else if (keyReady) {
                            "Custom STT API Key saved & ready."
                        } else {
                            "No key found yet — paste a key below or add it in AI Providers."
                        },
                        style = MaterialTheme.typography.labelSmall,
                        color = if (keyReady) CelEmeraldThought else CelAmber,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                    )
                }
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = sttKeyDraft,
                    onValueChange = { sttKeyDraft = it },
                    label = { Text("Optional STT API Key (blank = auto-use provider key)") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                )
                Spacer(Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(modifier = Modifier.weight(1f)) {
                        val activeLabel = sttModelDraft.ifBlank {
                            discoveredSttModels.firstOrNull() ?: activeStt.defaultModel
                        }
                        Surface(
                            shape = RoundedCornerShape(12.dp),
                            color = CelTerminalBg,
                            modifier = Modifier
                                .fillMaxWidth()
                                .border(1.dp, visuals.activeBorder, RoundedCornerShape(12.dp))
                                .clip(RoundedCornerShape(12.dp))
                                .clickable { sttDropdownExpanded = true },
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 12.dp, vertical = 11.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = if (discoveredSttModels.isNotEmpty()) {
                                            "Voice Model (${discoveredSttModels.size} live from key)"
                                        } else {
                                            "Voice Model (Dropdown)"
                                        },
                                        style = MaterialTheme.typography.labelSmall,
                                        color = CelLavender,
                                    )
                                    Text(
                                        text = activeLabel,
                                        style = MaterialTheme.typography.labelMedium.copy(fontFamily = JetBrainsMono),
                                        color = CelTextPrimary,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                Icon(
                                    imageVector = if (sttDropdownExpanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                                    contentDescription = "Choose STT model",
                                    tint = CelLavender,
                                )
                            }
                        }

                        DropdownMenu(
                            expanded = sttDropdownExpanded,
                            onDismissRequest = { sttDropdownExpanded = false },
                        ) {
                            dropdownModels.forEach { modelId ->
                                val isLive = discoveredSttModels.any { it.equals(modelId, ignoreCase = true) }
                                val isSelected = activeLabel.equals(modelId, ignoreCase = true)
                                DropdownMenuItem(
                                    text = {
                                        Column {
                                            Text(
                                                text = modelId,
                                                style = MaterialTheme.typography.labelMedium.copy(fontFamily = JetBrainsMono),
                                                color = if (isSelected) visuals.primary else CelTextPrimary,
                                            )
                                            Text(
                                                text = if (isLive) "Verified live on your API key" else "Known preset",
                                                style = MaterialTheme.typography.labelSmall,
                                                color = if (isLive) CelEmeraldThought else CelTextMuted,
                                            )
                                        }
                                    },
                                    trailingIcon = if (isSelected) {
                                        { Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(16.dp)) }
                                    } else null,
                                    onClick = {
                                        sttDropdownExpanded = false
                                        sttModelDraft = modelId
                                        scope.launch {
                                            viewModel.prefsStore.updateSttSettings(
                                                engine = activeStt.id,
                                                apiKey = sttKeyDraft,
                                                model = modelId,
                                            )
                                            viewModel.notifyPrefsChangedForSync()
                                            viewModel.showSettingsFeedback("STT model set to $modelId.")
                                        }
                                    },
                                )
                            }
                        }
                    }

                    OutlinedButton(
                        onClick = { runPingDiscovery(showToast = true) },
                        enabled = !isPingingStt,
                        shape = RoundedCornerShape(12.dp),
                    ) {
                        if (isPingingStt) {
                            CircularProgressIndicator(modifier = Modifier.size(15.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(15.dp))
                        }
                        Spacer(Modifier.width(4.dp))
                        Text("Ping", maxLines = 1, softWrap = false)
                    }
                }

                if (!sttPingError.isNullOrBlank()) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = sttPingError!!,
                        style = MaterialTheme.typography.labelSmall,
                        color = CelAmber,
                    )
                }

                Spacer(Modifier.height(6.dp))
                OutlinedTextField(
                    value = sttModelDraft,
                    onValueChange = { sttModelDraft = it },
                    label = { Text("Custom Model ID (optional override)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                )
                Spacer(Modifier.height(6.dp))
                OutlinedButton(
                    onClick = {
                        scope.launch {
                            viewModel.prefsStore.updateSttSettings(
                                engine = activeStt.id,
                                apiKey = sttKeyDraft,
                                model = sttModelDraft,
                            )
                            viewModel.notifyPrefsChangedForSync()
                            viewModel.showSettingsFeedback("STT settings saved (${activeStt.label}).")
                        }
                    },
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Text("Save STT Key & Model", maxLines = 1, softWrap = false)
                }
            }
        }

        // 4. Cel Typing Speed, Mood Engine & Sound Effects
        GlassCard(shape = RoundedCornerShape(22.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Speed, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("Cel Typing Speed, Mood & SFX", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("Pace Cel's reply reveal so Groove Synth / Cozy Chatter chirps shine", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                }
            }
            Spacer(Modifier.height(10.dp))

            Text("Cel Typing Speed", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                TYPING_SPEED_OPTIONS.forEach { (id, label) ->
                    FilterChip(
                        selected = prefs.typingSpeed == id,
                        onClick = {
                            viewModel.soundEngine.playClick()
                            scope.launch {
                                viewModel.prefsStore.updateTypingSpeed(id)
                                viewModel.notifyPrefsChangedForSync()
                            }
                        },
                        label = { Text(label, maxLines = 1, softWrap = false) },
                    )
                }
            }

            HorizontalDivider(color = visuals.subtleBorder, modifier = Modifier.padding(vertical = 8.dp))

            Text("Streaming Typing Sound Style", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = prefs.typingSoundStyle == "scratchin_melodii",
                    onClick = {
                        viewModel.soundEngine.typingSoundStyle = "scratchin_melodii"
                        viewModel.soundEngine.typingSoundPitch = chirpPitchDraft
                        viewModel.soundEngine.playAnimalesePurr()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                sounds = prefs.soundsEnabled,
                                animalese = prefs.animaleseEnabled,
                                haptics = prefs.hapticsEnabled,
                                volume = sfxVolDraft,
                                typingStyle = "scratchin_melodii",
                                typingPitch = chirpPitchDraft,
                                typingCadence = prefs.typingSoundCadence,
                            )
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Groove Synth (Default)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = prefs.typingSoundStyle != "scratchin_melodii",
                    onClick = {
                        viewModel.soundEngine.typingSoundStyle = "animal_crossing"
                        viewModel.soundEngine.typingSoundPitch = chirpPitchDraft
                        viewModel.soundEngine.playAnimalesePurr()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                sounds = prefs.soundsEnabled,
                                animalese = prefs.animaleseEnabled,
                                haptics = prefs.hapticsEnabled,
                                volume = sfxVolDraft,
                                typingStyle = "animal_crossing",
                                typingPitch = chirpPitchDraft,
                                typingCadence = prefs.typingSoundCadence,
                            )
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Cozy Chatter", maxLines = 1, softWrap = false) },
                )
            }

            Spacer(Modifier.height(8.dp))
            Text(
                text = "Typing Voice Pitch: ${String.format(Locale.US, "%.2f", chirpPitchDraft)}x (0.25x Deep <-> 2.50x Bright)",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = chirpPitchDraft,
                onValueChange = {
                    chirpPitchDraft = it
                    viewModel.soundEngine.typingSoundPitch = it
                },
                onValueChangeFinished = {
                    viewModel.soundEngine.typingSoundPitch = chirpPitchDraft
                    viewModel.soundEngine.playAnimalesePurr()
                    scope.launch {
                        viewModel.prefsStore.updateAudioSettings(
                            sounds = prefs.soundsEnabled,
                            animalese = prefs.animaleseEnabled,
                            haptics = prefs.hapticsEnabled,
                            volume = sfxVolDraft,
                            typingStyle = prefs.typingSoundStyle,
                            typingPitch = chirpPitchDraft,
                            typingCadence = prefs.typingSoundCadence,
                        )
                        viewModel.notifyPrefsChangedForSync()
                    }
                },
                valueRange = 0.25f..2.50f,
            )

            Text("Typing Voice Cadence", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Spacer(Modifier.height(4.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = prefs.typingSoundCadence != "letter",
                    onClick = {
                        viewModel.soundEngine.playClick()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                sounds = prefs.soundsEnabled,
                                animalese = prefs.animaleseEnabled,
                                haptics = prefs.hapticsEnabled,
                                volume = sfxVolDraft,
                                typingStyle = prefs.typingSoundStyle,
                                typingPitch = chirpPitchDraft,
                                typingCadence = "word",
                            )
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Word by Word", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = prefs.typingSoundCadence == "letter",
                    onClick = {
                        viewModel.soundEngine.playClick()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                sounds = prefs.soundsEnabled,
                                animalese = prefs.animaleseEnabled,
                                haptics = prefs.hapticsEnabled,
                                volume = sfxVolDraft,
                                typingStyle = prefs.typingSoundStyle,
                                typingPitch = chirpPitchDraft,
                                typingCadence = "letter",
                            )
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Letter by Letter", maxLines = 1, softWrap = false) },
                )
            }

            HorizontalDivider(color = visuals.subtleBorder, modifier = Modifier.padding(vertical = 8.dp))

            Text("Live Avatar Mood Engine", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Text("Controls how Cel updates her facial expression during Chat & Live calls", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = prefs.moodMethod != "background_ai",
                    onClick = {
                        scope.launch {
                            viewModel.prefsStore.updateMoodMethod("inline_tag")
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Method 1: Inline Tag (Fast)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = prefs.moodMethod == "background_ai",
                    onClick = {
                        scope.launch {
                            viewModel.prefsStore.updateMoodMethod("background_ai")
                            viewModel.notifyPrefsChangedForSync()
                        }
                    },
                    label = { Text("Method 2: Background AI", maxLines = 1, softWrap = false) },
                )
            }

            Spacer(Modifier.height(6.dp))
            SettingSwitchRow("Auto-Read Chat Replies Aloud", prefs.autoReadReplies) {
                scope.launch {
                    viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, it, prefs.liveHandsFreeLoop, prefs.ttsEngine)
                    viewModel.notifyPrefsChangedForSync()
                }
            }
            SettingSwitchRow("Live Mode Hands-Free Auto Loop", prefs.liveHandsFreeLoop) {
                scope.launch {
                    viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, it, prefs.ttsEngine)
                    viewModel.notifyPrefsChangedForSync()
                }
            }
            SettingSwitchRow("UI Sound Effects (Media Channel)", prefs.soundsEnabled) {
                scope.launch {
                    viewModel.prefsStore.updateAudioSettings(it, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft, prefs.typingSoundStyle, chirpPitchDraft, prefs.typingSoundCadence)
                    viewModel.notifyPrefsChangedForSync()
                }
            }
            SettingSwitchRow("Streaming Voice Chirps", prefs.animaleseEnabled) {
                scope.launch {
                    viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, it, prefs.hapticsEnabled, sfxVolDraft, prefs.typingSoundStyle, chirpPitchDraft, prefs.typingSoundCadence)
                    viewModel.notifyPrefsChangedForSync()
                }
            }
            SettingSwitchRow("Tactile Haptic Feedback", prefs.hapticsEnabled) {
                scope.launch {
                    viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, it, sfxVolDraft, prefs.typingSoundStyle, chirpPitchDraft, prefs.typingSoundCadence)
                    viewModel.notifyPrefsChangedForSync()
                }
                if (it) viewModel.soundEngine.hapticDoubleClick()
            }
            SettingSwitchRow("Bundled Background Chat Notifications", prefs.notificationsEnabled) {
                scope.launch {
                    viewModel.prefsStore.updateNotificationsEnabled(it)
                    viewModel.notifyPrefsChangedForSync()
                }
            }

            Spacer(Modifier.height(6.dp))
            OutlinedButton(
                onClick = { viewModel.soundEngine.playPop() },
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.fillMaxWidth().testTag("test_sfx_haptic_button"),
            ) {
                Icon(Icons.Rounded.VolumeUp, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Test Audible SFX & Haptic Pulse", maxLines = 1, softWrap = false)
            }

            Spacer(Modifier.height(6.dp))
            Text("SFX Volume: ${(sfxVolDraft * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = sfxVolDraft,
                onValueChange = { sfxVolDraft = it },
                onValueChangeFinished = {
                    scope.launch {
                        viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft, prefs.typingSoundStyle, chirpPitchDraft, prefs.typingSoundCadence)
                        viewModel.notifyPrefsChangedForSync()
                    }
                },
                valueRange = 0f..1f,
            )
        }

        // 5. Default Android Assistant & "Okay Cel" Wake Word Engine (#5)
        GlassCard(highlighted = prefs.wakeWordEnabled, shape = RoundedCornerShape(22.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Assistant, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("Default Android Assistant & Wake Word", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("Summon Cel from Power/Home hold or say \"Okay Cel\"", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                }
            }
            Spacer(Modifier.height(10.dp))

            OutlinedButton(
                onClick = {
                    val intent = Intent(Settings.ACTION_VOICE_INPUT_SETTINGS)
                    runCatching { context.startActivity(intent) }.onFailure {
                        runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)) }
                    }
                },
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Rounded.Assistant, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Set Cel.Cellium as Default Assistant (Zero Mic Dot)", maxLines = 1, softWrap = false)
            }

            Spacer(Modifier.height(10.dp))
            HorizontalDivider(color = visuals.subtleBorder)
            Spacer(Modifier.height(8.dp))

            SettingSwitchRow("Enable \"Okay Cel\" Wake Word Detection", prefs.wakeWordEnabled) { enabled ->
                if (enabled) {
                    val micOk = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
                    if (!micOk) {
                        wakeMicLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    } else {
                        scope.launch { viewModel.prefsStore.updateWakeWordSettings(enabled = true) }
                        WakeWordService.start(context)
                        viewModel.showSettingsFeedback("Okay Cel wake word listening started.")
                    }
                } else {
                    scope.launch { viewModel.prefsStore.updateWakeWordSettings(enabled = false) }
                    WakeWordService.stop(context)
                    viewModel.showSettingsFeedback("Okay Cel wake word stopped.")
                }
            }

            SettingSwitchRow("Smart Screen-On Only (Releases Mic When Locked)", prefs.wakeWordScreenOnOnly) { screenOnly ->
                scope.launch {
                    viewModel.prefsStore.updateWakeWordSettings(
                        enabled = prefs.wakeWordEnabled,
                        screenOnOnly = screenOnly,
                    )
                }
            }

            if (wakeRunning || prefs.wakeWordEnabled) {
                Spacer(Modifier.height(6.dp))
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = CelTerminalBg,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text(
                                text = if (wakeMicActive) "Live Test — Say \"Okay Cel\"" else "Wake Engine Standby (Mic Released)",
                                style = MaterialTheme.typography.labelSmall,
                                color = if (wakeMicActive) CelEmeraldThought else CelTextSecondary,
                            )
                            Text(
                                text = "${(liveWakeScore * 100).toInt()}% / ${(wakeSensDraft * 100).toInt()}%",
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = if (liveWakeScore >= wakeSensDraft) CelEmeraldThought else CelLavender,
                            )
                        }
                        Spacer(Modifier.height(5.dp))
                        LinearProgressIndicator(
                            progress = { liveWakeScore.coerceIn(0f, 1f) },
                            color = if (liveWakeScore >= wakeSensDraft) CelEmeraldThought else visuals.primary,
                            trackColor = visuals.subtleBorder,
                            modifier = Modifier.fillMaxWidth().height(7.dp).clip(RoundedCornerShape(99.dp)),
                        )
                    }
                }
            }

            Spacer(Modifier.height(6.dp))
            Text(
                text = "Trigger Threshold: ${(wakeSensDraft * 100).toInt()}% (Lower = Easier to Trigger)",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = wakeSensDraft,
                onValueChange = { wakeSensDraft = it },
                onValueChangeFinished = {
                    scope.launch { viewModel.prefsStore.updateWakeWordSettings(prefs.wakeWordEnabled, sensitivity = wakeSensDraft) }
                },
                valueRange = 0.05f..0.90f,
            )

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(
                    onClick = { customTflitePicker.launch(arrayOf("*/*")) },
                    shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Rounded.FolderOpen, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(5.dp))
                    Text("Custom .tflite Model", maxLines = 1, softWrap = false)
                }
                if (prefs.wakeWordCustomPath.isNotBlank()) {
                    TextButton(
                        onClick = {
                            scope.launch { viewModel.prefsStore.updateWakeWordSettings(prefs.wakeWordEnabled, customPath = "") }
                            viewModel.showSettingsFeedback("Reset to built-in oh_kay_sell.tflite.")
                        },
                    ) {
                        Text("Built-In", maxLines = 1, softWrap = false)
                    }
                }
            }

            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Rounded.GraphicEq, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(15.dp).padding(top = 2.dp))
                Text(
                    text = "Active model: ${if (prefs.wakeWordCustomPath.isBlank()) "Built-in oh_kay_sell.tflite" else File(prefs.wakeWordCustomPath).name} (exact 1760-sample openWakeWord LiteRT). Note on the green mic dot: Android 12-16 locks hardware zero-dot DSP hotwording (AlwaysOnHotwordDetector / CAPTURE_AUDIO_HOTWORD) strictly to OEM-signed system apps like Google Assistant. Smart Screen-On Only turns the mic & green dot completely OFF whenever your screen locks or a voice session pauses. For zero green dot 24/7, set Cel as your Default Assistant above and hold Power/Home!",
                    style = MaterialTheme.typography.labelSmall,
                    color = CelTextMuted,
                )
            }
        }
    }
}

@Composable
fun SettingSwitchRow(
    label: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { onCheckedChange(!checked) },
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = CelTextPrimary, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

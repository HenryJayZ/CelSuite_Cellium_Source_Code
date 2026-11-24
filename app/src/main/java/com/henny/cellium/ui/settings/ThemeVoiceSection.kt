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
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Hearing
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material.icons.rounded.Wallpaper
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
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
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.assistant.WakeWordService
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.theme.CelAmber
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

    // Local drag states so sliders stay silky smooth at 60fps without thrashing DataStore
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

    val selectedEngine = prefs.ttsEngine.ifBlank { CelliumTtsEngine.ENGINE_EDGE }

    // System voices are ONLY loaded lazily when the user opens the "System" engine tab!
    var systemVoices by remember { mutableStateOf<List<SystemVoiceItem>>(emptyList()) }
    var expandedGroups by remember { mutableStateOf<Set<String>>(emptySet()) }
    var voiceSearch by remember { mutableStateOf("") }

    // Smooth slider drafts
    var pitchDraft by remember(prefs.ttsPitch) { mutableFloatStateOf(prefs.ttsPitch) }
    var rateDraft by remember(prefs.ttsSpeechRate) { mutableFloatStateOf(prefs.ttsSpeechRate) }
    var sfxVolDraft by remember(prefs.sfxVolume) { mutableFloatStateOf(prefs.sfxVolume) }
    var wakeSensDraft by remember(prefs.wakeWordSensitivity) { mutableFloatStateOf(prefs.wakeWordSensitivity) }

    // STT override drafts
    var sttKeyDraft by remember(prefs.sttApiKey) { mutableStateOf(prefs.sttApiKey) }
    var sttModelDraft by remember(prefs.sttModel) { mutableStateOf(prefs.sttModel) }

    val wakeMicLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) {
            scope.launch { viewModel.prefsStore.updateWakeWordSettings(enabled = true) }
            WakeWordService.start(context)
            viewModel.showBanner("Okay Cel wake word listening active.")
        } else {
            viewModel.showBanner("Microphone permission required for Okay Cel wake word.")
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
                    viewModel.showBanner("Custom wake word .tflite imported.")
                } else {
                    viewModel.showBanner("Failed to import custom .tflite file.")
                }
            }
        }
    }

    // Lazily query system Android TTS voices ONLY if System tab is active
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
                // Auto-expand English (United States) only if no search query
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

    val filteredEdgeVoices = remember(voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) CelliumTtsEngine.EDGE_VOICES
        else CelliumTtsEngine.EDGE_VOICES.filter {
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

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // 1. TTS Voice Lab (Sectioned: Edge Neural / Google TTS / System Voices)
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
                            CelliumTtsEngine.ENGINE_EDGE -> "Edge Neural TTS · ${CelliumTtsEngine.EDGE_VOICES.size} studio voices"
                            CelliumTtsEngine.ENGINE_GOOGLE -> "Google TTS · ${CelliumTtsEngine.GOOGLE_VOICES.size} crisp voices"
                            else -> "System Offline TTS · ${groupedSystemVoices.size} languages (${systemVoices.size})"
                        }
                        Text(subtitle, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    }
                }
                OutlinedButton(
                    onClick = {
                        viewModel.speakText("Hey bestie! Cel dot Cellium voice lab is crystal clear.")
                    },
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Icon(Icons.Rounded.VolumeUp, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Test", maxLines = 1, softWrap = false)
                }
            }

            Spacer(Modifier.height(10.dp))

            // TTS Engine Tabs
            Text("TTS Engine", style = MaterialTheme.typography.labelSmall, color = CelLavender)
            Spacer(Modifier.height(4.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_EDGE,
                    onClick = {
                        val defaultVoice = if (prefs.ttsVoiceName.endsWith("Neural", true)) prefs.ttsVoiceName else CelliumTtsEngine.EDGE_VOICES.first().id
                        scope.launch {
                            viewModel.prefsStore.updateVoiceSettings(
                                voice = defaultVoice,
                                pitch = pitchDraft,
                                rate = rateDraft,
                                autoRead = prefs.autoReadReplies,
                                handsFree = prefs.liveHandsFreeLoop,
                                ttsEngine = CelliumTtsEngine.ENGINE_EDGE,
                            )
                        }
                    },
                    label = { Text("Edge Neural (Free)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_GOOGLE,
                    onClick = {
                        val defaultVoice = if (prefs.ttsVoiceName.startsWith("google:")) prefs.ttsVoiceName else CelliumTtsEngine.GOOGLE_VOICES.first().id
                        scope.launch {
                            viewModel.prefsStore.updateVoiceSettings(
                                voice = defaultVoice,
                                pitch = pitchDraft,
                                rate = rateDraft,
                                autoRead = prefs.autoReadReplies,
                                handsFree = prefs.liveHandsFreeLoop,
                                ttsEngine = CelliumTtsEngine.ENGINE_GOOGLE,
                            )
                        }
                    },
                    label = { Text("Google TTS (Free)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = selectedEngine == CelliumTtsEngine.ENGINE_SYSTEM,
                    onClick = {
                        val defaultVoice = if (prefs.ttsVoiceName.startsWith("google:") || prefs.ttsVoiceName.endsWith("Neural", true)) "" else prefs.ttsVoiceName
                        scope.launch {
                            viewModel.prefsStore.updateVoiceSettings(
                                voice = defaultVoice,
                                pitch = pitchDraft,
                                rate = rateDraft,
                                autoRead = prefs.autoReadReplies,
                                handsFree = prefs.liveHandsFreeLoop,
                                ttsEngine = CelliumTtsEngine.ENGINE_SYSTEM,
                            )
                        }
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
                            CelliumTtsEngine.ENGINE_EDGE -> "Search Edge Neural voices (Aria, Ana, Sonia...)"
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

            // Voice List by Section
            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                when (selectedEngine) {
                    CelliumTtsEngine.ENGINE_EDGE -> {
                        items(filteredEdgeVoices, key = { it.id }) { v ->
                            val sel = prefs.ttsVoiceName == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        scope.launch {
                                            viewModel.prefsStore.updateVoiceSettings(
                                                v.id, pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, CelliumTtsEngine.ENGINE_EDGE
                                            )
                                        }
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
                            val sel = prefs.ttsVoiceName == v.id
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        scope.launch {
                                            viewModel.prefsStore.updateVoiceSettings(
                                                v.id, pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, CelliumTtsEngine.ENGINE_GOOGLE
                                            )
                                        }
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
                            val sel = prefs.ttsVoiceName.isBlank()
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                    .clickable {
                                        scope.launch {
                                            viewModel.prefsStore.updateVoiceSettings(
                                                "", pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, CelliumTtsEngine.ENGINE_SYSTEM
                                            )
                                        }
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text("System Default Voice", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary)
                                if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(15.dp))
                            }
                        }

                        // Grouped collapsible language sections so 250+ device voices stay super organized!
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
                                    val sel = prefs.ttsVoiceName == item.rawName
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(start = 10.dp)
                                            .clip(RoundedCornerShape(10.dp))
                                            .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                            .clickable {
                                                scope.launch {
                                                    viewModel.prefsStore.updateVoiceSettings(
                                                        item.rawName, pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, CelliumTtsEngine.ENGINE_SYSTEM
                                                    )
                                                }
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

            Text("Voice Pitch: ${"%.2f".format(pitchDraft)}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = pitchDraft,
                onValueChange = { pitchDraft = it },
                onValueChangeFinished = {
                    scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, selectedEngine) }
                },
                valueRange = 0.65f..1.55f,
            )

            Text("Speech Rate: ${"%.2f".format(rateDraft)}x", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = rateDraft,
                onValueChange = { rateDraft = it },
                onValueChangeFinished = {
                    scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, pitchDraft, rateDraft, prefs.autoReadReplies, prefs.liveHandsFreeLoop, selectedEngine) }
                },
                valueRange = 0.65f..1.65f,
            )
        }

        // 2. Speech-to-Text (STT) Engine Selector (Groq Whisper BYOK, Pollinations Free, OpenAI, HuggingFace, Android System)
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
                val resolvedKey = viewModel.resolveSttApiKey(activeStt.id)
                val keyReady = resolvedKey.isNotBlank()
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
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(
                    value = sttModelDraft,
                    onValueChange = { sttModelDraft = it },
                    label = { Text("Model Override (default: ${activeStt.defaultModel})") },
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
                            viewModel.showBanner("STT settings saved (${activeStt.label}).")
                        }
                    },
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Text("Save STT Key & Model", maxLines = 1, softWrap = false)
                }
            }
        }

        // 3. Cel Typing Speed, Mood Engine & Sound Effects
        GlassCard(shape = RoundedCornerShape(22.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Speed, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("Cel Typing Speed, Mood & SFX", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("Pace Cel's reply reveal so Animal Crossing / Melodii chirps shine", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
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
                            scope.launch { viewModel.prefsStore.updateTypingSpeed(id) }
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
                    selected = prefs.typingSoundStyle != "scratchin_melodii",
                    onClick = {
                        viewModel.soundEngine.typingSoundStyle = "animal_crossing"
                        viewModel.soundEngine.playAnimalesePurr()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft, "animal_crossing"
                            )
                        }
                    },
                    label = { Text("Animal Crossing", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = prefs.typingSoundStyle == "scratchin_melodii",
                    onClick = {
                        viewModel.soundEngine.typingSoundStyle = "scratchin_melodii"
                        viewModel.soundEngine.playAnimalesePurr()
                        scope.launch {
                            viewModel.prefsStore.updateAudioSettings(
                                prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft, "scratchin_melodii"
                            )
                        }
                    },
                    label = { Text("Scratchin' Melodii", maxLines = 1, softWrap = false) },
                )
            }

            HorizontalDivider(color = visuals.subtleBorder, modifier = Modifier.padding(vertical = 8.dp))

            Text("Live Avatar Mood Engine", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Text("Controls how Cel updates her facial expression during Chat & Live calls", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Spacer(Modifier.height(6.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = prefs.moodMethod != "background_ai",
                    onClick = { scope.launch { viewModel.prefsStore.updateMoodMethod("inline_tag") } },
                    label = { Text("Method 1: Inline Tag (Fast)", maxLines = 1, softWrap = false) },
                )
                FilterChip(
                    selected = prefs.moodMethod == "background_ai",
                    onClick = { scope.launch { viewModel.prefsStore.updateMoodMethod("background_ai") } },
                    label = { Text("Method 2: Background AI", maxLines = 1, softWrap = false) },
                )
            }

            Spacer(Modifier.height(6.dp))
            SettingSwitchRow("Auto-Read Chat Replies Aloud", prefs.autoReadReplies) {
                scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, pitchDraft, rateDraft, it, prefs.liveHandsFreeLoop, selectedEngine) }
            }
            SettingSwitchRow("Live Mode Hands-Free Loop", prefs.liveHandsFreeLoop) {
                scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, pitchDraft, rateDraft, prefs.autoReadReplies, it, selectedEngine) }
            }
            SettingSwitchRow("UI Sound Effects (Media Channel)", prefs.soundsEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(it, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft) }
            }
            SettingSwitchRow("Streaming Voice Chirps", prefs.animaleseEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, it, prefs.hapticsEnabled, sfxVolDraft) }
            }
            SettingSwitchRow("Tactile Haptic Feedback", prefs.hapticsEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, it, sfxVolDraft) }
                if (it) viewModel.soundEngine.hapticDoubleClick()
            }
            SettingSwitchRow("Bundled Background Chat Notifications", prefs.notificationsEnabled) {
                scope.launch { viewModel.prefsStore.updateNotificationsEnabled(it) }
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
                    scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, sfxVolDraft) }
                },
                valueRange = 0f..1f,
            )
        }

        // 4. Default Android Assistant & "Okay Cel" Wake Word Engine
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
                Text("Set Cel.Cellium as Default Assistant", maxLines = 1, softWrap = false)
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
                        viewModel.showBanner("Okay Cel wake word listening started.")
                    }
                } else {
                    scope.launch { viewModel.prefsStore.updateWakeWordSettings(enabled = false) }
                    WakeWordService.stop(context)
                    viewModel.showBanner("Okay Cel wake word stopped.")
                }
            }

            Text(
                text = "Wake Word Sensitivity: ${(wakeSensDraft * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = wakeSensDraft,
                onValueChange = { wakeSensDraft = it },
                onValueChangeFinished = {
                    scope.launch { viewModel.prefsStore.updateWakeWordSettings(prefs.wakeWordEnabled, sensitivity = wakeSensDraft) }
                },
                valueRange = 0.25f..0.90f,
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
                            viewModel.showBanner("Reset to built-in oh_kay_sell.tflite")
                        },
                    ) {
                        Text("Built-In", maxLines = 1, softWrap = false)
                    }
                }
            }

            Spacer(Modifier.height(6.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Rounded.GraphicEq, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(15.dp))
                Text(
                    text = "Active model: ${if (prefs.wakeWordCustomPath.isBlank()) "Built-in oh_kay_sell.tflite" else File(prefs.wakeWordCustomPath).name}. Runs via low-CPU RMS-gated foreground LiteRT (Android reserves zero-battery DSP chips for OEM-signed system apps).",
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

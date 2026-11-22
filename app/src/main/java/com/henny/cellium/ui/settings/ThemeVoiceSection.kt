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
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material.icons.rounded.Wallpaper
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.assistant.WakeWordService
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
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
        Text("Wallpaper Dim: ${(prefs.wallpaperDim * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = prefs.wallpaperDim,
            onValueChange = { v ->
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(v, prefs.glassOpacity, prefs.borderGlow, prefs.particleDensity, prefs.fontScale)
                }
            },
            valueRange = 0.15f..0.88f,
        )

        Text("Glass Opacity: ${(prefs.glassOpacity * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = prefs.glassOpacity,
            onValueChange = { v ->
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(prefs.wallpaperDim, v, prefs.borderGlow, prefs.particleDensity, prefs.fontScale)
                }
            },
            valueRange = 0.35f..0.96f,
        )

        Text("Border Glow: ${(prefs.borderGlow * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = prefs.borderGlow,
            onValueChange = { v ->
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(prefs.wallpaperDim, prefs.glassOpacity, v, prefs.particleDensity, prefs.fontScale)
                }
            },
            valueRange = 0.15f..1.0f,
        )

        Text("Ambient Particles: ${prefs.particleDensity}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
        Slider(
            value = prefs.particleDensity.toFloat(),
            onValueChange = { v ->
                scope.launch {
                    viewModel.prefsStore.updateGlassVisuals(prefs.wallpaperDim, prefs.glassOpacity, prefs.borderGlow, v.toInt(), prefs.fontScale)
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

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun VoiceAndAudioLabCard(
    prefs: CelliumPreferences,
    viewModel: CelliumViewModel,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var tts by remember { mutableStateOf<TextToSpeech?>(null) }
    var voiceEntries by remember { mutableStateOf<List<Pair<String, String>>>(emptyList()) }
    var voiceSearch by remember { mutableStateOf("") }

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

    DisposableEffect(context) {
        var engine: TextToSpeech? = null
        engine = TextToSpeech(context) { st ->
            if (st == TextToSpeech.SUCCESS) {
                engine?.language = Locale.US
                val all = engine?.voices
                    ?.filter { !it.isNetworkConnectionRequired }
                    ?.sortedWith(
                        compareByDescending<android.speech.tts.Voice> { it.locale.language == "en" }
                            .thenBy { it.locale.displayName }
                            .thenBy { it.name }
                    )
                    ?.map { v ->
                        val shortCode = v.name.substringAfterLast('#').substringAfterLast('-').take(16)
                        val label = "${v.locale.displayLanguage} (${v.locale.country.ifBlank { v.locale.language }}) · $shortCode"
                        v.name to label
                    }
                    .orEmpty()
                voiceEntries = all
            }
        }
        tts = engine
        onDispose {
            engine?.stop()
            engine?.shutdown()
        }
    }

    val filteredVoices = remember(voiceEntries, voiceSearch) {
        val q = voiceSearch.trim().lowercase()
        if (q.isEmpty()) voiceEntries else voiceEntries.filter {
            it.first.lowercase().contains(q) || it.second.lowercase().contains(q)
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        // 1. TTS Voice Lab, Mood Engine & Typing Sound Style
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
                        Text("Voice Lab, Mood & SFX", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                        Text("${voiceEntries.size} local device TTS voices available", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    }
                }
                OutlinedButton(
                    onClick = {
                        tts?.let { engine ->
                            engine.setPitch(prefs.ttsPitch)
                            engine.setSpeechRate(prefs.ttsSpeechRate)
                            if (prefs.ttsVoiceName.isNotBlank()) {
                                engine.voices?.firstOrNull { it.name == prefs.ttsVoiceName }?.let { engine.voice = it }
                            }
                            engine.speak("Hey bestie! Cel dot Cellium voice lab is crystal clear.", TextToSpeech.QUEUE_FLUSH, null, "preview")
                        }
                    },
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Icon(Icons.Rounded.VolumeUp, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Test", maxLines = 1, softWrap = false)
                }
            }

            Spacer(Modifier.height(10.dp))

            if (voiceEntries.isNotEmpty()) {
                Text("Device Local TTS Voices (${filteredVoices.size})", style = MaterialTheme.typography.labelSmall, color = CelLavender)
                Spacer(Modifier.height(4.dp))
                if (voiceEntries.size > 6) {
                    OutlinedTextField(
                        value = voiceSearch,
                        onValueChange = { voiceSearch = it },
                        placeholder = { Text("Search all ${voiceEntries.size} device voices...") },
                        leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                    Spacer(Modifier.height(6.dp))
                }
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().heightIn(max = 180.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    item(key = "sys_default_voice") {
                        val sel = prefs.ttsVoiceName.isBlank()
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                .clickable {
                                    scope.launch {
                                        viewModel.prefsStore.updateVoiceSettings("", prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, prefs.liveHandsFreeLoop)
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
                    items(filteredVoices, key = { it.first }) { (rawName, displayLabel) ->
                        val sel = prefs.ttsVoiceName == rawName
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(10.dp))
                                .background(if (sel) visuals.primary.copy(alpha = 0.22f) else CelTerminalBg)
                                .clickable {
                                    scope.launch {
                                        viewModel.prefsStore.updateVoiceSettings(rawName, prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, prefs.liveHandsFreeLoop)
                                    }
                                }
                                .padding(horizontal = 10.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(displayLabel, style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(rawName, style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono), color = CelTextMuted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                            if (sel) Icon(Icons.Rounded.Check, contentDescription = null, tint = visuals.primary, modifier = Modifier.size(15.dp))
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }

            Text("Voice Pitch: ${"%.2f".format(prefs.ttsPitch)}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = prefs.ttsPitch,
                onValueChange = { p ->
                    scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, p, prefs.ttsSpeechRate, prefs.autoReadReplies, prefs.liveHandsFreeLoop) }
                },
                valueRange = 0.65f..1.55f,
            )

            Text("Speech Rate: ${"%.2f".format(prefs.ttsSpeechRate)}x", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = prefs.ttsSpeechRate,
                onValueChange = { r ->
                    scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, r, prefs.autoReadReplies, prefs.liveHandsFreeLoop) }
                },
                valueRange = 0.65f..1.65f,
            )

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
                                prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, prefs.sfxVolume, "animal_crossing"
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
                                prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, prefs.sfxVolume, "scratchin_melodii"
                            )
                        }
                    },
                    label = { Text("Scratchin' Melodii", maxLines = 1, softWrap = false) },
                )
            }

            Spacer(Modifier.height(6.dp))
            SettingSwitchRow("Auto-Read Chat Replies Aloud", prefs.autoReadReplies) {
                scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, it, prefs.liveHandsFreeLoop) }
            }
            SettingSwitchRow("Live Mode Hands-Free Loop", prefs.liveHandsFreeLoop) {
                scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, it) }
            }
            SettingSwitchRow("UI Sound Effects (Media Channel)", prefs.soundsEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(it, prefs.animaleseEnabled, prefs.hapticsEnabled, prefs.sfxVolume) }
            }
            SettingSwitchRow("Streaming Voice Chirps", prefs.animaleseEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, it, prefs.hapticsEnabled, prefs.sfxVolume) }
            }
            SettingSwitchRow("Tactile Haptic Feedback", prefs.hapticsEnabled) {
                scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, it, prefs.sfxVolume) }
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
            Text("SFX Volume: ${(prefs.sfxVolume * 100).toInt()}%", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Slider(
                value = prefs.sfxVolume,
                onValueChange = { vol ->
                    scope.launch { viewModel.prefsStore.updateAudioSettings(prefs.soundsEnabled, prefs.animaleseEnabled, prefs.hapticsEnabled, vol) }
                },
                valueRange = 0f..1f,
            )
        }

        // 2. Default Android Assistant & "Okay Cel" Wake Word Engine
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
                text = "Wake Word Sensitivity: ${(prefs.wakeWordSensitivity * 100).toInt()}%",
                style = MaterialTheme.typography.labelSmall,
                color = CelTextSecondary,
            )
            Slider(
                value = prefs.wakeWordSensitivity,
                onValueChange = { v ->
                    scope.launch { viewModel.prefsStore.updateWakeWordSettings(prefs.wakeWordEnabled, sensitivity = v) }
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

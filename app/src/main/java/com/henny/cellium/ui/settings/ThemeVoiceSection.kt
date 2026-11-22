package com.henny.cellium.ui.settings

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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material.icons.rounded.Wallpaper
import androidx.compose.material3.FilterChip
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
import androidx.compose.ui.unit.dp
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.CelliumThemePresets
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch
import java.util.Locale

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ThemeWallpaperStudioCard(
    prefs: CelliumPreferences,
    viewModel: CelliumViewModel,
) {
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
                    label = { Text(preset.name) },
                )
            }
            FilterChip(
                selected = prefs.themePresetId == "custom",
                onClick = { scope.launch { viewModel.prefsStore.updateThemePreset("custom") } },
                label = { Text("Custom Hex") },
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
                Text("Custom Wallpaper")
            }
            if (prefs.customWallpaperUri.isNotBlank()) {
                TextButton(onClick = { scope.launch { viewModel.prefsStore.updateCustomWallpaperUri("") } }) {
                    Text("Reset")
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
            valueRange = 0f..55f,
        )

        SettingSwitchRow("60 FPS High-Smoothness Mode", prefs.highFpsMode) {
            scope.launch { viewModel.prefsStore.updateHighFpsMode(it) }
        }
        SettingSwitchRow("Floating Mini-Cel Companion", prefs.floatingMiniCel) {
            scope.launch { viewModel.prefsStore.updateFloatingMiniCel(it) }
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
    var voiceNames by remember { mutableStateOf<List<String>>(emptyList()) }

    DisposableEffect(context) {
        var engine: TextToSpeech? = null
        engine = TextToSpeech(context) { st ->
            if (st == TextToSpeech.SUCCESS) {
                engine?.language = Locale.US
                val all = engine?.voices
                    ?.filter { !it.isNetworkConnectionRequired && it.locale.language == "en" }
                    ?.map { it.name }
                    ?.sorted()
                    ?.take(12)
                    .orEmpty()
                voiceNames = all
            }
        }
        tts = engine
        onDispose {
            engine?.stop()
            engine?.shutdown()
        }
    }

    GlassCard(shape = RoundedCornerShape(22.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.RecordVoiceOver, contentDescription = null, tint = visuals.secondary)
                Column {
                    Text("Voice Lab & Animalese SFX", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("TTS Voice, Pitch, Rate, Auto-Read & SFX", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
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
                Text("Test")
            }
        }

        Spacer(Modifier.height(8.dp))

        if (voiceNames.isNotEmpty()) {
            Text("Device TTS Voice", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
            Spacer(Modifier.height(4.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(
                    selected = prefs.ttsVoiceName.isBlank(),
                    onClick = {
                        scope.launch {
                            viewModel.prefsStore.updateVoiceSettings("", prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, prefs.liveHandsFreeLoop)
                        }
                    },
                    label = { Text("System Default") },
                )
                voiceNames.take(8).forEach { vn ->
                    FilterChip(
                        selected = prefs.ttsVoiceName == vn,
                        onClick = {
                            scope.launch {
                                viewModel.prefsStore.updateVoiceSettings(vn, prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, prefs.liveHandsFreeLoop)
                            }
                        },
                        label = { Text(vn.substringAfterLast('-').take(14)) },
                    )
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

        SettingSwitchRow("Auto-Read Chat Replies Aloud", prefs.autoReadReplies) {
            scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, it, prefs.liveHandsFreeLoop) }
        }
        SettingSwitchRow("Live Mode Hands-Free Loop", prefs.liveHandsFreeLoop) {
            scope.launch { viewModel.prefsStore.updateVoiceSettings(prefs.ttsVoiceName, prefs.ttsPitch, prefs.ttsSpeechRate, prefs.autoReadReplies, it) }
        }
        SettingSwitchRow("UI Sound Effects (Media Channel)", prefs.soundsEnabled) {
            scope.launch { viewModel.prefsStore.updateAudioSettings(it, prefs.animaleseEnabled, prefs.hapticsEnabled, prefs.sfxVolume) }
        }
        SettingSwitchRow("Animalese Streaming Chirps & Purrs", prefs.animaleseEnabled) {
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
            Text("Test Audible SFX Chime & Haptic Pulse")
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
        Text(label, style = MaterialTheme.typography.bodySmall, color = CelTextPrimary)
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

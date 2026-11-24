package com.henny.cellium.ui.settings

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.rounded.Logout
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Backup
import androidx.compose.material.icons.rounded.BarChart
import androidx.compose.material.icons.rounded.BatteryChargingFull
import androidx.compose.material.icons.rounded.CloudSync
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Face
import androidx.compose.material.icons.rounded.FileDownload
import androidx.compose.material.icons.rounded.FileUpload
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.NotificationsActive
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.Psychology
import androidx.compose.material.icons.rounded.RecordVoiceOver
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Restore
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.SettingsApplications
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.BuildConfig
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.UserProfile
import com.henny.cellium.data.local.CustomPersonaEntity
import com.henny.cellium.data.local.PromptTemplateEntity
import com.henny.cellium.data.sync.CloudSyncManager
import com.henny.cellium.shizuku.ShizukuStatus
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.CelliumIcons
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch
import java.util.Locale

private enum class SettingsCategory(
    val title: String,
    val keywords: String,
    val icon: ImageVector,
    val accentHex: Long,
) {
    PROVIDERS("AI Providers & Keys", "providers keys models openrouter gemini pollinations starred hidden retry", Icons.Rounded.Key, 0xFFA855F7),
    OFFLINE("Offline AI & RAM", "offline local gguf task mediapipe llama ram memory free mount", Icons.Rounded.Memory, 0xFF38BDF8),
    APPEARANCE("Appearance & Glass", "theme wallpaper glass opacity glow particles fps word wrap floating cel", Icons.Rounded.Palette, 0xFFF472B6),
    VOICE("Voice, Live & Assistant", "voice tts pitch rate mood engine animalese typing sound wake word okay cel assistant", Icons.Rounded.RecordVoiceOver, 0xFF34D399),
    PERSONAS("Personas & Memories", "persona edit delete restore memories prompt", Icons.Rounded.Psychology, 0xFFC084FC),
    CONTEXT("Context & Engine Modify", "context modify system prompt history gguf temperature top-p mmap flash attention", Icons.Rounded.Tune, 0xFFFBBF24),
    AGENT("Agent & Shizuku", "agent shizuku shell workspace folder directory anti-kill ram guard", Icons.Rounded.Shield, 0xFF10B981),
    CLOUD("Cloud Sync & Storage", "cloud sync google firestore quota storage delete backup account", Icons.Rounded.CloudSync, 0xFF60A5FA),
    SYSTEM("System, Commands & Backup", "battery optimization permissions notifications slash compact template json export import", Icons.Rounded.SettingsApplications, 0xFFFB7185),
}

@SuppressLint("BatteryLife")
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun SettingsScreen(
    viewModel: CelliumViewModel,
    user: UserProfile?,
    googleAuthBusy: Boolean,
    onSignInWithGoogle: () -> Unit,
    onSignOutGoogle: () -> Unit,
    onOpenAvatarStudio: () -> Unit,
    onOpenStats: () -> Unit,
    onJumpToChat: () -> Unit = {},
) {
    val context = LocalContext.current
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val processRamMb by viewModel.processRamMb.collectAsStateWithLifecycle()

    var activeCategory by remember { mutableStateOf<SettingsCategory?>(null) }
    var hubSearch by remember { mutableStateOf("") }

    // Persona / Memory / Template dialogs
    var editingPersona by remember { mutableStateOf<CustomPersonaEntity?>(null) }
    var showPersonaDialog by remember { mutableStateOf(false) }
    var showAddMemory by remember { mutableStateOf(false) }
    var editingTemplate by remember { mutableStateOf<PromptTemplateEntity?>(null) }
    var showTemplateDialog by remember { mutableStateOf(false) }
    var backupIncludeKeys by remember { mutableStateOf(false) }

    BackHandler(enabled = activeCategory != null) {
        activeCategory = null
    }

    LaunchedEffect(activeCategory, user) {
        if (activeCategory == SettingsCategory.CLOUD && user != null) {
            viewModel.refreshCloudStorage()
        }
    }

    val notifPermLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.showBanner(if (granted) "Notifications enabled." else "Notification permission denied.")
    }
    val micPermLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        viewModel.showBanner(if (granted) "Microphone ready for Live Voice." else "Microphone permission denied.")
    }
    val exportBackupLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json")
    ) { uri: Uri? ->
        if (uri != null) viewModel.exportFullBackupToUri(uri, includeApiKeys = backupIncludeKeys)
    }
    val importBackupLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        if (uri != null) viewModel.importFullBackupFromUri(uri)
    }

    val notifGranted = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
    } else true
    val micGranted = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    val batteryUnrestricted = remember(context, activeCategory) {
        val pm = context.getSystemService(PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations(context.packageName) == true
    }

    if (activeCategory == null) {
        // ── CLEAN CATEGORY HUB ──
        val visibleCategories = remember(hubSearch) {
            val q = hubSearch.trim().lowercase()
            if (q.isEmpty()) SettingsCategory.entries
            else SettingsCategory.entries.filter {
                it.title.lowercase().contains(q) || it.keywords.contains(q)
            }
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text("Cel.Cellium Settings", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
                Text(
                    "${BuildConfig.VERSION_NAME} · Local-First Room SQLite · CelSuite.HenryJayz.Cellium",
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = CelTextSecondary,
                )
            }

            item {
                OutlinedTextField(
                    value = hubSearch,
                    onValueChange = { hubSearch = it },
                    placeholder = { Text("Search settings (wake word, GGUF, keys, cloud...)") },
                    leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, tint = CelLavender) },
                    singleLine = true,
                    shape = RoundedCornerShape(16.dp),
                    modifier = Modifier.fillMaxWidth().testTag("settings_hub_search"),
                )
            }

            // Quick Studios Row
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    StudioQuickTile(
                        icon = Icons.Rounded.Face,
                        title = "Avatar Studio",
                        subtitle = "3,800+ dot-matrix",
                        accent = visuals.primary,
                        onClick = {
                            viewModel.soundEngine.playPop()
                            onOpenAvatarStudio()
                        },
                        modifier = Modifier.weight(1f).testTag("settings_open_avatar_studio"),
                    )
                    StudioQuickTile(
                        icon = Icons.Rounded.BarChart,
                        title = "Stats & Logs",
                        subtitle = "${uiState.totalMessageCount} msgs · Console",
                        accent = Color(0xFF38BDF8),
                        onClick = {
                            viewModel.soundEngine.playPop()
                            onOpenStats()
                        },
                        modifier = Modifier.weight(1f).testTag("settings_open_stats"),
                    )
                }
            }

            // Category Rows
            visibleCategories.forEach { cat ->
                item(key = cat.name) {
                    val subtitle = when (cat) {
                        SettingsCategory.PROVIDERS -> "${uiState.activeProvider?.name ?: "None"} · Retry ${prefs.maxAutoRetries}x"
                        SettingsCategory.OFFLINE -> "${uiState.registeredLocalModels.size} models · Live RAM $processRamMb MB"
                        SettingsCategory.APPEARANCE -> "Theme: ${prefs.themePresetId} · Wrap ${if (prefs.codeWordWrap) "ON" else "OFF"}"
                        SettingsCategory.VOICE -> "TTS: ${prefs.ttsEngine.uppercase()} · STT: ${prefs.sttEngine.substringBefore('_').uppercase()} · Speed: ${prefs.typingSpeed}"
                        SettingsCategory.PERSONAS -> "${uiState.customPersonas.size} personas · ${uiState.memories.size} memories"
                        SettingsCategory.CONTEXT -> "History ${prefs.contextModify.historyLimit} turns · n_ctx ${prefs.contextModify.ggufContextLength}"
                        SettingsCategory.AGENT -> "Shizuku: ${uiState.shizukuStatus.name} · Agent ${if (prefs.agentModeEnabled) "ON" else "OFF"}"
                        SettingsCategory.CLOUD -> if (user != null) "Signed in: ${user.email ?: user.displayName}" else "Guest Mode · Optional Google Sync"
                        SettingsCategory.SYSTEM -> "Battery ${if (batteryUnrestricted) "Unrestricted" else "Standard"} · ${uiState.promptTemplates.size} slash cmds"
                    }
                    SettingsCategoryRow(
                        icon = cat.icon,
                        title = cat.title,
                        subtitle = subtitle,
                        accent = Color(cat.accentHex),
                        onClick = {
                            viewModel.soundEngine.playClick()
                            activeCategory = cat
                        },
                    )
                }
            }
        }
    } else {
        // ── FOCUSED SUB-SCREEN ──
        val cat = activeCategory!!
        Column(modifier = Modifier.fillMaxSize()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                IconButton(onClick = { activeCategory = null }) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back to Settings", tint = CelTextPrimary)
                }
                Icon(cat.icon, contentDescription = null, tint = Color(cat.accentHex), modifier = Modifier.size(22.dp))
                Text(
                    text = cat.title,
                    style = MaterialTheme.typography.titleLarge,
                    color = CelTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }

            LazyColumn(
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                when (cat) {
                    SettingsCategory.PROVIDERS -> {
                        item { ProvidersHubCard(uiState = uiState, prefs = prefs, viewModel = viewModel) }
                    }

                    SettingsCategory.OFFLINE -> {
                        item {
                            OnDeviceModelManagerCard(
                                uiState = uiState,
                                prefs = prefs,
                                processRamMb = processRamMb,
                                viewModel = viewModel,
                                onJumpToChat = onJumpToChat,
                            )
                        }
                    }

                    SettingsCategory.APPEARANCE -> {
                        item { ThemeWallpaperStudioCard(prefs = prefs, viewModel = viewModel) }
                    }

                    SettingsCategory.VOICE -> {
                        item { VoiceAndAudioLabCard(prefs = prefs, viewModel = viewModel) }
                    }

                    SettingsCategory.PERSONAS -> {
                        // All Personas (Built-ins + Custom, all editable & deletable + Restore Defaults!)
                        item {
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
                                        Icon(Icons.Rounded.AutoAwesome, contentDescription = null, tint = visuals.primary)
                                        Text("All Personas (${uiState.customPersonas.size})", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                    }
                                    Row {
                                        IconButton(onClick = { viewModel.restoreDefaultPersonas() }) {
                                            Icon(Icons.Rounded.Restore, contentDescription = "Restore default personas", tint = CelLavender)
                                        }
                                        IconButton(
                                            onClick = {
                                                editingPersona = null
                                                showPersonaDialog = true
                                            },
                                            modifier = Modifier.testTag("settings_add_persona"),
                                        ) {
                                            Icon(Icons.Rounded.Add, contentDescription = "Add persona", tint = visuals.primary)
                                        }
                                    }
                                }
                                Text(
                                    text = "Edit or remove any persona (including Cel's defaults). Tap Restore anytime to bring defaults back.",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = CelTextSecondary,
                                )
                                Spacer(Modifier.height(8.dp))
                                uiState.customPersonas.forEach { p ->
                                    val accent = runCatching { Color(android.graphics.Color.parseColor(p.accentHex)) }.getOrDefault(visuals.primary)
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(vertical = 4.dp)
                                            .clip(RoundedCornerShape(12.dp))
                                            .background(CelTerminalBg.copy(alpha = 0.72f))
                                            .clickable {
                                                editingPersona = p
                                                showPersonaDialog = true
                                            }
                                            .padding(horizontal = 10.dp, vertical = 8.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                                    ) {
                                        VectorBadgeIcon(iconKey = p.iconKey, contentDescription = p.name, tint = accent, containerSize = 30.dp, iconSize = 16.dp)
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(p.name, style = MaterialTheme.typography.titleSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                            if (p.tagline.isNotBlank()) {
                                                Text(p.tagline, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                            }
                                        }
                                        IconButton(
                                            onClick = {
                                                editingPersona = p
                                                showPersonaDialog = true
                                            },
                                            modifier = Modifier.size(32.dp),
                                        ) {
                                            Icon(Icons.Rounded.Edit, contentDescription = "Edit persona", tint = CelLavender, modifier = Modifier.size(17.dp))
                                        }
                                        IconButton(
                                            onClick = { viewModel.deleteCustomPersona(p.id) },
                                            modifier = Modifier.size(32.dp),
                                        ) {
                                            Icon(Icons.Rounded.Delete, contentDescription = "Delete persona", tint = CelDangerRed, modifier = Modifier.size(17.dp))
                                        }
                                    }
                                }
                            }
                        }

                        // Persistent Memories
                        item {
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Icon(Icons.Rounded.Psychology, contentDescription = null, tint = visuals.tertiary)
                                        Text("Persistent Memories (${uiState.memories.size})", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                    }
                                    IconButton(onClick = { showAddMemory = true }, modifier = Modifier.testTag("settings_add_memory")) {
                                        Icon(Icons.Rounded.Add, contentDescription = "Add memory", tint = visuals.tertiary)
                                    }
                                }
                                if (uiState.memories.isEmpty()) {
                                    Text("Injected into every prompt across all providers.", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                                } else {
                                    uiState.memories.forEach { m ->
                                        Row(
                                            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Checkbox(checked = m.enabled, onCheckedChange = { viewModel.toggleMemory(m) })
                                            Column(modifier = Modifier.weight(1f)) {
                                                Text(m.title, style = MaterialTheme.typography.labelLarge, color = CelTextPrimary)
                                                Text(m.content, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary, maxLines = 2)
                                            }
                                            IconButton(onClick = { viewModel.deleteMemory(m.id) }) {
                                                Icon(Icons.Rounded.Delete, contentDescription = "Delete memory", tint = CelDangerRed, modifier = Modifier.size(18.dp))
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    SettingsCategory.CONTEXT -> {
                        item {
                            val cfg = prefs.contextModify
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text("Context & GGUF Modify", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                        Text("Controls both API & Offline system injections + llama.cpp params", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                    }
                                    OutlinedButton(onClick = { scope.launch { viewModel.prefsStore.updateContextModify(ContextModifyConfig()) } }) {
                                        Text("Reset", maxLines = 1, softWrap = false)
                                    }
                                }
                                Spacer(Modifier.height(8.dp))
                                SettingSwitchRow("Include Active Persona Prompt", cfg.includePersona) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(includePersona = it)) }
                                }
                                SettingSwitchRow("Include Persistent Memories", cfg.includeMemories) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(includeMemories = it)) }
                                }
                                SettingSwitchRow("Include Illume Auto-Art Instructions", cfg.includeIllumeInstructions) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(includeIllumeInstructions = it)) }
                                }
                                SettingSwitchRow("Include Agent / Shizuku Instructions", cfg.includeAgentInstructions) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(includeAgentInstructions = it)) }
                                }
                                SettingSwitchRow("Include Inline Mood Tag Instructions", cfg.includeMoodInstructions) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(includeMoodInstructions = it)) }
                                }

                                var histDraft by remember(cfg.historyLimit) { mutableFloatStateOf(cfg.historyLimit.toFloat()) }
                                var ctxDraft by remember(cfg.ggufContextLength) { mutableFloatStateOf(cfg.ggufContextLength.toFloat()) }
                                var maxTokDraft by remember(cfg.ggufMaxTokens) { mutableFloatStateOf(cfg.ggufMaxTokens.toFloat()) }
                                var tempDraft by remember(cfg.ggufTemperature) { mutableFloatStateOf(cfg.ggufTemperature) }
                                var topPDraft by remember(cfg.ggufTopP) { mutableFloatStateOf(cfg.ggufTopP) }
                                var repDraft by remember(cfg.ggufRepeatPenalty) { mutableFloatStateOf(cfg.ggufRepeatPenalty) }
                                var threadsDraft by remember(cfg.ggufThreads) { mutableFloatStateOf(cfg.ggufThreads.toFloat()) }
                                var gpuLayersDraft by remember(cfg.ggufGpuLayers) { mutableFloatStateOf(cfg.ggufGpuLayers.toFloat()) }

                                Text("History Turns Sent: ${histDraft.toInt()}", style = MaterialTheme.typography.labelSmall, color = CelLavender)
                                Slider(
                                    value = histDraft,
                                    onValueChange = { histDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(historyLimit = histDraft.toInt())) } },
                                    valueRange = 2f..64f,
                                )

                                HorizontalDivider(color = visuals.subtleBorder, modifier = Modifier.padding(vertical = 8.dp))
                                Text("Offline .gguf llama.cpp Knobs (No Caps)", style = MaterialTheme.typography.titleSmall, color = visuals.primary)
                                Spacer(Modifier.height(6.dp))

                                Text("Context Length (n_ctx): ${(ctxDraft.toInt() / 256) * 256}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = ctxDraft,
                                    onValueChange = { ctxDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufContextLength = (ctxDraft.toInt() / 256) * 256)) } },
                                    valueRange = 512f..32768f,
                                )
                                Text("Max Output Tokens: ${(maxTokDraft.toInt() / 64) * 64}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = maxTokDraft,
                                    onValueChange = { maxTokDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufMaxTokens = (maxTokDraft.toInt() / 64) * 64)) } },
                                    valueRange = 128f..16384f,
                                )
                                Text("Temperature: ${String.format(Locale.US, "%.2f", tempDraft)}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = tempDraft,
                                    onValueChange = { tempDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufTemperature = tempDraft)) } },
                                    valueRange = 0f..1.8f,
                                )
                                Text("Top-P: ${String.format(Locale.US, "%.2f", topPDraft)} · Top-K: ${cfg.ggufTopK}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = topPDraft,
                                    onValueChange = { topPDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufTopP = topPDraft)) } },
                                    valueRange = 0.1f..1.0f,
                                )
                                Text("Repeat Penalty: ${String.format(Locale.US, "%.2f", repDraft)}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = repDraft,
                                    onValueChange = { repDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufRepeatPenalty = repDraft)) } },
                                    valueRange = 1.0f..1.45f,
                                )
                                Text("CPU Threads: ${threadsDraft.toInt()}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = threadsDraft,
                                    onValueChange = { threadsDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufThreads = threadsDraft.toInt())) } },
                                    valueRange = 1f..16f,
                                )
                                Text("GPU Offload Layers: ${gpuLayersDraft.toInt()}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                Slider(
                                    value = gpuLayersDraft,
                                    onValueChange = { gpuLayersDraft = it },
                                    onValueChangeFinished = { scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufGpuLayers = gpuLayersDraft.toInt())) } },
                                    valueRange = 0f..99f,
                                )
                                SettingSwitchRow("Memory-Map Weights (mmap · Saves RAM)", cfg.ggufUseMmap) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufUseMmap = it)) }
                                }
                                SettingSwitchRow("Flash Attention (Lower KV-Cache RAM)", cfg.ggufFlashAttention) {
                                    scope.launch { viewModel.prefsStore.updateContextModify(cfg.copy(ggufFlashAttention = it)) }
                                }
                            }
                        }
                    }

                    SettingsCategory.AGENT -> {
                        item {
                            val shizukuColor = when (uiState.shizukuStatus) {
                                ShizukuStatus.CONNECTED_ROOT, ShizukuStatus.CONNECTED_SHELL -> CelEmeraldThought
                                ShizukuStatus.PERMISSION_REQUIRED, ShizukuStatus.BINDING -> CelAmber
                                ShizukuStatus.NOT_RUNNING -> CelDangerRed
                            }
                            val ramProgress = (processRamMb.toFloat() / prefs.ramGuardThresholdMb.coerceAtLeast(256).toFloat()).coerceIn(0f, 1f)
                            var workspaceDraft by remember(prefs.agentWorkspacePath) { mutableStateOf(prefs.agentWorkspacePath) }

                            GlassCard(highlighted = uiState.shizukuAntiKill, shape = RoundedCornerShape(22.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Icon(Icons.Rounded.Shield, contentDescription = null, tint = shizukuColor)
                                    Column {
                                        Text("Shizuku, Agent & RAM Watchdog", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                        Text(
                                            text = "${uiState.shizukuStatus.name} · Live RAM $processRamMb / ${prefs.ramGuardThresholdMb} MB",
                                            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                            color = shizukuColor,
                                        )
                                    }
                                }
                                Spacer(Modifier.height(8.dp))
                                LinearProgressIndicator(
                                    progress = { ramProgress },
                                    color = if (ramProgress > 0.85f) CelDangerRed else visuals.primary,
                                    trackColor = CelTerminalBg,
                                    modifier = Modifier.fillMaxWidth().height(7.dp).clip(RoundedCornerShape(99.dp)),
                                )
                                Spacer(Modifier.height(6.dp))
                                Text(uiState.shizukuReport, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                                Spacer(Modifier.height(10.dp))

                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(
                                        onClick = { viewModel.shizukuBridge.requestPermission() },
                                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                                        shape = RoundedCornerShape(12.dp),
                                        modifier = Modifier.weight(1f).testTag("settings_shizuku_auth_button"),
                                    ) {
                                        Text("Authorize", maxLines = 1, softWrap = false)
                                    }
                                    OutlinedButton(
                                        onClick = { viewModel.testShizukuCommand() },
                                        shape = RoundedCornerShape(12.dp),
                                        modifier = Modifier.weight(1f).testTag("settings_shizuku_test_button"),
                                    ) {
                                        Icon(Icons.Rounded.Terminal, contentDescription = null, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(4.dp))
                                        Text("Test Shell", maxLines = 1, softWrap = false)
                                    }
                                }

                                Spacer(Modifier.height(8.dp))
                                OutlinedButton(
                                    onClick = { viewModel.triggerManualShizukuAntiKill() },
                                    shape = RoundedCornerShape(12.dp),
                                    modifier = Modifier.fillMaxWidth().testTag("settings_shizuku_antikill_button"),
                                ) {
                                    Text("Apply Anti-Kill Protection Now", maxLines = 1, softWrap = false)
                                }

                                Spacer(Modifier.height(10.dp))
                                HorizontalDivider(color = visuals.subtleBorder)
                                Spacer(Modifier.height(10.dp))

                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Icon(Icons.Rounded.Folder, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(18.dp))
                                    Text("Agent Project Workspace Folder", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                                }
                                Spacer(Modifier.height(6.dp))
                                OutlinedTextField(
                                    value = workspaceDraft,
                                    onValueChange = { workspaceDraft = it },
                                    label = { Text("Workspace Directory") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(12.dp),
                                )
                                Spacer(Modifier.height(6.dp))
                                OutlinedButton(
                                    onClick = {
                                        scope.launch {
                                            viewModel.prefsStore.updateAgentWorkspace(workspaceDraft, prompted = true)
                                            viewModel.showBanner("Agent workspace updated.")
                                        }
                                    },
                                    shape = RoundedCornerShape(10.dp),
                                ) {
                                    Text("Save Workspace Path", maxLines = 1, softWrap = false)
                                }

                                Spacer(Modifier.height(10.dp))
                                SettingSwitchRow("Auto-Protect When RAM Crosses Threshold", prefs.shizukuAutoGuard) {
                                    scope.launch { viewModel.prefsStore.updateShizukuSettings(it, prefs.ramGuardThresholdMb, prefs.agentAutoApproveSafe) }
                                }
                                var ramGuardDraft by remember(prefs.ramGuardThresholdMb) { mutableFloatStateOf(prefs.ramGuardThresholdMb.toFloat()) }
                                Text(
                                    "RAM Guard Trigger: ${ramGuardDraft.toInt()} MB (${"%.1f".format(ramGuardDraft / 1024f)} GB)",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = CelTextSecondary,
                                )
                                Slider(
                                    value = ramGuardDraft,
                                    onValueChange = { ramGuardDraft = it },
                                    onValueChangeFinished = {
                                        scope.launch { viewModel.prefsStore.updateShizukuSettings(prefs.shizukuAutoGuard, ramGuardDraft.toInt(), prefs.agentAutoApproveSafe) }
                                    },
                                    valueRange = 512f..16384f,
                                )
                                SettingSwitchRow("Enable AI Agent Mode (Shizuku Shell Calls)", prefs.agentModeEnabled) {
                                    scope.launch { viewModel.prefsStore.updateAgentMode(it) }
                                }
                                SettingSwitchRow("Auto-Run SAFE Read-Only Agent Commands", prefs.agentAutoApproveSafe) {
                                    scope.launch { viewModel.prefsStore.updateShizukuSettings(prefs.shizukuAutoGuard, prefs.ramGuardThresholdMb, it) }
                                }
                            }
                        }
                    }

                    SettingsCategory.CLOUD -> {
                        item {
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Icon(Icons.Rounded.CloudSync, contentDescription = null, tint = visuals.tertiary)
                                    Column {
                                        Text("Optional Google Cloud Sync", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                        Text(
                                            text = if (user != null) "Signed in: ${user.email ?: user.displayName}" else "Guest Mode Active (100% Local Room SQLite)",
                                            style = MaterialTheme.typography.labelSmall,
                                            color = if (user != null) CelEmeraldThought else CelLavender,
                                        )
                                    }
                                }
                                Spacer(Modifier.height(8.dp))
                                Text(
                                    "Privately syncs your API keys, starred models, hidden providers, settings, chats, templates, personas, and memories to your Google account (strictly private to your UID).",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = CelTextSecondary,
                                )
                                Spacer(Modifier.height(10.dp))
                                if (user != null) {
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Button(
                                            onClick = { viewModel.syncWithGoogleCloud() },
                                            enabled = !uiState.isSyncingCloud,
                                            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                                            shape = RoundedCornerShape(12.dp),
                                            modifier = Modifier.weight(1f).testTag("settings_sync_now_button"),
                                        ) {
                                            if (uiState.isSyncingCloud) CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                            else Icon(Icons.Rounded.CloudSync, contentDescription = null, modifier = Modifier.size(16.dp))
                                            Spacer(Modifier.width(6.dp))
                                            Text("Sync Now", maxLines = 1, softWrap = false)
                                        }
                                        OutlinedButton(
                                            onClick = onSignOutGoogle,
                                            shape = RoundedCornerShape(12.dp),
                                        ) {
                                            Icon(Icons.AutoMirrored.Rounded.Logout, contentDescription = null, modifier = Modifier.size(16.dp))
                                            Spacer(Modifier.width(4.dp))
                                            Text("Guest", maxLines = 1, softWrap = false)
                                        }
                                    }
                                } else {
                                    OutlinedButton(
                                        onClick = onSignInWithGoogle,
                                        enabled = !googleAuthBusy,
                                        shape = RoundedCornerShape(12.dp),
                                        modifier = Modifier.fillMaxWidth().testTag("settings_google_signin_button"),
                                    ) {
                                        if (googleAuthBusy) CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                        Spacer(Modifier.width(6.dp))
                                        Text("Sign in with Google for Sync", maxLines = 1, softWrap = false)
                                    }
                                }
                            }
                        }

                        // Cloud Storage Quota & Per-Item Manager (#32)
                        if (user != null) {
                            item {
                                val summary = uiState.cloudStorageSummary
                                val usedBytes = summary?.usedBytes ?: 0L
                                val quotaBytes = summary?.quotaBytes ?: CloudSyncManager.USER_QUOTA_BYTES
                                val pct = (usedBytes.toFloat() / quotaBytes.coerceAtLeast(1L).toFloat()).coerceIn(0f, 1f)

                                GlassCard(shape = RoundedCornerShape(22.dp)) {
                                    Row(
                                        modifier = Modifier.fillMaxWidth(),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                            Icon(Icons.Rounded.Storage, contentDescription = null, tint = Color(0xFF60A5FA))
                                            Column {
                                                Text("Cloud Storage Manager", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                                Text(
                                                    text = "${String.format(Locale.US, "%.1f", usedBytes / 1024.0)} KB / ${String.format(Locale.US, "%.1f", quotaBytes / 1024.0)} KB (0.01% Spark)",
                                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                                    color = if (pct > 0.85f) CelDangerRed else CelEmeraldThought,
                                                )
                                            }
                                        }
                                        IconButton(
                                            onClick = { viewModel.refreshCloudStorage() },
                                            enabled = !uiState.cloudStorageLoading,
                                        ) {
                                            if (uiState.cloudStorageLoading) CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                                            else Icon(Icons.Rounded.Refresh, contentDescription = "Refresh cloud storage", tint = CelLavender)
                                        }
                                    }
                                    Spacer(Modifier.height(8.dp))
                                    LinearProgressIndicator(
                                        progress = { pct },
                                        color = if (pct > 0.85f) CelDangerRed else visuals.primary,
                                        trackColor = CelTerminalBg,
                                        modifier = Modifier.fillMaxWidth().height(7.dp).clip(RoundedCornerShape(99.dp)),
                                    )
                                    Spacer(Modifier.height(8.dp))

                                    val cloudItems = summary?.items.orEmpty()
                                    if (cloudItems.isEmpty()) {
                                        Text(
                                            text = if (uiState.cloudStorageLoading) "Inspecting your Firestore documents..." else "No cloud items yet. Tap Sync Now above to back up.",
                                            style = MaterialTheme.typography.bodySmall,
                                            color = CelTextSecondary,
                                        )
                                    } else {
                                        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                            cloudItems.forEach { item ->
                                                Row(
                                                    modifier = Modifier
                                                        .fillMaxWidth()
                                                        .clip(RoundedCornerShape(12.dp))
                                                        .background(CelTerminalBg.copy(alpha = 0.72f))
                                                        .padding(horizontal = 10.dp, vertical = 8.dp),
                                                    verticalAlignment = Alignment.CenterVertically,
                                                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                                                ) {
                                                    Column(modifier = Modifier.weight(1f)) {
                                                        Text(item.title, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                                        Text(
                                                            text = "${item.subtitle} · ${String.format(Locale.US, "%.1f", item.sizeBytes / 1024.0)} KB",
                                                            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                                            color = CelTextMuted,
                                                            maxLines = 1,
                                                            overflow = TextOverflow.Ellipsis,
                                                        )
                                                    }
                                                    if (item.collection != "account") {
                                                        IconButton(
                                                            onClick = { viewModel.deleteCloudStorageItem(item.collection, item.docId) },
                                                            modifier = Modifier.size(30.dp),
                                                        ) {
                                                            Icon(Icons.Rounded.Delete, contentDescription = "Delete from cloud", tint = CelDangerRed, modifier = Modifier.size(16.dp))
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    SettingsCategory.SYSTEM -> {
                        // System Permissions & Direct Battery Optimization Popup (#10)
                        item {
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Icon(Icons.Rounded.Security, contentDescription = null, tint = Color(0xFF38BDF8))
                                    Column {
                                        Text("System Permissions & Power", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                        Text("Direct battery exemption popup, notifications & mic", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                    }
                                }
                                Spacer(Modifier.height(10.dp))
                                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                    PermissionShortcutRow(
                                        icon = Icons.Rounded.BatteryChargingFull,
                                        label = "Battery Optimization Exemption",
                                        status = if (batteryUnrestricted) "Unrestricted" else "Allow Popup",
                                        granted = batteryUnrestricted,
                                        onClick = {
                                            val direct = Intent(
                                                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                                Uri.parse("package:${context.packageName}"),
                                            )
                                            runCatching { context.startActivity(direct) }.onFailure {
                                                runCatching { context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
                                            }
                                        },
                                        testTag = "perm_battery_btn",
                                    )
                                    PermissionShortcutRow(
                                        icon = Icons.Rounded.NotificationsActive,
                                        label = "Bundled Chat Notifications",
                                        status = if (notifGranted) "Granted" else "Tap to Grant",
                                        granted = notifGranted,
                                        onClick = {
                                            if (!notifGranted && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                                                notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                                            } else {
                                                val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).apply {
                                                    putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                                                }
                                                runCatching { context.startActivity(intent) }
                                            }
                                        },
                                        testTag = "perm_notifications_btn",
                                    )
                                    PermissionShortcutRow(
                                        icon = Icons.Rounded.Mic,
                                        label = "Microphone (Live Voice & Wake Word)",
                                        status = if (micGranted) "Granted" else "Tap to Grant",
                                        granted = micGranted,
                                        onClick = {
                                            if (!micGranted) micPermLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                            else viewModel.showBanner("Microphone permission already granted.")
                                        },
                                        testTag = "perm_mic_btn",
                                    )
                                    PermissionShortcutRow(
                                        icon = Icons.Rounded.SettingsApplications,
                                        label = "Android App Info & Storage Access",
                                        status = "System Info",
                                        granted = true,
                                        onClick = {
                                            val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                                data = Uri.fromParts("package", context.packageName, null)
                                            }
                                            runCatching { context.startActivity(intent) }
                                        },
                                        testTag = "perm_app_info_btn",
                                    )
                                }
                            }
                        }

                        // Slash Prompt Templates (including editable unremovable /compact #14)
                        item {
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        Icon(Icons.Rounded.Tune, contentDescription = null, tint = visuals.primary)
                                        Text("Slash Prompt Templates (${uiState.promptTemplates.size})", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                    }
                                    IconButton(
                                        onClick = {
                                            editingTemplate = null
                                            showTemplateDialog = true
                                        },
                                        modifier = Modifier.testTag("settings_add_template"),
                                    ) {
                                        Icon(Icons.Rounded.Add, contentDescription = "Add slash template", tint = visuals.primary)
                                    }
                                }
                                Text("Type / in Chat to trigger /compact, /illume, /web, /url, /agent, or custom templates. Tap any template to edit.", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                                Spacer(Modifier.height(6.dp))
                                uiState.promptTemplates.forEach { tpl ->
                                    val isCompact = tpl.id == "tpl_compact" || tpl.slashKey.trim().lowercase().removePrefix("/") == "compact"
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(vertical = 3.dp)
                                            .clip(RoundedCornerShape(10.dp))
                                            .background(CelTerminalBg.copy(alpha = 0.65f))
                                            .clickable {
                                                editingTemplate = tpl
                                                showTemplateDialog = true
                                            }
                                            .padding(horizontal = 10.dp, vertical = 8.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                text = "${tpl.slashKey} · ${tpl.title}${if (isCompact) " (Core)" else ""}",
                                                style = MaterialTheme.typography.labelLarge.copy(fontFamily = JetBrainsMono),
                                                color = CelLavender,
                                            )
                                            Text(tpl.promptBody, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                        }
                                        IconButton(
                                            onClick = {
                                                editingTemplate = tpl
                                                showTemplateDialog = true
                                            },
                                            modifier = Modifier.size(30.dp),
                                        ) {
                                            Icon(Icons.Rounded.Edit, contentDescription = "Edit template", tint = CelLavender, modifier = Modifier.size(16.dp))
                                        }
                                        if (!isCompact) {
                                            IconButton(
                                                onClick = { viewModel.deletePromptTemplate(tpl.id) },
                                                modifier = Modifier.size(30.dp),
                                            ) {
                                                Icon(Icons.Rounded.Delete, contentDescription = "Delete template", tint = CelDangerRed, modifier = Modifier.size(16.dp))
                                            }
                                        }
                                    }
                                }
                            }
                        }

                        // Full JSON Backup
                        item {
                            GlassCard(shape = RoundedCornerShape(22.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Icon(Icons.Rounded.Backup, contentDescription = null, tint = CelEmeraldThought)
                                    Column {
                                        Text("Full App Backup (.json)", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                                        Text("Export or restore all chats, branches, personas, memories & templates", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                                    }
                                }
                                Spacer(Modifier.height(8.dp))
                                SettingSwitchRow("Include Local API Keys in Exported JSON", backupIncludeKeys) {
                                    backupIncludeKeys = it
                                }
                                Spacer(Modifier.height(8.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(
                                        onClick = { exportBackupLauncher.launch("cellium_backup_v2611.json") },
                                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                                        shape = RoundedCornerShape(12.dp),
                                        modifier = Modifier.weight(1f).testTag("settings_export_backup_btn"),
                                    ) {
                                        Icon(Icons.Rounded.FileUpload, contentDescription = null, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("Export JSON", maxLines = 1, softWrap = false)
                                    }
                                    OutlinedButton(
                                        onClick = { importBackupLauncher.launch(arrayOf("application/json", "*/*")) },
                                        shape = RoundedCornerShape(12.dp),
                                        modifier = Modifier.weight(1f).testTag("settings_import_backup_btn"),
                                    ) {
                                        Icon(Icons.Rounded.FileDownload, contentDescription = null, modifier = Modifier.size(16.dp))
                                        Spacer(Modifier.width(6.dp))
                                        Text("Import JSON", maxLines = 1, softWrap = false)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Add / Edit Persona Dialog (works for ALL personas including built-ins)
    if (showPersonaDialog) {
        val existing = editingPersona
        var name by remember(existing?.id) { mutableStateOf(existing?.name.orEmpty()) }
        var selectedIconKey by remember(existing?.id) { mutableStateOf(existing?.iconKey?.ifBlank { "sparkle" } ?: "sparkle") }
        var tagline by remember(existing?.id) { mutableStateOf(existing?.tagline.orEmpty()) }
        var prompt by remember(existing?.id) { mutableStateOf(existing?.systemPrompt.orEmpty()) }
        val accentHex = existing?.accentHex?.ifBlank { "#A855F7" } ?: "#A855F7"

        AlertDialog(
            onDismissRequest = { showPersonaDialog = false },
            title = { Text(if (existing == null) "New Persona" else "Edit Persona") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Name") }, singleLine = true)
                    Text("Icon Badge", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        CelliumIcons.SELECTABLE_PERSONA_KEYS.forEach { (key, label) ->
                            val active = key == selectedIconKey
                            Box(
                                modifier = Modifier
                                    .size(34.dp)
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (active) visuals.primary.copy(alpha = 0.28f) else CelTerminalBg)
                                    .border(1.dp, if (active) visuals.primary else visuals.subtleBorder, RoundedCornerShape(10.dp))
                                    .clickable { selectedIconKey = key },
                                contentAlignment = Alignment.Center,
                            ) {
                                Icon(
                                    imageVector = CelliumIcons.resolve(key),
                                    contentDescription = label,
                                    tint = if (active) visuals.primary else CelTextSecondary,
                                    modifier = Modifier.size(17.dp),
                                )
                            }
                        }
                    }
                    OutlinedTextField(value = tagline, onValueChange = { tagline = it }, label = { Text("Tagline") }, singleLine = true)
                    OutlinedTextField(value = prompt, onValueChange = { prompt = it }, label = { Text("System Prompt") }, minLines = 3)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.savePersona(existing?.id, name, selectedIconKey, tagline, prompt, accentHex)
                        showPersonaDialog = false
                    },
                    enabled = name.isNotBlank() && prompt.isNotBlank(),
                ) { Text("Save", maxLines = 1, softWrap = false) }
            },
            dismissButton = { TextButton(onClick = { showPersonaDialog = false }) { Text("Cancel", maxLines = 1, softWrap = false) } },
        )
    }

    if (showAddMemory) {
        var title by remember { mutableStateOf("") }
        var content by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAddMemory = false },
            title = { Text("New Persistent Memory") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = title, onValueChange = { title = it }, label = { Text("Title") }, singleLine = true)
                    OutlinedTextField(value = content, onValueChange = { content = it }, label = { Text("Memory Detail") }, minLines = 2)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.addMemory(title, content)
                        showAddMemory = false
                    },
                    enabled = title.isNotBlank() && content.isNotBlank(),
                ) { Text("Save", maxLines = 1, softWrap = false) }
            },
            dismissButton = { TextButton(onClick = { showAddMemory = false }) { Text("Cancel", maxLines = 1, softWrap = false) } },
        )
    }

    // Add / Edit Slash Template Dialog (keeps /compact trigger locked while allowing prompt customization)
    if (showTemplateDialog) {
        val existing = editingTemplate
        val isCompact = existing?.id == "tpl_compact" || existing?.slashKey?.trim()?.lowercase()?.removePrefix("/") == "compact"
        var trigger by remember(existing?.id) { mutableStateOf(existing?.slashKey ?: "/custom") }
        var title by remember(existing?.id) { mutableStateOf(existing?.title.orEmpty()) }
        var body by remember(existing?.id) { mutableStateOf(existing?.promptBody.orEmpty()) }

        AlertDialog(
            onDismissRequest = { showTemplateDialog = false },
            title = { Text(if (existing == null) "New Slash Template" else if (isCompact) "Edit /compact Prompt" else "Edit Slash Template") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = trigger,
                        onValueChange = { if (!isCompact) trigger = it },
                        enabled = !isCompact,
                        label = { Text("Trigger (e.g. /eli5)") },
                        singleLine = true,
                    )
                    OutlinedTextField(value = title, onValueChange = { title = it }, label = { Text("Title") }, singleLine = true)
                    OutlinedTextField(value = body, onValueChange = { body = it }, label = { Text("Prompt Body") }, minLines = 4)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.savePromptTemplate(existing?.id, if (isCompact) "/compact" else trigger, title, body)
                        showTemplateDialog = false
                    },
                    enabled = trigger.isNotBlank() && body.isNotBlank(),
                ) { Text("Save", maxLines = 1, softWrap = false) }
            },
            dismissButton = { TextButton(onClick = { showTemplateDialog = false }) { Text("Cancel", maxLines = 1, softWrap = false) } },
        )
    }
}

@Composable
private fun SettingsCategoryRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    accent: Color,
    onClick: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(visuals.glassSurface)
            .border(1.dp, visuals.subtleBorder, RoundedCornerShape(18.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier
                .size(38.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(accent.copy(alpha = 0.18f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = title, tint = accent, modifier = Modifier.size(20.dp))
        }
        Column(modifier = Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Icon(Icons.AutoMirrored.Rounded.KeyboardArrowRight, contentDescription = null, tint = CelTextMuted, modifier = Modifier.size(20.dp))
    }
}

@Composable
private fun StudioQuickTile(
    icon: ImageVector,
    title: String,
    subtitle: String,
    accent: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        color = CelTerminalBg.copy(alpha = 0.72f),
        shape = RoundedCornerShape(16.dp),
        border = androidx.compose.foundation.BorderStroke(1.dp, accent.copy(alpha = 0.45f)),
        modifier = modifier,
    ) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(
                modifier = Modifier
                    .size(34.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(accent.copy(alpha = 0.20f)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = title, tint = accent, modifier = Modifier.size(19.dp))
            }
            Text(title, style = MaterialTheme.typography.titleSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun PermissionShortcutRow(
    icon: ImageVector,
    label: String,
    status: String,
    granted: Boolean,
    onClick: () -> Unit,
    testTag: String,
) {
    val visuals = LocalCelliumVisuals.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(CelTerminalBg.copy(alpha = 0.72f))
            .border(1.dp, visuals.subtleBorder, RoundedCornerShape(12.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .testTag(testTag),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(icon, contentDescription = null, tint = if (granted) CelEmeraldThought else CelAmber, modifier = Modifier.size(20.dp))
        Text(label, style = MaterialTheme.typography.bodySmall, color = CelTextPrimary, modifier = Modifier.weight(1f))
        Surface(
            color = (if (granted) CelEmeraldThought else CelAmber).copy(alpha = 0.16f),
            shape = RoundedCornerShape(8.dp),
        ) {
            Text(
                text = status,
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                color = if (granted) CelEmeraldThought else CelAmber,
                maxLines = 1,
                softWrap = false,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            )
        }
    }
}

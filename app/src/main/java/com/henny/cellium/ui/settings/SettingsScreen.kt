package com.henny.cellium.ui.settings

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
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
import androidx.compose.material.icons.automirrored.rounded.Logout
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Backup
import androidx.compose.material.icons.rounded.BarChart
import androidx.compose.material.icons.rounded.BatteryChargingFull
import androidx.compose.material.icons.rounded.CloudSync
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Face
import androidx.compose.material.icons.rounded.FileDownload
import androidx.compose.material.icons.rounded.FileUpload
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.NotificationsActive
import androidx.compose.material.icons.rounded.Psychology
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.SettingsApplications
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.getValue
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
import com.henny.cellium.core.UserProfile
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
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

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
) {
    val context = LocalContext.current
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    // Isolated RAM polling — only Settings recomposes when RAM updates every 5s
    val processRamMb by viewModel.processRamMb.collectAsStateWithLifecycle()

    var showAddPersona by remember { mutableStateOf(false) }
    var showAddMemory by remember { mutableStateOf(false) }
    var showAddTemplate by remember { mutableStateOf(false) }
    var backupIncludeKeys by remember { mutableStateOf(false) }

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
    val batteryUnrestricted = remember(context) {
        val pm = context.getSystemService(PowerManager::class.java)
        pm?.isIgnoringBatteryOptimizations(context.packageName) == true
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Cel.Cellium Settings", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
            Text(
                "v2611.21.0 · Local-First Room SQLite · CelSuite.HenryJayz.Cellium",
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                color = CelTextSecondary,
            )
        }

        // 0. Studios & Developer Console (Avatar Studio + Stats moved into Settings)
        item {
            GlassCard(highlighted = true, shape = RoundedCornerShape(22.dp)) {
                Text("Studios & Diagnostics", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                Spacer(Modifier.height(8.dp))
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
        }

        // 1. Multi-Provider BYOK API Keys Hub (200+ catalog)
        item { ProvidersHubCard(uiState = uiState, viewModel = viewModel) }

        // 2. On-Device Offline AI (.gguf llama.cpp + .task MediaPipe)
        item {
            OnDeviceModelManagerCard(
                uiState = uiState,
                prefs = prefs,
                processRamMb = processRamMb,
                viewModel = viewModel,
            )
        }

        // 3. Shizuku Privilege, RAM Watchdog (>1.5GB Anti-Kill) & AI Agent Mode
        item {
            val shizukuColor = when (uiState.shizukuStatus) {
                ShizukuStatus.CONNECTED_ROOT, ShizukuStatus.CONNECTED_SHELL -> CelEmeraldThought
                ShizukuStatus.PERMISSION_REQUIRED, ShizukuStatus.BINDING -> CelAmber
                ShizukuStatus.NOT_RUNNING -> CelDangerRed
            }
            val ramProgress = (processRamMb.toFloat() / prefs.ramGuardThresholdMb.coerceAtLeast(256).toFloat()).coerceIn(0f, 1f)
            GlassCard(highlighted = uiState.shizukuAntiKill, shape = RoundedCornerShape(22.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Rounded.Shield, contentDescription = null, tint = shizukuColor)
                        Column {
                            Text("Shizuku & RAM Watchdog", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                            Text(
                                text = "${uiState.shizukuStatus.name} · Live RAM $processRamMb / ${prefs.ramGuardThresholdMb} MB",
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = shizukuColor,
                            )
                        }
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
                        Text("Authorize Shizuku")
                    }
                    OutlinedButton(
                        onClick = { viewModel.testShizukuCommand() },
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.weight(1f).testTag("settings_shizuku_test_button"),
                    ) {
                        Icon(Icons.Rounded.Terminal, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(4.dp))
                        Text("Test Shell")
                    }
                }

                Spacer(Modifier.height(8.dp))
                OutlinedButton(
                    onClick = { viewModel.triggerManualShizukuAntiKill() },
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth().testTag("settings_shizuku_antikill_button"),
                ) {
                    Text("Apply Anti-Kill Protection Now (Doze + OOM + Phantom)")
                }

                Spacer(Modifier.height(10.dp))
                SettingSwitchRow("Auto-Protect When RAM Crosses Threshold", prefs.shizukuAutoGuard) {
                    scope.launch { viewModel.prefsStore.updateShizukuSettings(it, prefs.ramGuardThresholdMb, prefs.agentAutoApproveSafe) }
                }
                Text(
                    "RAM Guard Trigger: ${prefs.ramGuardThresholdMb} MB (${"%.1f".format(prefs.ramGuardThresholdMb / 1024f)} GB)",
                    style = MaterialTheme.typography.labelSmall,
                    color = CelTextSecondary,
                )
                Slider(
                    value = prefs.ramGuardThresholdMb.toFloat(),
                    onValueChange = { v ->
                        scope.launch { viewModel.prefsStore.updateShizukuSettings(prefs.shizukuAutoGuard, v.toInt(), prefs.agentAutoApproveSafe) }
                    },
                    valueRange = 512f..3584f,
                )
                SettingSwitchRow("Enable AI Agent Mode (Shizuku Shell Calls)", prefs.agentModeEnabled) {
                    scope.launch { viewModel.prefsStore.updateAgentMode(it) }
                }
                SettingSwitchRow("Auto-Run SAFE Read-Only Agent Commands", prefs.agentAutoApproveSafe) {
                    scope.launch { viewModel.prefsStore.updateShizukuSettings(prefs.shizukuAutoGuard, prefs.ramGuardThresholdMb, it) }
                }
            }
        }

        // 4. System Permissions & Power Center
        item {
            GlassCard(shape = RoundedCornerShape(22.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Icon(Icons.Rounded.Security, contentDescription = null, tint = Color(0xFF38BDF8))
                    Column {
                        Text("System Permissions & Power Center", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                        Text("Quick shortcuts for background notifications & battery freedom", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    }
                }
                Spacer(Modifier.height(10.dp))
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
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
                        icon = Icons.Rounded.BatteryChargingFull,
                        label = "Battery Optimization Exemption",
                        status = if (batteryUnrestricted) "Unrestricted" else "Open Settings",
                        granted = batteryUnrestricted,
                        onClick = {
                            runCatching {
                                context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                            }
                        },
                        testTag = "perm_battery_btn",
                    )
                    PermissionShortcutRow(
                        icon = Icons.Rounded.Mic,
                        label = "Microphone (Live Voice & Dictation)",
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

        // 5. Theme, Wallpaper & Liquid Glass Studio
        item { ThemeWallpaperStudioCard(prefs = prefs, viewModel = viewModel) }

        // 6. Voice Lab, Animalese SFX, Haptics & Notifications
        item { VoiceAndAudioLabCard(prefs = prefs, viewModel = viewModel) }

        // 7. Prompt Templates & Slash Commands Manager
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
                    IconButton(onClick = { showAddTemplate = true }, modifier = Modifier.testTag("settings_add_template")) {
                        Icon(Icons.Rounded.Add, contentDescription = "Add slash template", tint = visuals.primary)
                    }
                }
                Text("Type / in Chat to trigger templates, /web, /url, /imagine, or /agent.", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                Spacer(Modifier.height(6.dp))
                uiState.promptTemplates.forEach { tpl ->
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("${tpl.slashKey} · ${tpl.title}", style = MaterialTheme.typography.labelLarge.copy(fontFamily = JetBrainsMono), color = CelLavender)
                            Text(tpl.promptBody, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        IconButton(onClick = { viewModel.deletePromptTemplate(tpl.id) }) {
                            Icon(Icons.Rounded.Delete, contentDescription = "Delete template", tint = CelDangerRed, modifier = Modifier.size(18.dp))
                        }
                    }
                }
            }
        }

        // 8. Full App Backup (.json Export & Import)
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
                        Text("Export JSON")
                    }
                    OutlinedButton(
                        onClick = { importBackupLauncher.launch(arrayOf("application/json", "*/*")) },
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.weight(1f).testTag("settings_import_backup_btn"),
                    ) {
                        Icon(Icons.Rounded.FileDownload, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Import JSON")
                    }
                }
            }
        }

        // 9. Custom Personas (100% Vector Icons — Zero Emojis)
        item {
            GlassCard(shape = RoundedCornerShape(22.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Icon(Icons.Rounded.AutoAwesome, contentDescription = null, tint = visuals.primary)
                        Text("Custom Personas (${uiState.customPersonas.size})", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    }
                    IconButton(onClick = { showAddPersona = true }, modifier = Modifier.testTag("settings_add_persona")) {
                        Icon(Icons.Rounded.Add, contentDescription = "Add persona", tint = visuals.primary)
                    }
                }
                if (uiState.customPersonas.isEmpty()) {
                    Text("8 built-in Cel personas included. Tap + to create your own.", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                } else {
                    uiState.customPersonas.forEach { p ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            VectorBadgeIcon(iconKey = p.iconKey, contentDescription = p.name, tint = visuals.primary, containerSize = 28.dp, iconSize = 15.dp)
                            Column(modifier = Modifier.weight(1f)) {
                                Text(p.name, style = MaterialTheme.typography.bodyMedium, color = CelTextPrimary)
                                if (p.tagline.isNotBlank()) {
                                    Text(p.tagline, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                            }
                            IconButton(onClick = { viewModel.deleteCustomPersona(p.id) }) {
                                Icon(Icons.Rounded.Delete, contentDescription = "Delete persona", tint = CelDangerRed, modifier = Modifier.size(18.dp))
                            }
                        }
                    }
                }
            }
        }

        // 10. Persistent Memories
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

        // 11. Optional Google Sign-In & Cloud Backup Sync
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
                    "Privately backs up all your API keys, Kaggle & Imagine credentials, usage stats, settings, chats, templates, custom personas, and memories to your Google account (strictly accessible only by you).",
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
                            Text("Sync Now")
                        }
                        OutlinedButton(
                            onClick = onSignOutGoogle,
                            shape = RoundedCornerShape(12.dp),
                        ) {
                            Icon(Icons.AutoMirrored.Rounded.Logout, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("Guest")
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
                        Text("Sign in with Google for Optional Sync")
                    }
                }
            }
        }
    }

    if (showAddPersona) {
        var name by remember { mutableStateOf("") }
        var selectedIconKey by remember { mutableStateOf("sparkle") }
        var tagline by remember { mutableStateOf("") }
        var prompt by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAddPersona = false },
            title = { Text("New Custom Persona") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Name") }, singleLine = true)
                    Text("Icon Badge", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        CelliumIcons.SELECTABLE_PERSONA_KEYS.forEach { (key, label) ->
                            val active = key == selectedIconKey
                            Box(
                                modifier = Modifier
                                    .size(36.dp)
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
                                    modifier = Modifier.size(18.dp),
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
                        viewModel.addCustomPersona(name, selectedIconKey, tagline, prompt)
                        showAddPersona = false
                    },
                    enabled = name.isNotBlank() && prompt.isNotBlank(),
                ) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { showAddPersona = false }) { Text("Cancel") } },
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
                ) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { showAddMemory = false }) { Text("Cancel") } },
        )
    }

    if (showAddTemplate) {
        var trigger by remember { mutableStateOf("/custom") }
        var title by remember { mutableStateOf("") }
        var body by remember { mutableStateOf("") }
        AlertDialog(
            onDismissRequest = { showAddTemplate = false },
            title = { Text("New Slash Prompt Template") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(value = trigger, onValueChange = { trigger = it }, label = { Text("Trigger (e.g. /eli5)") }, singleLine = true)
                    OutlinedTextField(value = title, onValueChange = { title = it }, label = { Text("Title") }, singleLine = true)
                    OutlinedTextField(value = body, onValueChange = { body = it }, label = { Text("Prompt Body") }, minLines = 3)
                }
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.addPromptTemplate(trigger, title, body)
                        showAddTemplate = false
                    },
                    enabled = trigger.isNotBlank() && body.isNotBlank(),
                ) { Text("Save") }
            },
            dismissButton = { TextButton(onClick = { showAddTemplate = false }) { Text("Cancel") } },
        )
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
    val visuals = LocalCelliumVisuals.current
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
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
            )
        }
    }
}

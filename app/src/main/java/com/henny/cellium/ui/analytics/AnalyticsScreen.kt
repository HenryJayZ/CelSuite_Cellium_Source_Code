package com.henny.cellium.ui.analytics

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DeleteSweep
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.components.copyTextToClipboard
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono

/**
 * Stats & Developer Console sub-screen (opened from Settings).
 * Note: RAM Watchdog now lives inside Settings -> Shizuku & RAM Watchdog per user request.
 */
@Composable
fun AnalyticsScreen(
    viewModel: CelliumViewModel,
    onBack: () -> Unit,
) {
    BackHandler { onBack() }

    val context = LocalContext.current
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val logs by DevLogBuffer.entries.collectAsStateWithLifecycle()

    val totalTokens = uiState.sessions.sumOf { it.tokenCount }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back to Settings", tint = CelTextPrimary)
                }
                Column {
                    Text("Stats & Developer Console", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
                    Text(
                        "Local Room SQLite metrics & live network/engine logs",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            }
        }

        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                KpiCard("Sessions", "${uiState.sessions.size}", Modifier.weight(1f))
                KpiCard("Messages", "${uiState.totalMessageCount}", Modifier.weight(1f))
                KpiCard("Est. Tokens", "$totalTokens", Modifier.weight(1f))
            }
        }

        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                KpiCard("Artworks", "${uiState.artworks.size}", Modifier.weight(1f))
                KpiCard("Personas", "${8 + uiState.customPersonas.size}", Modifier.weight(1f))
                KpiCard("Memories", "${uiState.memories.size}", Modifier.weight(1f))
            }
        }

        item {
            GlassCard(shape = RoundedCornerShape(20.dp)) {
                Text("Ready Providers", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                Spacer(Modifier.height(8.dp))
                val readyProviders = uiState.providers.filter { !it.requiresKey || it.apiKey.isNotBlank() || it.protocol == "on_device" }
                if (readyProviders.isEmpty()) {
                    Text("No providers configured yet.", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                } else {
                    readyProviders.take(12).forEach { p ->
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                VectorBadgeIcon(iconKey = p.badge, contentDescription = null, containerSize = 22.dp, iconSize = 12.dp)
                                Text(p.name, style = MaterialTheme.typography.bodySmall, color = CelTextPrimary)
                            }
                            Text(p.selectedModel.take(24), style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono), color = CelLavender)
                        }
                    }
                }
            }
        }

        item {
            GlassCard(shape = RoundedCornerShape(20.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Developer Console (${logs.size})", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                    Row {
                        IconButton(
                            onClick = {
                                val text = logs.joinToString("\n") { "[${it.timestamp}] ${it.level}/${it.tag}: ${it.message}" }
                                copyTextToClipboard(context, text)
                                viewModel.showBanner("Copied ${logs.size} log lines.")
                            },
                            modifier = Modifier.testTag("dev_console_copy_all"),
                        ) {
                            Icon(Icons.Rounded.ContentCopy, contentDescription = "Copy all logs", tint = CelTextSecondary, modifier = Modifier.size(18.dp))
                        }
                        IconButton(onClick = { DevLogBuffer.clear() }) {
                            Icon(Icons.Rounded.DeleteSweep, contentDescription = "Clear logs", tint = CelDangerRed, modifier = Modifier.size(18.dp))
                        }
                    }
                }
                Spacer(Modifier.height(6.dp))
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(CelTerminalBg)
                        .border(1.dp, CelBorderSubtle, RoundedCornerShape(12.dp))
                        .padding(10.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    if (logs.isEmpty()) {
                        Text("No logs yet.", style = MaterialTheme.typography.bodySmall.copy(fontFamily = JetBrainsMono), color = CelTextSecondary)
                    } else {
                        logs.takeLast(30).reversed().forEach { entry ->
                            val col = when (entry.level) {
                                "ERROR" -> CelDangerRed
                                "WARN" -> CelAmber
                                else -> CelEmeraldThought
                            }
                            Text(
                                text = "[${entry.timestamp}] ${entry.tag}: ${entry.message}",
                                style = MaterialTheme.typography.labelSmall.copy(
                                    fontFamily = JetBrainsMono,
                                    lineHeight = 15.sp,
                                ),
                                color = col,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun KpiCard(label: String, value: String, modifier: Modifier = Modifier) {
    GlassCard(modifier = modifier, shape = RoundedCornerShape(16.dp), contentPadding = 12.dp) {
        Text(value, style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
        Text(label, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
    }
}

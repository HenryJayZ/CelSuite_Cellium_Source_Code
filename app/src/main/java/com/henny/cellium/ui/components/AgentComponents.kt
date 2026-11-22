package com.henny.cellium.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Block
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.henny.cellium.shizuku.CommandAssessment
import com.henny.cellium.shizuku.CommandSafetyTier
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals

@Composable
fun CommandGuardCard(
    assessment: CommandAssessment,
    shizukuReady: Boolean,
    onApprove: (editedCommand: String) -> Unit,
    onDeny: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalCelliumVisuals.current
    var editableCmd by remember(assessment.command) { mutableStateOf(assessment.command) }

    val (accent, badgeLabel, icon) = when (assessment.tier) {
        CommandSafetyTier.SAFE -> Triple(CelEmeraldThought, "SAFE · READ-ONLY", Icons.Rounded.CheckCircle)
        CommandSafetyTier.CAUTION -> Triple(CelAmber, "CAUTION · REVIEW", Icons.Rounded.Warning)
        CommandSafetyTier.BLOCKED -> Triple(CelDangerRed, "BLOCKED · DESTRUCTIVE", Icons.Rounded.Block)
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(CelTerminalBg.copy(alpha = 0.94f))
            .border(1.2.dp, accent.copy(alpha = 0.65f), RoundedCornerShape(16.dp))
            .padding(14.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(Icons.Rounded.Shield, contentDescription = "Command Guard", tint = accent, modifier = Modifier.size(18.dp))
            Text(
                text = "Shizuku Agent Guard · $badgeLabel",
                style = MaterialTheme.typography.labelLarge,
                color = accent,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            text = assessment.reason,
            style = MaterialTheme.typography.bodySmall,
            color = CelTextSecondary,
        )
        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = editableCmd,
            onValueChange = { editableCmd = it },
            enabled = assessment.tier != CommandSafetyTier.BLOCKED,
            singleLine = false,
            maxLines = 4,
            textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = JetBrainsMono),
            modifier = Modifier
                .fillMaxWidth()
                .testTag("agent_command_input"),
            shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = accent,
                unfocusedBorderColor = CelBorderSubtle,
                focusedTextColor = CelTextPrimary,
                unfocusedTextColor = CelTextPrimary,
            ),
        )

        if (!shizukuReady && assessment.tier != CommandSafetyTier.BLOCKED) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = "Shizuku is not currently connected. Open Settings -> Shizuku to authorize.",
                style = MaterialTheme.typography.labelSmall,
                color = CelAmber,
            )
        }

        Spacer(Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (assessment.tier != CommandSafetyTier.BLOCKED) {
                Button(
                    onClick = { onApprove(editableCmd.trim()) },
                    enabled = editableCmd.isNotBlank(),
                    colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier
                        .weight(1f)
                        .testTag("agent_approve_button"),
                ) {
                    Icon(Icons.Rounded.PlayArrow, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Run via Shizuku")
                }
            }
            OutlinedButton(
                onClick = onDeny,
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier
                    .weight(if (assessment.tier == CommandSafetyTier.BLOCKED) 1f else 0.7f)
                    .testTag("agent_deny_button"),
            ) {
                Icon(Icons.Rounded.Close, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(if (assessment.tier == CommandSafetyTier.BLOCKED) "Dismiss" else "Deny")
            }
        }
    }
}

@Composable
fun TerminalOutputCard(
    command: String,
    output: String,
    status: String,
    modifier: Modifier = Modifier,
) {
    if (command.isBlank() && output.isBlank()) return
    val context = LocalContext.current
    var expanded by remember { mutableStateOf(true) }
    val statusColor = when (status) {
        "approved" -> CelEmeraldThought
        "denied" -> CelAmber
        "blocked" -> CelDangerRed
        else -> CelTextSecondary
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(CelTerminalBg)
            .border(1.dp, statusColor.copy(alpha = 0.40f), RoundedCornerShape(12.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Rounded.Terminal, contentDescription = "Shizuku shell", tint = statusColor, modifier = Modifier.size(15.dp))
                Text(
                    text = "$ $command",
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = statusColor,
                    maxLines = 1,
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(
                    onClick = { copyTextToClipboard(context, "$ $command\n$output") },
                    modifier = Modifier.size(30.dp),
                ) {
                    Icon(Icons.Rounded.ContentCopy, contentDescription = "Copy terminal output", tint = CelTextSecondary, modifier = Modifier.size(14.dp))
                }
                Icon(
                    imageVector = if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                    contentDescription = "Toggle output",
                    tint = CelTextSecondary,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
        AnimatedVisibility(visible = expanded && output.isNotBlank()) {
            Text(
                text = output,
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = JetBrainsMono,
                    lineHeight = 16.sp,
                ),
                color = Color(0xFFD6F5E3),
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(start = 10.dp, end = 10.dp, bottom = 10.dp),
            )
        }
    }
}

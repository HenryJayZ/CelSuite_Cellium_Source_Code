package com.henny.cellium.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountTree
import androidx.compose.material.icons.rounded.ChevronLeft
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.VolumeUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.shizuku.CommandSafetyTier
import com.henny.cellium.ui.components.MarkdownMessageContent
import com.henny.cellium.ui.components.ThoughtAccordion
import com.henny.cellium.ui.components.copyTextToClipboard
import com.henny.cellium.ui.theme.CelAmberWarn
import com.henny.cellium.ui.theme.CelBorderActive
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelRedError
import com.henny.cellium.ui.theme.CelSoftLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import java.io.File
import java.util.Locale

@Composable
fun ChatMessageBubble(
    message: MessageEntity,
    personaName: String,
    branchInfo: BranchSlotInfo?,
    onSwitchBranch: (String) -> Unit,
    onEditInPlace: (MessageEntity, String, Boolean) -> Unit,
    onEditAsBranch: (MessageEntity, String, Boolean) -> Unit,
    onRegenerate: (MessageEntity) -> Unit,
    onForkSession: (MessageEntity) -> Unit,
    onSpeak: (String) -> Unit,
    onDelete: (MessageEntity) -> Unit,
) {
    val context = LocalContext.current
    val visuals = LocalCelliumVisuals.current
    val isUser = message.role == "user"
    val isTool = message.role == "tool"
    val isError = message.isError
    var showEditDialog by remember(message.id) { mutableStateOf(false) }

    if (showEditDialog) {
        EditMessageBranchDialog(
            message = message,
            onDismiss = { showEditDialog = false },
            onEditInPlace = { edited, regen ->
                showEditDialog = false
                onEditInPlace(message, edited, regen)
            },
            onEditAsBranch = { edited, regen ->
                showEditDialog = false
                onEditAsBranch(message, edited, regen)
            },
        )
    }

    if (isTool) {
        ToolExecutionCard(message)
        return
    }

    val bubbleBg = when {
        isError -> CelRedError.copy(alpha = 0.14f)
        isUser -> visuals.primary.copy(alpha = (visuals.glassOpacity * 0.50f).coerceIn(0.16f, 0.56f))
        else -> visuals.glassSurface
    }
    val bubbleBorder = when {
        isError -> CelRedError.copy(alpha = 0.55f)
        isUser -> visuals.activeBorder
        else -> visuals.subtleBorder
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(bubbleBg)
            .border(1.dp, bubbleBorder, RoundedCornerShape(18.dp))
            .padding(horizontal = 13.dp, vertical = 11.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // FIXED SINGLE-LINE HEADER ROW: weight(1f) + Ellipsis on left, softWrap=false on right
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val leftLabel = if (isUser) {
                "You"
            } else {
                val speaker = message.speakerLabel.ifBlank { personaName }
                val cleanModel = message.modelName.removePrefix("models/")
                listOf(speaker, message.providerName, cleanModel)
                    .filter { it.isNotBlank() }
                    .joinToString(" · ")
            }
            if (isError) {
                Icon(
                    imageVector = Icons.Rounded.ErrorOutline,
                    contentDescription = "Error",
                    tint = CelRedError,
                    modifier = Modifier.size(14.dp),
                )
            }
            Text(
                text = leftLabel,
                style = MaterialTheme.typography.labelSmall.copy(
                    fontFamily = JetBrainsMono,
                    fontWeight = FontWeight.SemiBold,
                ),
                color = if (isError) CelRedError else if (isUser) CelSoftLavender else visuals.primary,
                maxLines = 1,
                softWrap = false,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (!isUser && message.latencyMs > 0L) {
                val secStr = String.format(Locale.US, "%.1fs", message.latencyMs / 1000.0)
                val tpsStr = if (message.tokensPerSec >= 1f) {
                    " · ${String.format(Locale.US, "%.0f", message.tokensPerSec)} t/s"
                } else ""
                val costStr = if (message.estimatedCostUsd >= 0.0001) {
                    " · $${String.format(Locale.US, "%.4f", message.estimatedCostUsd)}"
                } else ""
                Text(
                    text = "$secStr$tpsStr$costStr",
                    style = MaterialTheme.typography.labelSmall.copy(
                        fontFamily = JetBrainsMono,
                        fontSize = 10.sp,
                    ),
                    color = CelTextMuted,
                    maxLines = 1,
                    softWrap = false,
                )
            }
        }

        if (message.attachmentFileName.isNotBlank()) {
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = visuals.primary.copy(alpha = 0.14f),
                border = androidx.compose.foundation.BorderStroke(1.dp, visuals.subtleBorder),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Icon(
                        imageVector = Icons.Rounded.Description,
                        contentDescription = "Attached file",
                        tint = CelLavender,
                        modifier = Modifier.size(15.dp),
                    )
                    Text(
                        text = message.attachmentFileName,
                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                        color = CelTextPrimary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }

        if (message.attachmentPath.isNotBlank() && File(message.attachmentPath).exists()) {
            AsyncImage(
                model = File(message.attachmentPath),
                contentDescription = "Attached image",
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 220.dp)
                    .clip(RoundedCornerShape(12.dp)),
            )
        }

        if (message.thought.isNotBlank()) {
            ThoughtAccordion(thought = message.thought)
        }

        if (isUser) {
            Text(
                text = message.content,
                style = MaterialTheme.typography.bodyMedium,
                color = CelTextPrimary,
            )
        } else {
            MarkdownMessageContent(text = message.content)
        }

        if (isError) {
            Button(
                onClick = { onRegenerate(message) },
                colors = ButtonDefaults.buttonColors(containerColor = CelRedError),
                modifier = Modifier.testTag("error_retry_button"),
            ) {
                Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.size(6.dp))
                Text("Retry Request")
            }
        }

        // Branch switcher + Action toolbar (Copy, Edit w/ Branch Choice, Retry, Speak, Fork, Delete)
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            if (branchInfo != null && branchInfo.total > 1) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(
                        onClick = { branchInfo.prevId?.let(onSwitchBranch) },
                        enabled = branchInfo.prevId != null,
                        modifier = Modifier.size(30.dp),
                    ) {
                        Icon(
                            Icons.Rounded.ChevronLeft,
                            contentDescription = "Previous branch",
                            tint = CelTextSecondary,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                    Text(
                        text = "${branchInfo.currentIndex + 1}/${branchInfo.total}",
                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                        color = CelLavender,
                    )
                    IconButton(
                        onClick = { branchInfo.nextId?.let(onSwitchBranch) },
                        enabled = branchInfo.nextId != null,
                        modifier = Modifier.size(30.dp),
                    ) {
                        Icon(
                            Icons.Rounded.ChevronRight,
                            contentDescription = "Next branch",
                            tint = CelTextSecondary,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
            } else {
                Spacer(Modifier.size(4.dp))
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                IconButton(
                    onClick = { copyTextToClipboard(context, message.content) },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Rounded.ContentCopy, contentDescription = "Copy", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                }
                // Edit is now available on BOTH User AND Cel (Assistant) bubbles!
                IconButton(
                    onClick = { showEditDialog = true },
                    modifier = Modifier.size(32.dp).testTag("edit_msg_btn_${message.id}"),
                ) {
                    Icon(Icons.Rounded.Edit, contentDescription = "Edit message", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                }
                if (!isUser) {
                    IconButton(
                        onClick = { onRegenerate(message) },
                        modifier = Modifier.size(32.dp).testTag("retry_msg_btn_${message.id}"),
                    ) {
                        Icon(Icons.Rounded.Refresh, contentDescription = "Retry response", tint = CelLavender, modifier = Modifier.size(15.dp))
                    }
                    IconButton(
                        onClick = { onSpeak(message.content) },
                        modifier = Modifier.size(32.dp),
                    ) {
                        Icon(Icons.Rounded.VolumeUp, contentDescription = "Speak aloud", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                    }
                }
                IconButton(
                    onClick = { onForkSession(message) },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Rounded.AccountTree, contentDescription = "Fork into new chat", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                }
                IconButton(
                    onClick = { onDelete(message) },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Rounded.DeleteOutline, contentDescription = "Delete", tint = CelTextMuted, modifier = Modifier.size(15.dp))
                }
            }
        }
    }
}

@Composable
private fun EditMessageBranchDialog(
    message: MessageEntity,
    onDismiss: () -> Unit,
    onEditInPlace: (String, Boolean) -> Unit,
    onEditAsBranch: (String, Boolean) -> Unit,
) {
    val isUser = message.role == "user"
    var draft by remember(message.id) { mutableStateOf(message.content) }
    var regenerateReply by remember(message.id) { mutableStateOf(isUser) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF140D26),
        title = {
            Text(
                text = if (isUser) "Edit Your Message" else "Edit Cel's Reply",
                color = CelTextPrimary,
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 100.dp, max = 240.dp),
                    label = { Text("Message content") },
                )
                if (isUser) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { regenerateReply = !regenerateReply },
                    ) {
                        Checkbox(checked = regenerateReply, onCheckedChange = { regenerateReply = it })
                        Text(
                            text = "Regenerate Cel's reply after saving",
                            style = MaterialTheme.typography.bodySmall,
                            color = CelTextSecondary,
                        )
                    }
                }
                Text(
                    text = "Choose whether to overwrite this bubble in place or create a new sibling branch you can switch between.",
                    style = MaterialTheme.typography.labelSmall,
                    color = CelTextMuted,
                )
            }
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = { onEditInPlace(draft, regenerateReply) },
                    enabled = draft.isNotBlank(),
                    modifier = Modifier.testTag("edit_in_place_button"),
                ) {
                    Text("Edit in Place")
                }
                Button(
                    onClick = { onEditAsBranch(draft, regenerateReply) },
                    enabled = draft.isNotBlank(),
                    modifier = Modifier.testTag("edit_as_branch_button"),
                ) {
                    Text("New Branch")
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

@Composable
private fun ToolExecutionCard(message: MessageEntity) {
    val badgeColor = when (message.toolStatus) {
        "approved" -> CelEmeraldThought
        "blocked" -> CelRedError
        else -> CelAmberWarn
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(CelTerminalBg)
            .border(1.dp, badgeColor.copy(alpha = 0.45f), RoundedCornerShape(14.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Icon(Icons.Rounded.Terminal, contentDescription = null, tint = badgeColor, modifier = Modifier.size(16.dp))
            Text(
                text = "SHIZUKU AGENT · ${message.toolStatus.uppercase()}",
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                color = badgeColor,
            )
        }
        if (message.toolCommand.isNotBlank()) {
            Text(
                text = "$ ${message.toolCommand}",
                style = MaterialTheme.typography.bodySmall.copy(fontFamily = JetBrainsMono),
                color = CelSoftLavender,
            )
        }
        if (message.toolOutput.isNotBlank()) {
            Text(
                text = message.toolOutput.take(1800),
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono, lineHeight = 16.sp),
                color = CelTextSecondary,
            )
        }
    }
}

@Composable
fun AgentCommandGuardDialog(
    pending: PendingAgentGuard,
    onApprove: (String) -> Unit,
    onDeny: () -> Unit,
) {
    var editableCmd by remember(pending) { mutableStateOf(pending.assessment.command) }
    val tier = pending.assessment.tier
    val tierColor = when (tier) {
        CommandSafetyTier.SAFE -> CelEmeraldThought
        CommandSafetyTier.CAUTION -> CelAmberWarn
        CommandSafetyTier.BLOCKED -> CelRedError
    }
    AlertDialog(
        onDismissRequest = onDeny,
        containerColor = Color(0xFF140D26),
        icon = { Icon(Icons.Rounded.Security, contentDescription = null, tint = tierColor) },
        title = { Text("Shizuku Command Guard · ${tier.name}", color = CelTextPrimary) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(pending.assessment.reason, style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
                OutlinedTextField(
                    value = editableCmd,
                    onValueChange = { editableCmd = it },
                    label = { Text("Shell command (editable)") },
                    textStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = JetBrainsMono),
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            if (tier != CommandSafetyTier.BLOCKED) {
                Button(
                    onClick = { onApprove(editableCmd) },
                    colors = ButtonDefaults.buttonColors(containerColor = tierColor),
                ) { Text("Run via Shizuku", color = Color.Black) }
            }
        },
        dismissButton = {
            TextButton(onClick = onDeny) {
                Text(if (tier == CommandSafetyTier.BLOCKED) "Dismiss" else "Deny")
            }
        },
    )
}

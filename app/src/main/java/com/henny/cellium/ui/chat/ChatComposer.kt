package com.henny.cellium.ui.chat

import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.content.MediaType
import androidx.compose.foundation.content.ReceiveContentListener
import androidx.compose.foundation.content.TransferableContent
import androidx.compose.foundation.content.consume
import androidx.compose.foundation.content.contentReceiver
import androidx.compose.foundation.content.hasMediaType
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.input.clearText
import androidx.compose.foundation.text.input.rememberTextFieldState
import androidx.compose.foundation.text.input.setTextAndPlaceCursorAtEnd
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Compress
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Language
import androidx.compose.material.icons.rounded.Link
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.UploadFile
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.henny.cellium.data.local.PromptTemplateEntity
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelRedError
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals

private data class SlashOption(
    val trigger: String,
    val title: String,
    val subtitle: String,
    val icon: ImageVector,
    val insertText: String,
    val isArenaShortcut: Boolean = false,
)

/**
 * Isolated zero-lag Chat Composer with:
 * - BasicTextField(TextFieldState) + contentReceiver for GBoard clipboard image/GIF paste
 * - Multi-image attachment strip (up to 5 images per turn) + text file attachment chip
 * - '+' button opening Upload Images / Upload File / Prompt Templates sheet
 * - Inline '/' Slash Command & Prompt Template autocomplete menu (/compact, /illume, /web, /url, /agent, /arena, /clear)
 */
@OptIn(ExperimentalFoundationApi::class, ExperimentalMaterial3Api::class)
@Composable
fun ChatComposerBar(
    personaName: String,
    isStreaming: Boolean,
    promptTemplates: List<PromptTemplateEntity>,
    pendingImages: List<Bitmap>,
    pendingFile: AttachedTextFile?,
    injectedText: String?,
    onClearInjectedText: () -> Unit,
    onPastedBitmap: (Bitmap) -> Unit,
    onRemoveImageAt: (Int) -> Unit,
    onClearFile: () -> Unit,
    onPickImage: () -> Unit,
    onPickFile: () -> Unit,
    onStartVoiceInput: () -> Unit,
    onOpenArena: () -> Unit,
    onStopStreaming: () -> Unit,
    onSend: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val visuals = LocalCelliumVisuals.current
    val textState = rememberTextFieldState()
    var showAttachSheet by remember { mutableStateOf(false) }

    LaunchedEffect(injectedText) {
        if (!injectedText.isNullOrBlank()) {
            val existing = textState.text.toString()
            val next = if (existing.isBlank()) injectedText else "$existing $injectedText"
            textState.setTextAndPlaceCursorAtEnd(next)
            onClearInjectedText()
        }
    }

    val currentText by remember { derivedStateOf { textState.text.toString() } }

    val builtInSlashOptions = remember {
        listOf(
            SlashOption("/compact", "Compact Context", "Summarize history into a clean fresh boundary", Icons.Rounded.Compress, "/compact"),
            SlashOption("/illume ", "Illume Art", "Generate artwork directly into Chat", Icons.Rounded.Palette, "/illume "),
            SlashOption("/web ", "Web Search", "Search live web & attach citations", Icons.Rounded.Language, "/web "),
            SlashOption("/url ", "Read Webpage", "Extract article text from any URL", Icons.Rounded.Link, "/url https://"),
            SlashOption("/agent ", "Shizuku Shell", "Run guarded Android command", Icons.Rounded.Terminal, "/agent "),
            SlashOption("/arena", "Open Arena Mode", "Launch 2-AI group chat", Icons.Rounded.Forum, "/arena", isArenaShortcut = true),
            SlashOption("/clear", "New Chat", "Start a fresh conversation", Icons.Rounded.AutoAwesome, "/clear"),
        )
    }

    val matchingSlashOptions by remember(promptTemplates) {
        derivedStateOf {
            val t = textState.text.toString()
            if (!t.startsWith("/") || t.contains("\n") || t.length > 26) {
                emptyList()
            } else {
                val query = t.lowercase()
                val custom = promptTemplates
                    .filterNot { it.slashKey.trim().lowercase().removePrefix("/") == "compact" }
                    .map { tpl ->
                        SlashOption(
                            trigger = tpl.slashKey.let { if (it.startsWith("/")) it else "/$it" },
                            title = tpl.title,
                            subtitle = tpl.promptBody.replace("\n", " ").take(64),
                            icon = Icons.Rounded.AutoAwesome,
                            insertText = tpl.promptBody,
                        )
                    }
                (builtInSlashOptions + custom).filter {
                    it.trigger.lowercase().startsWith(query) || it.title.lowercase().contains(query.removePrefix("/"))
                }.take(7)
            }
        }
    }

    val contentListener = remember(context) {
        ReceiveContentListener { transferableContent: TransferableContent ->
            if (!transferableContent.hasMediaType(MediaType.Image)) {
                transferableContent
            } else {
                transferableContent.consume { item ->
                    val uri = item.uri
                    if (uri != null) {
                        val bmp = decodeBitmapFromUri(context, uri)
                        if (bmp != null) {
                            onPastedBitmap(bmp)
                            true
                        } else false
                    } else false
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        AnimatedVisibility(visible = matchingSlashOptions.isNotEmpty()) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(16.dp))
                    .background(Color(0xF0120B24))
                    .border(1.dp, visuals.activeBorder, RoundedCornerShape(16.dp))
                    .padding(6.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                matchingSlashOptions.forEach { opt ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(12.dp))
                            .clickable {
                                if (opt.isArenaShortcut) {
                                    textState.clearText()
                                    onOpenArena()
                                } else {
                                    textState.setTextAndPlaceCursorAtEnd(opt.insertText)
                                }
                            }
                            .padding(horizontal = 10.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        Icon(opt.icon, contentDescription = null, tint = CelLavender, modifier = Modifier.size(18.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp),
                            ) {
                                Text(
                                    text = opt.trigger.trim(),
                                    style = MaterialTheme.typography.labelMedium.copy(
                                        fontFamily = JetBrainsMono,
                                        fontWeight = FontWeight.Bold,
                                    ),
                                    color = visuals.primary,
                                    maxLines = 1,
                                    softWrap = false,
                                )
                                Text(
                                    text = opt.title,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = CelTextPrimary,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Text(
                                text = opt.subtitle,
                                style = MaterialTheme.typography.labelSmall,
                                color = CelTextMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                    }
                }
            }
        }

        // Pending Multi-Image & File Attachment Strip
        if (pendingImages.isNotEmpty() || pendingFile != null) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                pendingImages.forEachIndexed { idx, bmp ->
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = visuals.glassSurface,
                        border = androidx.compose.foundation.BorderStroke(1.dp, visuals.activeBorder),
                    ) {
                        Row(
                            modifier = Modifier.padding(5.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(5.dp),
                        ) {
                            Image(
                                bitmap = bmp.asImageBitmap(),
                                contentDescription = "Pending image ${idx + 1}",
                                contentScale = ContentScale.Crop,
                                modifier = Modifier.size(38.dp).clip(RoundedCornerShape(8.dp)),
                            )
                            Text(
                                text = "#${idx + 1}",
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = CelTextPrimary,
                                maxLines = 1,
                                softWrap = false,
                            )
                            IconButton(onClick = { onRemoveImageAt(idx) }, modifier = Modifier.size(22.dp)) {
                                Icon(Icons.Rounded.Close, contentDescription = "Remove image", tint = CelTextMuted, modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                }
                if (pendingFile != null) {
                    Surface(
                        shape = RoundedCornerShape(12.dp),
                        color = visuals.glassSurface,
                        border = androidx.compose.foundation.BorderStroke(1.dp, visuals.activeBorder),
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Icon(Icons.Rounded.Description, contentDescription = null, tint = CelLavender, modifier = Modifier.size(16.dp))
                            Text(
                                text = pendingFile.fileName,
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = CelTextPrimary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            IconButton(onClick = onClearFile, modifier = Modifier.size(22.dp)) {
                                Icon(Icons.Rounded.Close, contentDescription = "Remove file", tint = CelTextMuted, modifier = Modifier.size(14.dp))
                            }
                        }
                    }
                }
            }
        }

        // Main Pill Composer Bar
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(26.dp))
                .background(visuals.glassSurface)
                .border(1.dp, visuals.activeBorder, RoundedCornerShape(26.dp))
                .padding(horizontal = 6.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(
                onClick = { showAttachSheet = true },
                modifier = Modifier.size(44.dp).testTag("composer_plus_button"),
            ) {
                Icon(Icons.Rounded.Add, contentDescription = "Attach images, file, or template", tint = CelLavender)
            }
            IconButton(
                onClick = onStartVoiceInput,
                modifier = Modifier.size(40.dp).testTag("composer_mic_button"),
            ) {
                Icon(Icons.Rounded.Mic, contentDescription = "Voice input", tint = CelLavender, modifier = Modifier.size(20.dp))
            }

            Box(
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 6.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (currentText.isEmpty()) {
                    Text(
                        text = "Message $personaName or type /",
                        style = MaterialTheme.typography.bodyMedium,
                        color = CelTextMuted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                BasicTextField(
                    state = textState,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(color = CelTextPrimary),
                    cursorBrush = SolidColor(visuals.primary),
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 120.dp)
                        .contentReceiver(contentListener)
                        .testTag("chat_input_field"),
                )
            }

            if (isStreaming) {
                IconButton(
                    onClick = onStopStreaming,
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(CelRedError)
                        .testTag("stop_stream_button"),
                ) {
                    Icon(Icons.Rounded.Stop, contentDescription = "Stop generating", tint = Color.White)
                }
            } else {
                val canSend = currentText.isNotBlank() || pendingImages.isNotEmpty() || pendingFile != null
                IconButton(
                    onClick = {
                        val toSend = textState.text.toString()
                        textState.clearText()
                        onSend(toSend)
                    },
                    enabled = canSend,
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(if (canSend) visuals.primary else CelBorderSubtle)
                        .testTag("send_message_button"),
                ) {
                    Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = "Send", tint = Color.White, modifier = Modifier.size(20.dp))
                }
            }
        }
    }

    if (showAttachSheet) {
        ModalBottomSheet(
            onDismissRequest = { showAttachSheet = false },
            containerColor = Color(0xFF130B24),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 10.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text("Attach or Insert", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    AttachActionCard(
                        icon = Icons.Rounded.Image,
                        title = "Upload Images",
                        subtitle = "Up to 5 photos",
                        accent = visuals.primary,
                        modifier = Modifier.weight(1f).testTag("attach_image_option"),
                        onClick = {
                            showAttachSheet = false
                            onPickImage()
                        },
                    )
                    AttachActionCard(
                        icon = Icons.Rounded.UploadFile,
                        title = "Upload File",
                        subtitle = "Code, TXT, MD, JSON",
                        accent = Color(0xFF38BDF8),
                        modifier = Modifier.weight(1f).testTag("attach_file_option"),
                        onClick = {
                            showAttachSheet = false
                            onPickFile()
                        },
                    )
                }

                Text("Prompt Templates", style = MaterialTheme.typography.labelLarge, color = CelLavender)
                LazyColumn(
                    modifier = Modifier.fillMaxWidth().heightIn(max = 220.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(promptTemplates, key = { it.id }) { tpl ->
                        val isCompact = tpl.slashKey.trim().lowercase().removePrefix("/") == "compact"
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .background(visuals.glassSurface)
                                .border(1.dp, visuals.subtleBorder, RoundedCornerShape(12.dp))
                                .clickable {
                                    showAttachSheet = false
                                    textState.setTextAndPlaceCursorAtEnd(if (isCompact) "/compact" else tpl.promptBody)
                                }
                                .padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Icon(
                                imageVector = if (isCompact) Icons.Rounded.Compress else Icons.Rounded.AutoAwesome,
                                contentDescription = null,
                                tint = visuals.primary,
                                modifier = Modifier.size(18.dp),
                            )
                            Column(modifier = Modifier.weight(1f)) {
                                Text(tpl.title, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                                Text(
                                    text = tpl.slashKey.let { if (it.startsWith("/")) it else "/$it" },
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = CelTextMuted,
                                )
                            }
                        }
                    }
                }
                Text(
                    text = "Tip: Paste images/GIFs directly from GBoard clipboard, or pick multiple images at once.",
                    style = MaterialTheme.typography.labelSmall,
                    color = CelTextMuted,
                )
                Spacer(Modifier.height(16.dp))
            }
        }
    }
}

@Composable
private fun AttachActionCard(
    icon: ImageVector,
    title: String,
    subtitle: String,
    accent: Color,
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(accent.copy(alpha = 0.14f))
            .border(1.dp, accent.copy(alpha = 0.45f), RoundedCornerShape(16.dp))
            .clickable(onClick = onClick)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(icon, contentDescription = title, tint = accent, modifier = Modifier.size(24.dp))
        Text(title, style = MaterialTheme.typography.titleSmall, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(subtitle, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private fun decodeBitmapFromUri(context: android.content.Context, uri: Uri): Bitmap? = runCatching {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        ImageDecoder.decodeBitmap(ImageDecoder.createSource(context.contentResolver, uri)) { decoder, _, _ ->
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        }
    } else {
        @Suppress("DEPRECATION")
        MediaStore.Images.Media.getBitmap(context.contentResolver, uri)
    }
}.getOrNull()

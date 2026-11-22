package com.henny.cellium.ui.components

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Psychology
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalScrollCaptureInProgress
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import com.henny.cellium.R
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelPanelGlass
import com.henny.cellium.ui.theme.CelSoftLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.CelViolet
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.sin
import kotlin.random.Random

private data class AmbientMote(
    val xFrac: Float,
    val yFrac: Float,
    val radius: Float,
    val speed: Float,
    val phase: Float,
    val magenta: Boolean,
)

/**
 * Cellium signature backdrop: authentic cel_wallpaper.webp + configurable obsidian dim scrim +
 * neon-violet top aurora + optional gentle floating ambient particles.
 */
@Composable
fun CelliumBackground(
    dimAlpha: Float? = null,
    particlesEnabled: Boolean? = null,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val effectiveDim = dimAlpha ?: visuals.wallpaperDim
    val effectiveParticles = particlesEnabled ?: visuals.particlesEnabled
    val densityCount = visuals.particleDensity.coerceIn(0, 60)

    val motes = remember(densityCount) {
        val rng = Random(422026)
        List(densityCount) {
            AmbientMote(
                xFrac = rng.nextFloat(),
                yFrac = rng.nextFloat(),
                radius = 2.0f + rng.nextFloat() * 4.2f,
                speed = 0.012f + rng.nextFloat() * 0.025f,
                phase = rng.nextFloat() * 6.28f,
                magenta = rng.nextBoolean(),
            )
        }
    }
    val context = LocalContext.current
    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    var isResumed by remember { mutableStateOf(true) }
    androidx.compose.runtime.DisposableEffect(lifecycleOwner) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            when (event) {
                androidx.lifecycle.Lifecycle.Event.ON_RESUME -> isResumed = true
                androidx.lifecycle.Lifecycle.Event.ON_PAUSE -> isResumed = false
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    var tickMs by remember { mutableLongStateOf(0L) }
    val frameStepMs = if (visuals.highFpsMode) 20L else 48L
    LaunchedEffect(effectiveParticles, frameStepMs, isResumed) {
        if (!effectiveParticles || densityCount == 0 || !isResumed) return@LaunchedEffect
        var lastMs = 0L
        while (true) {
            withFrameMillis { now ->
                if (now - lastMs >= frameStepMs) {
                    lastMs = now
                    tickMs = now
                }
            }
        }
    }

    val wallpaperRequest = remember(visuals.customWallpaperUri) {
        val data: Any = if (visuals.customWallpaperUri.isNotBlank()) {
            visuals.customWallpaperUri
        } else {
            R.drawable.cel_wallpaper
        }
        coil.request.ImageRequest.Builder(context)
            .data(data)
            .size(720, 1280)
            .allowHardware(true)
            .build()
    }

    val neutralScrim = Color(0xFF06060A)
    Box(modifier = modifier.fillMaxSize().background(neutralScrim)) {
        AsyncImage(
            model = wallpaperRequest,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(),
        )
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        colors = listOf(
                            neutralScrim.copy(alpha = (effectiveDim + 0.14f).coerceIn(0.18f, 0.92f)),
                            neutralScrim.copy(alpha = effectiveDim.coerceIn(0.10f, 0.86f)),
                            neutralScrim.copy(alpha = (effectiveDim + 0.20f).coerceIn(0.24f, 0.94f)),
                        )
                    )
                )
        )
        val scrollCaptureActive = LocalScrollCaptureInProgress.current
        if (effectiveParticles && motes.isNotEmpty() && !scrollCaptureActive) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val t = tickMs * 0.001f
                for (m in motes) {
                    val y = ((m.yFrac - t * m.speed) % 1f + 1f) % 1f
                    val x = m.xFrac + sin(t * 0.7f + m.phase) * 0.025f
                    val alpha = (0.16f + 0.22f * (0.5f + 0.5f * sin(t * 1.4f + m.phase))).coerceIn(0.06f, 0.45f)
                    val color = if (m.magenta) visuals.secondary else visuals.primary
                    drawCircle(
                        color = color.copy(alpha = alpha),
                        radius = m.radius * density,
                        center = Offset(x * size.width, y * size.height),
                    )
                }
            }
        }
        content()
    }
}

@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    shape: Shape = RoundedCornerShape(20.dp),
    highlighted: Boolean = false,
    backgroundColor: Color? = null,
    contentPadding: Dp = 16.dp,
    content: @Composable ColumnScope.() -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val bg = backgroundColor ?: visuals.glassSurface
    val borderBrush = if (highlighted) {
        Brush.linearGradient(listOf(visuals.activeBorder, visuals.secondary.copy(alpha = 0.75f)))
    } else {
        Brush.linearGradient(listOf(visuals.activeBorder.copy(alpha = 0.55f), visuals.subtleBorder))
    }
    Column(
        modifier = modifier
            .clip(shape)
            .background(bg)
            .border(width = if (highlighted) 1.3.dp else 1.dp, brush = borderBrush, shape = shape)
            .padding(contentPadding),
        content = content,
    )
}

@Composable
fun GlassPill(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    content: @Composable RowScope.() -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val shape = RoundedCornerShape(999.dp)
    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = shape,
        color = if (selected) visuals.primary.copy(alpha = 0.28f) else CelPanelGlass,
        border = BorderStroke(
            width = 1.dp,
            color = if (selected) visuals.activeBorder else visuals.subtleBorder,
        ),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            content = content,
        )
    }
}

@Composable
fun ThoughtAccordion(
    thought: String,
    modifier: Modifier = Modifier,
) {
    if (thought.isBlank()) return
    var expanded by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(CelTerminalBg.copy(alpha = 0.85f))
            .border(1.dp, CelEmeraldThought.copy(alpha = 0.30f), RoundedCornerShape(12.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(
                    imageVector = Icons.Rounded.Psychology,
                    contentDescription = "Reasoning trace",
                    tint = CelEmeraldThought,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = if (expanded) "Hide Thought Process" else "View Thought Process",
                    style = MaterialTheme.typography.labelMedium,
                    color = CelEmeraldThought,
                )
            }
            Icon(
                imageVector = if (expanded) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                contentDescription = if (expanded) "Collapse thought" else "Expand thought",
                tint = CelEmeraldThought,
                modifier = Modifier.size(18.dp),
            )
        }
        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically(),
            exit = shrinkVertically(),
        ) {
            Text(
                text = thought,
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFamily = JetBrainsMono,
                    lineHeight = 18.sp,
                ),
                color = CelEmeraldThought.copy(alpha = 0.90f),
                modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp),
            )
        }
    }
}

private sealed interface MdBlock {
    data class Paragraph(val text: String) : MdBlock
    data class Heading(val level: Int, val text: String) : MdBlock
    data class Bullet(val text: String) : MdBlock
    data class Code(val language: String, val code: String) : MdBlock
}

private fun parseMarkdownBlocks(raw: String): List<MdBlock> {
    val blocks = mutableListOf<MdBlock>()
    val lines = raw.replace("\r\n", "\n").split('\n')
    var i = 0
    val para = StringBuilder()

    fun flushPara() {
        val text = para.toString().trim()
        if (text.isNotEmpty()) blocks.add(MdBlock.Paragraph(text))
        para.clear()
    }

    while (i < lines.size) {
        val line = lines[i]
        val trimmed = line.trimStart()
        if (trimmed.startsWith("```")) {
            flushPara()
            val lang = trimmed.removePrefix("```").trim()
            val codeSb = StringBuilder()
            i++
            while (i < lines.size && !lines[i].trimStart().startsWith("```")) {
                if (codeSb.isNotEmpty()) codeSb.append('\n')
                codeSb.append(lines[i])
                i++
            }
            blocks.add(MdBlock.Code(lang.ifEmpty { "code" }, codeSb.toString()))
            i++
            continue
        }
        when {
            trimmed.startsWith("### ") -> {
                flushPara()
                blocks.add(MdBlock.Heading(3, trimmed.removePrefix("### ").trim()))
            }
            trimmed.startsWith("## ") -> {
                flushPara()
                blocks.add(MdBlock.Heading(2, trimmed.removePrefix("## ").trim()))
            }
            trimmed.startsWith("# ") -> {
                flushPara()
                blocks.add(MdBlock.Heading(1, trimmed.removePrefix("# ").trim()))
            }
            trimmed.startsWith("- ") || trimmed.startsWith("* ") -> {
                flushPara()
                blocks.add(MdBlock.Bullet(trimmed.drop(2).trim()))
            }
            trimmed.isEmpty() -> flushPara()
            else -> {
                if (para.isNotEmpty()) para.append('\n')
                para.append(line)
            }
        }
        i++
    }
    flushPara()
    return blocks
}

private fun formatInlineMarkdown(text: String): AnnotatedString = buildAnnotatedString {
    var i = 0
    val n = text.length
    while (i < n) {
        if (i + 1 < n && text[i] == '*' && text[i + 1] == '*') {
            val end = text.indexOf("**", i + 2)
            if (end > i + 2) {
                withStyle(SpanStyle(fontWeight = FontWeight.Bold, color = CelTextPrimary)) {
                    append(text.substring(i + 2, end))
                }
                i = end + 2
                continue
            }
        }
        if (text[i] == '`') {
            val end = text.indexOf('`', i + 1)
            if (end > i + 1) {
                withStyle(
                    SpanStyle(
                        fontFamily = JetBrainsMono,
                        color = CelSoftLavender,
                        background = Color(0x553B1A6E),
                    )
                ) {
                    append(" ${text.substring(i + 1, end)} ")
                }
                i = end + 1
                continue
            }
        }
        if (text[i] == '*' && (i + 1 < n && text[i + 1] != ' ')) {
            val end = text.indexOf('*', i + 1)
            if (end > i + 1) {
                withStyle(SpanStyle(fontStyle = FontStyle.Italic, color = CelTextSecondary)) {
                    append(text.substring(i + 1, end))
                }
                i = end + 1
                continue
            }
        }
        append(text[i])
        i++
    }
}

@Composable
fun MarkdownMessageContent(
    text: String,
    defaultWordWrap: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val blocks = remember(text) { parseMarkdownBlocks(text) }
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (block in blocks) {
            when (block) {
                is MdBlock.Heading -> {
                    val style = when (block.level) {
                        1 -> MaterialTheme.typography.titleLarge
                        2 -> MaterialTheme.typography.titleMedium
                        else -> MaterialTheme.typography.titleSmall
                    }
                    Text(
                        text = formatInlineMarkdown(block.text),
                        style = style,
                        color = CelSoftLavender,
                    )
                }
                is MdBlock.Bullet -> {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            text = "•",
                            style = MaterialTheme.typography.bodyLarge,
                            color = CelViolet,
                        )
                        Text(
                            text = formatInlineMarkdown(block.text),
                            style = MaterialTheme.typography.bodyMedium,
                            color = CelTextPrimary,
                        )
                    }
                }
                is MdBlock.Paragraph -> {
                    Text(
                        text = formatInlineMarkdown(block.text),
                        style = MaterialTheme.typography.bodyMedium,
                        color = CelTextPrimary,
                    )
                }
                is MdBlock.Code -> CodeCard(
                    language = block.language,
                    code = block.code,
                    defaultWordWrap = defaultWordWrap,
                )
            }
        }
    }
}

@Composable
fun CodeCard(
    language: String,
    code: String,
    defaultWordWrap: Boolean = true,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var copied by remember { mutableStateOf(false) }
    var wrapEnabled by remember(defaultWordWrap) { mutableStateOf(defaultWordWrap) }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(CelTerminalBg)
            .border(1.dp, CelBorderSubtle, RoundedCornerShape(14.dp)),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color(0xFF161029))
                .padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = language.uppercase(),
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                color = CelLavender,
                maxLines = 1,
                softWrap = false,
            )
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text(
                    text = if (wrapEnabled) "Wrap" else "Scroll",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (wrapEnabled) CelLavender else CelTextSecondary,
                    maxLines = 1,
                    softWrap = false,
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { wrapEnabled = !wrapEnabled }
                        .padding(horizontal = 6.dp, vertical = 4.dp),
                )
                Row(
                    modifier = Modifier
                        .clip(RoundedCornerShape(8.dp))
                        .clickable {
                            copyTextToClipboard(context, code)
                            copied = true
                            scope.launch {
                                delay(1500)
                                copied = false
                            }
                        }
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Icon(
                        imageVector = if (copied) Icons.Rounded.Check else Icons.Rounded.ContentCopy,
                        contentDescription = "Copy code",
                        tint = if (copied) CelEmeraldThought else CelTextSecondary,
                        modifier = Modifier.size(14.dp),
                    )
                    Text(
                        text = if (copied) "Copied" else "Copy",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (copied) CelEmeraldThought else CelTextSecondary,
                        maxLines = 1,
                        softWrap = false,
                    )
                }
            }
        }
        Text(
            text = code,
            style = MaterialTheme.typography.bodySmall.copy(
                fontFamily = JetBrainsMono,
                lineHeight = 18.sp,
            ),
            color = CelTextPrimary,
            softWrap = wrapEnabled,
            modifier = if (wrapEnabled) {
                Modifier.fillMaxWidth().padding(12.dp)
            } else {
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(12.dp)
            },
        )
    }
}

fun copyTextToClipboard(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
    clipboard?.setPrimaryClip(ClipData.newPlainText("Cel.Cellium", text))
}

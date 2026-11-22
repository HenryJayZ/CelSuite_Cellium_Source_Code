package com.henny.cellium.ui.avatar

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/**
 * Draggable Floating Mini-Cel Companion (Android port of PC Cellium's floating companion widget).
 * Renders the authentic 3,800-expression dot-matrix avatar; tap to headpat, double-tap for Live Mode.
 */
@Composable
fun FloatingMiniCelOverlay(
    mood: String,
    avatarGender: String,
    highFps: Boolean,
    onHeadpat: () -> Unit,
    onOpenLiveMode: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    var offsetX by remember { mutableFloatStateOf(24f) }
    var offsetY by remember { mutableFloatStateOf(160f) }
    var happyPulse by remember { mutableStateOf(false) }
    var library by remember { mutableStateOf<AvatarLibrary?>(null) }

    LaunchedEffect(context) {
        library = withContext(Dispatchers.IO) { AvatarLibrary.load(context) }
    }

    val expr = remember(library, avatarGender, mood, happyPulse) {
        val baseName = if (happyPulse) "Heart Eyes" else MoodDetector.moodToExpressionName(mood)
        library?.get(avatarGender, baseName, "Base")
    }

    Box(
        modifier = modifier
            .offset { IntOffset(offsetX.roundToInt(), offsetY.roundToInt()) }
            .pointerInput(Unit) {
                detectDragGestures { change, dragAmount ->
                    change.consume()
                    offsetX = (offsetX + dragAmount.x).coerceIn(-20f, 880f)
                    offsetY = (offsetY + dragAmount.y).coerceIn(40f, 1750f)
                }
            }
            .pointerInput(Unit) {
                detectTapGestures(
                    onTap = {
                        happyPulse = !happyPulse
                        onHeadpat()
                    },
                    onDoubleTap = { onOpenLiveMode() },
                )
            }
            .testTag("floating_mini_cel"),
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .shadow(14.dp, CircleShape)
                .clip(CircleShape)
                .background(visuals.glassSurface.copy(alpha = 0.94f))
                .border(1.4.dp, visuals.activeBorder, CircleShape)
                .padding(8.dp),
        ) {
            DotMatrixAvatarCanvas(
                expression = expr,
                highFps = highFps,
                modifier = Modifier.size(74.dp),
            )
        }
        IconButton(
            onClick = onDismiss,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .offset(x = 8.dp, y = (-8).dp)
                .size(26.dp)
                .clip(CircleShape)
                .background(Color(0xDD1A102E))
                .border(1.dp, visuals.subtleBorder, CircleShape)
                .testTag("floating_mini_cel_close"),
        ) {
            Icon(
                imageVector = Icons.Rounded.Close,
                contentDescription = "Hide Mini-Cel",
                tint = Color.White,
                modifier = Modifier.size(14.dp),
            )
        }
    }
}

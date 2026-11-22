package com.henny.cellium.avatar

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameMillis
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import kotlin.math.PI
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

private data class OrbPose(
    val browL: Float,
    val browR: Float,
    val angL: Float,
    val angR: Float,
    val eyeRy: Float,
    val pupil: Float,
    val eyeL: Float,
    val eyeR: Float,
    val smile: Float,
    val open: Float,
    val blush: Float,
    val tilt: Float,
)

private val ORB_POSES = mapOf(
    "calm" to OrbPose(0.10f, 0.10f, 0f, 0f, 1.0f, 1.0f, 1f, 1f, 0.13f, 0f, 0.15f, 0f),
    "happy" to OrbPose(0.50f, 0.50f, -5f, 5f, 0.85f, 1.08f, 1f, 1f, 0.21f, 0f, 0.65f, 2.5f),
    "curious" to OrbPose(0.90f, 0.05f, -7f, 3f, 1.12f, 0.90f, 1f, 1f, 0.08f, 0.18f, 0.15f, -6f),
    "wink" to OrbPose(0.15f, 0.75f, 7f, -9f, 1.0f, 1.0f, 0f, 1f, 0.17f, 0f, 0.55f, 7f),
    "surprised" to OrbPose(1.0f, 1.0f, -3f, 3f, 1.40f, 0.68f, 1f, 1f, 0f, 0.82f, 0.1f, 0f),
    "flustered" to OrbPose(0.42f, 0.42f, -16f, 16f, 1.18f, 0.86f, 1f, 1f, 0.02f, 0f, 1.0f, -4f),
    "angry" to OrbPose(-0.18f, -0.18f, 20f, -20f, 0.64f, 1.05f, 1f, 1f, -0.15f, 0f, 0f, 0f),
)

private val PLAYFUL_MOODS = listOf("calm", "happy", "curious", "wink", "surprised", "flustered")

/**
 * Faithful Compose Canvas port of Cellium's AnimatedFaceOrb (widgets/welcome.py):
 * glossy neon-violet companion sphere, pulsing forehead diamond gem, gem-cut eyes with catchlights,
 * animated eyebrows, mood cross-fading, squishy tap bounce, and spam-tap red devil rage mode!
 */
@Composable
fun WelcomeFaceOrb(
    modifier: Modifier = Modifier,
    blushEnabled: Boolean = true,
    onTapFeedback: ((mood: String, angry: Boolean) -> Unit)? = null,
) {
    var clock by remember { mutableFloatStateOf(0f) }
    var bounce by remember { mutableFloatStateOf(0f) }
    var ring by remember { mutableFloatStateOf(1f) }
    var annoy by remember { mutableFloatStateOf(0f) }
    var mood by remember { mutableStateOf("happy") }
    var blinkT by remember { mutableFloatStateOf(-1f) }
    var flashT by remember { mutableFloatStateOf(-1f) }
    var gazeX by remember { mutableFloatStateOf(0f) }
    var gazeY by remember { mutableFloatStateOf(0f) }
    var frameTick by remember { mutableLongStateOf(0L) }

    // Smoothly interpolated live pose
    var livePose by remember { mutableStateOf(ORB_POSES["happy"]!!) }

    LaunchedEffect(Unit) {
        var lastMs = 0L
        var blinkWait = 2.6f
        var flashWait = 3.8f
        var wanderWait = 1.8f
        var moodLeft = 9.0f
        var targetGazeX = 0f
        var targetGazeY = 0f
        val rng = Random(System.nanoTime())

        while (true) {
            withFrameMillis { nowMs ->
                val dt = if (lastMs == 0L) 0.016f else ((nowMs - lastMs) / 1000f).coerceIn(0.001f, 0.06f)
                lastMs = nowMs
                clock += dt
                bounce = (bounce - dt * 2.6f).coerceAtLeast(0f)
                ring = (ring + dt * 1.9f).coerceAtMost(1f)
                annoy = (annoy - dt * 0.22f).coerceAtLeast(0f)

                if (blinkT < 0f) {
                    blinkWait -= dt
                    if (blinkWait <= 0f) blinkT = 0f
                } else {
                    blinkT += dt
                    if (blinkT >= 0.25f) {
                        blinkT = -1f
                        blinkWait = if (rng.nextFloat() < 0.22f) 0.18f else 2.2f + rng.nextFloat() * 3.0f
                    }
                }

                if (flashT < 0f) {
                    flashWait -= dt
                    if (flashWait <= 0f) flashT = 0f
                } else {
                    flashT += dt
                    if (flashT >= 0.38f) {
                        flashT = -1f
                        flashWait = 3.0f + rng.nextFloat() * 4.5f
                    }
                }

                wanderWait -= dt
                if (wanderWait <= 0f) {
                    targetGazeX = (rng.nextFloat() * 2f - 1f) * 3.0f
                    targetGazeY = (rng.nextFloat() * 2f - 1f) * 2.0f
                    wanderWait = 1.5f + rng.nextFloat() * 2.2f
                }
                gazeX += (targetGazeX - gazeX) * (dt * 7f).coerceAtMost(1f)
                gazeY += (targetGazeY - gazeY) * (dt * 7f).coerceAtMost(1f)

                moodLeft -= dt
                if (moodLeft <= 0f) {
                    mood = if (annoy > 0.55f) "angry" else PLAYFUL_MOODS.filter { it != mood }.random(rng)
                    moodLeft = if (annoy > 0.55f) 2.0f else 6.0f + rng.nextFloat() * 4.5f
                }

                val target = ORB_POSES[mood] ?: ORB_POSES["happy"]!!
                val r = (dt * 8.5f).coerceAtMost(1f)
                fun lp(a: Float, b: Float) = a + (b - a) * r
                livePose = OrbPose(
                    browL = lp(livePose.browL, target.browL),
                    browR = lp(livePose.browR, target.browR),
                    angL = lp(livePose.angL, target.angL),
                    angR = lp(livePose.angR, target.angR),
                    eyeRy = lp(livePose.eyeRy, target.eyeRy),
                    pupil = lp(livePose.pupil, target.pupil),
                    eyeL = lp(livePose.eyeL, target.eyeL),
                    eyeR = lp(livePose.eyeR, target.eyeR),
                    smile = lp(livePose.smile, target.smile),
                    open = lp(livePose.open, target.open),
                    blush = lp(livePose.blush, target.blush),
                    tilt = lp(livePose.tilt, target.tilt),
                )
                frameTick = nowMs
            }
        }
    }

    Canvas(
        modifier = modifier.pointerInput(Unit) {
            detectTapGestures {
                bounce = 1f
                ring = 0f
                annoy = (annoy + 0.34f).coerceAtMost(2.2f)
                val isAngry = annoy >= 1.0f
                mood = if (isAngry) {
                    "angry"
                } else {
                    PLAYFUL_MOODS.filter { it != mood }.random()
                }
                onTapFeedback?.invoke(mood, isAngry)
            }
        }
    ) {
        if (frameTick < 0L) return@Canvas
        val base = min(size.width, size.height) * 0.36f
        val rage = annoy.coerceIn(0f, 1f)
        val floatY = sin(clock * 1.45f) * base * 0.045f
        val trembleX = if (annoy > 1.4f) sin(clock * 65f) * 3.2f else 0f
        val trembleY = if (annoy > 1.4f) sin(clock * 52f) * 2.2f else 0f
        val sx = 1f + sin(bounce * PI.toFloat()) * 0.11f
        val sy = 1f - sin(bounce * PI.toFloat()) * 0.09f

        val cx = size.width / 2f + trembleX
        val cy = size.height / 2f + floatY + trembleY

        // Tap ripple ring
        if (ring < 0.99f) {
            val ringColor = lerp(Color(0xFFC084FC), Color(0xFFFF6B6B), rage)
            drawCircle(
                color = ringColor.copy(alpha = (1f - ring) * 0.55f),
                radius = base * (1.02f + ring * 0.42f),
                center = Offset(cx, cy),
                style = Stroke(width = 3f),
            )
        }

        // Ambient glow halo
        val glowCenter = lerp(Color(0xAA9333EA), Color(0xCCEF4444), rage)
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(glowCenter, glowCenter.copy(alpha = 0.25f), Color.Transparent),
                center = Offset(cx, cy),
                radius = base * 1.45f,
            ),
            radius = base * 1.45f,
            center = Offset(cx, cy),
        )

        translate(left = cx, top = cy) {
            rotate(degrees = livePose.tilt) {
                scale(scaleX = sx, scaleY = sy, pivot = Offset.Zero) {
                    // Devil horns fade in during rage
                    if (rage > 0.15f) {
                        drawDevilHorns(base, rage)
                    }

                    // Glossy 3D orb sphere
                    val hi = lerp(Color(0xFFD8B4FE), Color(0xFFFCA5A5), rage)
                    val mid = lerp(Color(0xFF8A2BE2), Color(0xFFDC2626), rage)
                    val deep = lerp(Color(0xFF3B0764), Color(0xFF5C0A15), rage)
                    drawCircle(
                        brush = Brush.radialGradient(
                            colors = listOf(hi, mid, deep),
                            center = Offset(-base * 0.26f, -base * 0.30f),
                            radius = base * 1.38f,
                        ),
                        radius = base,
                        center = Offset.Zero,
                    )
                    // Specular rim & glass top highlight
                    drawCircle(
                        color = Color.White.copy(alpha = 0.32f),
                        radius = base,
                        center = Offset.Zero,
                        style = Stroke(width = base * 0.045f),
                    )
                    drawOval(
                        brush = Brush.verticalGradient(
                            colors = listOf(Color.White.copy(alpha = 0.42f), Color.Transparent)
                        ),
                        topLeft = Offset(-base * 0.56f, -base * 0.86f),
                        size = Size(base * 1.12f, base * 0.44f),
                    )

                    // Forehead diamond gem
                    drawForeheadGem(base, clock, rage)

                    // Blush cheeks
                    val effectiveBlush = if (blushEnabled) (livePose.blush * (1f - rage)) else 0f
                    if (effectiveBlush > 0.03f) {
                        for (side in listOf(-1f, 1f)) {
                            val bx = side * base * 0.42f
                            val by = base * 0.16f
                            drawOval(
                                brush = Brush.radialGradient(
                                    colors = listOf(
                                        Color(0xFFF472B6).copy(alpha = 0.72f * effectiveBlush),
                                        Color.Transparent,
                                    ),
                                    center = Offset(bx, by),
                                    radius = base * 0.22f,
                                ),
                                topLeft = Offset(bx - base * 0.22f, by - base * 0.13f),
                                size = Size(base * 0.44f, base * 0.26f),
                            )
                        }
                    }

                    // Blink openness
                    val blinkOpen = when {
                        blinkT < 0f -> 1f
                        blinkT < 0.09f -> 1f - blinkT / 0.09f
                        blinkT < 0.13f -> 0f
                        else -> ((blinkT - 0.13f) / 0.12f).coerceIn(0f, 1f)
                    }

                    // Eyes
                    val eyeY = -base * 0.06f
                    val eyeRx = base * 0.155f
                    val eyeRy = base * 0.195f * livePose.eyeRy
                    drawOrbEye(base, -base * 0.30f, eyeY, eyeRx, eyeRy, blinkOpen * livePose.eyeL, gazeX, gazeY, -1f, livePose.pupil, rage)
                    drawOrbEye(base, base * 0.30f, eyeY, eyeRx, eyeRy, blinkOpen * livePose.eyeR, gazeX, gazeY, 1f, livePose.pupil, rage)

                    // Eyebrows
                    val flash = if (flashT >= 0f) sin(PI.toFloat() * (flashT / 0.38f).coerceIn(0f, 1f)).pow(1.5f) else 0f
                    drawOrbBrow(base, -1f, livePose.browL, livePose.angL, eyeY - eyeRy - base * 0.055f, flash, clock)
                    drawOrbBrow(base, 1f, livePose.browR, livePose.angR, eyeY - eyeRy - base * 0.055f, flash, clock)

                    // Mouth
                    drawOrbMouth(base, livePose.smile, livePose.open)

                    // Comic anger vein when boiling
                    if (rage > 0.65f) {
                        val pulse = 0.85f + 0.25f * sin(clock * 12f)
                        val vx = base * 0.56f
                        val vy = -base * 0.54f
                        val vr = base * 0.11f * pulse
                        val stroke = Stroke(width = (base * 0.036f).coerceAtLeast(2f), cap = StrokeCap.Round)
                        val veinColor = Color(0xFFFFD4D4)
                        drawLine(veinColor, Offset(vx - vr, vy - vr * 0.2f), Offset(vx - vr * 0.2f, vy - vr * 0.2f), stroke.width, StrokeCap.Round)
                        drawLine(veinColor, Offset(vx - vr * 0.2f, vy - vr * 0.2f), Offset(vx - vr * 0.2f, vy - vr), stroke.width, StrokeCap.Round)
                        drawLine(veinColor, Offset(vx + vr * 0.2f, vy + vr * 0.2f), Offset(vx + vr, vy + vr * 0.2f), stroke.width, StrokeCap.Round)
                        drawLine(veinColor, Offset(vx + vr * 0.2f, vy + vr * 0.2f), Offset(vx + vr * 0.2f, vy + vr), stroke.width, StrokeCap.Round)
                    }
                }
            }
        }
    }
}

private fun DrawScope.drawDevilHorns(base: Float, rage: Float) {
    val a = (rage * 1.5f).coerceIn(0f, 1f)
    for (side in listOf(-1f, 1f)) {
        val path = Path().apply {
            moveTo(side * base * 0.34f, -base * 0.72f)
            quadraticTo(side * base * 0.62f, -base * 0.96f, side * base * 0.72f, -base * 1.05f)
            quadraticTo(side * base * 0.58f, -base * 0.76f, side * base * 0.56f, -base * 0.65f)
            close()
        }
        drawPath(path, Color(0xFFDC2626).copy(alpha = a))
    }
}

private fun DrawScope.drawForeheadGem(base: Float, clock: Float, rage: Float) {
    val gy = -base * 0.52f
    val gr = base * 0.085f
    val pulse = 0.5f + 0.5f * sin(clock * 2.6f)
    val glowCol = lerp(Color(0xFFE8BEFF), Color(0xFFFFC4C4), rage)
    drawCircle(
        brush = Brush.radialGradient(
            colors = listOf(glowCol.copy(alpha = 0.45f + 0.3f * pulse), Color.Transparent),
            center = Offset(0f, gy),
            radius = gr * 3f,
        ),
        radius = gr * 3f,
        center = Offset(0f, gy),
    )
    val diamond = Path().apply {
        moveTo(0f, gy - gr)
        lineTo(gr * 0.72f, gy)
        lineTo(0f, gy + gr)
        lineTo(-gr * 0.72f, gy)
        close()
    }
    drawPath(diamond, lerp(Color(0xFFC684FF), Color(0xFFFFAAAA), rage))
    drawPath(diamond, Color(0xFF4E2082), style = Stroke(width = 1.6f))
    drawCircle(Color.White.copy(alpha = 0.92f), gr * 0.22f, Offset(-gr * 0.16f, gy - gr * 0.18f))
}

private fun DrawScope.drawOrbEye(
    base: Float,
    ex: Float,
    ey: Float,
    rx: Float,
    ry: Float,
    openness: Float,
    gx: Float,
    gy: Float,
    side: Float,
    pupilScale: Float,
    rage: Float,
) {
    val ryOpen = (ry * openness).coerceAtLeast(1f)
    if (openness < 0.2f) {
        val path = Path().apply {
            moveTo(ex - rx, ey + base * 0.015f)
            quadraticTo(ex, ey - base * 0.085f, ex + rx, ey + base * 0.015f)
        }
        drawPath(path, Color.White, style = Stroke(width = (base * 0.042f).coerceAtLeast(2.2f), cap = StrokeCap.Round))
        return
    }
    // Sclera
    drawOval(
        color = Color(0xFFFAF5FF),
        topLeft = Offset(ex - rx, ey - ryOpen),
        size = Size(rx * 2f, ryOpen * 2f),
    )
    // Iris & pupil following gaze
    val irisR = min(rx, ryOpen) * 0.76f * pupilScale
    val ix = ex + gx * (base * 0.012f)
    val iy = ey + gy * (base * 0.012f)
    val irisColor = lerp(Color(0xFF5B21B6), Color(0xFF991B1B), rage)
    drawCircle(irisColor, irisR, Offset(ix, iy))
    drawCircle(Color(0xFF1A0833), irisR * 0.56f, Offset(ix, iy))
    // Gem catchlights
    drawCircle(Color.White, irisR * 0.28f, Offset(ix - irisR * 0.30f, iy - irisR * 0.30f))
    drawCircle(Color.White.copy(alpha = 0.75f), irisR * 0.14f, Offset(ix + irisR * 0.28f, iy + irisR * 0.25f))
    // Upper lash rim
    val lash = Path().apply {
        moveTo(ex - rx * 1.02f, ey - ryOpen * 0.2f)
        quadraticTo(ex, ey - ryOpen * 1.25f, ex + rx * 1.02f, ey - ryOpen * 0.2f)
    }
    drawPath(lash, Color(0xFF2B104E), style = Stroke(width = (base * 0.036f).coerceAtLeast(2f), cap = StrokeCap.Round))
    // Outer wing lash
    val ox = ex + side * rx * 0.88f
    drawLine(
        Color(0xFF2B104E),
        Offset(ox, ey - ryOpen * 0.35f),
        Offset(ox + side * rx * 0.36f, ey - ryOpen * 0.78f),
        strokeWidth = (base * 0.028f).coerceAtLeast(1.8f),
        cap = StrokeCap.Round,
    )
}

private fun DrawScope.drawOrbBrow(
    base: Float,
    side: Float,
    lift: Float,
    angle: Float,
    browBaseY: Float,
    flash: Float,
    clock: Float,
) {
    val bob = sin(clock * 2.3f + side * 1.9f) * base * 0.011f
    val by = browBaseY - lift * base * 0.085f - flash * base * 0.055f + bob
    val bx = side * base * 0.305f
    val bw = base * 0.19f
    translate(bx, by) {
        rotate(angle) {
            val path = Path().apply {
                moveTo(-bw, base * 0.02f)
                quadraticTo(0f, -base * 0.06f, bw, base * 0.01f)
            }
            drawPath(path, Color(0x882C104A), style = Stroke(width = (base * 0.052f).coerceAtLeast(3f), cap = StrokeCap.Round, join = StrokeJoin.Round))
            drawPath(path, Color(0xFFFDF7FF), style = Stroke(width = (base * 0.032f).coerceAtLeast(2f), cap = StrokeCap.Round, join = StrokeJoin.Round))
        }
    }
}

private fun DrawScope.drawOrbMouth(base: Float, smile: Float, open: Float) {
    val my = base * 0.27f
    if (open > 0.15f) {
        val w = base * 0.14f
        val h = base * 0.19f * open
        drawOval(
            color = Color(0xFF3A0F52),
            topLeft = Offset(-w, my - h * 0.4f),
            size = Size(w * 2f, h * 1.4f),
        )
        drawOval(
            color = Color(0xFFF472B6).copy(alpha = 0.8f),
            topLeft = Offset(-w * 0.55f, my + h * 0.35f),
            size = Size(w * 1.1f, h * 0.45f),
        )
        drawOval(
            color = Color.White,
            topLeft = Offset(-w, my - h * 0.4f),
            size = Size(w * 2f, h * 1.4f),
            style = Stroke(width = (base * 0.028f).coerceAtLeast(1.8f)),
        )
    } else {
        val mw = base * 0.20f
        val path = Path().apply {
            moveTo(-mw, my)
            quadraticTo(0f, my + base * smile * 1.3f, mw, my)
        }
        drawPath(path, Color.White, style = Stroke(width = (base * 0.038f).coerceAtLeast(2.2f), cap = StrokeCap.Round))
    }
}

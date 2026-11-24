package com.henny.cellium.avatar

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
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
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

private val NO_BLINK_EXPRS = setOf(
    "sleepy", "sleepy (local)", "dead", "dizzy", "flustered", "blank",
    "disgusted", "feeling cool", "derp", "in love", "love and hearts",
    "happy", "annoyed", "uwu", "chibi joy", "pepelaugh", "starstruck",
    "excited", "blushing", "smitten", "error 404", "api crash", "net crash",
    "buffering", "hypnotized", "deadpan", "sarcastic",
)

private val INTENSE_SHAKE_EXPRS = setOf(
    "angry", "rage", "baka", "shocked", "terrified", "scared",
    "heavy sobbing", "crying", "menacing", "nani",
)

private val LAUGH_BOUT = floatArrayOf(0f, 2f, 1.5f, 1.5f, 1f, 1f, 2f, 0f)
private val SOB_BOUT = floatArrayOf(0f, 2.2f, 1.4f, 0.9f, 1.8f, 0.5f, 0.2f, 0f)

private class DotParticle(
    var cx: Float,
    var cy: Float,
    var tx: Float,
    var ty: Float,
    var alpha: Float,
    val size: Float,
    var kind: AvatarKind,
    var left: Boolean,
    val idx: Int,
)

private fun sampleBout(curve: FloatArray, tSec: Float, cycleS: Float): Float {
    val n = curve.size
    val pos = ((tSec / cycleS.coerceAtLeast(0.1f)) % 1f) * n
    val idx = pos.toInt() % n
    val frac = pos - pos.toInt()
    val u = frac.pow(0.62f)
    return curve[idx] * (1f - u) + curve[(idx + 1) % n] * u
}

/**
 * Authentic Cerebellium Dot-Matrix Avatar Canvas (ported directly from cellium/ui/avatar/widget.py).
 * Never joins points into polylines — every data point is rendered as a glowing rounded dot square
 * with 20% spring morphing, harmonic breathing, eyelid fade-mask blink, touch repulsion, and talk sync.
 */
@Composable
fun DotMatrixAvatarCanvas(
    expression: AvatarExpression?,
    modifier: Modifier = Modifier,
    scale: Float = 1f,
    showGrid: Boolean = false,
    highFps: Boolean = true,
    blinkTrigger: Int = 0,
    mouthOpenness: Float = 0f,
    onPetted: (() -> Unit)? = null,
    onTapped: (() -> Unit)? = null,
) {
    val particles = remember { mutableListOf<DotParticle>() }
    var frameTick by remember { mutableLongStateOf(0L) }
    var blinkActive by remember { mutableStateOf(false) }
    var blinkHoldUntilMs by remember { mutableLongStateOf(0L) }
    var blinkOffset by remember { mutableFloatStateOf(0f) }
    var dirtCounter by remember { mutableFloatStateOf(0f) }

    var touchCanonX by remember { mutableFloatStateOf(-9999f) }
    var touchCanonY by remember { mutableFloatStateOf(-9999f) }
    var touchActiveUntilMs by remember { mutableLongStateOf(0L) }
    var lastPetCallbackMs by remember { mutableLongStateOf(0L) }

    // Plain array avoids triggering Compose MutableState writes inside Canvas draw lambda
    val canvasDims = remember { floatArrayOf(600f, 400f) }

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

    // Manual blink trigger
    LaunchedEffect(blinkTrigger) {
        if (blinkTrigger > 0) {
            blinkActive = true
            blinkHoldUntilMs = System.currentTimeMillis() + 170L
            dirtCounter = 0f
        }
    }

    // Sync particle pool on expression change (preserving live cx/cy for smooth 20% spring morphing!)
    LaunchedEffect(expression?.name, expression?.gender, expression?.points?.size) {
        val pts = expression?.points.orEmpty()
        val old = particles.toList()
        val isFirst = old.isEmpty()
        val rng = Random(20261015)
        particles.clear()
        pts.forEachIndexed { i, p ->
            val sz = rng.nextInt(5, 10).toFloat()
            val (sx, sy, sa) = when {
                !isFirst && i < old.size -> Triple(old[i].cx, old[i].cy, old[i].alpha)
                !isFirst && old.isNotEmpty() -> {
                    val d = old[i % old.size]
                    Triple(d.cx, d.cy, d.alpha)
                }
                else -> Triple(p.x, p.y, 255f)
            }
            particles.add(
                DotParticle(
                    cx = sx,
                    cy = sy,
                    tx = p.x,
                    ty = p.y,
                    alpha = sa,
                    size = sz,
                    kind = p.kind,
                    left = p.left,
                    idx = i,
                )
            )
        }
    }

    // Continuous 60fps / 30fps physics simulation loop (paused automatically in background)
    LaunchedEffect(expression, highFps, isResumed) {
        if (!isResumed) return@LaunchedEffect
        var lastFrameMs = 0L
        var passiveAccumMs = 0f
        val minStepMs = if (highFps) 20L else 36L
        val rng = Random(System.nanoTime())

        while (true) {
            withFrameMillis { nowMs ->
                if (nowMs - lastFrameMs < minStepMs) return@withFrameMillis
                val dtMs = (if (lastFrameMs == 0L) 16f else (nowMs - lastFrameMs).toFloat()).coerceIn(1f, 80f)
                lastFrameMs = nowMs

                val expr = expression ?: return@withFrameMillis
                val bl = expr.baseName.lowercase()
                val tSec = nowMs * 0.001f
                val canBlink = expr.blinkEnabled && bl !in NO_BLINK_EXPRS

                // Part 2: "Dirt in the eye" passive blink accumulator
                if (canBlink) {
                    passiveAccumMs += dtMs
                    if (passiveAccumMs >= 1000f) {
                        passiveAccumMs -= 1000f
                        dirtCounter += rng.nextFloat() * 2f + 1.2f
                    }
                    if (!blinkActive && dirtCounter >= 14f) {
                        blinkActive = true
                        blinkHoldUntilMs = System.currentTimeMillis() + 150L
                        dirtCounter = 0f
                    }
                }
                if (blinkActive && System.currentTimeMillis() >= blinkHoldUntilMs) {
                    blinkActive = false
                    dirtCounter = 0f
                }

                // Part 3: Smooth blink offset & eyelid fade-mask edge
                val targetBlink = if (blinkActive) 160f else 0f
                val blinkLerp = if ("tired" in bl) 0.07f else 0.35f
                blinkOffset += (targetBlink - blinkOffset) * blinkLerp
                if (blinkOffset < 0.3f && targetBlink == 0f) blinkOffset = 0f

                val extraEdge = when {
                    "tired" in bl -> 45f
                    listOf("annoyed", "smug", "suspicious", "sus", "focused", "sad", "doomer", "shy").any { it in bl } -> 30f
                    else -> 0f
                }
                val eyelidEdge = 150f + extraEdge + blinkOffset

                // Part 1: Breathing float, laugh/sob bouts & micro-jitter
                val breathY = sin(nowMs * 0.003f) * 8f
                val intense = INTENSE_SHAKE_EXPRS.any { it in bl }
                val jitterAmp = if (intense) 2.8f else 0.55f
                val boutDy = when {
                    listOf("laugh", "chibi joy", "pepelaugh").any { it in bl } ->
                        -sampleBout(LAUGH_BOUT, tSec, 1.35f) * 6.5f
                    listOf("sob", "crying", "copium", "doomer").any { it in bl } ->
                        sampleBout(SOB_BOUT, tSec, 1.70f) * 5.0f
                    else -> 0f
                }
                val dizzySpin = "dizzy" in bl || "hypnotized" in bl
                val touchActive = System.currentTimeMillis() <= touchActiveUntilMs
                val pts = expr.points
                val mouth = mouthOpenness.coerceIn(0f, 1f)

                for (i in particles.indices) {
                    val p = particles[i]
                    if (i < pts.size) {
                        p.tx = pts[i].x
                        p.ty = pts[i].y
                    }
                    val sideBlinks = if (p.left) expr.blinkLeft else expr.blinkRight
                    val effBlink = if (sideBlinks) blinkOffset else 0f

                    var tx = p.tx
                    var ty = p.ty + breathY + boutDy

                    // Live Mode audio-reactive mouth openness
                    if (mouth > 0.01f) {
                        when {
                            p.kind == AvatarKind.STEM && !p.left -> ty += mouth * 13f
                            p.kind == AvatarKind.BOTTOM_BAR -> ty += mouth * 10f
                            p.kind == AvatarKind.MID_BAR -> ty += mouth * 5f
                        }
                    }

                    val restingTy = ty

                    // Dizzy / Hypnotized 360-degree spin
                    if (dizzySpin && (p.kind == AvatarKind.EYELID || p.kind == AvatarKind.STEM)) {
                        val eyeCx = if (p.left) 200f else 400f
                        val eyeCy = 215f + breathY
                        val dx0 = tx - eyeCx
                        val dy0 = p.ty - 215f
                        val ang = tSec * if (p.left) 4.5f else -4.5f
                        val ca = cos(ang)
                        val sa = sin(ang)
                        tx = eyeCx + dx0 * ca - dy0 * sa
                        ty = eyeCy + dx0 * sa + dy0 * ca
                    }

                    // Prop animations (tears, sweat, rising anger steam / Zzz dust)
                    val seed = p.idx * 0.37f
                    when (p.kind) {
                        AvatarKind.TEAR -> {
                            ty += ((tSec * 44f + (if (p.left) 0f else 11f) + p.ty * 0.35f) % 28f)
                        }
                        AvatarKind.CARTOON_SWEAT -> {
                            val ph = (tSec * 0.85f + (if (p.left) 0.3f else 0f)) % 1f
                            ty += min(1f, ph * 1.45f).pow(1.6f) * 22f
                        }
                        AvatarKind.DUST -> {
                            if (listOf("angry", "annoyed", "rage", "baka", "menacing", "tsundere").any { it in bl }) {
                                val puff = (tSec * 38f + (if (p.left) 0f else 14f) + seed * 3f) % 32f
                                ty -= puff
                                tx += (if (p.left) -1f else 1f) * (puff * 0.45f)
                            } else if (listOf("sleepy", "tired", "waking").any { it in bl }) {
                                val zf = (tSec * 22f) % 26f
                                tx += zf * 0.55f
                                ty -= zf
                            }
                        }
                        else -> Unit
                    }

                    // Eyelid descent + top-to-bottom fade-mask
                    when (p.kind) {
                        AvatarKind.EYELID -> {
                            ty = min(300f, ty + effBlink)
                            p.alpha = 255f
                        }
                        AvatarKind.MID_BAR -> {
                            ty += min(effBlink, 25f)
                            p.alpha = if (effBlink > 1.5f && restingTy < eyelidEdge) {
                                (p.alpha - 80f).coerceAtLeast(0f)
                            } else {
                                (p.alpha + 80f).coerceAtMost(255f)
                            }
                        }
                        AvatarKind.STEM, AvatarKind.BOTTOM_BAR -> {
                            p.alpha = if (effBlink > 1.5f && restingTy < eyelidEdge) {
                                (p.alpha - 80f).coerceAtLeast(0f)
                            } else {
                                (p.alpha + 80f).coerceAtMost(255f)
                            }
                        }
                        AvatarKind.EYEBROW -> {
                            val dip = if (p.left) expr.leftEyebrowDip else expr.rightEyebrowDip
                            ty += min(effBlink * 0.08f, dip)
                            p.alpha = 255f
                        }
                        AvatarKind.BLUSH, AvatarKind.PERM_BLUSH -> {
                            // Subtle cheek-lift / squint response synchronized with her blink
                            ty -= effBlink * 0.075f
                            tx += (if (p.left) 1f else -1f) * (effBlink * 0.025f)
                            p.alpha = 255f
                        }
                        else -> p.alpha = 255f
                    }

                    // Touch cursor repulsion (60px canonical radius)
                    if (touchActive) {
                        val dist = hypot(touchCanonX - p.cx, touchCanonY - p.cy)
                        if (dist < 62f) {
                            p.cx -= (touchCanonX - p.cx) * 0.36f
                            ty -= (touchCanonY - ty) * 0.36f
                        }
                    }

                    // Smooth frame-rate-normalized morphing with velocity cap so pixels glide gracefully
                    val morphLerp = (1f - (1f - 0.085f).pow(dtMs / 16.67f)).coerceIn(0.03f, 0.14f)
                    val stepX = ((tx - p.cx) * morphLerp).coerceIn(-16f, 16f)
                    val stepY = ((ty - p.cy) * morphLerp).coerceIn(-16f, 16f)
                    p.cx += stepX + sin(tSec * 7.3f + seed) * jitterAmp
                    p.cy += stepY + cos(tSec * 5.9f + seed * 1.31f) * jitterAmp
                }
                frameTick = nowMs
            }
        }
    }

    Canvas(
        modifier = modifier
            .pointerInput(scale) {
                detectTapGestures {
                    blinkActive = true
                    blinkHoldUntilMs = System.currentTimeMillis() + 170L
                    dirtCounter = 0f
                    onTapped?.invoke()
                }
            }
            .pointerInput(scale) {
                detectDragGestures(
                    onDrag = { change, _ ->
                        val cw = canvasDims[0]
                        val ch = canvasDims[1]
                        val s = min(cw / 600f, ch / 400f) * scale
                        if (s > 0.001f) {
                            val ox = (cw - 600f * s) * 0.5f
                            val oy = (ch - 400f * s) * 0.5f
                            touchCanonX = (change.position.x - ox) / s
                            touchCanonY = (change.position.y - oy) / s
                            touchActiveUntilMs = System.currentTimeMillis() + 180L
                            val now = System.currentTimeMillis()
                            if (now - lastPetCallbackMs > 420L) {
                                lastPetCallbackMs = now
                                onPetted?.invoke()
                            }
                        }
                    },
                )
            },
    ) {
        // Read frameTick so Canvas invalidates cleanly each physics frame
        val unusedTick = frameTick
        if (unusedTick < 0L) return@Canvas

        canvasDims[0] = size.width
        canvasDims[1] = size.height
        val s = min(size.width / 600f, size.height / 400f) * scale
        val ox = (size.width - 600f * s) * 0.5f
        val oy = (size.height - 400f * s) * 0.5f

        if (showGrid) {
            val step = (40f * s).coerceAtLeast(18f)
            var gx = 0f
            while (gx < size.width) {
                drawLine(Color(0x18A855F7), Offset(gx, 0f), Offset(gx, size.height), strokeWidth = 1f)
                gx += step
            }
            var gy = 0f
            while (gy < size.height) {
                drawLine(Color(0x18A855F7), Offset(0f, gy), Offset(size.width, gy), strokeWidth = 1f)
                gy += step
            }
        }

        val globalAlpha = (1f - (expression?.fadeOpacity ?: 0f)).coerceIn(0f, 1f)
        for (p in particles) {
            val a = ((p.alpha / 255f) * globalAlpha).coerceIn(0f, 1f)
            if (a <= 0.01f) continue
            val cx = p.cx.coerceIn(18f, 582f)
            val cy = p.cy.coerceIn(14f, 386f)
            val px = ox + cx * s
            val py = oy + cy * s
            val sz = (p.size * s).coerceAtLeast(2.4f)
            val rad = (sz * 0.28f).coerceAtLeast(1.1f)
            val dotColor = p.kind.defaultColor.copy(alpha = a)
            // Soft outer neon halo on high-FPS mode for signature Cellium glow
            if (highFps && p.kind != AvatarKind.DUST) {
                drawRoundRect(
                    color = dotColor.copy(alpha = a * 0.22f),
                    topLeft = Offset(px - sz * 0.75f, py - sz * 0.75f),
                    size = Size(sz * 1.5f, sz * 1.5f),
                    cornerRadius = CornerRadius(rad * 1.5f, rad * 1.5f),
                )
            }
            drawRoundRect(
                color = dotColor,
                topLeft = Offset(px - sz * 0.5f, py - sz * 0.5f),
                size = Size(sz, sz),
                cornerRadius = CornerRadius(rad, rad),
            )
        }
    }
}

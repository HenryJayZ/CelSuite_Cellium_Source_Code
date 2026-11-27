package com.henny.cellium.assistant

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import com.henny.cellium.avatar.AvatarExpression
import com.henny.cellium.avatar.AvatarKind
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.ExpressionDirector
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin
import kotlin.random.Random

/**
 * Pure Android Canvas View rendering Cel's fully animated dot-matrix face for true system-wide
 * WindowManager overlays and VoiceInteractionSession.
 * Features crisp non-spiraling spring morphing, anchored blush during blinks, anti-repetition
 * mood-to-expression resolution, talking mouth modulation, tear/sweat/steam/laugh/sob motion,
 * explicit expression overrides, and pixel-scatter disintegration on Hell Pit drop.
 */
class AssistantDotFaceView(
    context: Context,
    private var accentColor: Int = Color.parseColor("#C084FC"),
) : View(context) {

    private val library: AvatarLibrary = AvatarLibrary.load(context)
    private var gender: String = "Chibi"
    private var mood: String = "idle"
    private var explicitExpressionName: String? = null
    private var resolvedMoodExpressionName: String = ExpressionDirector.pickExpressionForMood("idle")
    private var talking: Boolean = false
    private var listening: Boolean = false
    private var micReady: Boolean = false
    private var handsFree: Boolean = false

    // Disintegration animation state (Hell Pit drop)
    private var disintegrating: Boolean = false
    private var disintegrateStartMs: Long = 0L
    private val disintegrateDurationMs: Long = 560L
    private var disintegrateOnComplete: (() -> Unit)? = null
    private var disintegrateVx = FloatArray(0)
    private var disintegrateVy = FloatArray(0)
    private var disintegrateFade = FloatArray(0)

    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4.2f
    }
    private val outerHaloPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f
    }
    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(226, 10, 7, 20)
    }
    private val sleepPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D8B4FE")
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
    }
    private val rect = RectF()
    private val startMs = SystemClock.uptimeMillis()
    private var lastFrameMs = startMs
    private var animRunning = false
    private val tickerHandler = Handler(Looper.getMainLooper())
    private var manualBlinkUntilMs = 0L

    // Smooth interpolated particle coordinates (x, y) in avatar 600x400 space (zero per-frame heap churn)
    private val currentPositions = ArrayList<FloatArray>()

    private val frameRunnable = object : Runnable {
        override fun run() {
            if (!animRunning) return
            invalidate()
            tickerHandler.postDelayed(this, if (disintegrating) 16L else 33L)
        }
    }

    init {
        setWillNotDraw(false)
    }

    fun updateState(
        newMood: String = mood,
        newGender: String = gender,
        isTalking: Boolean = talking,
        isListening: Boolean = listening,
        isMicReady: Boolean = micReady,
        isHandsFree: Boolean = handsFree,
        primaryColor: Int = accentColor,
        expressionOverride: String? = explicitExpressionName,
    ) {
        val moodChanged = newMood != mood
        mood = newMood
        gender = newGender
        talking = isTalking
        listening = isListening
        micReady = isMicReady
        handsFree = isHandsFree
        accentColor = primaryColor
        if (moodChanged && expressionOverride == explicitExpressionName) {
            explicitExpressionName = null
            resolvedMoodExpressionName = ExpressionDirector.pickExpressionForMood(newMood, resolvedMoodExpressionName)
        } else {
            explicitExpressionName = expressionOverride
            if (moodChanged) {
                resolvedMoodExpressionName = ExpressionDirector.pickExpressionForMood(newMood, resolvedMoodExpressionName)
            }
        }
        invalidate()
    }

    fun setExplicitExpression(name: String?) {
        explicitExpressionName = name
        if (name != null) {
            ExpressionDirector.recordExpression(name)
        }
        invalidate()
    }

    fun triggerManualBlink() {
        manualBlinkUntilMs = SystemClock.uptimeMillis() + 210L
        invalidate()
    }

    fun startDisintegration(onComplete: () -> Unit) {
        if (disintegrating) return
        disintegrating = true
        disintegrateStartMs = SystemClock.uptimeMillis()
        disintegrateOnComplete = onComplete
        val n = currentPositions.size.coerceAtLeast(1)
        disintegrateVx = FloatArray(n)
        disintegrateVy = FloatArray(n)
        disintegrateFade = FloatArray(n)
        val rng = Random(disintegrateStartMs)
        for (i in 0 until n) {
            val pos = currentPositions.getOrNull(i)
            val dx = (pos?.get(0) ?: 300f) - 300f
            val dy = (pos?.get(1) ?: 200f) - 200f
            val angle = rng.nextFloat() * (2f * PI.toFloat())
            val burst = 120f + rng.nextFloat() * 260f
            disintegrateVx[i] = dx * 1.4f + cos(angle) * burst
            disintegrateVy[i] = dy * 1.1f + sin(angle) * burst - 90f
            disintegrateFade[i] = 0.72f + rng.nextFloat() * 0.55f
        }
        startTicker()
        invalidate()
    }

    fun resetDisintegration() {
        disintegrating = false
        disintegrateOnComplete = null
        invalidate()
    }

    private fun startTicker() {
        if (animRunning) return
        animRunning = true
        lastFrameMs = SystemClock.uptimeMillis()
        tickerHandler.removeCallbacks(frameRunnable)
        tickerHandler.post(frameRunnable)
    }

    private fun stopTicker() {
        animRunning = false
        tickerHandler.removeCallbacks(frameRunnable)
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        startTicker()
    }

    override fun onDetachedFromWindow() {
        stopTicker()
        super.onDetachedFromWindow()
    }

    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        if (visibility == VISIBLE && isAttachedToWindow) {
            startTicker()
        } else if (visibility != VISIBLE) {
            stopTicker()
        }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        if (w <= 4f || h <= 4f) return

        val nowMs = SystemClock.uptimeMillis()
        val dtMs = (nowMs - lastFrameMs).coerceIn(8L, 64L).toFloat()
        lastFrameMs = nowMs
        val elapsedSec = (nowMs - startMs) / 1000f

        val cx = w * 0.5f
        val cy = h * 0.5f
        val radius = min(w, h) * 0.45f

        val disProg = if (disintegrating) {
            ((nowMs - disintegrateStartMs).toFloat() / disintegrateDurationMs.toFloat()).coerceIn(0f, 1f)
        } else 0f

        if (disintegrating) {
            // Backing orb shrinks and fades cleanly into embers as dots burst outward
            val bgScale = (1f - disProg * 1.35f).coerceIn(0f, 1f)
            if (bgScale > 0.02f) {
                bgPaint.alpha = (226 * bgScale).toInt().coerceIn(0, 226)
                canvas.drawCircle(cx, cy, radius * bgScale, bgPaint)
                ringPaint.color = Color.argb((220 * bgScale).toInt().coerceIn(0, 220), 239, 68, 68)
                canvas.drawCircle(cx, cy, (radius - 2f) * bgScale, ringPaint)
                bgPaint.alpha = 226
            }
            val unitScale = (min(w, h) / 480f) * 1.15f
            val baseDotHalf = (3.4f * unitScale).coerceAtLeast(1.4f)
            val tSec = disProg * (disintegrateDurationMs / 1000f)
            val gravity = 520f
            for (i in currentPositions.indices) {
                if (i >= disintegrateVx.size) break
                val pos = currentPositions[i]
                val fadeRate = disintegrateFade[i]
                val alphaF = (1f - disProg * fadeRate * 1.2f).coerceIn(0f, 1f)
                if (alphaF <= 0.02f) continue
                val px = pos[0] + disintegrateVx[i] * tSec
                val py = pos[1] + disintegrateVy[i] * tSec + 0.5f * gravity * tSec * tSec
                val sx = cx + (px - 300f) * unitScale
                val sy = cy + (py - 200f) * unitScale
                val dotHalf = (baseDotHalf * (0.45f + 0.65f * alphaF)).coerceAtLeast(1.0f)
                val alphaInt = (alphaF * 255f).toInt().coerceIn(0, 255)
                val emberR = (248 * (1f - disProg * 0.1f)).toInt().coerceIn(0, 255)
                val emberG = (180 * (1f - disProg * 0.7f)).toInt().coerceIn(0, 255)
                val emberB = (255 * (1f - disProg * 0.85f)).toInt().coerceIn(0, 255)
                glowPaint.color = Color.argb((alphaInt * 0.35f).toInt(), emberR, emberG, emberB)
                canvas.drawCircle(sx, sy, dotHalf * 2.1f, glowPaint)
                dotPaint.color = Color.argb(alphaInt, emberR, emberG, emberB)
                rect.set(sx - dotHalf, sy - dotHalf, sx + dotHalf, sy + dotHalf)
                canvas.drawRoundRect(rect, dotHalf * 0.45f, dotHalf * 0.45f, dotPaint)
            }
            if (disProg >= 1f) {
                val cb = disintegrateOnComplete
                disintegrateOnComplete = null
                stopTicker()
                cb?.let { post(it) }
            }
            return
        }

        // Circular dark obsidian glass backing
        canvas.drawCircle(cx, cy, radius, bgPaint)

        // Hands-free outer cyan halo when active
        if (handsFree) {
            val haloAlpha = (145 + 75 * sin(elapsedSec * 5f)).toInt().coerceIn(70, 230)
            outerHaloPaint.color = Color.argb(haloAlpha, 56, 189, 248)
            canvas.drawCircle(cx, cy, radius + 3.5f, outerHaloPaint)
        }

        val ringColor = when {
            mood == "angry" || mood == "scared" -> {
                val a = (175 + 70 * sin(elapsedSec * 12f)).toInt().coerceIn(100, 250)
                Color.argb(a, 239, 68, 68)
            }
            mood == "relieved" -> {
                val a = (165 + 65 * sin(elapsedSec * 7f)).toInt().coerceIn(95, 240)
                Color.argb(a, 52, 211, 153)
            }
            listening && micReady -> {
                val a = (175 + 75 * sin(elapsedSec * 8f)).toInt().coerceIn(100, 250)
                Color.argb(a, 52, 211, 153)
            }
            listening && !micReady -> {
                val a = (155 + 70 * sin(elapsedSec * 6f)).toInt().coerceIn(90, 235)
                Color.argb(a, 251, 191, 36)
            }
            talking -> {
                val a = (150 + 65 * sin(elapsedSec * 11f)).toInt().coerceIn(85, 235)
                Color.argb(a, Color.red(accentColor), Color.green(accentColor), Color.blue(accentColor))
            }
            mood == "sleepy" -> Color.argb(95, 167, 139, 250)
            else -> Color.argb(145, Color.red(accentColor), Color.green(accentColor), Color.blue(accentColor))
        }
        ringPaint.color = ringColor
        canvas.drawCircle(cx, cy, radius - 2f, ringPaint)

        val baseExpr: AvatarExpression = explicitExpressionName?.let { raw ->
            val modIdx = raw.indexOf(" - ")
            if (modIdx > 0) {
                library.get(gender, raw.substring(0, modIdx), raw.substring(modIdx + 3))
            } else {
                library.get(gender, raw)
            }
        }
            ?: library.get(gender, resolvedMoodExpressionName)
            ?: library.getForMood(gender, mood)
            ?: return
        val expr = if (talking) {
            val openness = (0.35f + 0.58f * abs(sin(elapsedSec * 13.5f))).coerceIn(0f, 1f)
            AvatarLibrary.talkingExpression(baseExpr, openness)
        } else baseExpr

        val bl = expr.baseName.lowercase()
        val isIntense = mood == "angry" || mood == "scared" ||
            "scared" in bl || "fearful" in bl || "terrified" in bl || "shocked" in bl || "angry" in bl || "rage" in bl
        val isLaugh = "laugh" in bl || "chibi joy" in bl || "excited" in bl
        val isSob = "cry" in bl || "sob" in bl || "sad" in bl
        val isAngryDust = "angry" in bl || "rage" in bl || "annoyed" in bl

        val targetCount = expr.points.size
        while (currentPositions.size < targetCount) {
            val pt = expr.points[currentPositions.size]
            currentPositions.add(floatArrayOf(pt.x, pt.y))
        }
        while (currentPositions.size > targetCount) {
            currentPositions.removeAt(currentPositions.size - 1)
        }

        // Crisp, non-spiraling frame-rate normalized spring morph
        val morphAlpha = (1f - (1f - 0.22f).pow(dtMs / 16.67f)).coerceIn(0.08f, 0.36f)
        val maxStep = 22f * (dtMs / 16.67f)

        // Lively blink cycle every 3.5s (disabled when asleep) + manual studio blink
        val cyclePos = elapsedSec % 3.5f
        val manualBlinkT = if (nowMs < manualBlinkUntilMs) {
            val rem = (manualBlinkUntilMs - nowMs).toFloat() / 210f
            sin((1f - rem).coerceIn(0f, 1f) * PI).toFloat().coerceIn(0f, 1f)
        } else 0f
        val autoBlinkT = if (mood != "sleepy" && expr.blinkEnabled && cyclePos < 0.22f) {
            sin((cyclePos / 0.22f) * PI).toFloat().coerceIn(0f, 1f)
        } else 0f
        val blinkT = maxOf(autoBlinkT, manualBlinkT)

        // Visible floating breathing & micro-expression bounce (scaled for compact floating circles!)
        val breathSpeed = if (mood == "sleepy") 1.5f else 2.7f
        val breathAmp = if (mood == "sleepy") 9.5f else 7.2f
        val breathY = sin(elapsedSec * breathSpeed) * breathAmp
        val swayX = sin(elapsedSec * 1.45f) * 3.8f
        val bounceY = when {
            isLaugh -> -abs(sin(elapsedSec * 8.5f)) * 9.0f
            isSob -> sin(elapsedSec * 6.0f) * 5.0f
            talking -> sin(elapsedSec * 10.5f) * 3.2f
            else -> 0f
        }
        val unitScale = (min(w, h) / 480f) * 1.15f
        val dotHalf = (3.3f * unitScale).coerceAtLeast(1.4f)

        val rAccent = if (mood == "angry" || mood == "scared") 248 else Color.red(accentColor)
        val gAccent = if (mood == "angry" || mood == "scared") 113 else Color.green(accentColor)
        val bAccent = if (mood == "angry" || mood == "scared") 113 else Color.blue(accentColor)

        for (i in 0 until targetCount) {
            val pt = expr.points[i]
            val pos = currentPositions[i]
            val dx = ((pt.x - pos[0]) * morphAlpha).coerceIn(-maxStep, maxStep)
            val dy = ((pt.y - pos[1]) * morphAlpha).coerceIn(-maxStep, maxStep)
            pos[0] += dx
            pos[1] += dy

            var px = pos[0] + swayX
            var py = pos[1] + breathY + bounceY
            var alpha = 255

            val seed = i * 0.41f
            if (isIntense) {
                // Bounded non-cumulative fear/anger shiver (zero spiraling!)
                px += sin(elapsedSec * 28f + seed) * 2.2f
                py += cos(elapsedSec * 25f + seed) * 2.2f
            }

            when (pt.kind) {
                AvatarKind.TEAR -> {
                    py += ((elapsedSec * 46f + (if (pt.left) 0f else 12f) + pt.y * 0.35f) % 28f)
                }
                AvatarKind.CARTOON_SWEAT -> {
                    val ph = (elapsedSec * 0.95f + (if (pt.left) 0.3f else 0f)) % 1f
                    py += min(1f, ph * 1.45f).pow(1.6f) * 22f
                }
                AvatarKind.DUST -> {
                    if (isAngryDust) {
                        val puff = (elapsedSec * 38f + (if (pt.left) 0f else 14f) + seed * 3f) % 30f
                        py -= puff
                        px += (if (pt.left) -1f else 1f) * (puff * 0.42f)
                    } else if (mood == "sleepy") {
                        val zf = (elapsedSec * 22f) % 24f
                        px += zf * 0.50f
                        py -= zf
                    }
                }
                else -> Unit
            }

            if (blinkT > 0.01f) {
                val sideEnabled = if (pt.left) expr.blinkLeft else expr.blinkRight
                if (sideEnabled) {
                    val depth = if (pt.left) expr.leftDepth else expr.rightDepth
                    val dip = if (pt.left) expr.leftEyebrowDip else expr.rightEyebrowDip
                    when (pt.kind) {
                        AvatarKind.EYELID -> py += depth * blinkT
                        AvatarKind.EYEBROW -> py += dip * blinkT
                        AvatarKind.BLUSH, AvatarKind.PERM_BLUSH -> Unit
                        AvatarKind.STEM, AvatarKind.BOTTOM_BAR, AvatarKind.MID_BAR -> {
                            alpha = ((1f - blinkT * (1f - expr.fadeOpacity)) * 255f).toInt().coerceIn(0, 255)
                        }
                        else -> Unit
                    }
                }
            }

            val sx = cx + (px - 300f) * unitScale
            val sy = cy + (py - 200f) * unitScale

            val dotColor = when (pt.kind) {
                AvatarKind.BLUSH, AvatarKind.PERM_BLUSH -> Color.argb(alpha, 244, 114, 182)
                AvatarKind.TEAR -> Color.argb(alpha, 56, 189, 248)
                AvatarKind.CARTOON_SWEAT -> Color.argb(alpha, 103, 232, 249)
                AvatarKind.EYELID, AvatarKind.EYEBROW -> Color.argb(alpha, rAccent, gAccent, bAccent)
                else -> Color.argb(alpha, 248, 244, 255)
            }

            glowPaint.color = Color.argb((alpha * 0.28f).toInt(), Color.red(dotColor), Color.green(dotColor), Color.blue(dotColor))
            canvas.drawCircle(sx, sy, dotHalf * 1.85f, glowPaint)

            dotPaint.color = dotColor
            rect.set(sx - dotHalf, sy - dotHalf, sx + dotHalf, sy + dotHalf)
            canvas.drawRoundRect(rect, dotHalf * 0.45f, dotHalf * 0.45f, dotPaint)
        }

        // Animated floating "Z z z" glyphs when Cel falls asleep
        if (mood == "sleepy") {
            for (k in 0..2) {
                val phase = (elapsedSec * 0.55f + k * 0.33f) % 1f
                val alphaZ = (sin(phase * PI).toFloat() * 235f).toInt().coerceIn(0, 235)
                val zx = cx + radius * 0.32f + phase * radius * 0.42f + k * 4f
                val zy = cy - radius * 0.20f - phase * radius * 0.58f
                sleepPaint.textSize = (w * (0.11f + k * 0.025f)).coerceAtLeast(11f)
                sleepPaint.alpha = alphaZ
                canvas.drawText(if (k == 2) "Z" else "z", zx, zy, sleepPaint)
            }
        }
    }
}

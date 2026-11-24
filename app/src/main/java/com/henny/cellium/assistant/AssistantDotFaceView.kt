package com.henny.cellium.assistant

import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.os.SystemClock
import android.view.View
import com.henny.cellium.avatar.AvatarExpression
import com.henny.cellium.avatar.AvatarKind
import com.henny.cellium.avatar.AvatarLibrary
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sin

/**
 * Pure Android Canvas View rendering Cel's animated dot-matrix face for true system-wide
 * WindowManager overlays and VoiceInteractionSession (zero Compose WindowManager overhead).
 * Supports smooth per-dot morphing, hands-free halo, mic-ready ring states, sleeping Zzz glyphs,
 * angry/scared crimson pulse, blush blink sync, subtle breathing, and talking mouth modulation.
 */
class AssistantDotFaceView(
    context: Context,
    private var accentColor: Int = Color.parseColor("#C084FC"),
) : View(context) {

    private val library: AvatarLibrary = AvatarLibrary.load(context)
    private var gender: String = "Female"
    private var mood: String = "idle"
    private var talking: Boolean = false
    private var listening: Boolean = false
    private var micReady: Boolean = false
    private var handsFree: Boolean = false

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
        color = Color.argb(220, 10, 7, 20)
    }
    private val sleepPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#D8B4FE")
        typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD)
    }
    private val rect = RectF()
    private val startMs = SystemClock.uptimeMillis()
    private var lastFrameMs = startMs
    private var animRunning = false

    // Smooth interpolated particle coordinates (x, y) in avatar 600x400 space
    private val currentPositions = ArrayList<FloatArray>()

    private val frameRunnable = object : Runnable {
        override fun run() {
            if (!animRunning) return
            invalidate()
            postDelayed(this, 33L)
        }
    }

    fun updateState(
        newMood: String = mood,
        newGender: String = gender,
        isTalking: Boolean = talking,
        isListening: Boolean = listening,
        isMicReady: Boolean = micReady,
        isHandsFree: Boolean = handsFree,
        primaryColor: Int = accentColor,
    ) {
        mood = newMood
        gender = newGender
        talking = isTalking
        listening = isListening
        micReady = isMicReady
        handsFree = isHandsFree
        accentColor = primaryColor
        invalidate()
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animRunning = true
        lastFrameMs = SystemClock.uptimeMillis()
        post(frameRunnable)
    }

    override fun onDetachedFromWindow() {
        animRunning = false
        removeCallbacks(frameRunnable)
        super.onDetachedFromWindow()
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

        // Circular dark obsidian glass backing
        canvas.drawCircle(cx, cy, radius, bgPaint)

        // Hands-free outer cyan halo when active
        if (handsFree) {
            val haloAlpha = (145 + 75 * sin(elapsedSec * 5f)).toInt().coerceIn(70, 230)
            outerHaloPaint.color = Color.argb(haloAlpha, 56, 189, 248)
            canvas.drawCircle(cx, cy, radius + 3.5f, outerHaloPaint)
        }

        // Ring color reflects exact state:
        // - Angry / Scared: fiery crimson pulse
        // - Listening & Mic Ready: vivid emerald pulse
        // - Listening & Starting Mic: warm amber pulse
        // - Talking: accent pulse
        // - Sleepy: muted soft violet
        val ringColor = when {
            mood == "angry" || mood == "scared" -> {
                val a = (175 + 70 * sin(elapsedSec * 12f)).toInt().coerceIn(100, 250)
                Color.argb(a, 239, 68, 68)
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
            else -> Color.argb(135, Color.red(accentColor), Color.green(accentColor), Color.blue(accentColor))
        }
        ringPaint.color = ringColor
        canvas.drawCircle(cx, cy, radius - 2f, ringPaint)

        val baseExpr: AvatarExpression = library.getForMood(gender, mood) ?: return
        val expr = if (talking) {
            val openness = (0.35f + 0.55f * abs(sin(elapsedSec * 12f))).coerceIn(0f, 1f)
            AvatarLibrary.talkingExpression(baseExpr, openness)
        } else baseExpr

        // Keep smooth per-dot positions synced with expression point count
        val targetCount = expr.points.size
        while (currentPositions.size < targetCount) {
            val pt = expr.points[currentPositions.size]
            currentPositions.add(floatArrayOf(pt.x, pt.y))
        }
        while (currentPositions.size > targetCount) {
            currentPositions.removeAt(currentPositions.size - 1)
        }

        // Frame-rate normalized gentle morph so pixels glide smoothly instead of whipping
        val morphAlpha = (1f - (1f - 0.11f).pow(dtMs / 16.67f)).coerceIn(0.05f, 0.22f)
        val maxStep = 14f * (dtMs / 16.67f)

        // Natural blink cycle every 4.2s (disabled when asleep)
        val cyclePos = elapsedSec % 4.2f
        val blinkT = if (mood != "sleepy" && expr.blinkEnabled && cyclePos < 0.24f) {
            sin((cyclePos / 0.24f) * PI).toFloat().coerceIn(0f, 1f)
        } else 0f

        val breathSpeed = if (mood == "sleepy") 1.1f else 2.1f
        val breathAmp = if (mood == "sleepy") 3.2f else 2.2f
        val breathY = sin(elapsedSec * breathSpeed) * breathAmp
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

            var py = pos[1] + breathY
            val px = pos[0]
            var alpha = 255
            if (blinkT > 0.01f) {
                val sideEnabled = if (pt.left) expr.blinkLeft else expr.blinkRight
                if (sideEnabled) {
                    val depth = if (pt.left) expr.leftDepth else expr.rightDepth
                    val dip = if (pt.left) expr.leftEyebrowDip else expr.rightEyebrowDip
                    when (pt.kind) {
                        AvatarKind.EYELID, AvatarKind.BLUSH, AvatarKind.PERM_BLUSH -> py += depth * blinkT
                        AvatarKind.EYEBROW -> py += dip * blinkT
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
                AvatarKind.EYELID, AvatarKind.EYEBROW -> Color.argb(alpha, rAccent, gAccent, bAccent)
                else -> Color.argb(alpha, 248, 244, 255)
            }

            glowPaint.color = Color.argb((alpha * 0.26f).toInt(), Color.red(dotColor), Color.green(dotColor), Color.blue(dotColor))
            canvas.drawCircle(sx, sy, dotHalf * 1.8f, glowPaint)

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

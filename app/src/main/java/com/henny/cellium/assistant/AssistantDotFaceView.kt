package com.henny.cellium.assistant

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.os.SystemClock
import android.view.View
import com.henny.cellium.avatar.AvatarExpression
import com.henny.cellium.avatar.AvatarKind
import com.henny.cellium.avatar.AvatarLibrary
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.min
import kotlin.math.sin

/**
 * Pure Android Canvas View rendering Cel's animated dot-matrix face for true system-wide
 * WindowManager overlays and VoiceInteractionSession (zero Compose WindowManager overhead).
 * Supports mood switching, blush blink sync, subtle breathing, and talking mouth modulation.
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

    private val dotPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4f
    }
    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = Color.argb(215, 10, 7, 20)
    }
    private val rect = RectF()
    private val startMs = SystemClock.uptimeMillis()
    private var animRunning = false

    private val frameRunnable = object : Runnable {
        override fun run() {
            if (!animRunning) return
            invalidate()
            postDelayed(this, 33L) // ~30fps ultra-lightweight overlay animation
        }
    }

    fun updateState(
        newMood: String = mood,
        newGender: String = gender,
        isTalking: Boolean = talking,
        isListening: Boolean = listening,
        primaryColor: Int = accentColor,
    ) {
        mood = newMood
        gender = newGender
        talking = isTalking
        listening = isListening
        accentColor = primaryColor
        invalidate()
    }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        animRunning = true
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

        val cx = w * 0.5f
        val cy = h * 0.5f
        val radius = min(w, h) * 0.46f

        val elapsedSec = (SystemClock.uptimeMillis() - startMs) / 1000f
        // Circular dark obsidian glass backing
        canvas.drawCircle(cx, cy, radius, bgPaint)

        // Subtle pulse ring when listening or talking
        val ringAlpha = when {
            listening -> (165 + 75 * sin(elapsedSec * 7f)).toInt().coerceIn(80, 245)
            talking -> (150 + 60 * sin(elapsedSec * 11f)).toInt().coerceIn(80, 230)
            else -> 130
        }
        ringPaint.color = Color.argb(
            ringAlpha,
            Color.red(accentColor),
            Color.green(accentColor),
            Color.blue(accentColor),
        )
        canvas.drawCircle(cx, cy, radius - 2f, ringPaint)

        val baseExpr: AvatarExpression = library.getForMood(gender, mood) ?: return
        val expr = if (talking) {
            val openness = (0.35f + 0.55f * abs(sin(elapsedSec * 12f))).coerceIn(0f, 1f)
            AvatarLibrary.talkingExpression(baseExpr, openness)
        } else baseExpr

        // Natural blink cycle every 4.2s
        val cyclePos = elapsedSec % 4.2f
        val blinkT = if (expr.blinkEnabled && cyclePos < 0.24f) {
            sin((cyclePos / 0.24f) * PI).toFloat().coerceIn(0f, 1f)
        } else 0f

        val breathY = sin(elapsedSec * 2.1f) * 2.2f
        val unitScale = (min(w, h) / 480f) * 1.18f
        val dotHalf = (3.4f * unitScale).coerceAtLeast(1.4f)

        val rAccent = Color.red(accentColor)
        val gAccent = Color.green(accentColor)
        val bAccent = Color.blue(accentColor)

        for (pt in expr.points) {
            var py = pt.y + breathY
            val px = pt.x
            var alpha = 255
            if (blinkT > 0.01f) {
                val sideEnabled = if (pt.left) expr.blinkLeft else expr.blinkRight
                if (sideEnabled) {
                    val depth = if (pt.left) expr.leftDepth else expr.rightDepth
                    val dip = if (pt.left) expr.leftEyebrowDip else expr.rightEyebrowDip
                    when (pt.kind) {
                        AvatarKind.EYELID, AvatarKind.BLUSH, AvatarKind.PERM_BLUSH -> py += depth * blinkT
                        AvatarKind.EYEBROW -> py += dip * blinkT
                        AvatarKind.STEM, AvatarKind.BOTTOM_BAR, AvatarKind.MID_BAR -> alpha = ((1f - blinkT * (1f - expr.fadeOpacity)) * 255f).toInt().coerceIn(0, 255)
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

            glowPaint.color = Color.argb((alpha * 0.28f).toInt(), Color.red(dotColor), Color.green(dotColor), Color.blue(dotColor))
            canvas.drawCircle(sx, sy, dotHalf * 1.85f, glowPaint)

            dotPaint.color = dotColor
            rect.set(sx - dotHalf, sy - dotHalf, sx + dotHalf, sy + dotHalf)
            canvas.drawRoundRect(rect, dotHalf * 0.45f, dotHalf * 0.45f, dotPaint)
        }
    }
}

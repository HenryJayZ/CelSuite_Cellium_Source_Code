package com.henny.cellium.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.SoundPool
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.henny.cellium.R
import java.util.concurrent.ConcurrentHashMap
import kotlin.random.Random

/**
 * Upgraded Audio & Haptics Engine for Cel.Cellium v2611.21.0.
 * Uses USAGE_MEDIA so UI chimes, Animalese chirps, and send/receive sounds remain reliably
 * audible on Samsung/Pixel/Xiaomi devices (where USAGE_ASSISTANCE_SONIFICATION is often muted).
 * Includes crisp tactile VibrationEffect haptics for every interaction.
 */
class CelliumSoundEngine(context: Context) {
    private val appCtx = context.applicationContext
    private val soundPool: SoundPool
    private val loadedIds = ConcurrentHashMap<Int, Boolean>()

    private val popId: Int
    private val sendId: Int
    private val recvId: Int
    private val clickId: Int
    private val openId: Int
    private val acNotes: IntArray

    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        (appCtx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        appCtx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    private val fallbackTone: ToneGenerator? = runCatching {
        ToneGenerator(AudioManager.STREAM_MUSIC, 38)
    }.getOrNull()

    @Volatile var enabled: Boolean = true
    @Volatile var animaleseEnabled: Boolean = true
    @Volatile var hapticsEnabled: Boolean = true
    @Volatile var masterVolume: Float = 0.80f

    init {
        val attrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        soundPool = SoundPool.Builder()
            .setMaxStreams(8)
            .setAudioAttributes(attrs)
            .build()
        soundPool.setOnLoadCompleteListener { _, sampleId, status ->
            if (status == 0) loadedIds[sampleId] = true
        }

        popId = soundPool.load(appCtx, R.raw.cerebrium_pop, 1)
        sendId = soundPool.load(appCtx, R.raw.cerebrium_send, 1)
        recvId = soundPool.load(appCtx, R.raw.cerebrium_recv, 1)
        clickId = soundPool.load(appCtx, R.raw.cerebrium_click, 1)
        openId = soundPool.load(appCtx, R.raw.cerebrium_open, 1)
        acNotes = intArrayOf(
            soundPool.load(appCtx, R.raw.ac_note_0, 1),
            soundPool.load(appCtx, R.raw.ac_note_2, 1),
            soundPool.load(appCtx, R.raw.ac_note_4, 1),
            soundPool.load(appCtx, R.raw.ac_note_6, 1),
            soundPool.load(appCtx, R.raw.ac_note_8, 1),
            soundPool.load(appCtx, R.raw.ac_note_10, 1),
        )
    }

    fun playPop() {
        hapticTick()
        play(popId, 0.88f, 1.0f, ToneGenerator.TONE_PROP_BEEP)
    }

    fun playSend() {
        hapticClick()
        play(sendId, 0.85f, 1.04f, ToneGenerator.TONE_PROP_ACK)
    }

    fun playRecv() {
        hapticDoubleClick()
        play(recvId, 0.85f, 1.0f, ToneGenerator.TONE_PROP_BEEP2)
    }

    fun playClick() {
        hapticTick()
        play(clickId, 0.65f, 1.0f, null)
    }

    fun playOpen() {
        hapticClick()
        play(openId, 0.80f, 1.0f, ToneGenerator.TONE_PROP_PROMPT)
    }

    fun playAnimalesePurr() {
        hapticTick()
        if (!enabled || !animaleseEnabled || acNotes.isEmpty()) return
        val note = acNotes[Random.nextInt(acNotes.size)]
        val rate = 0.92f + Random.nextFloat() * 0.24f
        val vol = (0.62f * masterVolume).coerceIn(0f, 1f)
        if (loadedIds[note] == true) {
            soundPool.play(note, vol, vol, 1, 0, rate)
        }
    }

    fun playAnimaleseChirp(charIndex: Int) {
        if (!enabled || !animaleseEnabled || acNotes.isEmpty()) return
        val note = acNotes[charIndex % acNotes.size]
        val vol = (0.36f * masterVolume).coerceIn(0f, 1f)
        if (loadedIds[note] == true) {
            soundPool.play(note, vol, vol, 1, 0, 1.06f)
        }
    }

    fun hapticTick() {
        if (!hapticsEnabled) return
        vibrateEffect(VibrationEffect.EFFECT_TICK, 10L, 48)
    }

    fun hapticClick() {
        if (!hapticsEnabled) return
        vibrateEffect(VibrationEffect.EFFECT_CLICK, 16L, 85)
    }

    fun hapticDoubleClick() {
        if (!hapticsEnabled) return
        vibrateEffect(VibrationEffect.EFFECT_DOUBLE_CLICK, 24L, 110)
    }

    fun hapticHeavy() {
        if (!hapticsEnabled) return
        vibrateEffect(VibrationEffect.EFFECT_HEAVY_CLICK, 32L, 150)
    }

    private fun vibrateEffect(predefinedEffect: Int, fallbackMs: Long, fallbackAmp: Int) {
        val v = vibrator ?: return
        if (!v.hasVibrator()) return
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                v.vibrate(VibrationEffect.createPredefined(predefinedEffect))
            } else {
                v.vibrate(VibrationEffect.createOneShot(fallbackMs, fallbackAmp))
            }
        }
    }

    private fun play(id: Int, baseVol: Float, rate: Float, fallbackToneType: Int?) {
        if (!enabled || id == 0) return
        val vol = (baseVol * masterVolume).coerceIn(0f, 1f)
        if (vol <= 0.01f) return
        if (loadedIds[id] == true) {
            soundPool.play(id, vol, vol, 1, 0, rate)
        } else if (fallbackToneType != null) {
            runCatching { fallbackTone?.startTone(fallbackToneType, 45) }
        }
    }

    fun release() {
        runCatching { soundPool.release() }
        runCatching { fallbackTone?.release() }
    }
}

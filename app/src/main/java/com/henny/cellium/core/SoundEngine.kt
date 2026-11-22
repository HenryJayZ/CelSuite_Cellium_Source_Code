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
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

/**
 * Upgraded Audio & Haptics Engine for Cel.Cellium.
 * Synthesizes authentic high-clarity PCM WAV banks in app cache for:
 *  - "animal_crossing": Animalese formant-filtered vowel chirps mapped deterministically per letter
 *  - "scratchin_melodii": Funky rhythmic vocal-chop & turntable groove blips on a pentatonic scale
 * Zero allocations inside playback hot path!
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

    // Synthesized high-clarity sound banks
    private val animaleseBank = IntArray(8)
    private val melodiiBank = IntArray(8)

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
    @Volatile var typingSoundStyle: String = "animal_crossing" // "animal_crossing" | "scratchin_melodii"
    @Volatile var hapticsEnabled: Boolean = true
    @Volatile var masterVolume: Float = 0.80f

    @Volatile private var lastChirpMs: Long = 0L

    init {
        val attrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        soundPool = SoundPool.Builder()
            .setMaxStreams(10)
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

        buildSynthesizedBanks()
    }

    private fun buildSynthesizedBanks() {
        val cacheDir = File(appCtx.cacheDir, "cel_sfx_v2").apply { mkdirs() }

        // 1. Animal Crossing Animalese: warm high-pitched formant vowel syllabic chirps (520–860 Hz)
        val acBaseFreqs = floatArrayOf(523.25f, 587.33f, 659.25f, 698.46f, 783.99f, 880.00f, 622.25f, 739.99f)
        val acFormants = floatArrayOf(1450f, 1820f, 2240f, 1650f, 2050f, 2400f, 1720f, 1960f)
        for (i in acBaseFreqs.indices) {
            val wavFile = File(cacheDir, "animalese_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeAnimaleseSyllable(acBaseFreqs[i], acFormants[i], durationMs = 54))
            }
            animaleseBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        }

        // 2. Scratchin' Melodii: bouncy funk pentatonic vocal-chop synth + crisp scratch transient
        val melodiiFreqs = floatArrayOf(392.00f, 440.00f, 493.88f, 587.33f, 659.25f, 783.99f, 523.25f, 698.46f)
        for (i in melodiiFreqs.indices) {
            val wavFile = File(cacheDir, "melodii_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeMelodiiChop(melodiiFreqs[i], i % 2 == 0, durationMs = 62))
            }
            melodiiBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        }
    }

    private fun synthesizeAnimaleseSyllable(f0: Float, formant: Float, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        var phase0 = 0.0
        var phaseF = 0.0
        for (i in 0 until n) {
            val t = i.toFloat() / n.toFloat()
            // Fast cute upward pitch scoop like Villager Animalese
            val pitchMod = 1.0f + 0.14f * sin(t * PI.toFloat())
            val freq = f0 * pitchMod
            phase0 += (2.0 * PI * freq) / sr
            phaseF += (2.0 * PI * formant) / sr

            // Soft vocal glottal pulse + nasal formant resonance
            val glottal = (sin(phase0) * 0.62 + sin(phase0 * 2.0) * 0.26 + sin(phase0 * 3.0) * 0.12)
            val vowel = sin(phaseF) * (0.45 + 0.55 * sin(phase0))
            val attack = (t / 0.12f).coerceIn(0f, 1f)
            val release = ((1f - t) / 0.35f).coerceIn(0f, 1f)
            val env = attack * release
            val sample = ((glottal * 0.68 + vowel * 0.32) * env * 0.72 * Short.MAX_VALUE)
                .toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = sample.toShort()
        }
        return out
    }

    private fun synthesizeMelodiiChop(f0: Float, upwardScratch: Boolean, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        var phase = 0.0
        var subPhase = 0.0
        for (i in 0 until n) {
            val t = i.toFloat() / n.toFloat()
            // Funky DJ scratch pitch glide at attack -> locked groove chord
            val glide = if (t < 0.22f) {
                val u = t / 0.22f
                if (upwardScratch) (0.72f + 0.34f * u) else (1.28f - 0.28f * u)
            } else {
                1.0f + 0.025f * sin(t * 24f)
            }
            phase += (2.0 * PI * f0 * glide) / sr
            subPhase += (2.0 * PI * (f0 * 0.5f) * glide) / sr

            // Punchy rhodes/vocal-chop waveform with crisp percussive transient
            val body = sin(phase) * 0.55 + sin(phase * 2.0) * 0.25 + sin(phase * 3.0) * 0.10 + sin(subPhase) * 0.22
            val transient = if (t < 0.08f) sin(phase * 5.2) * (1f - t / 0.08f) * 0.35 else 0.0
            val env = (t / 0.06f).coerceIn(0f, 1f) * exp((-3.2 * t)).toFloat()
            val sample = ((body + transient) * env * 0.80 * Short.MAX_VALUE)
                .toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = sample.toShort()
        }
        return out
    }

    private fun writeWav(file: File, pcm: ShortArray) {
        val sr = 22050
        val dataSize = pcm.size * 2
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray())
            putInt(36 + dataSize)
            put("WAVE".toByteArray())
            put("fmt ".toByteArray())
            putInt(16) // PCM chunk size
            putShort(1) // PCM format
            putShort(1) // Mono
            putInt(sr)
            putInt(sr * 2)
            putShort(2)
            putShort(16)
            put("data".toByteArray())
            putInt(dataSize)
        }.array()
        val dataBuf = ByteBuffer.allocate(dataSize).order(ByteOrder.LITTLE_ENDIAN)
        for (s in pcm) dataBuf.putShort(s)
        FileOutputStream(file).use { fos ->
            fos.write(header)
            fos.write(dataBuf.array())
        }
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
        if (!enabled || !animaleseEnabled) return
        val bank = if (typingSoundStyle == "scratchin_melodii") melodiiBank else animaleseBank
        val note = bank[Random.nextInt(bank.size)]
        val rate = 0.96f + Random.nextFloat() * 0.16f
        val vol = (0.64f * masterVolume).coerceIn(0f, 1f)
        if (note != 0 && loadedIds[note] == true) {
            soundPool.play(note, vol, vol, 1, 0, rate)
        }
    }

    /**
     * Plays a crisp Animal Crossing Animalese or Scratchin' Melodii typing syllable.
     * Throttled to natural speech cadence (~68ms) so rapid token streams sound musical, never noisy!
     */
    fun playAnimaleseChirp(charCodeOrIndex: Int, isQuestion: Boolean = false) {
        if (!enabled || !animaleseEnabled) return
        val now = System.currentTimeMillis()
        val minInterval = if (typingSoundStyle == "scratchin_melodii") 82L else 64L
        if (now - lastChirpMs < minInterval) return
        lastChirpMs = now

        val bank = if (typingSoundStyle == "scratchin_melodii") melodiiBank else animaleseBank
        val idx = (charCodeOrIndex.coerceAtLeast(0)) % bank.size
        val note = bank[idx]
        val baseRate = if (typingSoundStyle == "scratchin_melodii") {
            0.96f + ((charCodeOrIndex % 5) * 0.04f)
        } else {
            0.94f + ((charCodeOrIndex % 7) * 0.035f)
        }
        val rate = (if (isQuestion) baseRate * 1.14f else baseRate).coerceIn(0.7f, 1.45f)
        val vol = (0.46f * masterVolume).coerceIn(0f, 1f)
        if (note != 0 && loadedIds[note] == true) {
            soundPool.play(note, vol, vol, 1, 0, rate)
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

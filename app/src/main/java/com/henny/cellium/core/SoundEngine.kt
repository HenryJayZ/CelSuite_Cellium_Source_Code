package com.henny.cellium.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
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
import java.util.concurrent.Executors
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

data class StartupSoundPreset(
    val id: String,
    val label: String,
    val vibe: String,
    val notesHz: FloatArray,
    val spacingSec: Float,
    val decayRate: Float,
    val harmonic2: Float,
    val harmonic3: Float,
    val durationMs: Int,
    val waveform: String = "sine", // "sine", "bell", "pluck", "warm", "chip"
)

/**
 * Upgraded Audio & Haptics Engine for Cel.Cellium:
 *  - Default typing & synth voice is "scratchin_melodii" ("Groove Synth")
 *  - True wide pitch support (0.25x..2.50x) using dual-octave SoundPool banks so SoundPool's
 *    hardware 0.5x..2.0x rate clamp never clips extreme low or high pitches!
 *  - 5 distinct Synth Voice styles for ENGINE_SYNTH (Groove Synth, Cozy Chatter, Crystal Bell, Retro Bit, Lo-Fi Keys)
 *  - 22 pleasant, gentle, non-loud synthesized Start-up Sound presets + custom audio file playback +
 *    preset cache deletion to save storage!
 *  - All SoundPool / MediaPlayer / Vibrator calls dispatch on a single background executor for 0ms UI lag.
 */
class CelliumSoundEngine(context: Context) {
    private val appCtx = context.applicationContext
    private val soundPool: SoundPool
    private val loadedIds = ConcurrentHashMap<Int, Boolean>()
    private val startupSoundPoolIds = ConcurrentHashMap<String, Int>()
    private val sfxExecutor = Executors.newSingleThreadExecutor { r ->
        Thread(r, "cel-sfx-worker").apply { isDaemon = true }
    }

    @Volatile private var popId: Int = 0
    @Volatile private var sendId: Int = 0
    @Volatile private var recvId: Int = 0
    @Volatile private var clickId: Int = 0
    @Volatile private var openId: Int = 0
    @Volatile private var startupMediaPlayer: MediaPlayer? = null

    // Dual-octave banks for true 0.25x..2.50x pitch range without SoundPool clamping!
    private val animaleseBank = IntArray(8)
    private val animaleseLowBank = IntArray(8)
    private val melodiiBank = IntArray(8)
    private val melodiiLowBank = IntArray(8)
    private val crystalBank = IntArray(8)
    private val retroBank = IntArray(8)
    private val lofiBank = IntArray(8)

    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        (appCtx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        appCtx.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    @Volatile private var fallbackTone: ToneGenerator? = null

    @Volatile var enabled: Boolean = true
    @Volatile var animaleseEnabled: Boolean = true
    @Volatile var typingSoundStyle: String = "scratchin_melodii" // Default: Groove Synth!
    @Volatile var typingSoundPitch: Float = 1.0f // 0.25f..2.50f
    @Volatile var hapticsEnabled: Boolean = true
    @Volatile var masterVolume: Float = 0.80f
    @Volatile var startupSoundId: String = "soft_celesta"
    @Volatile var startupSoundCustomPath: String = ""
    @Volatile var startupSoundShuffleEnabled: Boolean = false
    @Volatile var startupSoundExcludedIds: Set<String> = emptySet()
    @Volatile var deletedStartupSoundIds: Set<String> = emptySet()
    @Volatile private var lastShuffledStartupId: String = ""

    @Volatile private var lastChirpMs: Long = 0L

    companion object {
        val STARTUP_SOUND_PRESETS: List<StartupSoundPreset> = listOf(
            StartupSoundPreset("soft_celesta", "Soft Celesta", "Gentle & airy", floatArrayOf(523.25f, 659.25f, 783.99f, 1046.50f), 0.065f, 6.2f, 0.16f, 0.05f, 440, "sine"),
            StartupSoundPreset("glass_drop", "Glass Drop", "Clean water droplet", floatArrayOf(783.99f, 1174.66f), 0.055f, 9.5f, 0.20f, 0.08f, 320, "bell"),
            StartupSoundPreset("velvet_harp", "Velvet Harp", "Warm mellow arpeggio", floatArrayOf(392.00f, 493.88f, 587.33f, 783.99f), 0.060f, 5.5f, 0.18f, 0.06f, 480, "pluck"),
            StartupSoundPreset("lofi_bell", "Lo-Fi Bell", "Cozy Rhodes chord", floatArrayOf(349.23f, 440.00f, 523.25f, 659.25f), 0.045f, 4.8f, 0.22f, 0.04f, 460, "warm"),
            StartupSoundPreset("cyber_chime", "Cyber Chime", "Sleek sci-fi wake", floatArrayOf(440.00f, 659.25f, 880.00f), 0.050f, 7.2f, 0.24f, 0.10f, 360, "sine"),
            StartupSoundPreset("dewdrop", "Dewdrop", "Minimal soft ping", floatArrayOf(659.25f, 987.77f), 0.060f, 8.8f, 0.12f, 0.03f, 300, "sine"),
            StartupSoundPreset("starlight_arp", "Starlight Arp", "Twinkling major-9", floatArrayOf(523.25f, 659.25f, 783.99f, 987.77f, 1174.66f), 0.052f, 6.4f, 0.18f, 0.07f, 480, "bell"),
            StartupSoundPreset("warm_marimba", "Warm Marimba", "Woody gentle pop", floatArrayOf(392.00f, 523.25f, 659.25f), 0.058f, 8.0f, 0.14f, 0.03f, 350, "pluck"),
            StartupSoundPreset("crystal_pluck", "Crystal Pluck", "Crisp kalimba spark", floatArrayOf(587.33f, 880.00f, 1174.66f), 0.055f, 7.8f, 0.22f, 0.09f, 380, "pluck"),
            StartupSoundPreset("breeze_pad", "Breeze Pad", "Calm ambient swell", floatArrayOf(293.66f, 440.00f, 554.37f), 0.025f, 4.2f, 0.12f, 0.02f, 480, "warm"),
            StartupSoundPreset("cozy_kalimba", "Cozy Kalimba", "Soft thumb piano", floatArrayOf(440.00f, 554.37f, 659.25f, 880.00f), 0.062f, 7.5f, 0.18f, 0.05f, 420, "pluck"),
            StartupSoundPreset("neon_blip", "Neon Blip", "Playful synth hop", floatArrayOf(493.88f, 739.99f, 987.77f), 0.042f, 9.2f, 0.28f, 0.12f, 310, "chip"),
            StartupSoundPreset("silk_chord", "Silk Chord", "Dreamy maj7 bloom", floatArrayOf(329.63f, 415.30f, 493.88f, 622.25f), 0.030f, 4.6f, 0.14f, 0.03f, 470, "warm"),
            StartupSoundPreset("dream_box", "Dream Box", "Delicate music box", floatArrayOf(659.25f, 783.99f, 1046.50f, 1318.51f), 0.058f, 7.4f, 0.20f, 0.08f, 430, "bell"),
            StartupSoundPreset("aura_ping", "Aura Ping", "Zen harmonic bowl", floatArrayOf(432.00f, 648.00f), 0.040f, 4.5f, 0.16f, 0.05f, 460, "bell"),
            StartupSoundPreset("echo_flute", "Echo Flute", "Soft airy breath", floatArrayOf(587.33f, 783.99f, 880.00f), 0.070f, 5.8f, 0.10f, 0.02f, 420, "warm"),
            StartupSoundPreset("twilight_bell", "Twilight Bell", "Evening chime", floatArrayOf(392.00f, 587.33f, 739.99f), 0.065f, 5.6f, 0.22f, 0.06f, 440, "bell"),
            StartupSoundPreset("mint_spark", "Mint Spark", "Fresh bright triad", floatArrayOf(523.25f, 659.25f, 987.77f), 0.045f, 8.2f, 0.18f, 0.06f, 340, "sine"),
            StartupSoundPreset("cloud_bloom", "Cloud Bloom", "Pillow-soft lift", floatArrayOf(349.23f, 523.25f, 698.46f), 0.055f, 5.2f, 0.12f, 0.03f, 430, "warm"),
            StartupSoundPreset("retro_coin", "Retro Spark", "Cute 8-bit chirp", floatArrayOf(587.33f, 880.00f), 0.055f, 8.5f, 0.30f, 0.14f, 290, "chip"),
            StartupSoundPreset("mist_pulse", "Mist Pulse", "Subtle low pulse", floatArrayOf(261.63f, 392.00f, 523.25f), 0.050f, 6.0f, 0.15f, 0.04f, 390, "warm"),
            StartupSoundPreset("quiet_click", "Whisper Tap", "Ultra-subtle click", floatArrayOf(740.00f, 987.77f), 0.030f, 13.5f, 0.10f, 0.02f, 190, "pluck"),
        )

        fun findStartupPreset(id: String): StartupSoundPreset =
            STARTUP_SOUND_PRESETS.firstOrNull { it.id == id } ?: STARTUP_SOUND_PRESETS.first()
    }

    init {
        val attrs = AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
            .build()
        soundPool = SoundPool.Builder()
            .setMaxStreams(12)
            .setAudioAttributes(attrs)
            .build()
        soundPool.setOnLoadCompleteListener { _, sampleId, status ->
            if (status == 0) loadedIds[sampleId] = true
        }

        sfxExecutor.execute {
            popId = runCatching { soundPool.load(appCtx, R.raw.cerebrium_pop, 1) }.getOrDefault(0)
            sendId = runCatching { soundPool.load(appCtx, R.raw.cerebrium_send, 1) }.getOrDefault(0)
            recvId = runCatching { soundPool.load(appCtx, R.raw.cerebrium_recv, 1) }.getOrDefault(0)
            clickId = runCatching { soundPool.load(appCtx, R.raw.cerebrium_click, 1) }.getOrDefault(0)
            openId = runCatching { soundPool.load(appCtx, R.raw.cerebrium_open, 1) }.getOrDefault(0)
            fallbackTone = runCatching { ToneGenerator(AudioManager.STREAM_MUSIC, 34) }.getOrNull()
            buildSynthesizedBanks()
        }
    }

    private fun startupCacheDir(): File = File(appCtx.cacheDir, "cel_startup_v1").apply { mkdirs() }

    private fun buildSynthesizedBanks() {
        val cacheDir = File(appCtx.cacheDir, "cel_sfx_v4").apply { mkdirs() }

        // 1. Cozy Chatter (normal + low octave for wide pitch)
        val acBaseFreqs = floatArrayOf(523.25f, 587.33f, 659.25f, 698.46f, 783.99f, 880.00f, 622.25f, 739.99f)
        val acFormants = floatArrayOf(1450f, 1820f, 2240f, 1650f, 2050f, 2400f, 1720f, 1960f)
        for (i in acBaseFreqs.indices) {
            val wavFile = File(cacheDir, "animalese_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeAnimaleseSyllable(acBaseFreqs[i], acFormants[i], durationMs = 54))
            }
            animaleseBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)

            val lowFile = File(cacheDir, "animalese_low_$i.wav")
            if (!lowFile.exists()) {
                writeWav(lowFile, synthesizeAnimaleseSyllable(acBaseFreqs[i] * 0.5f, acFormants[i] * 0.72f, durationMs = 60))
            }
            animaleseLowBank[i] = runCatching { soundPool.load(lowFile.absolutePath, 1) }.getOrDefault(0)
        }

        // 2. Groove Synth (normal + low octave for wide pitch)
        val melodiiFreqs = floatArrayOf(392.00f, 440.00f, 493.88f, 587.33f, 659.25f, 783.99f, 523.25f, 698.46f)
        for (i in melodiiFreqs.indices) {
            val wavFile = File(cacheDir, "melodii_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeMelodiiChop(melodiiFreqs[i], i % 2 == 0, durationMs = 62))
            }
            melodiiBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)

            val lowFile = File(cacheDir, "melodii_low_$i.wav")
            if (!lowFile.exists()) {
                writeWav(lowFile, synthesizeMelodiiChop(melodiiFreqs[i] * 0.5f, i % 2 == 0, durationMs = 68))
            }
            melodiiLowBank[i] = runCatching { soundPool.load(lowFile.absolutePath, 1) }.getOrDefault(0)
        }

        // 3. Crystal Bell synth voice bank
        val crystalFreqs = floatArrayOf(659.25f, 783.99f, 880.00f, 987.77f, 1046.50f, 1174.66f, 1318.51f, 739.99f)
        for (i in crystalFreqs.indices) {
            val wavFile = File(cacheDir, "crystal_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeCrystalTone(crystalFreqs[i], durationMs = 74))
            }
            crystalBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        }

        // 4. Retro Bit synth voice bank
        val retroFreqs = floatArrayOf(329.63f, 392.00f, 440.00f, 523.25f, 587.33f, 659.25f, 783.99f, 493.88f)
        for (i in retroFreqs.indices) {
            val wavFile = File(cacheDir, "retro_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeRetroTone(retroFreqs[i], durationMs = 52))
            }
            retroBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        }

        // 5. Lo-Fi Keys synth voice bank
        val lofiFreqs = floatArrayOf(293.66f, 329.63f, 392.00f, 440.00f, 493.88f, 523.25f, 587.33f, 349.23f)
        for (i in lofiFreqs.indices) {
            val wavFile = File(cacheDir, "lofi_$i.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeLofiTone(lofiFreqs[i], durationMs = 78))
            }
            lofiBank[i] = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        }

        // Pre-warm the default active start-up preset
        ensureStartupPresetLoaded(startupSoundId)
    }

    private fun ensureStartupPresetLoaded(presetId: String): Int {
        val existing = startupSoundPoolIds[presetId]
        if (existing != null && existing != 0) return existing
        val preset = findStartupPreset(presetId)
        val wavFile = File(startupCacheDir(), "startup_${preset.id}.wav")
        if (!wavFile.exists()) {
            writeWav(wavFile, synthesizeStartupPreset(preset))
        }
        val sid = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
        if (sid != 0) startupSoundPoolIds[presetId] = sid
        return sid
    }

    private fun synthesizeStartupPreset(preset: StartupSoundPreset): ShortArray {
        val sr = 22050
        val n = (sr * preset.durationMs) / 1000
        val out = ShortArray(n)
        // Soft, comfortable peak (~0.52) so start-up chimes never blast the user's ears!
        val peakGain = 0.50
        for (i in 0 until n) {
            val tSec = i.toFloat() / sr.toFloat()
            var mix = 0.0
            for (k in preset.notesHz.indices) {
                val onset = k * preset.spacingSec
                val dt = tSec - onset
                if (dt >= 0f) {
                    val f = preset.notesHz[k].toDouble()
                    val atk = (dt / 0.014f).coerceIn(0f, 1f).toDouble()
                    val dec = exp((-preset.decayRate * dt).toDouble())
                    val wave = when (preset.waveform) {
                        "bell" -> sin(2.0 * PI * f * dt) * 0.65 +
                            sin(2.0 * PI * f * 2.756 * dt) * preset.harmonic2 * exp((-10.0 * dt).toDouble()) +
                            sin(2.0 * PI * f * 5.404 * dt) * preset.harmonic3 * exp((-14.0 * dt).toDouble())
                        "pluck" -> sin(2.0 * PI * f * dt) * 0.72 +
                            sin(2.0 * PI * f * 2.0 * dt) * preset.harmonic2 * exp((-12.0 * dt).toDouble()) +
                            sin(2.0 * PI * f * 3.0 * dt) * preset.harmonic3 * exp((-16.0 * dt).toDouble())
                        "warm" -> sin(2.0 * PI * f * dt) * 0.78 +
                            sin(2.0 * PI * f * 0.5 * dt) * 0.18 +
                            sin(2.0 * PI * f * 2.0 * dt) * preset.harmonic2 * exp((-6.0 * dt).toDouble())
                        "chip" -> {
                            val s1 = sin(2.0 * PI * f * dt)
                            val sq = if (s1 >= 0.0) 0.55 else -0.55
                            s1 * 0.50 + sq * 0.35 + sin(2.0 * PI * f * 2.0 * dt) * preset.harmonic2
                        }
                        else -> sin(2.0 * PI * f * dt) * 0.74 +
                            sin(2.0 * PI * f * 2.0 * dt) * preset.harmonic2 * exp((-7.5 * dt).toDouble()) +
                            sin(2.0 * PI * f * 3.0 * dt) * preset.harmonic3 * exp((-11.0 * dt).toDouble())
                    }
                    mix += wave * atk * dec * (0.42 / preset.notesHz.size.coerceAtLeast(1).toDouble().let { kotlin.math.sqrt(it) })
                }
            }
            // Gentle fade-out on last 15ms to guarantee zero click
            val tailFade = ((n - 1 - i).toFloat() / (sr * 0.015f)).coerceIn(0f, 1f).toDouble()
            val sample = ((mix * peakGain * tailFade).coerceIn(-0.85, 0.85) * Short.MAX_VALUE).toInt()
            out[i] = sample.toShort()
        }
        return out
    }

    private fun synthesizeAnimaleseSyllable(f0: Float, formant: Float, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        var phase0 = 0.0
        var phaseF = 0.0
        for (i in 0 until n) {
            val t = i.toFloat() / n.toFloat()
            val pitchMod = 1.0f + 0.14f * sin(t * PI.toFloat())
            val freq = f0 * pitchMod
            phase0 += (2.0 * PI * freq) / sr
            phaseF += (2.0 * PI * formant) / sr

            val glottal = (sin(phase0) * 0.62 + sin(phase0 * 2.0) * 0.26 + sin(phase0 * 3.0) * 0.12)
            val vowel = sin(phaseF) * (0.45 + 0.55 * sin(phase0))
            val attack = (t / 0.12f).coerceIn(0f, 1f)
            val release = ((1f - t) / 0.35f).coerceIn(0f, 1f)
            val env = attack * release
            val sample = ((glottal * 0.68 + vowel * 0.32) * env * 0.68 * Short.MAX_VALUE)
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
            val glide = if (t < 0.22f) {
                val u = t / 0.22f
                if (upwardScratch) (0.72f + 0.34f * u) else (1.28f - 0.28f * u)
            } else {
                1.0f + 0.025f * sin(t * 24f)
            }
            phase += (2.0 * PI * f0 * glide) / sr
            subPhase += (2.0 * PI * (f0 * 0.5f) * glide) / sr

            val body = sin(phase) * 0.55 + sin(phase * 2.0) * 0.25 + sin(phase * 3.0) * 0.10 + sin(subPhase) * 0.22
            val transient = if (t < 0.08f) sin(phase * 5.2) * (1f - t / 0.08f) * 0.30 else 0.0
            val env = (t / 0.06f).coerceIn(0f, 1f) * exp((-3.2 * t)).toFloat()
            val sample = ((body + transient) * env * 0.74 * Short.MAX_VALUE)
                .toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = sample.toShort()
        }
        return out
    }

    private fun synthesizeCrystalTone(f0: Float, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i.toFloat() / sr.toFloat()
            val norm = i.toFloat() / n.toFloat()
            val env = (norm / 0.08f).coerceIn(0f, 1f) * exp((-5.5 * norm)).toFloat()
            val wave = sin(2.0 * PI * f0 * t) * 0.70 +
                sin(2.0 * PI * f0 * 2.75 * t) * 0.22 * exp((-8.0 * norm))
            val sample = (wave * env * 0.56 * Short.MAX_VALUE)
                .toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = sample.toShort()
        }
        return out
    }

    private fun synthesizeRetroTone(f0: Float, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i.toFloat() / sr.toFloat()
            val norm = i.toFloat() / n.toFloat()
            val env = (norm / 0.05f).coerceIn(0f, 1f) * (1f - norm * 0.75f)
            val s = sin(2.0 * PI * f0 * t)
            val sq = if (s >= 0.0) 0.50 else -0.50
            val wave = sq * 0.55 + s * 0.45
            val sample = (wave * env * 0.52 * Short.MAX_VALUE)
                .toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = sample.toShort()
        }
        return out
    }

    private fun synthesizeLofiTone(f0: Float, durationMs: Int): ShortArray {
        val sr = 22050
        val n = (sr * durationMs) / 1000
        val out = ShortArray(n)
        for (i in 0 until n) {
            val t = i.toFloat() / sr.toFloat()
            val norm = i.toFloat() / n.toFloat()
            val env = (norm / 0.10f).coerceIn(0f, 1f) * exp((-3.8 * norm)).toFloat()
            val wave = sin(2.0 * PI * f0 * t) * 0.72 +
                sin(2.0 * PI * f0 * 0.5 * t) * 0.20 +
                sin(2.0 * PI * f0 * 2.0 * t) * 0.12 * exp((-6.0 * norm))
            val sample = (wave * env * 0.62 * Short.MAX_VALUE)
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
            putInt(16)
            putShort(1)
            putShort(1)
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
        play(popId, 0.78f, 1.0f, ToneGenerator.TONE_PROP_BEEP)
    }

    fun playSend() {
        hapticClick()
        play(sendId, 0.78f, 1.04f, ToneGenerator.TONE_PROP_ACK)
    }

    fun playRecv() {
        hapticDoubleClick()
        play(recvId, 0.78f, 1.0f, ToneGenerator.TONE_PROP_BEEP2)
    }

    fun playClick() {
        hapticTick()
        play(clickId, 0.60f, 1.0f, null)
    }

    fun playOpen() {
        hapticClick()
        play(openId, 0.72f, 1.0f, ToneGenerator.TONE_PROP_PROMPT)
    }

    /**
     * Plays Cel's customizable Start-up Sound (either one of 22 moderate presets or a user-uploaded custom audio file).
     */
    fun playAssistantSummon(
        overrideSoundId: String? = null,
        overrideCustomPath: String? = null,
    ) {
        hapticDoubleClick()
        if (!enabled) return
        val customPath = (overrideCustomPath ?: startupSoundCustomPath).trim()
        val soundId = when {
            !overrideSoundId.isNullOrBlank() -> overrideSoundId
            startupSoundShuffleEnabled -> {
                val excluded = startupSoundExcludedIds + deletedStartupSoundIds
                val pool = STARTUP_SOUND_PRESETS.map { it.id }.filter { it !in excluded }.toMutableList()
                if (customPath.isNotBlank() && File(customPath).exists() && "custom" !in excluded) {
                    pool.add("custom")
                }
                if (pool.isEmpty()) {
                    startupSoundId.ifBlank { "soft_celesta" }
                } else {
                    val candidates = if (pool.size > 1) pool.filter { it != lastShuffledStartupId } else pool
                    val picked = candidates[Random.nextInt(candidates.size)]
                    lastShuffledStartupId = picked
                    picked
                }
            }
            else -> startupSoundId.ifBlank { "soft_celesta" }
        }
        val vol = (0.68f * masterVolume).coerceIn(0f, 0.85f)
        if (vol <= 0.01f) return

        sfxExecutor.execute {
            if (soundId == "custom" && customPath.isNotBlank() && File(customPath).exists()) {
                playCustomStartupFile(customPath, vol)
                return@execute
            }
            val preset = findStartupPreset(soundId)
            val wavFile = File(startupCacheDir(), "startup_${preset.id}.wav")
            if (!wavFile.exists()) {
                writeWav(wavFile, synthesizeStartupPreset(preset))
            }
            val existingId = startupSoundPoolIds[preset.id]
            if (existingId != null && existingId != 0 && loadedIds[existingId] == true) {
                runCatching { soundPool.play(existingId, vol, vol, 1, 0, 1.0f) }
            } else {
                // Play via MediaPlayer immediately on first synthesize while also preloading into SoundPool
                playCustomStartupFile(wavFile.absolutePath, vol)
                val sid = runCatching { soundPool.load(wavFile.absolutePath, 1) }.getOrDefault(0)
                if (sid != 0) startupSoundPoolIds[preset.id] = sid
            }
        }
    }

    private fun playCustomStartupFile(path: String, vol: Float) {
        runCatching {
            startupMediaPlayer?.stop()
            startupMediaPlayer?.release()
        }
        startupMediaPlayer = null
        runCatching {
            val mp = MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                )
                setDataSource(path)
                setVolume(vol, vol)
                setOnPreparedListener { it.start() }
                setOnCompletionListener { player ->
                    runCatching { player.release() }
                    if (startupMediaPlayer === player) startupMediaPlayer = null
                }
                setOnErrorListener { player, _, _ ->
                    runCatching { player.release() }
                    if (startupMediaPlayer === player) startupMediaPlayer = null
                    true
                }
                prepareAsync()
            }
            startupMediaPlayer = mp
        }
    }

    /** Deletes a preset's synthesized WAV file from cache to save storage. Returns bytes freed. */
    fun deleteStartupPresetCache(presetId: String): Long {
        val wavFile = File(startupCacheDir(), "startup_$presetId.wav")
        val bytes = if (wavFile.exists()) wavFile.length() else 0L
        runCatching { wavFile.delete() }
        val sid = startupSoundPoolIds.remove(presetId)
        if (sid != null && sid != 0) {
            loadedIds.remove(sid)
            sfxExecutor.execute { runCatching { soundPool.unload(sid) } }
        }
        return bytes
    }

    fun getStartupCacheBytes(): Long {
        val dir = startupCacheDir()
        return dir.listFiles()?.sumOf { it.length() } ?: 0L
    }

    private fun resolveBankAndRate(style: String, requestedPitch: Float, baseRate: Float): Pair<IntArray, Float> {
        val clampedPitch = requestedPitch.coerceIn(0.25f, 2.50f)
        val rawRate = baseRate * clampedPitch
        return when (style) {
            "animal_crossing", "cozy_chatter" -> {
                if (rawRate < 0.55f) animaleseLowBank to (rawRate * 2.0f).coerceIn(0.50f, 2.0f)
                else animaleseBank to rawRate.coerceIn(0.50f, 2.0f)
            }
            "crystal_bell" -> crystalBank to rawRate.coerceIn(0.50f, 2.0f)
            "retro_bit" -> retroBank to rawRate.coerceIn(0.50f, 2.0f)
            "lofi_keys" -> lofiBank to rawRate.coerceIn(0.50f, 2.0f)
            else -> { // "scratchin_melodii" / "groove_synth"
                if (rawRate < 0.55f) melodiiLowBank to (rawRate * 2.0f).coerceIn(0.50f, 2.0f)
                else melodiiBank to rawRate.coerceIn(0.50f, 2.0f)
            }
        }
    }

    fun playAnimalesePurr() {
        hapticTick()
        if (!enabled || !animaleseEnabled) return
        val style = typingSoundStyle
        val pitchScale = typingSoundPitch.coerceIn(0.25f, 2.50f)
        val vol = (0.58f * masterVolume).coerceIn(0f, 1f)
        if (vol <= 0.01f) return
        sfxExecutor.execute {
            val baseRate = 0.96f + Random.nextFloat() * 0.16f
            val (bank, rate) = resolveBankAndRate(style, pitchScale, baseRate)
            val note = bank[Random.nextInt(bank.size)]
            if (note != 0 && loadedIds[note] == true) {
                runCatching { soundPool.play(note, vol, vol, 1, 0, rate) }
            }
        }
    }

    /**
     * Plays a Groove Synth / Cozy Chatter typing syllable off the UI thread.
     */
    fun playAnimaleseChirp(charCodeOrIndex: Int, isQuestion: Boolean = false) {
        if (!enabled || !animaleseEnabled) return
        val now = System.currentTimeMillis()
        val style = typingSoundStyle
        val minInterval = if (style == "scratchin_melodii") 78L else 62L
        if (now - lastChirpMs < minInterval) return
        lastChirpMs = now
        playSynthChirpForVoice(
            voiceStyle = style,
            charCodeOrIndex = charCodeOrIndex,
            pitch = typingSoundPitch,
            isQuestion = isQuestion,
            volumeScale = 0.44f,
        )
    }

    /**
     * Plays a single synth speech syllable for ENGINE_SYNTH (Groove Synth, Cozy Chatter, Crystal Bell, Retro Bit, Lo-Fi Keys).
     */
    fun playSynthChirpForVoice(
        voiceStyle: String,
        charCodeOrIndex: Int,
        pitch: Float = 1.0f,
        isQuestion: Boolean = false,
        volumeScale: Float = 0.56f,
    ) {
        val vol = (volumeScale * masterVolume).coerceIn(0f, 1f)
        if (vol <= 0.01f) return
        sfxExecutor.execute {
            val baseRate = when (voiceStyle) {
                "animal_crossing", "cozy_chatter" -> 0.94f + ((charCodeOrIndex.coerceAtLeast(0) % 7) * 0.035f)
                "crystal_bell" -> 0.95f + ((charCodeOrIndex.coerceAtLeast(0) % 6) * 0.03f)
                else -> 0.96f + ((charCodeOrIndex.coerceAtLeast(0) % 5) * 0.04f)
            }
            val effectiveBase = if (isQuestion) baseRate * 1.14f else baseRate
            val (bank, rate) = resolveBankAndRate(voiceStyle, pitch, effectiveBase)
            val idx = (charCodeOrIndex.coerceAtLeast(0)) % bank.size
            val note = bank[idx]
            if (note != 0 && loadedIds[note] == true) {
                runCatching { soundPool.play(note, vol, vol, 1, 0, rate) }
            }
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
        sfxExecutor.execute {
            runCatching {
                if (!v.hasVibrator()) return@execute
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    v.vibrate(VibrationEffect.createPredefined(predefinedEffect))
                } else {
                    v.vibrate(VibrationEffect.createOneShot(fallbackMs, fallbackAmp))
                }
            }
        }
    }

    private fun play(id: Int, baseVol: Float, rate: Float, fallbackToneType: Int?) {
        if (!enabled || id == 0) return
        val vol = (baseVol * masterVolume).coerceIn(0f, 1f)
        if (vol <= 0.01f) return
        sfxExecutor.execute {
            if (loadedIds[id] == true) {
                runCatching { soundPool.play(id, vol, vol, 1, 0, rate) }
            } else if (fallbackToneType != null) {
                runCatching { fallbackTone?.startTone(fallbackToneType, 45) }
            }
        }
    }

    fun release() {
        runCatching {
            startupMediaPlayer?.stop()
            startupMediaPlayer?.release()
        }
        startupMediaPlayer = null
        runCatching { sfxExecutor.shutdownNow() }
        runCatching { soundPool.release() }
        runCatching { fallbackTone?.release() }
    }
}

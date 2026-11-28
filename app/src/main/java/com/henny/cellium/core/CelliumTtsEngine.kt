package com.henny.cellium.core

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.URLEncoder
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.math.roundToInt

data class TtsVoicePreset(
    val id: String,
    val label: String,
    val accent: String,
    val gender: String,
    val engine: String, // "edge", "polly", "tiktok", "google"
)

/**
 * Microsoft Edge Read-Aloud Sec-MS-GEC v2 token generator (matches rany2/edge-tts >= 7.3.0).
 * Produces "<16-hex-CS64>-<64-hex-salted-SHA256>" with automatic server clock-skew adjustment
 * so Edge Neural WSS handshakes succeed cleanly instead of returning HTTP 403.
 */
internal object EdgeSecMsGecV2 {
    const val TRUSTED_CLIENT_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
    const val CHROMIUM_FULL_VERSION = "143.0.3650.75"
    const val CHROMIUM_MAJOR_VERSION = "143"
    const val SEC_MS_GEC_VERSION = "2-$CHROMIUM_FULL_VERSION"

    private const val WIN_EPOCH_SEC = 11644473600L
    private const val M = 0xFFFFFFFFL

    @Volatile
    private var clockSkewSec: Long = 0L

    private val secureRng = SecureRandom()

    private val SHA256_INITIAL = longArrayOf(
        0x6A09E667L, 0xBB67AE85L, 0x3C6EF372L, 0xA54FF53AL,
        0x510E527FL, 0x9B05688CL, 0x1F83D9ABL, 0x5BE0CD19L,
    )
    private val SHA256_STATE = longArrayOf(
        0xFD9FBEA2L, 0x91243CE7L, 0xBE499094L, 0xCD2E1E0AL,
        0x6C006F49L, 0x04BD35ABL, 0xFEB0A7E4L, 0x03EFFBD2L,
    )
    private val SHA256_SCHEDULE = longArrayOf(
        0xEB24BF9EL, 0x1558691FL, 0xA0C09EE2L, 0x0CFA32BAL,
        0xA622EE8CL, 0xD1DD9491L, 0xC0DD25A0L, 0xF9E70AB6L,
        0xF0C31573L, 0x7058CE4EL, 0x7188E606L, 0x00E5AB33L,
        0xD258B060L, 0x72766564L,
    )
    private val SHA256_ROUND_CONSTANTS = longArrayOf(
        0x428A2F98L, 0x71374491L, 0xB5C0FBCFL, 0xE9B5DBA5L,
        0x3956C25BL, 0x59F111F1L, 0x923F82A4L, 0xAB1C5ED5L,
        0xD807AA98L, 0x12835B01L, 0x243185BEL, 0x550C7DC3L,
        0x72BE5D74L, 0x80DEB1FEL, 0x9BDC06A7L, 0xC19BF174L,
        0xE49B69C1L, 0xEFBE4786L, 0x0FC19DC6L, 0x240CA1CCL,
        0x2DE92C6FL, 0x4A7484AAL, 0x5CB0A9DCL, 0x76F988DAL,
        0x983E5152L, 0xA831C66DL, 0xB00327C8L, 0xBF597FC7L,
        0xC6E00BF3L, 0xD5A79147L, 0x06CA6351L, 0x14292967L,
        0x27B70A85L, 0x2E1B2138L, 0x4D2C6DFCL, 0x53380D13L,
        0x650A7354L, 0x766A0ABBL, 0x81C2C92EL, 0x92722C85L,
        0xA2BFE8A1L, 0xA81A664BL, 0xC24B8B70L, 0xC76C51A3L,
        0xD192E819L, 0xD6990624L, 0xF40E3585L, 0x106AA070L,
        0x19A4C116L, 0x1E376C08L, 0x2748774CL, 0x34B0BCB5L,
        0x391C0CB3L, 0x4ED8AA4AL, 0x5B9CCA4FL, 0x682E6FF3L,
        0x748F82EEL, 0x78A5636FL, 0x84C87814L, 0x8CC70208L,
        0x90BEFFFAL, 0xA4506CEBL, 0xBEF9A3F7L, 0xC67178F2L,
    )
    private const val SHA256_ADJUSTMENT = 0xC9DC06A7L
    private val SHA256_BLOCK_CONSTANTS = LongArray(64) { idx ->
        if (idx == 14) SHA256_ADJUSTMENT else SHA256_ROUND_CONSTANTS[idx]
    }
    private const val SHA256_SIGMA0_ADJUSTMENT = 0x059C0B80L
    private const val SHA256_SIGMA1_ADJUSTMENT = 0x000B92C0L

    private val CS64_COEFF_A = longArrayOf(
        0xE82E91B1L, 0x44DE24C6L, 0x3BEB65BCL, 0xC89C5933L,
        0x8D1EC211L, 0x314EF5D5L, 0xE92491B1L, 0xF0A5B9D5L,
        0x06064CF3L, 0xDA79FA60L, 0xBED20560L, 0x89F9C9F8L,
        0x35FA38C6L, 0xCB49E3C6L,
    )
    private val CS64_COEFF_B = longArrayOf(
        0xB32700D0L, 0x88DFF51DL, 0x29514038L, 0xB328CBDFL,
        0xD405B4D5L, 0x26E55F3CL, 0x607801C6L, 0x82B2C1FBL,
        0xFA51A3DAL, 0x207CC464L, 0x3C3C74F3L, 0xD2D14B61L,
        0xBB04A2C1L, 0xC5626167L,
    )
    private const val CS64_FACTOR = 0x82893933L
    private const val CS64_ADJUSTMENT0 = 0xF2F90B1AL
    private const val CS64_ADJUSTMENT1 = 0x0B1A0000L

    fun adjustClockSkewFromDateHeader(dateHeader: String?): Boolean {
        if (dateHeader.isNullOrBlank()) return false
        val sdf = SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss zzz", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("GMT")
        }
        val serverDate = runCatching { sdf.parse(dateHeader.trim()) }.getOrNull() ?: return false
        val serverSec = serverDate.time / 1000L
        val clientSec = (System.currentTimeMillis() / 1000L) + clockSkewSec
        clockSkewSec += (serverSec - clientSec)
        return true
    }

    fun generateMuid(): String {
        val bytes = ByteArray(16)
        secureRng.nextBytes(bytes)
        val sb = StringBuilder(32)
        for (b in bytes) sb.append("%02X".format(b))
        return sb.toString()
    }

    fun generateToken(unixSecondsOverride: Long? = null): String {
        val unixSec = unixSecondsOverride ?: ((System.currentTimeMillis() / 1000L) + clockSkewSec)
        var ticks = unixSec + WIN_EPOCH_SEC
        ticks -= (ticks % 300L)
        val filetimeTicks = ticks * 10_000_000L
        val payload = "${filetimeTicks}$TRUSTED_CLIENT_TOKEN".toByteArray(Charsets.US_ASCII)
        val digest = sha256Digest(payload)
        val (w0, w1) = cs64Digest(payload, digest)
        val cs64Bytes = ByteArray(8)
        putLe32(cs64Bytes, 0, w0)
        putLe32(cs64Bytes, 4, w1)
        return "${bytesToUpperHex(cs64Bytes)}-${bytesToUpperHex(digest)}"
    }

    private fun rol16(v: Long): Long {
        val u = v and M
        return ((u shl 16) or (u ushr 16)) and M
    }

    private fun rotr32(v: Long, n: Int): Long {
        val u = v and M
        return ((u ushr n) or (u shl (32 - n))) and M
    }

    private fun sigma0(v: Long): Long {
        val u = v and M
        return ((u ushr 7) xor (u shl 25) xor (u ushr 18) xor (u shl 14) xor (u ushr 3)) and M
    }

    private fun sigma1(v: Long): Long {
        val u = v and M
        return ((u ushr 17) xor (u shl 15) xor (u ushr 19) xor (u shl 13) xor (u ushr 10)) and M
    }

    private fun expandSchedule(words: LongArray, firstWord: Int) {
        for (i in firstWord until 64) {
            val s1 = sigma1(words[i - 2])
            val s0 = sigma0(words[i - 15])
            words[i] = (s1 + words[i - 7] + s0 + words[i - 16]) and M
        }
    }

    private fun sha256Rounds(state: LongArray, words: LongArray, firstRound: Int): LongArray {
        var a = state[0]
        var b = state[1]
        var c = state[2]
        var d = state[3]
        var e = state[4]
        var f = state[5]
        var g = state[6]
        var h = state[7]
        val constants = if (firstRound == 14) SHA256_BLOCK_CONSTANTS else SHA256_ROUND_CONSTANTS
        for (i in firstRound until 64) {
            val s1 = (rotr32(e, 6) xor rotr32(e, 11) xor rotr32(e, 25)) and M
            val ch = (g xor (e and (f xor g))) and M
            val t1 = (h + s1 + ch + constants[i] + words[i]) and M
            val s0 = (rotr32(a, 2) xor rotr32(a, 13) xor rotr32(a, 22)) and M
            val maj = ((a and b) or (c and (a or b))) and M
            val t2 = (s0 + maj) and M
            h = g
            g = f
            f = e
            e = (d + t1) and M
            d = c
            c = b
            b = a
            a = (t1 + t2) and M
        }
        return longArrayOf(a, b, c, d, e, f, g, h)
    }

    private fun sha256Init(prefix7: ByteArray): LongArray {
        val words = LongArray(64)
        words[14] = ((prefix7[0].toLong() and 0xFFL) shl 16) or
            ((prefix7[1].toLong() and 0xFFL) shl 8) or
            (prefix7[2].toLong() and 0xFFL)
        words[15] = ((prefix7[3].toLong() and 0xFFL) shl 24) or
            ((prefix7[4].toLong() and 0xFFL) shl 16) or
            ((prefix7[5].toLong() and 0xFFL) shl 8) or
            (prefix7[6].toLong() and 0xFFL)
        for (i in 16 until 30) {
            var v = SHA256_SCHEDULE[i - 16]
            if (i - 2 >= 14) {
                val s1 = sigma1(words[i - 2])
                v += if (i == 16) (s1 xor SHA256_SIGMA1_ADJUSTMENT) else s1
            }
            if (i - 7 >= 14) {
                v += words[i - 7]
            }
            if (i - 15 >= 14) {
                val s0 = sigma0(words[i - 15])
                v += if (i == 29) (s0 xor SHA256_SIGMA0_ADJUSTMENT) else s0
            }
            words[i] = v and M
        }
        words[30] = (
            sigma1(words[28]) +
                words[23] +
                sigma0(words[15]) +
                words[14] +
                SHA256_ADJUSTMENT -
                SHA256_ROUND_CONSTANTS[14]
            ) and M
        expandSchedule(words, 31)
        val working = sha256Rounds(SHA256_STATE, words, 14)
        return LongArray(8) { idx -> (SHA256_INITIAL[idx] + working[idx]) and M }
    }

    private fun sha256Digest(data: ByteArray): ByteArray {
        val totalLen = 57L + data.size.toLong()
        val tail = data.copyOfRange(7, data.size)
        val zeroCount = ((55L - totalLen) % 64L + 64L) % 64L
        val padded = ByteArray(tail.size + 1 + zeroCount.toInt() + 8)
        System.arraycopy(tail, 0, padded, 0, tail.size)
        padded[tail.size] = 0x80.toByte()
        val bitLen = totalLen * 8L
        val lenPos = padded.size - 8
        for (i in 0 until 8) {
            padded[lenPos + i] = ((bitLen ushr (56 - i * 8)) and 0xFFL).toByte()
        }

        var state = sha256Init(data.copyOfRange(0, 7))
        val words = LongArray(64)
        var offset = 0
        while (offset < padded.size) {
            for (i in 0 until 16) {
                val p = offset + i * 4
                words[i] = ((padded[p].toLong() and 0xFFL) shl 24) or
                    ((padded[p + 1].toLong() and 0xFFL) shl 16) or
                    ((padded[p + 2].toLong() and 0xFFL) shl 8) or
                    (padded[p + 3].toLong() and 0xFFL)
            }
            expandSchedule(words, 16)
            val working = sha256Rounds(state, words, 0)
            for (i in 0 until 8) {
                state[i] = (state[i] + working[i]) and M
            }
            offset += 64
        }

        val out = ByteArray(32)
        for (i in 0 until 8) {
            val w = state[i]
            out[i * 4] = ((w ushr 24) and 0xFFL).toByte()
            out[i * 4 + 1] = ((w ushr 16) and 0xFFL).toByte()
            out[i * 4 + 2] = ((w ushr 8) and 0xFFL).toByte()
            out[i * 4 + 3] = (w and 0xFFL).toByte()
        }
        return out
    }

    private fun cs64Digest(data: ByteArray, digest: ByteArray): Pair<Long, Long> {
        val keyA = getLe32(digest, 0) or 1L
        val keyB = getLe32(digest, 4) or 1L
        val factorA = (keyA * CS64_FACTOR) and M
        val factorB = (keyB * CS64_FACTOR) and M

        val prefixed = ByteArray(1 + data.size)
        prefixed[0] = 0
        System.arraycopy(data, 0, prefixed, 1, data.size)
        val padBytes = (4 - (prefixed.size % 4)) % 4
        var wordCount = (prefixed.size + padBytes) / 4
        if (wordCount % 2 != 0) wordCount += 1

        val totalTerms = CS64_COEFF_A.size + wordCount
        val terms = LongArray(totalTerms)
        val offsets = LongArray(totalTerms)

        for (i in CS64_COEFF_A.indices) {
            terms[i] = (CS64_COEFF_A[i] * if (i % 2 == 0) factorA else factorB) and M
            offsets[i] = CS64_COEFF_B[i]
        }

        for (i in 0 until wordCount) {
            val base = i * 4
            val b0 = if (base < prefixed.size) prefixed[base].toLong() and 0xFFL else 0L
            val b1 = if (base + 1 < prefixed.size) prefixed[base + 1].toLong() and 0xFFL else 0L
            val b2 = if (base + 2 < prefixed.size) prefixed[base + 2].toLong() and 0xFFL else 0L
            val b3 = if (base + 3 < prefixed.size) prefixed[base + 3].toLong() and 0xFFL else 0L
            val word = b0 or (b1 shl 8) or (b2 shl 16) or (b3 shl 24)
            var term = (word * if (i % 2 == 0) keyA else keyB) and M
            var off = (rol16(word) * if (i % 2 == 0) 0xEF0569FBL else 0xC31713DBL) and M
            if (i == 0) {
                term = (term + ((CS64_ADJUSTMENT0 * factorA) and M)) and M
                off = (off + CS64_ADJUSTMENT1) and M
            }
            val dst = CS64_COEFF_A.size + i
            terms[dst] = term
            offsets[dst] = off
        }

        var swapAcc = 0L
        var swapLast = 0L
        var state = 0L
        var acc = 0L
        var idx = 0
        while (idx < totalTerms) {
            val x = terms[idx]
            val y = terms[idx + 1]

            var t = rol16((offsets[idx] + x) and M)
            var q = (t * 0x76F50F34L) and M
            swapAcc = (swapAcc + ((rol16(q) * 0xC3EFEA97L + q) and M)) and M

            t = rol16((offsets[idx + 1] + y) and M)
            q = (t * 0x1881CE3CL) and M
            swapLast = (rol16(q) * 0x35BD1EC9L + q) and M
            swapAcc = (swapAcc + swapLast) and M

            state = (state * keyA + x) and M
            state = (rol16(state) * 0xCF98B111L) and M
            state = (rol16(state) * 0x87085B9FL) and M
            state = (rol16(state) * 0x12CEB96DL) and M
            state = (rol16(state) * 0x257E1D83L) and M
            acc = (acc + state) and M

            t = (state * keyB + y) and M
            t = (rol16(t) * 0xA27416F5L) and M
            t = (rol16(t) * 0xD38396FFL) and M
            state = (rol16((rol16(t) * 0x7C932B89L) and M) * 0xBFA49F69L) and M
            acc = (acc + state) and M

            idx += 2
        }
        return ((swapLast xor state) and M) to ((swapAcc xor acc) and M)
    }

    private fun getLe32(bytes: ByteArray, offset: Int): Long =
        (bytes[offset].toLong() and 0xFFL) or
            ((bytes[offset + 1].toLong() and 0xFFL) shl 8) or
            ((bytes[offset + 2].toLong() and 0xFFL) shl 16) or
            ((bytes[offset + 3].toLong() and 0xFFL) shl 24)

    private fun putLe32(dst: ByteArray, offset: Int, v: Long) {
        dst[offset] = (v and 0xFFL).toByte()
        dst[offset + 1] = ((v ushr 8) and 0xFFL).toByte()
        dst[offset + 2] = ((v ushr 16) and 0xFFL).toByte()
        dst[offset + 3] = ((v ushr 24) and 0xFFL).toByte()
    }

    private fun bytesToUpperHex(bytes: ByteArray): String {
        val sb = StringBuilder(bytes.size * 2)
        for (b in bytes) sb.append("%02X".format(b))
        return sb.toString()
    }
}

/**
 * Unified Multi-Engine Text-to-Speech player for Cel.Cellium:
 *  1) "edge"   — Microsoft Edge Neural Read-Aloud TTS (free, Sec-MS-GEC v2 studio neural voices via WSS)
 *  2) "polly"  — Amazon Polly Voices via TTSMP3 (free, keyless, warm studio voices)
 *  3) "tiktok" — Expressive TikTok Voices via LazyPy (free, keyless, iconic character & natural voices)
 *  4) "google" — Google TTS (free online natural regional accents with automatic sentence chunking)
 *  5) "system" — Local Android TextToSpeech (offline device voices)
 *
 * Automatically falls back cleanly if the device is offline or a cloud service hits a limit,
 * while surfacing transparent fallback notices so the user always knows which voice spoke.
 */
class CelliumTtsEngine(
    context: Context,
    private val sharedSoundEngine: CelliumSoundEngine? = null,
) {
    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val json = Json { ignoreUnknownKeys = true }
    private val ownedSoundEngine: CelliumSoundEngine by lazy {
        sharedSoundEngine ?: CelliumSoundEngine(appContext)
    }

    private val httpClient = CelliumHttp.clientWithTimeouts(
        connectSec = 12L,
        readSec = 25L,
        writeSec = 15L,
    )

    @Volatile private var systemTts: TextToSpeech? = null
    @Volatile private var systemReady: Boolean = false
    @Volatile private var systemInitFailed: Boolean = false
    @Volatile private var activePlayer: MediaPlayer? = null
    @Volatile private var speakJob: Job? = null
    @Volatile private var activeWebSocket: WebSocket? = null

    private var pendingSystemOnDone: (() -> Unit)? = null
    private val pendingSystemOnReady = mutableListOf<(TextToSpeech?) -> Unit>()

    companion object {
        const val ENGINE_SYNTH = "synth"
        const val ENGINE_EDGE = "edge"
        const val ENGINE_POLLY = "polly"
        const val ENGINE_TIKTOK = "tiktok"
        const val ENGINE_GOOGLE = "google"
        const val ENGINE_SYSTEM = "system"

        val SYNTH_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("synth:groove_synth", "Groove Synth", "Cel Default", "Funky Vocal-Chop Synth", ENGINE_SYNTH),
            TtsVoicePreset("synth:cozy_chatter", "Cozy Chatter", "Formant Vowel", "Animal-Crossing Style", ENGINE_SYNTH),
            TtsVoicePreset("synth:crystal_bell", "Crystal Bell", "Music Box", "Delicate Shimmer Chimes", ENGINE_SYNTH),
            TtsVoicePreset("synth:retro_bit", "Retro Bit", "8-Bit Chiptune", "Playful Arcade Blips", ENGINE_SYNTH),
            TtsVoicePreset("synth:lofi_keys", "Lo-Fi Keys", "Rhodes Electric", "Soft Chill Syllables", ENGINE_SYNTH),
        )

        fun engineLabel(engine: String): String = when (engine.lowercase()) {
            ENGINE_SYNTH -> "Synth"
            ENGINE_EDGE -> "Edge Neural"
            ENGINE_POLLY -> "Polly Studio"
            ENGINE_TIKTOK -> "TikTok Voices"
            ENGINE_GOOGLE -> "Google TTS"
            else -> "System Offline"
        }

        private val ALL_VOICES_BY_ID: Map<String, TtsVoicePreset> by lazy {
            (SYNTH_VOICES + EDGE_VOICES + POLLY_VOICES + TIKTOK_VOICES + GOOGLE_VOICES)
                .associateBy { it.id.lowercase() }
        }

        fun resolveVoiceLabel(engine: String, voiceId: String): String {
            ALL_VOICES_BY_ID[voiceId.lowercase()]?.let { return it.label }
            return when (engine.lowercase()) {
                ENGINE_SYNTH -> SYNTH_VOICES.first().label
                ENGINE_EDGE -> voiceId.removeSuffix("Neural").substringAfterLast('-').ifBlank { "Emma Multilingual" }
                ENGINE_POLLY -> voiceId.removePrefix("polly:").ifBlank { "Joanna" }
                ENGINE_TIKTOK -> voiceId.removePrefix("tiktok:").ifBlank { "Jessie" }
                ENGINE_GOOGLE -> voiceId.removePrefix("google:").ifBlank { "Google US English" }
                else -> voiceId.ifBlank { "Default System Voice" }
            }
        }

        val EDGE_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("en-US-EmmaMultilingualNeural", "Emma Multilingual", "English (US)", "Female · Ultra-Natural HD", ENGINE_EDGE),
            TtsVoicePreset("en-US-AvaMultilingualNeural", "Ava Multilingual", "English (US)", "Female · Warm Studio HD", ENGINE_EDGE),
            TtsVoicePreset("en-US-AriaNeural", "Aria", "English (US)", "Female · Expressive", ENGINE_EDGE),
            TtsVoicePreset("en-US-JennyNeural", "Jenny", "English (US)", "Female · Friendly", ENGINE_EDGE),
            TtsVoicePreset("en-US-AnaNeural", "Ana", "English (US)", "Female · Cute / Youthful", ENGINE_EDGE),
            TtsVoicePreset("en-US-AndrewMultilingualNeural", "Andrew Multilingual", "English (US)", "Male · Warm Studio HD", ENGINE_EDGE),
            TtsVoicePreset("en-US-BrianMultilingualNeural", "Brian Multilingual", "English (US)", "Male · Deep Studio HD", ENGINE_EDGE),
            TtsVoicePreset("en-US-GuyNeural", "Guy", "English (US)", "Male · Casual", ENGINE_EDGE),
            TtsVoicePreset("en-GB-SoniaNeural", "Sonia", "English (UK)", "Female · British", ENGINE_EDGE),
            TtsVoicePreset("en-GB-LibbyNeural", "Libby", "English (UK)", "Female · Soft British", ENGINE_EDGE),
            TtsVoicePreset("en-GB-MaisieNeural", "Maisie", "English (UK)", "Female · Youthful UK", ENGINE_EDGE),
            TtsVoicePreset("en-GB-RyanNeural", "Ryan", "English (UK)", "Male · British", ENGINE_EDGE),
            TtsVoicePreset("en-AU-NatashaNeural", "Natasha", "English (AU)", "Female · Australian", ENGINE_EDGE),
            TtsVoicePreset("en-CA-ClaraNeural", "Clara", "English (CA)", "Female · Canadian", ENGINE_EDGE),
            TtsVoicePreset("en-IE-EmilyNeural", "Emily", "English (IE)", "Female · Irish", ENGINE_EDGE),
            TtsVoicePreset("ja-JP-NanamiNeural", "Nanami", "Japanese", "Female · Neural", ENGINE_EDGE),
            TtsVoicePreset("ko-KR-SunHiNeural", "Sun-Hi", "Korean", "Female · Neural", ENGINE_EDGE),
            TtsVoicePreset("fr-FR-DeniseNeural", "Denise", "French", "Female · Neural", ENGINE_EDGE),
            TtsVoicePreset("es-ES-ElviraNeural", "Elvira", "Spanish", "Female · Neural", ENGINE_EDGE),
            TtsVoicePreset("de-DE-KatjaNeural", "Katja", "German", "Female · Neural", ENGINE_EDGE),
            TtsVoicePreset("pt-BR-FranciscaNeural", "Francisca", "Portuguese (BR)", "Female · Neural", ENGINE_EDGE),
        )

        val POLLY_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("polly:Joanna", "Joanna", "English (US)", "Female · Crisp Studio", ENGINE_POLLY),
            TtsVoicePreset("polly:Salli", "Salli", "English (US)", "Female · Soft & Friendly", ENGINE_POLLY),
            TtsVoicePreset("polly:Kendra", "Kendra", "English (US)", "Female · Clear", ENGINE_POLLY),
            TtsVoicePreset("polly:Kimberly", "Kimberly", "English (US)", "Female · Warm", ENGINE_POLLY),
            TtsVoicePreset("polly:Ivy", "Ivy", "English (US)", "Female · Cute / Young", ENGINE_POLLY),
            TtsVoicePreset("polly:Matthew", "Matthew", "English (US)", "Male · Broadcast", ENGINE_POLLY),
            TtsVoicePreset("polly:Joey", "Joey", "English (US)", "Male · Casual", ENGINE_POLLY),
            TtsVoicePreset("polly:Justin", "Justin", "English (US)", "Male · Youthful", ENGINE_POLLY),
            TtsVoicePreset("polly:Amy", "Amy", "English (UK)", "Female · Classic British", ENGINE_POLLY),
            TtsVoicePreset("polly:Emma", "Emma", "English (UK)", "Female · Polished British", ENGINE_POLLY),
            TtsVoicePreset("polly:Brian", "Brian", "English (UK)", "Male · Classic Streamer UK", ENGINE_POLLY),
            TtsVoicePreset("polly:Nicole", "Nicole", "English (AU)", "Female · Whispery AU", ENGINE_POLLY),
            TtsVoicePreset("polly:Russell", "Russell", "English (AU)", "Male · Australian", ENGINE_POLLY),
            TtsVoicePreset("polly:Mizuki", "Mizuki", "Japanese", "Female · Standard", ENGINE_POLLY),
            TtsVoicePreset("polly:Seoyeon", "Seoyeon", "Korean", "Female · Standard", ENGINE_POLLY),
            TtsVoicePreset("polly:Celine", "Celine", "French", "Female · Standard", ENGINE_POLLY),
            TtsVoicePreset("polly:Conchita", "Conchita", "Spanish", "Female · Standard", ENGINE_POLLY),
            TtsVoicePreset("polly:Marlene", "Marlene", "German", "Female · Standard", ENGINE_POLLY),
        )

        val TIKTOK_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("tiktok:en_us_001", "Jessie (Classic)", "English (US)", "Female · Upbeat Viral", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_002", "US Female 2", "English (US)", "Female · Bright", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_006", "US Male 1", "English (US)", "Male · Conversational", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_007", "US Male 2", "English (US)", "Male · Smooth", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_009", "US Male 3", "English (US)", "Male · Energetic", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_010", "US Male 4", "English (US)", "Male · Narrator", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_uk_001", "UK Male 1", "English (UK)", "Male · British", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_uk_003", "UK Male 2", "English (UK)", "Male · Posh British", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_au_001", "AU Female", "English (AU)", "Female · Australian", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_au_002", "AU Male", "English (AU)", "Male · Australian", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_stitch", "Alien Buddy", "Character", "Playful Character", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_ghostface", "Ghostface", "Character", "Spooky Dramatic", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_c3po", "Protocol Droid", "Character", "Sci-Fi Robotic", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:en_us_rocket", "Space Raccoon", "Character", "Sassy Character", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:jp_001", "Miho", "Japanese", "Female · Expressive", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:jp_005", "Sakura", "Japanese", "Female · Cute Anime", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:kr_003", "Korean Female", "Korean", "Female · Expressive", ENGINE_TIKTOK),
            TtsVoicePreset("tiktok:fr_001", "French Male", "French", "Male · Expressive", ENGINE_TIKTOK),
        )

        val GOOGLE_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("google:en-US", "Google US English", "English (US)", "Clear & Natural", ENGINE_GOOGLE),
            TtsVoicePreset("google:en-GB", "Google UK English", "English (UK)", "British Accent", ENGINE_GOOGLE),
            TtsVoicePreset("google:en-AU", "Google AU English", "English (AU)", "Australian Accent", ENGINE_GOOGLE),
            TtsVoicePreset("google:en-IN", "Google IN English", "English (IN)", "Indian Accent", ENGINE_GOOGLE),
            TtsVoicePreset("google:ja", "Google Japanese", "Japanese", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:ko", "Google Korean", "Korean", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:fr", "Google French", "French", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:es", "Google Spanish", "Spanish", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:de", "Google German", "German", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:pt-BR", "Google Portuguese (BR)", "Portuguese", "Brazilian", ENGINE_GOOGLE),
            TtsVoicePreset("google:it", "Google Italian", "Italian", "Standard", ENGINE_GOOGLE),
            TtsVoicePreset("google:hi", "Google Hindi", "Hindi", "Standard", ENGINE_GOOGLE),
        )

        fun cleanTextForSpeech(raw: String): String {
            val strippedTags = raw
                .replace(Regex("```[\\s\\S]*?```"), " code block ")
                .replace(Regex("\\[ILLUME_GEN][\\s\\S]*?\\[/ILLUME_GEN]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[WEB_SEARCH][\\s\\S]*?\\[/WEB_SEARCH]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[WEB_IMAGE][\\s\\S]*?\\[/WEB_IMAGE]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[DEVICE_ACTION][\\s\\S]*?\\[/DEVICE_ACTION]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[VIEW_IMAGE][\\s\\S]*?\\[/VIEW_IMAGE]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[(?:SHIZUKU_RUN|AGENT_RUN)][\\s\\S]*?\\[/(?:SHIZUKU_RUN|AGENT_RUN)]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[\\[CELLIUM_IMG[^]]*]]"), "")
                .replace(Regex("\\[MOOD:[^]]+]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("https?://\\S+"), "link")
                .replace(Regex("\\([^()]{1,14}\\)")) { m ->
                    val inner = m.value.substring(1, m.value.length - 1)
                    val hasAlphaNum = inner.any { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' }
                    if (!hasAlphaNum) " " else m.value
                }
                .replace(Regex("[`*_#>~|^]"), "")

            val sb = StringBuilder(strippedTags.length)
            var i = 0
            while (i < strippedTags.length) {
                val cp = strippedTags.codePointAt(i)
                val charCount = Character.charCount(cp)
                val isEmojiOrSymbol = cp in 0x1F000..0x1FAFF ||
                    cp in 0x2600..0x27BF ||
                    cp in 0x2300..0x23FF ||
                    cp in 0x2B00..0x2BFF ||
                    cp in 0xFE00..0xFE0F ||
                    cp == 0x200D ||
                    cp == 0x20E3 ||
                    cp in 0xE0020..0xE007F ||
                    cp in 0x2190..0x21FF ||
                    Character.getType(cp) == Character.OTHER_SYMBOL.toInt()
                if (!isEmojiOrSymbol) {
                    sb.appendCodePoint(cp)
                } else {
                    sb.append(' ')
                }
                i += charCount
            }

            return sb.toString()
                .replace(Regex("\\s+"), " ")
                .trim()
                .take(1800)
        }
    }

    private fun ensureSystemTts(onReady: ((TextToSpeech?) -> Unit)? = null) {
        val existing = systemTts
        if (existing != null && systemReady) {
            onReady?.invoke(existing)
            return
        }
        if (systemInitFailed) {
            onReady?.invoke(null)
            return
        }
        if (onReady != null) {
            synchronized(pendingSystemOnReady) {
                pendingSystemOnReady.add(onReady)
            }
        }
        if (existing != null) return
        var created: TextToSpeech? = null
        created = runCatching {
            TextToSpeech(appContext) { status ->
                val callbacks = synchronized(pendingSystemOnReady) {
                    pendingSystemOnReady.toList().also { pendingSystemOnReady.clear() }
                }
                if (status == TextToSpeech.SUCCESS) {
                    systemReady = true
                    created?.language = Locale.US
                    created?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) {}
                        override fun onDone(utteranceId: String?) {
                            val cb = pendingSystemOnDone
                            pendingSystemOnDone = null
                            cb?.invoke()
                        }
                        @Deprecated("Deprecated in Java")
                        override fun onError(utteranceId: String?) {
                            val cb = pendingSystemOnDone
                            pendingSystemOnDone = null
                            cb?.invoke()
                        }
                    })
                    callbacks.forEach { it(created) }
                } else {
                    systemInitFailed = true
                    callbacks.forEach { it(null) }
                }
            }
        }.getOrNull()
        if (created == null) {
            systemInitFailed = true
            val callbacks = synchronized(pendingSystemOnReady) {
                pendingSystemOnReady.toList().also { pendingSystemOnReady.clear() }
            }
            callbacks.forEach { it(null) }
        } else {
            systemTts = created
        }
    }

    fun stop() {
        speakJob?.cancel()
        speakJob = null
        pendingSystemOnDone = null
        runCatching { activeWebSocket?.cancel() }
        activeWebSocket = null
        runCatching {
            activePlayer?.stop()
            activePlayer?.release()
        }
        activePlayer = null
        runCatching { systemTts?.stop() }
    }

    fun speak(
        rawText: String,
        engine: String = ENGINE_SYNTH,
        voiceName: String = "",
        pitch: Float = 1.0f,
        speechRate: Float = 1.04f,
        onStart: (() -> Unit)? = null,
        onComplete: (() -> Unit)? = null,
        onError: ((String) -> Unit)? = null,
        onFallback: ((String) -> Unit)? = null,
        onSynthCharProgress: ((Int) -> Unit)? = null,
    ) {
        val clean = cleanTextForSpeech(rawText)
        if (clean.isBlank()) {
            onStart?.invoke()
            onComplete?.invoke()
            return
        }

        val prevJob = speakJob
        stop()
        speakJob = scope.launch {
            runCatching { prevJob?.cancelAndJoin() }
            when (engine.lowercase()) {
                ENGINE_SYNTH -> {
                    val style = voiceName.removePrefix("synth:").ifBlank { "groove_synth" }
                    speakSynthVoice(
                        displayText = rawText,
                        cleanText = clean,
                        voiceStyle = style,
                        pitch = pitch.coerceIn(0.25f, 2.50f),
                        speechRate = speechRate.coerceIn(0.50f, 2.20f),
                        onStart = onStart,
                        onCharProgress = onSynthCharProgress,
                    )
                    if (isActive) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                    }
                    return@launch
                }
                ENGINE_EDGE -> {
                    val chosenVoice = voiceName.takeIf { it.endsWith("Neural", ignoreCase = true) }
                        ?: EDGE_VOICES.first().id
                    val ok = speakEdgeNeural(clean, chosenVoice, pitch, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    withContext(Dispatchers.Main) {
                        onFallback?.invoke("Edge Neural unreachable right now — fell back to Google TTS.")
                    }
                    val gOk = speakGoogleTts(clean, "en-US", pitch, speechRate, onStart)
                    if (gOk) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                ENGINE_POLLY -> {
                    val speaker = voiceName.removePrefix("polly:").takeIf {
                        it.isNotBlank() && !it.contains(':') && !it.endsWith("Neural", true)
                    } ?: "Joanna"
                    val ok = speakPollyTts(clean, speaker, pitch, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    withContext(Dispatchers.Main) {
                        onFallback?.invoke("Polly free endpoint busy or daily limit hit — fell back to Edge Neural.")
                    }
                    val edgeOk = speakEdgeNeural(clean, EDGE_VOICES.first().id, pitch, speechRate, onStart)
                    if (edgeOk) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                ENGINE_TIKTOK -> {
                    val voiceId = voiceName.removePrefix("tiktok:").takeIf {
                        it.isNotBlank() && !it.contains(':') && !it.endsWith("Neural", true)
                    } ?: "en_us_001"
                    val ok = speakTikTokTts(clean, voiceId, pitch, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    withContext(Dispatchers.Main) {
                        onFallback?.invoke("TikTok voice bridge busy — fell back to Edge Neural.")
                    }
                    val edgeOk = speakEdgeNeural(clean, EDGE_VOICES.first().id, pitch, speechRate, onStart)
                    if (edgeOk) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                ENGINE_GOOGLE -> {
                    val lang = voiceName.removePrefix("google:").takeIf {
                        it.isNotBlank() && !it.contains(':') && !it.endsWith("Neural", true)
                    } ?: "en-US"
                    val ok = speakGoogleTts(clean, lang, pitch, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    withContext(Dispatchers.Main) {
                        onFallback?.invoke("Google TTS offline — fell back to System Offline TTS.")
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                else -> {
                    speakSystemInternal(clean, voiceName, pitch, speechRate, onStart, onComplete)
                }
            }
        }
    }

    private suspend fun speakSynthVoice(
        displayText: String,
        cleanText: String,
        voiceStyle: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
        onCharProgress: ((Int) -> Unit)?,
    ) {
        withContext(Dispatchers.Main) { onStart?.invoke() }
        val target = displayText.ifBlank { cleanText }
        val totalLen = target.length
        if (totalLen == 0) return
        val baseCharDelayMs = (36f / speechRate.coerceIn(0.50f, 2.20f)).toLong().coerceIn(14L, 85L)
        var lastChirpAt = 0L
        val minChirpGapMs = (74f / speechRate.coerceIn(0.50f, 2.20f)).toLong().coerceIn(38L, 120L)
        val step = if (totalLen > 240) 2 else 1
        var idx = 0
        while (idx < totalLen && kotlinx.coroutines.currentCoroutineContext().isActive) {
            idx = (idx + step).coerceAtMost(totalLen)
            val ch = target[idx - 1]
            if (onCharProgress != null) {
                val snap = idx
                withContext(Dispatchers.Main) { onCharProgress(snap) }
            }
            if (ch.isLetterOrDigit()) {
                val now = System.currentTimeMillis()
                if (now - lastChirpAt >= minChirpGapMs) {
                    lastChirpAt = now
                    val nearQuestion = target.substring(idx - 1, (idx + 6).coerceAtMost(totalLen)).contains('?')
                    ownedSoundEngine.playSynthChirpForVoice(
                        voiceStyle = voiceStyle,
                        charCodeOrIndex = ch.code,
                        pitch = pitch,
                        isQuestion = nearQuestion,
                        volumeScale = 0.58f,
                    )
                }
            }
            val pauseExtra = when (ch) {
                '.', '!', '?' -> baseCharDelayMs * 3L
                ',', ';', ':' -> baseCharDelayMs * 2L
                else -> 0L
            }
            delay(baseCharDelayMs + pauseExtra)
        }
        if (onCharProgress != null) {
            withContext(Dispatchers.Main) { onCharProgress(totalLen) }
        }
    }

    private suspend fun speakEdgeNeural(
        text: String,
        voiceName: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean {
        val clampedPitch = pitch.coerceIn(0.25f, 2.50f)
        // Edge SSML handles moderate pitch cleanly; apply extra pitch multiplier on MediaPlayer for extreme low/high
        val ssmlPitch = clampedPitch.coerceIn(0.60f, 1.60f)
        val residualMediaPitch = (clampedPitch / ssmlPitch).coerceIn(0.40f, 2.00f)
        val (firstBytes, shouldRetryClock) = synthesizeEdgeAttempt(text, voiceName, ssmlPitch, speechRate)
        val mp3Bytes = if (firstBytes != null && firstBytes.size >= 256) {
            firstBytes
        } else if (shouldRetryClock) {
            synthesizeEdgeAttempt(text, voiceName, ssmlPitch, speechRate).first
        } else {
            null
        }
        if (mp3Bytes == null || mp3Bytes.size < 256) return false
        val cacheFile = File(appContext.cacheDir, "cel_edge_tts.mp3")
        runCatching {
            FileOutputStream(cacheFile).use { it.write(mp3Bytes) }
        }.onFailure { return false }
        return playAudioFileBlocking(cacheFile, pitch = residualMediaPitch, speechRate = 1.0f, onStart = onStart)
    }

    private suspend fun synthesizeEdgeAttempt(
        text: String,
        voiceName: String,
        pitch: Float,
        speechRate: Float,
    ): Pair<ByteArray?, Boolean> = withTimeoutOrNull(18_000L) {
        suspendCancellableCoroutine { cont ->
            val connId = UUID.randomUUID().toString().replace("-", "")
            val gec = EdgeSecMsGecV2.generateToken()
            val muid = EdgeSecMsGecV2.generateMuid()
            val url = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1" +
                "?TrustedClientToken=${EdgeSecMsGecV2.TRUSTED_CLIENT_TOKEN}" +
                "&Sec-MS-GEC=$gec" +
                "&Sec-MS-GEC-Version=${EdgeSecMsGecV2.SEC_MS_GEC_VERSION}" +
                "&ConnectionId=$connId"

            val major = EdgeSecMsGecV2.CHROMIUM_MAJOR_VERSION
            val req = Request.Builder()
                .url(url)
                .header("Pragma", "no-cache")
                .header("Cache-Control", "no-cache")
                .header("Origin", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold")
                .header(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$major.0.0.0 Safari/537.36 Edg/$major.0.0.0",
                )
                .header("Accept-Language", "en-US,en;q=0.9")
                .header("Cookie", "muid=$muid;")
                .build()

            val audioOut = ByteArrayOutputStream()
            val ratePct = ((speechRate.coerceIn(0.50f, 2.20f) - 1.0f) * 100f).roundToInt().coerceIn(-50, 100)
            val rateStr = if (ratePct >= 0) "+${ratePct}%" else "${ratePct}%"
            val pitchHz = ((pitch.coerceIn(0.55f, 1.65f) - 1.0f) * 55f).roundToInt().coerceIn(-45, 65)
            val pitchStr = if (pitchHz >= 0) "+${pitchHz}Hz" else "${pitchHz}Hz"

            val escapedText = text
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&apos;")

            val listener = object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    val ts = edgeTimestamp()
                    val configMsg = "X-Timestamp:$ts\r\n" +
                        "Content-Type:application/json; charset=utf-8\r\n" +
                        "Path:speech.config\r\n\r\n" +
                        "{\"context\":{\"synthesis\":{\"audio\":{\"metadataoptions\":{\"sentenceBoundaryEnabled\":\"false\",\"wordBoundaryEnabled\":\"false\"},\"outputFormat\":\"audio-24khz-48kbitrate-mono-mp3\"}}}}\r\n"
                    webSocket.send(configMsg)

                    val reqId = UUID.randomUUID().toString().replace("-", "")
                    val ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>" +
                        "<voice name='$voiceName'><prosody pitch='$pitchStr' rate='$rateStr' volume='+0%'>$escapedText</prosody></voice></speak>"
                    val ssmlMsg = "X-RequestId:$reqId\r\n" +
                        "Content-Type:application/ssml+xml\r\n" +
                        "X-Timestamp:$ts\r\n" +
                        "Path:ssml\r\n\r\n$ssml"
                    webSocket.send(ssmlMsg)
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (text.contains("Path:turn.end")) {
                        webSocket.close(1000, "done")
                        if (cont.isActive) cont.resume(audioOut.toByteArray() to false)
                    }
                }

                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    val raw = bytes.toByteArray()
                    if (raw.size > 2) {
                        val headerLen = ((raw[0].toInt() and 0xFF) shl 8) or (raw[1].toInt() and 0xFF)
                        val audioOffset = 2 + headerLen
                        if (audioOffset < raw.size) {
                            audioOut.write(raw, audioOffset, raw.size - audioOffset)
                        }
                    }
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    val adjusted = if (response?.code == 403) {
                        EdgeSecMsGecV2.adjustClockSkewFromDateHeader(response.header("Date"))
                    } else {
                        false
                    }
                    DevLogBuffer.add("WARN", "EdgeTTS", "Edge TTS HTTP ${response?.code ?: "?"}: ${t.localizedMessage}")
                    if (cont.isActive) cont.resume(null to adjusted)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    if (cont.isActive) {
                        val data = audioOut.toByteArray()
                        cont.resume((if (data.size > 256) data else null) to false)
                    }
                }
            }

            val ws = httpClient.newWebSocket(req, listener)
            activeWebSocket = ws
            cont.invokeOnCancellation { runCatching { ws.cancel() } }
        }
    } ?: (null to false)

    private fun edgeTimestamp(): String {
        val sdf = SimpleDateFormat("EEE MMM dd yyyy HH:mm:ss 'GMT+0000 (Coordinated Universal Time)'", Locale.US)
        sdf.timeZone = TimeZone.getTimeZone("UTC")
        return sdf.format(Date())
    }

    private suspend fun speakPollyTts(
        text: String,
        speaker: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean {
        val chunks = splitIntoTtsChunks(text, maxChars = 280)
        if (chunks.isEmpty()) return false
        var started = false
        for ((idx, chunk) in chunks.withIndex()) {
            val form = FormBody.Builder()
                .add("msg", chunk)
                .add("lang", speaker)
                .add("source", "ttsmp3")
                .build()
            val req = Request.Builder()
                .url("https://ttsmp3.com/makemp3_new.php")
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143.0.0.0 Mobile Safari/537.36")
                .header("Origin", "https://ttsmp3.com")
                .header("Referer", "https://ttsmp3.com/")
                .post(form)
                .build()

            val mp3Url = runCatching {
                httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@use null
                    val body = resp.body?.string().orEmpty()
                    val obj = json.parseToJsonElement(body).jsonObject
                    val err = obj["Error"]?.jsonPrimitive?.content
                    if (err != null && err != "0") return@use null
                    obj["URL"]?.jsonPrimitive?.content?.takeIf { it.startsWith("http") }
                }
            }.getOrNull() ?: return false

            val audioBytes = runCatching {
                val dlReq = Request.Builder()
                    .url(mp3Url)
                    .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143.0.0.0 Mobile Safari/537.36")
                    .header("Referer", "https://ttsmp3.com/")
                    .build()
                httpClient.newCall(dlReq).execute().use { resp ->
                    if (!resp.isSuccessful) null else resp.body?.bytes()
                }
            }.getOrNull() ?: return false
            if (audioBytes.size < 256) return false

            val cacheFile = File(appContext.cacheDir, "cel_polly_$idx.mp3")
            runCatching { FileOutputStream(cacheFile).use { it.write(audioBytes) } }.onFailure { return false }
            val played = playAudioFileBlocking(
                file = cacheFile,
                pitch = pitch.coerceIn(0.25f, 2.50f),
                speechRate = speechRate.coerceIn(0.50f, 2.20f),
                onStart = if (!started) {
                    started = true
                    onStart
                } else null,
            )
            if (!played) return false
        }
        return true
    }

    private suspend fun speakTikTokTts(
        text: String,
        voiceId: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean {
        val chunks = splitIntoTtsChunks(text, maxChars = 240)
        if (chunks.isEmpty()) return false
        var started = false
        for ((idx, chunk) in chunks.withIndex()) {
            val form = FormBody.Builder()
                .add("service", "TikTok")
                .add("voice", voiceId)
                .add("text", chunk)
                .build()
            val req = Request.Builder()
                .url("https://lazypy.ro/tts/request_tts.php")
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143.0.0.0 Mobile Safari/537.36")
                .header("Origin", "https://lazypy.ro")
                .header("Referer", "https://lazypy.ro/tts/")
                .post(form)
                .build()

            val audioUrl = runCatching {
                httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@use null
                    val body = resp.body?.string().orEmpty()
                    val obj = json.parseToJsonElement(body).jsonObject
                    val ok = obj["success"]?.jsonPrimitive?.booleanOrNull == true
                    if (!ok) return@use null
                    obj["audio_url"]?.jsonPrimitive?.content?.takeIf { it.startsWith("http") }
                }
            }.getOrNull() ?: return false

            val audioBytes = runCatching {
                val dlReq = Request.Builder()
                    .url(audioUrl)
                    .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143.0.0.0 Mobile Safari/537.36")
                    .header("Referer", "https://lazypy.ro/tts/")
                    .build()
                httpClient.newCall(dlReq).execute().use { resp ->
                    if (!resp.isSuccessful) null else resp.body?.bytes()
                }
            }.getOrNull() ?: return false
            if (audioBytes.size < 256) return false

            val cacheFile = File(appContext.cacheDir, "cel_tiktok_$idx.mp3")
            runCatching { FileOutputStream(cacheFile).use { it.write(audioBytes) } }.onFailure { return false }
            val played = playAudioFileBlocking(
                file = cacheFile,
                pitch = pitch.coerceIn(0.25f, 2.50f),
                speechRate = speechRate.coerceIn(0.50f, 2.20f),
                onStart = if (!started) {
                    started = true
                    onStart
                } else null,
            )
            if (!played) return false
        }
        return true
    }

    private suspend fun speakGoogleTts(
        text: String,
        langCode: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean {
        val chunks = splitIntoTtsChunks(text, maxChars = 185)
        if (chunks.isEmpty()) return false
        var started = false
        for ((idx, chunk) in chunks.withIndex()) {
            val encoded = URLEncoder.encode(chunk, "UTF-8")
            val url = "https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=$langCode&q=$encoded"
            val req = Request.Builder()
                .url(url)
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/143.0.0.0 Mobile Safari/537.36")
                .header("Referer", "https://translate.google.com/")
                .build()
            val bytes = runCatching {
                httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) null else resp.body?.bytes()
                }
            }.getOrNull() ?: return false
            if (bytes.size < 128) return false

            val cacheFile = File(appContext.cacheDir, "cel_gtts_$idx.mp3")
            runCatching { FileOutputStream(cacheFile).use { it.write(bytes) } }.onFailure { return false }
            val played = playAudioFileBlocking(
                file = cacheFile,
                pitch = pitch.coerceIn(0.25f, 2.50f),
                speechRate = speechRate.coerceIn(0.50f, 2.20f),
                onStart = if (!started) {
                    started = true
                    onStart
                } else null,
            )
            if (!played) return false
        }
        return true
    }

    private fun splitIntoTtsChunks(text: String, maxChars: Int): List<String> {
        if (text.length <= maxChars) return listOf(text)
        val result = mutableListOf<String>()
        val sentences = text.split(Regex("(?<=[.!?])\\s+"))
        val current = StringBuilder()
        for (s in sentences) {
            if (current.length + s.length + 1 <= maxChars) {
                if (current.isNotEmpty()) current.append(' ')
                current.append(s)
            } else {
                if (current.isNotEmpty()) {
                    result.add(current.toString())
                    current.clear()
                }
                if (s.length <= maxChars) {
                    current.append(s)
                } else {
                    var idx = 0
                    while (idx < s.length) {
                        val end = (idx + maxChars).coerceAtMost(s.length)
                        result.add(s.substring(idx, end))
                        idx = end
                    }
                }
            }
        }
        if (current.isNotEmpty()) result.add(current.toString())
        return result
    }

    private suspend fun playAudioFileBlocking(
        file: File,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean = suspendCancellableCoroutine { cont ->
        runCatching {
            val mp = MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                setDataSource(file.absolutePath)
                setOnPreparedListener { player ->
                    runCatching {
                        if (speechRate != 1.0f || pitch != 1.0f) {
                            player.playbackParams = player.playbackParams
                                .setSpeed(speechRate.coerceIn(0.50f, 2.20f))
                                .setPitch(pitch.coerceIn(0.25f, 2.50f))
                        }
                    }
                    scope.launch(Dispatchers.Main) { onStart?.invoke() }
                    player.start()
                }
                setOnCompletionListener { player ->
                    runCatching { player.release() }
                    if (activePlayer === player) activePlayer = null
                    if (cont.isActive) cont.resume(true)
                }
                setOnErrorListener { player, _, _ ->
                    runCatching { player.release() }
                    if (activePlayer === player) activePlayer = null
                    if (cont.isActive) cont.resume(false)
                    true
                }
                prepareAsync()
            }
            activePlayer = mp
            cont.invokeOnCancellation {
                runCatching {
                    mp.stop()
                    mp.release()
                }
                if (activePlayer === mp) activePlayer = null
            }
        }.onFailure {
            if (cont.isActive) cont.resume(false)
        }
    }

    private suspend fun speakSystemInternal(
        text: String,
        voiceName: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
        onComplete: (() -> Unit)?,
    ) = withContext(Dispatchers.Main) {
        ensureSystemTts { engine ->
            if (engine == null) {
                onStart?.invoke()
                onComplete?.invoke()
                return@ensureSystemTts
            }
            engine.setPitch(pitch.coerceIn(0.25f, 2.50f))
            engine.setSpeechRate(speechRate.coerceIn(0.50f, 2.20f))
            if (voiceName.isNotBlank() &&
                !voiceName.startsWith("synth:") &&
                !voiceName.startsWith("google:") &&
                !voiceName.startsWith("polly:") &&
                !voiceName.startsWith("tiktok:") &&
                !voiceName.endsWith("Neural")
            ) {
                engine.voices?.firstOrNull { it.name == voiceName }?.let { engine.voice = it }
            }
            pendingSystemOnDone = {
                scope.launch(Dispatchers.Main) { onComplete?.invoke() }
            }
            onStart?.invoke()
            val status = runCatching {
                engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "cel_sys_${System.currentTimeMillis()}")
            }.getOrDefault(TextToSpeech.ERROR)
            if (status == TextToSpeech.ERROR) {
                val cb = pendingSystemOnDone
                pendingSystemOnDone = null
                cb?.invoke()
            }
        }
    }

    fun release() {
        stop()
        runCatching { systemTts?.shutdown() }
        systemTts = null
        systemReady = false
        if (sharedSoundEngine == null) {
            runCatching { ownedSoundEngine.release() }
        }
    }
}

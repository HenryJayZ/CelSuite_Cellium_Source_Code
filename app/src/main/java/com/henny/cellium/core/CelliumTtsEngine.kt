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
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
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
import java.security.MessageDigest
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
    val engine: String, // "edge" or "google"
)

/**
 * Unified Multi-Engine Text-to-Speech player for Cel.Cellium:
 *  1) "edge"   — Microsoft Edge Neural Read-Aloud TTS (free, ultra-natural neural voices via WSS)
 *  2) "google" — Google TTS (free online natural voices with automatic sentence chunking)
 *  3) "system" — Local Android TextToSpeech (offline device voices)
 *
 * Automatically falls back cleanly to local Android TTS if the device is offline or a cloud
 * synthesis call fails, so Cel NEVER goes silent.
 */
class CelliumTtsEngine(context: Context) {
    private val appContext = context.applicationContext
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(25, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .build()

    @Volatile private var systemTts: TextToSpeech? = null
    @Volatile private var systemReady: Boolean = false
    @Volatile private var activePlayer: MediaPlayer? = null
    @Volatile private var speakJob: Job? = null
    @Volatile private var activeWebSocket: WebSocket? = null

    private var pendingSystemOnDone: (() -> Unit)? = null

    companion object {
        const val ENGINE_EDGE = "edge"
        const val ENGINE_GOOGLE = "google"
        const val ENGINE_SYSTEM = "system"

        private const val EDGE_TRUSTED_TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4"
        private const val EDGE_CHROMIUM_VER = "143.0.3650.75"
        private const val EDGE_SEC_MS_GEC_VERSION = "1-143.0.3650.75"
        private const val WIN_EPOCH_OFFSET_SEC = 11644473600L

        val EDGE_VOICES: List<TtsVoicePreset> = listOf(
            TtsVoicePreset("en-US-AriaNeural", "Aria", "English (US)", "Female · Expressive", ENGINE_EDGE),
            TtsVoicePreset("en-US-AvaNeural", "Ava", "English (US)", "Female · Warm & Natural", ENGINE_EDGE),
            TtsVoicePreset("en-US-JennyNeural", "Jenny", "English (US)", "Female · Friendly", ENGINE_EDGE),
            TtsVoicePreset("en-US-EmmaNeural", "Emma", "English (US)", "Female · Bright", ENGINE_EDGE),
            TtsVoicePreset("en-US-AnaNeural", "Ana", "English (US)", "Female · Cute / Anime", ENGINE_EDGE),
            TtsVoicePreset("en-US-AndrewNeural", "Andrew", "English (US)", "Male · Warm", ENGINE_EDGE),
            TtsVoicePreset("en-US-GuyNeural", "Guy", "English (US)", "Male · Casual", ENGINE_EDGE),
            TtsVoicePreset("en-US-BrianNeural", "Brian", "English (US)", "Male · Deep", ENGINE_EDGE),
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

        fun cleanTextForSpeech(raw: String): String =
            raw.replace(Regex("```[\\s\\S]*?```"), " code block ")
                .replace(Regex("\\[ILLUME_GEN][\\s\\S]*?\\[/ILLUME_GEN]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("\\[MOOD:[^]]+]", RegexOption.IGNORE_CASE), "")
                .replace(Regex("[`*_#>~|]"), "")
                .replace(Regex("https?://\\S+"), "link")
                .replace(Regex("\\s+"), " ")
                .trim()
                .take(1800)
    }

    private fun ensureSystemTts(onReady: ((TextToSpeech) -> Unit)? = null) {
        val existing = systemTts
        if (existing != null && systemReady) {
            onReady?.invoke(existing)
            return
        }
        if (existing != null) return
        var created: TextToSpeech? = null
        created = TextToSpeech(appContext) { status ->
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
                created?.let { onReady?.invoke(it) }
            }
        }
        systemTts = created
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
        engine: String = ENGINE_EDGE,
        voiceName: String = "",
        pitch: Float = 1.06f,
        speechRate: Float = 1.04f,
        onStart: (() -> Unit)? = null,
        onComplete: (() -> Unit)? = null,
        onError: ((String) -> Unit)? = null,
    ) {
        val clean = cleanTextForSpeech(rawText)
        if (clean.isBlank()) {
            onComplete?.invoke()
            return
        }

        val prevJob = speakJob
        stop()
        speakJob = scope.launch {
            runCatching { prevJob?.cancelAndJoin() }
            when (engine.lowercase()) {
                ENGINE_EDGE -> {
                    val chosenVoice = voiceName.takeIf { it.endsWith("Neural", ignoreCase = true) }
                        ?: EDGE_VOICES.first().id
                    val ok = speakEdgeNeural(clean, chosenVoice, pitch, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    // Graceful fallback to Google TTS, then System TTS if Edge WSS fails/offline
                    val gOk = speakGoogleTts(clean, "en-US", speechRate, onStart)
                    if (gOk) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                ENGINE_GOOGLE -> {
                    val lang = voiceName.removePrefix("google:").ifBlank { "en-US" }
                    val ok = speakGoogleTts(clean, lang, speechRate, onStart)
                    if (ok) {
                        withContext(Dispatchers.Main) { onComplete?.invoke() }
                        return@launch
                    }
                    speakSystemInternal(clean, "", pitch, speechRate, onStart, onComplete)
                }
                else -> {
                    speakSystemInternal(clean, voiceName, pitch, speechRate, onStart, onComplete)
                }
            }
        }
    }

    private suspend fun speakEdgeNeural(
        text: String,
        voiceName: String,
        pitch: Float,
        speechRate: Float,
        onStart: (() -> Unit)?,
    ): Boolean {
        val mp3Bytes = synthesizeEdgeBytes(text, voiceName, pitch, speechRate) ?: return false
        if (mp3Bytes.size < 256) return false
        val cacheFile = File(appContext.cacheDir, "cel_edge_tts.mp3")
        runCatching {
            FileOutputStream(cacheFile).use { it.write(mp3Bytes) }
        }.onFailure { return false }
        return playAudioFileBlocking(cacheFile, speechRate = 1.0f, onStart = onStart)
    }

    private suspend fun synthesizeEdgeBytes(
        text: String,
        voiceName: String,
        pitch: Float,
        speechRate: Float,
    ): ByteArray? = withTimeoutOrNull(18_000L) {
        suspendCancellableCoroutine { cont ->
            val connId = UUID.randomUUID().toString().replace("-", "")
            val gec = generateSecMsGec()
            val url = "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1" +
                "?TrustedClientToken=$EDGE_TRUSTED_TOKEN" +
                "&Sec-MS-GEC=$gec" +
                "&Sec-MS-GEC-Version=$EDGE_SEC_MS_GEC_VERSION" +
                "&ConnectionId=$connId"

            val req = Request.Builder()
                .url(url)
                .header("Pragma", "no-cache")
                .header("Cache-Control", "no-cache")
                .header("Origin", "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold")
                .header(
                    "User-Agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$EDGE_CHROMIUM_VER Safari/537.36 Edg/$EDGE_CHROMIUM_VER",
                )
                .header("Accept-Encoding", "gzip, deflate, br")
                .header("Accept-Language", "en-US,en;q=0.9")
                .build()

            val audioOut = ByteArrayOutputStream()
            val ratePct = ((speechRate.coerceIn(0.65f, 1.65f) - 1.0f) * 100f).roundToInt()
            val rateStr = if (ratePct >= 0) "+${ratePct}%" else "${ratePct}%"
            val pitchHz = ((pitch.coerceIn(0.65f, 1.55f) - 1.0f) * 40f).roundToInt()
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
                        if (cont.isActive) cont.resume(audioOut.toByteArray())
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
                    DevLogBuffer.add("WARN", "EdgeTTS", "Edge TTS fallback: ${t.localizedMessage ?: response?.code}")
                    if (cont.isActive) cont.resume(null)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    if (cont.isActive) {
                        val data = audioOut.toByteArray()
                        cont.resume(if (data.size > 256) data else null)
                    }
                }
            }

            val ws = httpClient.newWebSocket(req, listener)
            activeWebSocket = ws
            cont.invokeOnCancellation { runCatching { ws.cancel() } }
        }
    }

    private fun generateSecMsGec(): String {
        val unixSec = System.currentTimeMillis() / 1000L
        var ticks = unixSec + WIN_EPOCH_OFFSET_SEC
        ticks -= (ticks % 300L) // Round down to nearest 5 minutes
        val filetimeTicks = ticks * 10_000_000L
        val payload = "${filetimeTicks}$EDGE_TRUSTED_TOKEN"
        val digest = MessageDigest.getInstance("SHA-256").digest(payload.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02X".format(it) }
    }

    private fun edgeTimestamp(): String {
        val sdf = SimpleDateFormat("EEE MMM dd yyyy HH:mm:ss 'GMT+0000 (Coordinated Universal Time)'", Locale.US)
        sdf.timeZone = TimeZone.getTimeZone("UTC")
        return sdf.format(Date())
    }

    private suspend fun speakGoogleTts(
        text: String,
        langCode: String,
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
                .header("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0.0.0 Mobile Safari/537.36")
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
                speechRate = speechRate.coerceIn(0.65f, 1.65f),
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
                        if (speechRate != 1.0f) {
                            player.playbackParams = player.playbackParams.setSpeed(speechRate)
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
            engine.setPitch(pitch.coerceIn(0.65f, 1.55f))
            engine.setSpeechRate(speechRate.coerceIn(0.65f, 1.65f))
            if (voiceName.isNotBlank() && !voiceName.startsWith("google:") && !voiceName.endsWith("Neural")) {
                engine.voices?.firstOrNull { it.name == voiceName }?.let { engine.voice = it }
            }
            pendingSystemOnDone = {
                scope.launch(Dispatchers.Main) { onComplete?.invoke() }
            }
            onStart?.invoke()
            engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "cel_sys_${System.currentTimeMillis()}")
        }
    }

    fun release() {
        stop()
        runCatching { systemTts?.shutdown() }
        systemTts = null
        systemReady = false
    }
}

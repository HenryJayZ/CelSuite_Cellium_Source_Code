package com.henny.cellium.core

import android.annotation.SuppressLint
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.speech.RecognitionService
import android.speech.SpeechRecognizer
import android.util.Base64
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.math.sqrt

data class SttEngineOption(
    val id: String,
    val label: String,
    val subtitle: String,
    val defaultModel: String,
    val requiresKey: Boolean,
)

/**
 * Multi-Engine Speech-to-Text (STT) recorder & transcriber for Cel.Cellium:
 *  - "device": Android built-in SpeechRecognizer (handled natively in caller)
 *  - "groq_whisper": Groq Cloud Whisper (BYOK, free tier, live API key model discovery + self-healing fallback)
 *  - "pollinations_audio": Pollinations Free Keyless Audio Transcription
 *  - "openai_whisper": OpenAI Whisper / gpt-4o-mini-transcribe (BYOK, live model discovery)
 *  - "huggingface_whisper": HuggingFace Inference Whisper (BYOK, free tier)
 */
class CelliumSttEngine(context: Context) {
    @Suppress("unused")
    private val appContext = context.applicationContext
    private val json = Json { ignoreUnknownKeys = true }
    private val httpClient = CelliumHttp.clientWithTimeouts(
        connectSec = 20L,
        readSec = 45L,
        writeSec = 30L,
    )

    @Volatile private var manualStopRequested = false
    @Volatile private var cancelRequested = false

    private data class CachedModelList(
        val fetchedAtMs: Long,
        val models: List<String>,
    )

    private val discoveredModelsCache = ConcurrentHashMap<String, CachedModelList>()

    companion object {
        const val ENGINE_DEVICE = "device"
        const val ENGINE_GROQ = "groq_whisper"
        const val ENGINE_POLLINATIONS = "pollinations_audio"
        const val ENGINE_OPENAI = "openai_whisper"
        const val ENGINE_HUGGINGFACE = "huggingface_whisper"

        private const val MODEL_CACHE_TTL_MS = 10 * 60 * 1000L

        private val PREFERRED_RECOGNIZER_PACKAGES = listOf(
            "com.google.android.tts",
            "com.google.android.as",
            "com.google.android.googlequicksearchbox",
            "com.samsung.android.bixby.agent",
            "com.samsung.android.scs",
        )

        /**
         * Creates a system SpeechRecognizer explicitly bound to a real external RecognitionService
         * (excluding Cellium's own stub CelliumRecognitionService, which Android can otherwise select
         * automatically whenever Cellium is set as the Default Digital Assistant).
         */
        fun createBestDeviceSpeechRecognizer(context: Context): SpeechRecognizer? {
            val appCtx = context.applicationContext
            val externalComponent: ComponentName? = runCatching {
                val pm = appCtx.packageManager
                val queryIntent = Intent(RecognitionService.SERVICE_INTERFACE)
                val resolved = pm.queryIntentServices(queryIntent, PackageManager.MATCH_ALL)
                    .mapNotNull { it.serviceInfo }
                    .filter { si -> si.packageName != appCtx.packageName && si.enabled }
                val best = PREFERRED_RECOGNIZER_PACKAGES.firstNotNullOfOrNull { pkg ->
                    resolved.firstOrNull { it.packageName == pkg }
                } ?: resolved.firstOrNull()
                best?.let { ComponentName(it.packageName, it.name) }
            }.getOrNull()

            if (externalComponent != null) {
                val created = runCatching {
                    SpeechRecognizer.createSpeechRecognizer(context, externalComponent)
                }.getOrNull()
                if (created != null) return created
            }
            return if (SpeechRecognizer.isRecognitionAvailable(context)) {
                runCatching { SpeechRecognizer.createSpeechRecognizer(context) }.getOrNull()
            } else {
                null
            }
        }

        val ALL_ENGINES: List<SttEngineOption> = listOf(
            SttEngineOption(
                id = ENGINE_DEVICE,
                label = "Android System",
                subtitle = "Free · Built-in device recognizer with live captions",
                defaultModel = "system",
                requiresKey = false,
            ),
            SttEngineOption(
                id = ENGINE_GROQ,
                label = "Groq Whisper (BYOK)",
                subtitle = "Ultra-accurate & blazing fast · Auto-detects live Whisper models from your Groq key",
                defaultModel = "whisper-large-v3-turbo",
                requiresKey = true,
            ),
            SttEngineOption(
                id = ENGINE_POLLINATIONS,
                label = "Pollinations Audio (Free)",
                subtitle = "Keyless cloud speech recognition · Great accuracy without a key",
                defaultModel = "openai-audio",
                requiresKey = false,
            ),
            SttEngineOption(
                id = ENGINE_OPENAI,
                label = "OpenAI Whisper (BYOK)",
                subtitle = "Studio accuracy · Auto-detects live transcription models from your OpenAI key",
                defaultModel = "whisper-1",
                requiresKey = true,
            ),
            SttEngineOption(
                id = ENGINE_HUGGINGFACE,
                label = "HuggingFace Whisper (BYOK)",
                subtitle = "Free HF Inference tier · Auto-uses HuggingFace token",
                defaultModel = "openai/whisper-large-v3-turbo",
                requiresKey = true,
            ),
        )

        val KNOWN_MODELS_BY_ENGINE: Map<String, List<String>> = mapOf(
            ENGINE_GROQ to listOf(
                "whisper-large-v3-turbo",
                "whisper-large-v3",
                "distil-whisper-large-v3-en",
            ),
            ENGINE_OPENAI to listOf(
                "gpt-4o-mini-transcribe",
                "gpt-4o-transcribe",
                "whisper-1",
            ),
            ENGINE_HUGGINGFACE to listOf(
                "openai/whisper-large-v3-turbo",
                "openai/whisper-large-v3",
                "distil-whisper/distil-large-v3",
                "openai/whisper-medium",
            ),
            ENGINE_POLLINATIONS to listOf("openai-audio"),
        )

        private val WHISPER_SILENCE_HALLUCINATIONS = setOf(
            "you",
            "thank you",
            "thanks",
            "thanks for watching",
            "thank you for watching",
            "bye",
            "bye bye",
            "goodbye",
            "mbc",
            "subtitles by",
            "amara org",
            "um",
            "uh",
            "hmm",
            "hm",
            "oh",
            "ah",
            "silence",
            "music",
            "applause",
            "laughter",
        )

        /**
         * Filters out accidental STT noise outputs like ".", "...", punctuation-only artifacts,
         * and classic Whisper silence hallucinations on very short bursts so they never get posted to chat.
         */
        fun sanitizeTranscript(raw: String, speechDurationMs: Long = 2000L): String {
            val trimmed = raw.trim()
            if (trimmed.isEmpty()) return ""
            val alphaNumOnly = trimmed.filter { it.isLetterOrDigit() }
            if (alphaNumOnly.isEmpty()) return ""
            val normalized = trimmed
                .lowercase()
                .replace(Regex("[^a-z0-9\\s]"), " ")
                .replace(Regex("\\s+"), " ")
                .trim()
            if (normalized.isEmpty()) return ""
            if (speechDurationMs < 1100L && normalized in WHISPER_SILENCE_HALLUCINATIONS) {
                return ""
            }
            if (normalized.startsWith("subtitles by") || normalized.startsWith("transcribed by") || normalized.contains("amara.org")) {
                return ""
            }
            return trimmed
        }
    }

    fun requestStopRecording() {
        manualStopRequested = true
    }

    fun cancelRecording() {
        cancelRequested = true
        manualStopRequested = true
    }

    /**
     * Pings the selected STT provider's live `/models` endpoint with the user's API key
     * and returns the available speech-to-text / Whisper model IDs sorted by speed & quality.
     */
    suspend fun fetchAvailableSttModels(
        engineId: String,
        apiKey: String,
        forceRefresh: Boolean = true,
    ): Result<List<String>> = withContext(Dispatchers.IO) {
        fetchAvailableSttModelsSync(engineId, apiKey.trim(), forceRefresh)
    }

    private fun fetchAvailableSttModelsSync(
        engineId: String,
        apiKey: String,
        forceRefresh: Boolean,
    ): Result<List<String>> = runCatching {
        if (apiKey.isBlank()) {
            throw IllegalStateException("No API key found for $engineId.")
        }
        val cacheKey = "$engineId:${apiKey.hashCode()}"
        if (!forceRefresh) {
            val cached = discoveredModelsCache[cacheKey]
            if (cached != null && (System.currentTimeMillis() - cached.fetchedAtMs) < MODEL_CACHE_TTL_MS) {
                return@runCatching cached.models
            }
        }

        val models = when (engineId) {
            ENGINE_GROQ -> fetchOpenAiCompatibleAudioModels(
                url = "https://api.groq.com/openai/v1/models",
                apiKey = apiKey,
                preferredOrder = listOf(
                    "whisper-large-v3-turbo",
                    "whisper-large-v3",
                    "distil-whisper-large-v3-en",
                ),
            )
            ENGINE_OPENAI -> fetchOpenAiCompatibleAudioModels(
                url = "https://api.openai.com/v1/models",
                apiKey = apiKey,
                preferredOrder = listOf(
                    "gpt-4o-mini-transcribe",
                    "gpt-4o-transcribe",
                    "whisper-1",
                ),
            )
            ENGINE_HUGGINGFACE -> {
                val req = Request.Builder()
                    .url("https://huggingface.co/api/whoami-v2")
                    .header("Authorization", "Bearer $apiKey")
                    .get()
                    .build()
                httpClient.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        throw IllegalStateException("HuggingFace key check failed (HTTP ${resp.code}).")
                    }
                }
                KNOWN_MODELS_BY_ENGINE[ENGINE_HUGGINGFACE].orEmpty()
            }
            else -> KNOWN_MODELS_BY_ENGINE[engineId].orEmpty()
        }

        discoveredModelsCache[cacheKey] = CachedModelList(System.currentTimeMillis(), models)
        models
    }

    private fun fetchOpenAiCompatibleAudioModels(
        url: String,
        apiKey: String,
        preferredOrder: List<String>,
    ): List<String> {
        val req = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $apiKey")
            .get()
            .build()
        httpClient.newCall(req).execute().use { resp ->
            val raw = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("Key check HTTP ${resp.code}: ${raw.take(160)}")
            }
            val root = json.parseToJsonElement(raw).jsonObject
            val data = root["data"]?.jsonArray.orEmpty()
            val allIds = data.mapNotNull { el ->
                el.jsonObject["id"]?.jsonPrimitive?.content?.trim()?.takeIf { it.isNotBlank() }
            }
            val audioIds = allIds.filter { id ->
                val low = id.lowercase()
                val looksStt = low.contains("whisper") ||
                    low.contains("transcrib") ||
                    low.contains("stt") ||
                    low.contains("asr")
                val looksTtsOnly = low.contains("tts") || low.contains("orpheus") || low.contains("playai")
                looksStt && !looksTtsOnly
            }.distinct()

            return audioIds.sortedWith(
                compareBy<String> { id ->
                    val idx = preferredOrder.indexOfFirst { it.equals(id, ignoreCase = true) }
                    if (idx >= 0) idx else 100
                }.thenBy { it }
            )
        }
    }

    private fun sanitizeModelForEngine(engineId: String, rawModel: String): String {
        val trimmed = rawModel.trim()
        if (trimmed.isBlank()) return ""
        return when (engineId) {
            ENGINE_GROQ -> {
                if (trimmed.equals("system", true) ||
                    trimmed.equals("openai-audio", true) ||
                    trimmed.contains("/")
                ) "" else trimmed
            }
            ENGINE_OPENAI -> {
                if (trimmed.equals("system", true) ||
                    trimmed.equals("openai-audio", true) ||
                    trimmed.contains("/")
                ) "" else trimmed
            }
            ENGINE_HUGGINGFACE -> {
                if (trimmed.equals("system", true) ||
                    trimmed.equals("openai-audio", true)
                ) "" else trimmed
            }
            else -> trimmed
        }
    }

    private fun isModelNotFoundError(msg: String): Boolean {
        val low = msg.lowercase()
        return low.contains("model") && (
            low.contains("does not exist") ||
                low.contains("not_found") ||
                low.contains("not found") ||
                low.contains("decommissioned") ||
                low.contains("not supported") ||
                low.contains("invalid") ||
                low.contains("http 404") ||
                low.contains("http 400")
            )
    }

    /**
     * Records microphone audio until silence-after-speech (VAD) or [requestStopRecording] is called,
     * then transcribes using the selected cloud STT engine.
     */
    @SuppressLint("MissingPermission")
    suspend fun recordAndTranscribe(
        engineId: String,
        apiKey: String,
        modelOverride: String = "",
        maxDurationMs: Long = 180_000L,
        preSpeechTimeoutMs: Long = 60_000L,
        silenceAutoStopMs: Long = 3_500L,
        manualStopOnly: Boolean = false,
        onReadyForSpeech: () -> Unit = {},
        onRmsLevel: (Float) -> Unit = {},
        onElapsedSeconds: (Int) -> Unit = {},
        onTranscribing: () -> Unit = {},
        onModelAutoSelected: (String) -> Unit = {},
    ): Result<String> = withContext(Dispatchers.IO) {
        manualStopRequested = false
        cancelRequested = false
        val sampleRate = 16000
        val minBuf = AudioRecord.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        ).coerceAtLeast(3200)

        val recorder = runCatching {
            AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                minBuf * 2,
            )
        }.getOrElse {
            return@withContext Result.failure(IllegalStateException("Could not open microphone: ${it.localizedMessage}"))
        }

        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            runCatching { recorder.release() }
            return@withContext Result.failure(IllegalStateException("Microphone initialization failed."))
        }

        val pcmOut = ByteArrayOutputStream(64 * 1024)
        val buf = ShortArray(1024)
        val byteScratch = ByteArray(buf.size * 2)
        var speechDetected = false
        var speechStartMs = 0L
        var consecutiveSpeechFrames = 0
        var lastSpeechMs = System.currentTimeMillis()
        val startMs = System.currentTimeMillis()
        var lastReportedSec = -1

        var ambientRms = 180f
        var calibratedFrames = 0

        try {
            recorder.startRecording()
            withContext(Dispatchers.Main) {
                onReadyForSpeech()
                onElapsedSeconds(0)
            }

            while (currentCoroutineContext().isActive && !manualStopRequested && !cancelRequested) {
                val read = recorder.read(buf, 0, buf.size)
                if (read > 0) {
                    var sumSq = 0.0
                    for (i in 0 until read) {
                        val s = buf[i].toInt()
                        sumSq += s.toDouble() * s.toDouble()
                        byteScratch[i * 2] = (s and 0xFF).toByte()
                        byteScratch[i * 2 + 1] = ((s shr 8) and 0xFF).toByte()
                    }
                    pcmOut.write(byteScratch, 0, read * 2)

                    val rms = sqrt(sumSq / read).toFloat()
                    val now = System.currentTimeMillis()
                    val elapsedSec = ((now - startMs) / 1000L).toInt()
                    if (elapsedSec != lastReportedSec) {
                        lastReportedSec = elapsedSec
                        withContext(Dispatchers.Main) { onElapsedSeconds(elapsedSec) }
                    }

                    val normLevel = ((rms - (ambientRms * 0.7f)) / 3200f).coerceIn(0.05f, 0.98f)
                    withContext(Dispatchers.Main) { onRmsLevel(normLevel) }

                    if (!manualStopOnly) {
                        if (calibratedFrames < 6) {
                            ambientRms = if (calibratedFrames == 0) rms.coerceIn(55f, 600f)
                            else (ambientRms * 0.72f + rms.coerceIn(55f, 600f) * 0.28f)
                            calibratedFrames++
                        } else if (!speechDetected && rms < ambientRms * 1.45f) {
                            ambientRms = (ambientRms * 0.96f + rms.coerceIn(55f, 600f) * 0.04f)
                        }

                        // Peak-envelope VAD with natural breath grace window (>= 2.2s silence required)
                        val crispPeakThreshold = maxOf(460f, ambientRms * 2.60f)
                        val onsetThreshold = maxOf(260f, ambientRms * 1.85f)
                        val holdThreshold = maxOf(135f, ambientRms * 1.20f)

                        if (!speechDetected) {
                            if (rms >= crispPeakThreshold) {
                                speechDetected = true
                                speechStartMs = now
                                lastSpeechMs = now
                                consecutiveSpeechFrames = 2
                            } else if (rms >= onsetThreshold) {
                                consecutiveSpeechFrames++
                                if (consecutiveSpeechFrames >= 2) {
                                    speechDetected = true
                                    speechStartMs = now
                                    lastSpeechMs = now
                                }
                            } else {
                                consecutiveSpeechFrames = 0
                                if (now - startMs >= preSpeechTimeoutMs) {
                                    break
                                }
                            }
                        } else {
                            if (rms >= holdThreshold) {
                                lastSpeechMs = now
                            }
                            // Always wait at least 2.2s of true silence so natural breath pauses never cut off speech
                            val effectiveSilenceMs = maxOf(silenceAutoStopMs, 2_200L)
                            if (now - lastSpeechMs >= effectiveSilenceMs) {
                                break
                            }
                        }
                    }

                    val effectiveMaxMs = if (manualStopOnly) maxOf(maxDurationMs, 300_000L) else maxDurationMs
                    if (now - startMs >= effectiveMaxMs) {
                        break
                    }
                }
            }
        } catch (ce: CancellationException) {
            throw ce
        } finally {
            runCatching { recorder.stop() }
            runCatching { recorder.release() }
        }

        if (cancelRequested) {
            return@withContext Result.success("")
        }

        val pcmBytes = pcmOut.toByteArray()
        if (pcmBytes.size < 4000 || (!manualStopOnly && !speechDetected && !manualStopRequested)) {
            return@withContext Result.success("")
        }

        val speechDurationMs = if (speechStartMs > 0L) (lastSpeechMs - speechStartMs).coerceAtLeast(200L) else 2000L
        withContext(Dispatchers.Main) { onTranscribing() }
        val wavBytes = wrapPcmAsWav(pcmBytes, sampleRate)
        transcribeWav(engineId, apiKey.trim(), modelOverride.trim(), wavBytes, onModelAutoSelected)
            .map { raw -> sanitizeTranscript(raw, speechDurationMs) }
    }

    private fun transcribeWav(
        engineId: String,
        apiKey: String,
        modelOverride: String,
        wavBytes: ByteArray,
        onModelAutoSelected: (String) -> Unit,
    ): Result<String> = runCatching {
        when (engineId) {
            ENGINE_GROQ -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("Groq Whisper needs a Groq API key. Add it in Providers (Groq) or Voice Settings.")
                }
                transcribeWithDiscoveryRetry(
                    engineId = ENGINE_GROQ,
                    endpointUrl = "https://api.groq.com/openai/v1/audio/transcriptions",
                    apiKey = apiKey,
                    rawModelOverride = modelOverride,
                    fallbackDefault = "whisper-large-v3-turbo",
                    wavBytes = wavBytes,
                    onModelAutoSelected = onModelAutoSelected,
                )
            }
            ENGINE_OPENAI -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("OpenAI Whisper needs an OpenAI API key. Add it in Providers (OpenAI) or Voice Settings.")
                }
                transcribeWithDiscoveryRetry(
                    engineId = ENGINE_OPENAI,
                    endpointUrl = "https://api.openai.com/v1/audio/transcriptions",
                    apiKey = apiKey,
                    rawModelOverride = modelOverride,
                    fallbackDefault = "whisper-1",
                    wavBytes = wavBytes,
                    onModelAutoSelected = onModelAutoSelected,
                )
            }
            ENGINE_HUGGINGFACE -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("HuggingFace Whisper needs a HuggingFace token. Add it in Providers or Voice Settings.")
                }
                val model = sanitizeModelForEngine(ENGINE_HUGGINGFACE, modelOverride)
                    .ifBlank { "openai/whisper-large-v3-turbo" }
                val req = Request.Builder()
                    .url("https://router.huggingface.co/hf-inference/models/$model")
                    .header("Authorization", "Bearer $apiKey")
                    .post(wavBytes.toRequestBody("audio/wav".toMediaType()))
                    .build()
                httpClient.newCall(req).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) {
                        throw IllegalStateException("HuggingFace STT HTTP ${resp.code}: ${body.take(160)}")
                    }
                    val root = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
                    root?.get("text")?.jsonPrimitive?.content?.trim().orEmpty()
                }
            }
            ENGINE_POLLINATIONS -> {
                val b64 = Base64.encodeToString(wavBytes, Base64.NO_WRAP)
                val payload = buildJsonObject {
                    put("model", modelOverride.ifBlank { "openai-audio" })
                    put("messages", buildJsonArray {
                        add(buildJsonObject {
                            put("role", "user")
                            put("content", buildJsonArray {
                                add(buildJsonObject {
                                    put("type", "text")
                                    put("text", "Transcribe the spoken words in this audio clip accurately. Output ONLY the exact transcription with no extra commentary.")
                                })
                                add(buildJsonObject {
                                    put("type", "input_audio")
                                    put("input_audio", buildJsonObject {
                                        put("data", b64)
                                        put("format", "wav")
                                    })
                                })
                            })
                        })
                    })
                }.toString()

                val req = Request.Builder()
                    .url("https://text.pollinations.ai/openai")
                    .header("Content-Type", "application/json")
                    .post(payload.toRequestBody("application/json".toMediaType()))
                    .build()
                httpClient.newCall(req).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) {
                        throw IllegalStateException("Pollinations Audio STT HTTP ${resp.code}: ${body.take(160)}")
                    }
                    val root = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
                    val text = root?.get("choices")?.jsonArray?.firstOrNull()
                        ?.jsonObject?.get("message")?.jsonObject?.get("content")?.jsonPrimitive?.content
                        ?: body
                    text.trim().removeSurrounding("\"")
                }
            }
            else -> ""
        }
    }

    private fun transcribeWithDiscoveryRetry(
        engineId: String,
        endpointUrl: String,
        apiKey: String,
        rawModelOverride: String,
        fallbackDefault: String,
        wavBytes: ByteArray,
        onModelAutoSelected: (String) -> Unit,
    ): String {
        val sanitized = sanitizeModelForEngine(engineId, rawModelOverride)
        var chosenModel = sanitized
        if (chosenModel.isBlank()) {
            val discovered = fetchAvailableSttModelsSync(engineId, apiKey, forceRefresh = false).getOrNull().orEmpty()
            chosenModel = discovered.firstOrNull() ?: fallbackDefault
            if (discovered.isNotEmpty()) {
                onModelAutoSelected(chosenModel)
            }
        }

        return try {
            transcribeOpenAiCompatible(endpointUrl, apiKey, chosenModel, wavBytes)
        } catch (firstErr: Exception) {
            val msg = firstErr.message.orEmpty()
            if (!isModelNotFoundError(msg)) throw firstErr

            // Self-heal: ping the API key live to find an enabled speech model and retry once
            val freshModels = fetchAvailableSttModelsSync(engineId, apiKey, forceRefresh = true).getOrNull().orEmpty()
            val candidate = freshModels.firstOrNull { !it.equals(chosenModel, ignoreCase = true) }
                ?: KNOWN_MODELS_BY_ENGINE[engineId].orEmpty().firstOrNull { !it.equals(chosenModel, ignoreCase = true) }
                ?: throw firstErr

            DevLogBuffer.add("INFO", "STT", "Model '$chosenModel' unavailable on key; auto-switching to '$candidate'")
            val result = transcribeOpenAiCompatible(endpointUrl, apiKey, candidate, wavBytes)
            onModelAutoSelected(candidate)
            result
        }
    }

    private fun transcribeOpenAiCompatible(
        url: String,
        apiKey: String,
        model: String,
        wavBytes: ByteArray,
    ): String {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                "speech.wav",
                wavBytes.toRequestBody("audio/wav".toMediaType()),
            )
            .addFormDataPart("model", model)
            .addFormDataPart("response_format", "json")
            .build()

        val req = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $apiKey")
            .post(body)
            .build()

        httpClient.newCall(req).execute().use { resp ->
            val raw = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("Whisper STT HTTP ${resp.code}: ${raw.take(180)}")
            }
            val root = runCatching { json.parseToJsonElement(raw).jsonObject }.getOrNull()
            return root?.get("text")?.jsonPrimitive?.content?.trim().orEmpty()
        }
    }

    private fun wrapPcmAsWav(pcm: ByteArray, sampleRate: Int): ByteArray {
        val dataSize = pcm.size
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray())
            putInt(36 + dataSize)
            put("WAVE".toByteArray())
            put("fmt ".toByteArray())
            putInt(16)
            putShort(1) // PCM
            putShort(1) // Mono
            putInt(sampleRate)
            putInt(sampleRate * 2)
            putShort(2)
            putShort(16)
            put("data".toByteArray())
            putInt(dataSize)
        }.array()
        val out = ByteArray(44 + dataSize)
        System.arraycopy(header, 0, out, 0, 44)
        System.arraycopy(pcm, 0, out, 44, dataSize)
        return out
    }
}

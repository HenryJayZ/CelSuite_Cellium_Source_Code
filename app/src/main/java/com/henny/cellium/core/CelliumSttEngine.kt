package com.henny.cellium.core

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Base64
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
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
 *  - "groq_whisper": Groq Cloud Whisper-large-v3-turbo (BYOK, free tier, ultra-fast & super accurate!)
 *  - "pollinations_audio": Pollinations Free Keyless Audio Transcription (no API key needed!)
 *  - "openai_whisper": OpenAI Whisper / gpt-4o-mini-transcribe (BYOK)
 *  - "huggingface_whisper": HuggingFace Inference Whisper-large-v3-turbo (BYOK, free tier)
 *
 * Uses crisp 16kHz 16-bit mono PCM WAV recording with real-time RMS level callbacks and
 * smart Voice Activity Detection (auto-stops cleanly ~1.35s after you finish speaking, or on manual stop!).
 */
class CelliumSttEngine(context: Context) {
    @Suppress("unused")
    private val appContext = context.applicationContext
    private val json = Json { ignoreUnknownKeys = true }
    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    @Volatile private var manualStopRequested = false

    companion object {
        const val ENGINE_DEVICE = "device"
        const val ENGINE_GROQ = "groq_whisper"
        const val ENGINE_POLLINATIONS = "pollinations_audio"
        const val ENGINE_OPENAI = "openai_whisper"
        const val ENGINE_HUGGINGFACE = "huggingface_whisper"

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
                subtitle = "Ultra-accurate & blazing fast · Free Groq tier · Auto-uses Groq provider key",
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
                subtitle = "Studio accuracy · Auto-uses OpenAI provider key",
                defaultModel = "whisper-1",
                requiresKey = true,
            ),
            SttEngineOption(
                id = ENGINE_HUGGINGFACE,
                label = "HuggingFace Whisper (BYOK)",
                subtitle = "Free HF Inference tier · Auto-uses HuggingFace key",
                defaultModel = "openai/whisper-large-v3-turbo",
                requiresKey = true,
            ),
        )
    }

    fun requestStopRecording() {
        manualStopRequested = true
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
        maxDurationMs: Long = 22_000L,
        silenceAutoStopMs: Long = 1_350L,
        onReadyForSpeech: () -> Unit = {},
        onRmsLevel: (Float) -> Unit = {},
        onTranscribing: () -> Unit = {},
    ): Result<String> = withContext(Dispatchers.IO) {
        manualStopRequested = false
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

        val pcmOut = ByteArrayOutputStream()
        val buf = ShortArray(1024)
        var speechDetected = false
        var lastSpeechMs = System.currentTimeMillis()
        val startMs = System.currentTimeMillis()

        try {
            recorder.startRecording()
            withContext(Dispatchers.Main) { onReadyForSpeech() }

            while (currentCoroutineContext().isActive && !manualStopRequested) {
                val read = recorder.read(buf, 0, buf.size)
                if (read > 0) {
                    var sumSq = 0.0
                    val bytes = ByteArray(read * 2)
                    for (i in 0 until read) {
                        val s = buf[i].toInt()
                        sumSq += s.toDouble() * s.toDouble()
                        bytes[i * 2] = (s and 0xFF).toByte()
                        bytes[i * 2 + 1] = ((s shr 8) and 0xFF).toByte()
                    }
                    pcmOut.write(bytes)

                    val rms = sqrt(sumSq / read).toFloat()
                    val normLevel = ((rms - 180f) / 3600f).coerceIn(0.05f, 0.95f)
                    withContext(Dispatchers.Main) { onRmsLevel(normLevel) }

                    val now = System.currentTimeMillis()
                    if (rms > 580f) {
                        speechDetected = true
                        lastSpeechMs = now
                    }
                    if (speechDetected && now - lastSpeechMs >= silenceAutoStopMs) {
                        break
                    }
                    if (!speechDetected && now - startMs >= 7_500L) {
                        break
                    }
                    if (now - startMs >= maxDurationMs) {
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

        val pcmBytes = pcmOut.toByteArray()
        if (pcmBytes.size < 4000 || (!speechDetected && !manualStopRequested)) {
            return@withContext Result.success("")
        }

        withContext(Dispatchers.Main) { onTranscribing() }
        val wavBytes = wrapPcmAsWav(pcmBytes, sampleRate)
        transcribeWav(engineId, apiKey.trim(), modelOverride.trim(), wavBytes)
    }

    private fun transcribeWav(
        engineId: String,
        apiKey: String,
        modelOverride: String,
        wavBytes: ByteArray,
    ): Result<String> = runCatching {
        when (engineId) {
            ENGINE_GROQ -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("Groq Whisper needs a Groq API key. Add it in Providers (Groq) or Voice Settings.")
                }
                val model = modelOverride.ifBlank { "whisper-large-v3-turbo" }
                transcribeOpenAiCompatible(
                    url = "https://api.groq.com/openai/v1/audio/transcriptions",
                    apiKey = apiKey,
                    model = model,
                    wavBytes = wavBytes,
                )
            }
            ENGINE_OPENAI -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("OpenAI Whisper needs an OpenAI API key. Add it in Providers (OpenAI) or Voice Settings.")
                }
                val model = modelOverride.ifBlank { "whisper-1" }
                transcribeOpenAiCompatible(
                    url = "https://api.openai.com/v1/audio/transcriptions",
                    apiKey = apiKey,
                    model = model,
                    wavBytes = wavBytes,
                )
            }
            ENGINE_HUGGINGFACE -> {
                if (apiKey.isBlank()) {
                    throw IllegalStateException("HuggingFace Whisper needs a HuggingFace token. Add it in Providers or Voice Settings.")
                }
                val model = modelOverride.ifBlank { "openai/whisper-large-v3-turbo" }
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

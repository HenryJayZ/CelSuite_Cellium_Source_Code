package com.henny.cellium.ai

import android.graphics.Bitmap
import android.util.Base64
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.data.PersonaSpec
import com.henny.cellium.data.local.MemoryEntity
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

data class StreamChunk(
    val contentDelta: String = "",
    val thoughtDelta: String = "",
)

/**
 * Universal Multi-Provider AI Bridge for Cel.Cellium (200+ providers).
 * Supports keyless free providers (Pollinations AI with automatic mirror fallback),
 * any OpenAI-compatible provider, native Anthropic Messages, raw file attachments, and vision.
 */
class UniversalLlmClient {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val mediaTypeJson = "application/json; charset=utf-8".toMediaType()

    private val client = OkHttpClient.Builder()
        .connectTimeout(25, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    fun buildSystemPrompt(
        persona: PersonaSpec,
        memories: List<MemoryEntity>,
        agentModeEnabled: Boolean,
        shizukuConnected: Boolean,
        extraInstruction: String = "",
    ): String = buildString {
        append(persona.systemPrompt.trim())
        val activeMemories = memories.filter { it.enabled && it.content.isNotBlank() }
        if (activeMemories.isNotEmpty()) {
            append("\n\n[Persistent User Memories]\n")
            activeMemories.forEach { m ->
                append("- ${m.title}: ${m.content}\n")
            }
        }
        if (agentModeEnabled) {
            append("\n\n[Cel.Cellium Android Agent Mode]\n")
            append(
                if (shizukuConnected) {
                    "You have privileged Android Shizuku shell access. When the user asks to inspect the device, run diagnostics, list packages, check RAM/battery, or execute shell commands, emit EXACTLY ONE command wrapped in:\n[SHIZUKU_RUN]\n<command>\n[/SHIZUKU_RUN]\nWait for the tool output before summarizing results. Never suggest destructive commands."
                } else {
                    "Agent Mode is toggled ON, but Shizuku is not currently connected. If the user asks for a device command, explain briefly how to authorize Shizuku in Settings -> System & Shizuku or still provide a [SHIZUKU_RUN] block for them to review."
                }
            )
        }
        if (extraInstruction.isNotBlank()) {
            append("\n\n").append(extraInstruction.trim())
        }
    }

    suspend fun fetchModels(provider: ProviderProfileEntity): Result<List<String>> = withContext(Dispatchers.IO) {
        if (provider.protocol == "on_device") {
            return@withContext Result.success(
                listOf(provider.selectedModel.ifBlank { "No local model loaded" })
            )
        }
        val cleanBase = provider.baseUrl.trim().trimEnd('/')
        if (cleanBase.isBlank()) {
            return@withContext Result.failure(IllegalArgumentException("Base URL cannot be empty."))
        }
        val key = provider.apiKey.trim()
        val isLocalNetwork = cleanBase.contains("127.0.0.1") ||
            cleanBase.contains("localhost") ||
            cleanBase.contains("192.168.") ||
            cleanBase.contains("10.")
        val isKeyless = !provider.requiresKey || provider.id == ProviderPresets.ID_POLLINATIONS_FREE
        if (key.isBlank() && !isLocalNetwork && !isKeyless) {
            return@withContext Result.failure(
                IllegalStateException("Enter your ${provider.name} API key first so Cellium can ping the key and fetch its live models.")
            )
        }

        // 1. Google AI Studio / Gemini API: query native paginated /v1beta/models?key=... to get EVERY live model on the key
        if (cleanBase.contains("generativelanguage.googleapis.com", ignoreCase = true)) {
            val googleRes = fetchAllGoogleAiModels(key)
            if (googleRes.isSuccess && googleRes.getOrNull().orEmpty().isNotEmpty()) {
                return@withContext googleRes
            }
            // Fallback to OpenAI-compatible /models if native failed
            val openaiRes = fetchModelsFromUrl("$cleanBase/models", provider)
            return@withContext if (openaiRes.isSuccess) openaiRes else googleRes
        }

        // 2. Anthropic native /models with pagination
        if (provider.protocol == "anthropic") {
            return@withContext fetchAllAnthropicModels(cleanBase, provider)
        }

        // 3. Ollama local server (/v1/models OR native /api/tags)
        if (cleanBase.contains(":11434")) {
            val primary = fetchModelsFromUrl("$cleanBase/models", provider)
            if (primary.isSuccess && primary.getOrNull().orEmpty().isNotEmpty()) return@withContext primary
            val tagsUrl = cleanBase.removeSuffix("/v1") + "/api/tags"
            return@withContext fetchModelsFromUrl(tagsUrl, provider)
        }

        // 4. Pollinations AI (Keyless Free): ping live /models endpoint directly
        if (provider.id == ProviderPresets.ID_POLLINATIONS_FREE) {
            val res = fetchModelsFromUrl("$cleanBase/models", provider)
            if (res.isSuccess && res.getOrNull().orEmpty().isNotEmpty()) return@withContext res
            return@withContext fetchModelsFromUrl("https://text.pollinations.ai/models", provider)
        }

        // 5. Standard OpenAI-compatible /models (OpenRouter, OpenAI, Groq, DeepSeek, xAI, Mistral, Together, Fireworks, etc.)
        fetchModelsFromUrl("$cleanBase/models", provider)
    }

    private fun fetchAllGoogleAiModels(apiKey: String): Result<List<String>> = runCatching {
        val collected = LinkedHashSet<String>()
        var pageToken: String? = null
        var pages = 0
        do {
            val url = buildString {
                append("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&key=")
                append(java.net.URLEncoder.encode(apiKey, "UTF-8"))
                if (!pageToken.isNullOrBlank()) {
                    append("&pageToken=").append(java.net.URLEncoder.encode(pageToken, "UTF-8"))
                }
            }
            val req = Request.Builder()
                .url(url)
                .header("User-Agent", "Cel.Cellium-Android/2611.21.0")
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                val bodyStr = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw IllegalStateException("Google AI HTTP ${resp.code}: ${extractApiError(bodyStr)}")
                }
                val root = json.parseToJsonElement(bodyStr).jsonObject
                val arr = root["models"]?.jsonArray ?: JsonArray(emptyList())
                arr.forEach { el ->
                    val obj = el as? JsonObject ?: return@forEach
                    val rawName = obj["name"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
                    if (rawName.isNotBlank()) {
                        collected.add(rawName.removePrefix("models/"))
                    }
                }
                pageToken = root["nextPageToken"]?.jsonPrimitive?.contentOrNull
            }
            pages++
        } while (!pageToken.isNullOrBlank() && pages < 10)

        val sorted = collected.toList().sorted()
        DevLogBuffer.add("INFO", "Models", "Google AI live key ping returned ${sorted.size} models")
        sorted
    }.onFailure { err ->
        DevLogBuffer.add("ERROR", "Models", "Google AI key fetch failed: ${err.localizedMessage}")
    }

    private fun fetchAllAnthropicModels(cleanBase: String, provider: ProviderProfileEntity): Result<List<String>> = runCatching {
        val collected = LinkedHashSet<String>()
        var afterId: String? = null
        var pages = 0
        do {
            val url = buildString {
                append("$cleanBase/models?limit=1000")
                if (!afterId.isNullOrBlank()) append("&after_id=").append(afterId)
            }
            val reqBuilder = Request.Builder().url(url).get()
            applyAuthHeaders(reqBuilder, provider)
            client.newCall(reqBuilder.build()).execute().use { resp ->
                val bodyStr = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw IllegalStateException("Anthropic HTTP ${resp.code}: ${extractApiError(bodyStr)}")
                }
                val root = json.parseToJsonElement(bodyStr).jsonObject
                val arr = root["data"]?.jsonArray ?: JsonArray(emptyList())
                arr.forEach { el ->
                    val id = (el as? JsonObject)?.get("id")?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
                    if (id.isNotBlank()) collected.add(id)
                }
                val hasMore = root["has_more"]?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull() == true
                afterId = if (hasMore) root["last_id"]?.jsonPrimitive?.contentOrNull else null
            }
            pages++
        } while (!afterId.isNullOrBlank() && pages < 10)

        val sorted = collected.toList().sorted()
        DevLogBuffer.add("INFO", "Models", "Anthropic live key ping returned ${sorted.size} models")
        sorted
    }.onFailure { err ->
        DevLogBuffer.add("ERROR", "Models", "Anthropic key fetch failed: ${err.localizedMessage}")
    }

    private fun fetchModelsFromUrl(url: String, provider: ProviderProfileEntity): Result<List<String>> {
        val reqBuilder = Request.Builder().url(url).get()
        applyAuthHeaders(reqBuilder, provider)
        return runCatching {
            client.newCall(reqBuilder.build()).execute().use { resp ->
                val bodyStr = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw IllegalStateException("HTTP ${resp.code}: ${extractApiError(bodyStr)}")
                }
                val parsedEl = json.parseToJsonElement(bodyStr)
                val dataArr = when (parsedEl) {
                    is JsonArray -> parsedEl
                    is JsonObject -> parsedEl["data"]?.jsonArray
                        ?: parsedEl["models"]?.jsonArray
                        ?: parsedEl["items"]?.jsonArray
                        ?: JsonArray(emptyList())
                    else -> JsonArray(emptyList())
                }
                val ids = dataArr.mapNotNull { el ->
                    when (el) {
                        is JsonObject -> (el["id"]?.jsonPrimitive?.contentOrNull
                            ?: el["name"]?.jsonPrimitive?.contentOrNull
                            ?: el["model"]?.jsonPrimitive?.contentOrNull)
                            ?.trim()
                            ?.removePrefix("models/")
                        is JsonPrimitive -> el.contentOrNull?.trim()?.removePrefix("models/")
                        else -> null
                    }
                }.filter { it.isNotBlank() }.distinct().sorted()
                if (ids.isEmpty()) {
                    throw IllegalStateException("Connected to ${provider.name}, but endpoint returned 0 models.")
                }
                DevLogBuffer.add("INFO", "Models", "Live key ping returned ${ids.size} models from ${provider.name}")
                ids
            }
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "Models", "${provider.name} fetch failed: ${err.localizedMessage}")
        }
    }

    fun streamChat(
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        imageBitmap: Bitmap? = null,
        attachedFileName: String = "",
        attachedFileContent: String = "",
    ): Flow<StreamChunk> = flow {
        val cleanBase = provider.baseUrl.trim().trimEnd('/')
        require(cleanBase.isNotBlank()) { "Provider Base URL is missing. Configure it in Settings -> Providers." }
        val model = provider.selectedModel.trim()
        require(model.isNotBlank()) { "No model selected for ${provider.name}." }
        val isLocalNetwork = cleanBase.contains("127.0.0.1") ||
            cleanBase.contains("localhost") ||
            cleanBase.contains("192.168.") ||
            cleanBase.contains("10.")
        val isKeyless = !provider.requiresKey || provider.id == ProviderPresets.ID_POLLINATIONS_FREE
        if (provider.apiKey.isBlank() && !isLocalNetwork && !isKeyless) {
            throw IllegalStateException(
                "API key is empty for ${provider.name}. Open Settings -> Providers to add your key, or switch to Pollinations AI (Free · No Key)."
            )
        }

        val enrichedPrompt = buildString {
            if (attachedFileName.isNotBlank() && attachedFileContent.isNotBlank()) {
                append("[Attached File: ").append(attachedFileName).append("]\n```\n")
                append(attachedFileContent.take(12_000))
                append("\n```\n\n")
            }
            append(userPrompt)
        }.trim()

        if (provider.protocol == "anthropic") {
            streamAnthropic(cleanBase, provider, systemPrompt, history, enrichedPrompt, imageBitmap)
                .collect { emit(it) }
        } else if (provider.id == ProviderPresets.ID_POLLINATIONS_FREE) {
            streamPollinationsWithFallback(cleanBase, provider, systemPrompt, history, enrichedPrompt, imageBitmap)
                .collect { emit(it) }
        } else {
            streamOpenAiCompat(cleanBase, provider, systemPrompt, history, enrichedPrompt, imageBitmap)
                .collect { emit(it) }
        }
    }.flowOn(Dispatchers.IO)

    private fun streamPollinationsWithFallback(
        primaryBase: String,
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        imageBitmap: Bitmap?,
    ): Flow<StreamChunk> = flow {
        val candidates = listOf(
            primaryBase,
            "https://text.pollinations.ai/openai",
        ).distinct()
        var lastError: Throwable? = null
        for (base in candidates) {
            var emittedAny = false
            try {
                streamOpenAiCompat(base, provider, systemPrompt, history, userPrompt, imageBitmap)
                    .collect { chunk ->
                        emittedAny = true
                        emit(chunk)
                    }
                if (emittedAny) return@flow
            } catch (err: Throwable) {
                lastError = err
                if (emittedAny) throw err
                DevLogBuffer.add("WARN", "Pollinations", "Mirror $base failed (${err.localizedMessage}), trying fallback...")
            }
        }
        throw lastError ?: IllegalStateException("Pollinations Free endpoint did not respond. Please retry or pick another provider.")
    }

    private fun streamOpenAiCompat(
        cleanBase: String,
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        imageBitmap: Bitmap?,
    ): Flow<StreamChunk> = flow {
        val messagesJson = buildJsonArray {
            if (systemPrompt.isNotBlank()) {
                add(buildJsonObject {
                    put("role", "system")
                    put("content", systemPrompt)
                })
            }
            history.takeLast(24).forEach { msg ->
                val role = if (msg.role == "assistant") "assistant" else "user"
                val text = buildString {
                    if (msg.attachmentFileName.isNotBlank() && msg.attachmentFileContent.isNotBlank()) {
                        append("[File: ${msg.attachmentFileName}]\n${msg.attachmentFileContent.take(3000)}\n\n")
                    }
                    append(msg.content)
                    if (msg.toolCommand.isNotBlank() && msg.toolOutput.isNotBlank()) {
                        append("\n[Shizuku Command Output for `${msg.toolCommand}`]:\n${msg.toolOutput.take(2500)}")
                    }
                }.trim()
                if (text.isNotEmpty()) {
                    add(buildJsonObject {
                        put("role", role)
                        put("content", text)
                    })
                }
            }
            if (imageBitmap != null) {
                val b64 = bitmapToBase64Jpeg(imageBitmap)
                add(buildJsonObject {
                    put("role", "user")
                    put("content", buildJsonArray {
                        add(buildJsonObject {
                            put("type", "text")
                            put("text", userPrompt.ifBlank { "Describe this image in detail." })
                        })
                        add(buildJsonObject {
                            put("type", "image_url")
                            put("image_url", buildJsonObject {
                                put("url", "data:image/jpeg;base64,$b64")
                            })
                        })
                    })
                })
            } else {
                add(buildJsonObject {
                    put("role", "user")
                    put("content", userPrompt)
                })
            }
        }

        val payload = buildJsonObject {
            put("model", provider.selectedModel.trim())
            put("messages", messagesJson)
            put("stream", true)
            put("temperature", provider.temperature.toDouble())
            put("top_p", provider.topP.toDouble())
            put("max_tokens", provider.maxTokens.coerceIn(128, 16384))
        }.toString()

        val endpoint = if (cleanBase.endsWith("/chat/completions")) cleanBase else "$cleanBase/chat/completions"
        val reqBuilder = Request.Builder()
            .url(endpoint)
            .post(payload.toRequestBody(mediaTypeJson))
        applyAuthHeaders(reqBuilder, provider)
        reqBuilder.header("Accept", "text/event-stream")

        DevLogBuffer.add("INFO", "LlmBridge", "POST ${provider.name} -> ${provider.selectedModel}")
        client.newCall(reqBuilder.build()).execute().use { resp ->
            if (!resp.isSuccessful) {
                val errBody = resp.body?.string().orEmpty()
                throw IllegalStateException("${provider.name} HTTP ${resp.code}: ${extractApiError(errBody)}")
            }
            val contentType = resp.header("Content-Type").orEmpty()
            if (contentType.contains("application/json", ignoreCase = true)) {
                val bodyStr = resp.body?.string().orEmpty()
                val parsed = runCatching { json.parseToJsonElement(bodyStr).jsonObject }.getOrNull()
                val msgObj = parsed?.get("choices")?.jsonArray?.firstOrNull()?.jsonObject?.get("message")?.jsonObject
                val content = msgObj?.get("content")?.jsonPrimitive?.contentOrNull.orEmpty()
                if (content.isNotEmpty()) {
                    emit(StreamChunk(contentDelta = content))
                }
                return@use
            }
            val source = resp.body?.source() ?: throw IllegalStateException("Empty response body.")
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                val trimmed = line.trim()
                if (!trimmed.startsWith("data:")) continue
                val data = trimmed.removePrefix("data:").trim()
                if (data == "[DONE]" || data.isEmpty()) break
                val parsed = runCatching { json.parseToJsonElement(data).jsonObject }.getOrNull() ?: continue
                val choices = parsed["choices"]?.jsonArray ?: continue
                val first = choices.firstOrNull()?.jsonObject ?: continue
                val delta = first["delta"]?.jsonObject ?: first["message"]?.jsonObject ?: continue
                val contentDelta = delta["content"]?.jsonPrimitive?.contentOrNull.orEmpty()
                val reasonDelta = delta["reasoning_content"]?.jsonPrimitive?.contentOrNull
                    ?: delta["reasoning"]?.jsonPrimitive?.contentOrNull
                    ?: ""
                if (contentDelta.isNotEmpty() || reasonDelta.isNotEmpty()) {
                    emit(StreamChunk(contentDelta = contentDelta, thoughtDelta = reasonDelta))
                }
            }
        }
    }

    private fun streamAnthropic(
        cleanBase: String,
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        imageBitmap: Bitmap?,
    ): Flow<StreamChunk> = flow {
        val messagesJson = buildJsonArray {
            history.takeLast(24).forEach { msg ->
                val role = if (msg.role == "assistant") "assistant" else "user"
                val text = msg.content.trim()
                if (text.isNotEmpty()) {
                    add(buildJsonObject {
                        put("role", role)
                        put("content", text)
                    })
                }
            }
            if (imageBitmap != null) {
                val b64 = bitmapToBase64Jpeg(imageBitmap)
                add(buildJsonObject {
                    put("role", "user")
                    put("content", buildJsonArray {
                        add(buildJsonObject {
                            put("type", "image")
                            put("source", buildJsonObject {
                                put("type", "base64")
                                put("media_type", "image/jpeg")
                                put("data", b64)
                            })
                        })
                        add(buildJsonObject {
                            put("type", "text")
                            put("text", userPrompt.ifBlank { "Describe this image." })
                        })
                    })
                })
            } else {
                add(buildJsonObject {
                    put("role", "user")
                    put("content", userPrompt)
                })
            }
        }

        val payload = buildJsonObject {
            put("model", provider.selectedModel.trim())
            put("max_tokens", provider.maxTokens.coerceIn(128, 8192))
            put("temperature", provider.temperature.toDouble())
            put("stream", true)
            if (systemPrompt.isNotBlank()) put("system", systemPrompt)
            put("messages", messagesJson)
        }.toString()

        val req = Request.Builder()
            .url("$cleanBase/messages")
            .post(payload.toRequestBody(mediaTypeJson))
            .header("x-api-key", provider.apiKey.trim())
            .header("anthropic-version", "2023-06-01")
            .header("Accept", "text/event-stream")
            .build()

        DevLogBuffer.add("INFO", "LlmBridge", "POST Anthropic -> ${provider.selectedModel}")
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                val errBody = resp.body?.string().orEmpty()
                throw IllegalStateException("Anthropic HTTP ${resp.code}: ${extractApiError(errBody)}")
            }
            val source = resp.body?.source() ?: throw IllegalStateException("Empty Anthropic stream.")
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                val trimmed = line.trim()
                if (!trimmed.startsWith("data:")) continue
                val data = trimmed.removePrefix("data:").trim()
                if (data.isEmpty()) continue
                val obj = runCatching { json.parseToJsonElement(data).jsonObject }.getOrNull() ?: continue
                if (obj["type"]?.jsonPrimitive?.contentOrNull == "content_block_delta") {
                    val delta = obj["delta"]?.jsonObject ?: continue
                    val deltaType = delta["type"]?.jsonPrimitive?.contentOrNull.orEmpty()
                    if (deltaType == "thinking_delta") {
                        val t = delta["thinking"]?.jsonPrimitive?.contentOrNull.orEmpty()
                        if (t.isNotEmpty()) emit(StreamChunk(thoughtDelta = t))
                    } else {
                        val txt = delta["text"]?.jsonPrimitive?.contentOrNull.orEmpty()
                        if (txt.isNotEmpty()) emit(StreamChunk(contentDelta = txt))
                    }
                }
            }
        }
    }

    private fun applyAuthHeaders(builder: Request.Builder, provider: ProviderProfileEntity) {
        val key = provider.apiKey.trim()
        builder.header("User-Agent", "Cel.Cellium-Android/2611.21.0")
        if (provider.protocol == "anthropic") {
            if (key.isNotEmpty()) builder.header("x-api-key", key)
            builder.header("anthropic-version", "2023-06-01")
        } else {
            if (key.isNotEmpty()) builder.header("Authorization", "Bearer $key")
            if (provider.baseUrl.contains("openrouter.ai", ignoreCase = true)) {
                builder.header("HTTP-Referer", "https://github.com/HenryJayZ/CelSuite_Cellium_Source_Code")
                builder.header("X-Title", "Cel.Cellium Android")
            }
        }
    }

    private fun extractApiError(body: String): String {
        val parsed = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
        val msg = parsed?.get("error")?.let { errEl ->
            (errEl as? JsonObject)?.get("message")?.jsonPrimitive?.contentOrNull
                ?: (errEl as? JsonPrimitive)?.contentOrNull
        } ?: parsed?.get("message")?.jsonPrimitive?.contentOrNull
        return (msg ?: body).take(260).ifBlank { "Request rejected by provider" }
    }

    private fun bitmapToBase64Jpeg(bitmap: Bitmap): String {
        val maxSide = 1024
        val scale = minOf(maxSide.toFloat() / bitmap.width, maxSide.toFloat() / bitmap.height, 1f)
        val target = if (scale < 1f) {
            Bitmap.createScaledBitmap(
                bitmap,
                (bitmap.width * scale).toInt().coerceAtLeast(1),
                (bitmap.height * scale).toInt().coerceAtLeast(1),
                true,
            )
        } else bitmap
        val out = ByteArrayOutputStream()
        target.compress(Bitmap.CompressFormat.JPEG, 84, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }
}

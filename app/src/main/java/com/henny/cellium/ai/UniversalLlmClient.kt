package com.henny.cellium.ai

import android.graphics.Bitmap
import android.util.Base64
import com.henny.cellium.avatar.AVATAR_MOODS
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.ContextModifyConfig
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
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit

data class StreamChunk(
    val contentDelta: String = "",
    val thoughtDelta: String = "",
)

/**
 * Universal Multi-Provider AI Bridge for Cel.Cellium (200+ providers).
 * Supports keyless free Pollinations AI (text.pollinations.ai/openai with openai-fast),
 * any OpenAI-compatible provider, native Anthropic Messages, multi-image vision,
 * immediate request cancellation, inline/background mood control, Illume tool calls, and ReAct Agent Mode.
 */
class UniversalLlmClient {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val mediaTypeJson = "application/json; charset=utf-8".toMediaType()
    private val activeCalls = CopyOnWriteArrayList<Call>()

    private val client = OkHttpClient.Builder()
        .connectTimeout(25, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    fun cancelActiveRequests() {
        val snapshot = activeCalls.toList()
        activeCalls.clear()
        snapshot.forEach { runCatching { it.cancel() } }
    }

    fun buildSystemPrompt(
        persona: PersonaSpec,
        memories: List<MemoryEntity>,
        agentModeEnabled: Boolean,
        shizukuConnected: Boolean,
        agentWorkspacePath: String = "/sdcard/Documents/CelliumProjects",
        moodMethod: String = "inline_tag",
        contextConfig: ContextModifyConfig = ContextModifyConfig(),
        extraInstruction: String = "",
    ): String = buildString {
        if (contextConfig.includePersona && persona.systemPrompt.isNotBlank()) {
            append(persona.systemPrompt.trim())
        } else {
            append("You are Cel, a concise, helpful AI assistant.")
        }

        if (contextConfig.includeMemories) {
            val activeMemories = memories.filter { it.enabled && it.content.isNotBlank() }
            if (activeMemories.isNotEmpty()) {
                append("\n\n[Persistent User Memories]\n")
                activeMemories.forEach { m ->
                    append("- ${m.title}: ${m.content}\n")
                }
            }
        }

        if (contextConfig.includeMoodInstructions && moodMethod == "inline_tag") {
            val allowed = MoodDetector.PROMPT_MOOD_LIST.joinToString(", ")
            append("\n\n[Avatar Expression Tag — REQUIRED]\n")
            append("Start EVERY response on line 1 with EXACTLY: mood: <key>\n")
            append("Choose ONLY ONE key from this exact list: $allowed\n")
            append("NEVER invent any other mood word. Put your normal reply on line 2.")
        }

        if (contextConfig.includeIllumeInstructions) {
            append("\n\n[Illume Built-In Image Generator & Keyless Web Tools — ACTIVE]\n")
            append("1. AI Image Generation: You HAVE a built-in image generator! Whenever the user asks you to generate, draw, paint, create, make, or render images/art/pictures, emit up to 5 separate blocks placed INLINE right where each image belongs in your explanation (no code fences):\n")
            append("[ILLUME_GEN]\n<detailed visual prompt>\n[/ILLUME_GEN]\n")
            append("NEVER claim you are text-only or cannot generate images.\n")
            append("2. Real-Time Web Search (Free Keyless): If you need up-to-date news, facts, versions, or current info, output ONLY a single block and wait for results:\n")
            append("[WEB_SEARCH]<concise search query>[/WEB_SEARCH]\n")
            append("3. Real Web/Stock Photos (Free Keyless): ONLY when the user explicitly asks for real photographs or stock/web images (NOT AI art), you may embed up to 5 inline blocks:\n")
            append("[WEB_IMAGE]<simple photo subject keywords>[/WEB_IMAGE]")
        }

        if (agentModeEnabled && contextConfig.includeAgentInstructions) {
            append("\n\n[Cel.Cellium Android Agent Mode]\n")
            append("Project Workspace Directory: $agentWorkspacePath\n")
            append(
                if (shizukuConnected) {
                    "Shizuku privileged shell IS CONNECTED (full ADB/system access + workspace files). When the user asks to inspect the device, run diagnostics, manage files in the workspace, check storage/RAM/battery, or execute shell commands:\n" +
                        "1. Output ONLY a single raw tool block and NOTHING ELSE (no intro sentence, no markdown ``` fences, no comments):\n" +
                        "[SHIZUKU_RUN]\n<single shell command>\n[/SHIZUKU_RUN]\n" +
                        "2. Cellium executes it immediately and sends stdout back to you so you can then give the final answer.\n" +
                        "3. For project files, work inside $agentWorkspacePath. Never emit destructive commands."
                } else {
                    "Local Android Shell IS ACTIVE (Shizuku is NOT connected, so privileged ADB commands like pm/am/dumpsys/settings are unavailable, but normal shell commands like ls, cat, pwd, mkdir, cp, mv, find, grep, wc, sed, head, tail, df, uname, date, sh scripts, and inspecting files inside the workspace work right away!).\n" +
                        "1. To run a normal shell command, output ONLY a single raw tool block and NOTHING ELSE (no markdown ``` fences):\n" +
                        "[SHIZUKU_RUN]\n<single shell command>\n[/SHIZUKU_RUN]\n" +
                        "2. If the user specifically needs privileged Android system commands (pm, am, dumpsys, settings), tell them in 1 sentence to authorize Shizuku in Settings -> Agent & Shizuku."
                }
            )
        }

        if (extraInstruction.isNotBlank()) {
            append("\n\n").append(extraInstruction.trim())
        }
    }

    /**
     * Method 2 Mood Engine: lightweight background classification call strictly returning
     * one valid mood key from AVATAR_MOODS.
     */
    suspend fun classifyMoodFast(
        provider: ProviderProfileEntity,
        assistantReply: String,
    ): String? = withContext(Dispatchers.IO) {
        if (provider.protocol == "on_device" || assistantReply.isBlank()) return@withContext null
        val cleanBase = provider.baseUrl.trim().trimEnd('/')
        if (cleanBase.isBlank()) return@withContext null
        val allowed = MoodDetector.PROMPT_MOOD_LIST.joinToString(", ")
        val prompt = "Classify the emotional tone of this message into EXACTLY ONE word from [$allowed]. Output ONLY that single lowercase word, nothing else.\n\nMessage:\n${assistantReply.take(700)}"
        runCatching {
            val raw = if (provider.protocol == "anthropic") {
                val payload = buildJsonObject {
                    put("model", provider.selectedModel.trim())
                    put("max_tokens", 12)
                    put("temperature", 0.0)
                    put("messages", buildJsonArray {
                        add(buildJsonObject {
                            put("role", "user")
                            put("content", prompt)
                        })
                    })
                }.toString()
                val req = Request.Builder()
                    .url("$cleanBase/messages")
                    .post(payload.toRequestBody(mediaTypeJson))
                    .header("x-api-key", provider.apiKey.trim())
                    .header("anthropic-version", "2023-06-01")
                    .build()
                client.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@use ""
                    val root = json.parseToJsonElement(resp.body?.string().orEmpty()).jsonObject
                    root["content"]?.jsonArray?.firstOrNull()?.jsonObject?.get("text")?.jsonPrimitive?.contentOrNull.orEmpty()
                }
            } else {
                val modelName = if (provider.id == ProviderPresets.ID_POLLINATIONS_FREE && provider.selectedModel.isBlank()) {
                    "openai-fast"
                } else provider.selectedModel.trim()
                val payload = buildJsonObject {
                    put("model", modelName)
                    put("max_tokens", 12)
                    put("temperature", 0.0)
                    put("stream", false)
                    put("messages", buildJsonArray {
                        add(buildJsonObject {
                            put("role", "user")
                            put("content", prompt)
                        })
                    })
                }.toString()
                val endpoint = if (cleanBase.endsWith("/chat/completions")) cleanBase else "$cleanBase/chat/completions"
                val rb = Request.Builder().url(endpoint).post(payload.toRequestBody(mediaTypeJson))
                applyAuthHeaders(rb, provider)
                client.newCall(rb.build()).execute().use { resp ->
                    if (!resp.isSuccessful) return@use ""
                    val root = json.parseToJsonElement(resp.body?.string().orEmpty()).jsonObject
                    root["choices"]?.jsonArray?.firstOrNull()?.jsonObject
                        ?.get("message")?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull.orEmpty()
                }
            }
            val token = raw.trim().lowercase().replace(Regex("[^a-z]"), "")
            if (token in AVATAR_MOODS) token else null
        }.getOrNull()
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
                IllegalStateException("Enter your ${provider.name} API key first so Cellium can fetch live models.")
            )
        }

        if (cleanBase.contains("generativelanguage.googleapis.com", ignoreCase = true)) {
            val googleRes = fetchAllGoogleAiModels(key)
            if (googleRes.isSuccess && googleRes.getOrNull().orEmpty().isNotEmpty()) {
                return@withContext googleRes
            }
            val openaiRes = fetchModelsFromUrl("$cleanBase/models", provider)
            return@withContext if (openaiRes.isSuccess) openaiRes else googleRes
        }

        if (provider.protocol == "anthropic") {
            return@withContext fetchAllAnthropicModels(cleanBase, provider)
        }

        if (cleanBase.contains(":11434")) {
            val primary = fetchModelsFromUrl("$cleanBase/models", provider)
            if (primary.isSuccess && primary.getOrNull().orEmpty().isNotEmpty()) return@withContext primary
            val tagsUrl = cleanBase.removeSuffix("/v1") + "/api/tags"
            return@withContext fetchModelsFromUrl(tagsUrl, provider)
        }

        if (provider.id == ProviderPresets.ID_POLLINATIONS_FREE) {
            val live = fetchPollinationsTextModels(provider)
            if (live.isSuccess && live.getOrNull().orEmpty().isNotEmpty()) return@withContext live
            return@withContext Result.success(listOf("openai-fast"))
        }

        fetchModelsFromUrl("$cleanBase/models", provider)
    }

    private fun fetchPollinationsTextModels(provider: ProviderProfileEntity): Result<List<String>> = runCatching {
        val reqBuilder = Request.Builder()
            .url("https://text.pollinations.ai/models")
            .header("User-Agent", "Cel.Cellium-Android/2611.22.0")
            .get()
        if (provider.apiKey.isNotBlank()) {
            reqBuilder.header("Authorization", "Bearer ${provider.apiKey.trim()}")
        }
        client.newCall(reqBuilder.build()).execute().use { resp ->
            val bodyStr = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw IllegalStateException("Pollinations HTTP ${resp.code}")
            val arr = json.parseToJsonElement(bodyStr).jsonArray
            val models = arr.mapNotNull { el ->
                when (el) {
                    is JsonObject -> {
                        val tier = el["tier"]?.jsonPrimitive?.contentOrNull?.lowercase().orEmpty()
                        val name = (el["name"]?.jsonPrimitive?.contentOrNull
                            ?: el["id"]?.jsonPrimitive?.contentOrNull)?.trim()
                        // If keyless, prioritize anonymous-tier models first
                        if (provider.apiKey.isBlank() && tier.isNotBlank() && tier != "anonymous" && tier != "free") {
                            null
                        } else {
                            name
                        }
                    }
                    is JsonPrimitive -> el.contentOrNull?.trim()
                    else -> null
                }
            }.filter { it.isNotBlank() }.distinct()
            models.ifEmpty { listOf("openai-fast") }
        }
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
                .header("User-Agent", "Cel.Cellium-Android/2611.22.0")
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
        imageBitmaps: List<Bitmap> = emptyList(),
        attachedFileName: String = "",
        attachedFileContent: String = "",
        historyLimit: Int = 24,
    ): Flow<StreamChunk> = flow {
        val allImages = buildList {
            if (imageBitmap != null) add(imageBitmap)
            addAll(imageBitmaps)
        }
        val cleanBase = provider.baseUrl.trim().trimEnd('/')
        require(cleanBase.isNotBlank()) { "Provider Base URL is missing. Configure it in Settings -> AI Providers." }
        val effectiveModel = if (provider.id == ProviderPresets.ID_POLLINATIONS_FREE && provider.selectedModel.isBlank()) {
            "openai-fast"
        } else {
            provider.selectedModel.trim()
        }
        require(effectiveModel.isNotBlank()) { "No model selected for ${provider.name}. Open the provider picker and select a live model." }
        val resolvedProvider = provider.copy(selectedModel = effectiveModel)

        val isLocalNetwork = cleanBase.contains("127.0.0.1") ||
            cleanBase.contains("localhost") ||
            cleanBase.contains("192.168.") ||
            cleanBase.contains("10.")
        val isKeyless = !resolvedProvider.requiresKey || resolvedProvider.id == ProviderPresets.ID_POLLINATIONS_FREE
        if (resolvedProvider.apiKey.isBlank() && !isLocalNetwork && !isKeyless) {
            throw IllegalStateException(
                "API key is empty for ${resolvedProvider.name}. Tap the provider dropdown to add your key, or switch to Pollinations AI (Free)."
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

        val limitedHistory = if (historyLimit >= 200) history.takeLast(400) else history.takeLast(historyLimit.coerceIn(2, 400))

        if (resolvedProvider.protocol == "anthropic") {
            streamAnthropic(cleanBase, resolvedProvider, systemPrompt, limitedHistory, enrichedPrompt, allImages)
                .collect { emit(it) }
        } else if (resolvedProvider.id == ProviderPresets.ID_POLLINATIONS_FREE) {
            streamPollinationsWithFallback(cleanBase, resolvedProvider, systemPrompt, limitedHistory, enrichedPrompt, allImages)
                .collect { emit(it) }
        } else {
            streamOpenAiCompat(cleanBase, resolvedProvider, systemPrompt, limitedHistory, enrichedPrompt, allImages)
                .collect { emit(it) }
        }
    }.flowOn(Dispatchers.IO)

    private fun streamPollinationsWithFallback(
        primaryBase: String,
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        images: List<Bitmap>,
    ): Flow<StreamChunk> = flow {
        val normalizedPrimary = if (primaryBase.contains("gen.pollinations.ai") && provider.apiKey.isBlank()) {
            "https://text.pollinations.ai/openai"
        } else {
            primaryBase
        }
        val candidates = listOf(
            normalizedPrimary to provider.selectedModel.ifBlank { "openai-fast" },
            "https://text.pollinations.ai/openai" to "openai-fast",
        ).distinct()
        var lastError: Throwable? = null
        for ((base, modelName) in candidates) {
            var emittedAny = false
            try {
                streamOpenAiCompat(
                    base,
                    provider.copy(selectedModel = modelName),
                    systemPrompt,
                    history,
                    userPrompt,
                    images,
                ).collect { chunk ->
                    emittedAny = true
                    emit(chunk)
                }
                if (emittedAny) return@flow
            } catch (err: Throwable) {
                lastError = err
                if (emittedAny) throw err
                DevLogBuffer.add("WARN", "Pollinations", "Attempt $base ($modelName) failed (${err.localizedMessage}), trying fallback...")
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
        images: List<Bitmap>,
    ): Flow<StreamChunk> = flow {
        val messagesJson = buildJsonArray {
            if (systemPrompt.isNotBlank()) {
                add(buildJsonObject {
                    put("role", "system")
                    put("content", systemPrompt)
                })
            }
            history.forEach { msg ->
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
            if (images.isNotEmpty()) {
                add(buildJsonObject {
                    put("role", "user")
                    put("content", buildJsonArray {
                        add(buildJsonObject {
                            put("type", "text")
                            put("text", userPrompt.ifBlank { "Describe these images in detail." })
                        })
                        images.forEach { bmp ->
                            val b64 = bitmapToBase64Jpeg(bmp)
                            add(buildJsonObject {
                                put("type", "image_url")
                                put("image_url", buildJsonObject {
                                    put("url", "data:image/jpeg;base64,$b64")
                                })
                            })
                        }
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
        val call = client.newCall(reqBuilder.build())
        activeCalls.add(call)
        try {
            call.execute().use { resp ->
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
                        ?: delta["thought"]?.jsonPrimitive?.contentOrNull
                        ?: ""
                    if (contentDelta.isNotEmpty() || reasonDelta.isNotEmpty()) {
                        emit(StreamChunk(contentDelta = contentDelta, thoughtDelta = reasonDelta))
                    }
                }
            }
        } finally {
            activeCalls.remove(call)
        }
    }

    private fun streamAnthropic(
        cleanBase: String,
        provider: ProviderProfileEntity,
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
        images: List<Bitmap>,
    ): Flow<StreamChunk> = flow {
        val messagesJson = buildJsonArray {
            history.forEach { msg ->
                val role = if (msg.role == "assistant") "assistant" else "user"
                val text = msg.content.trim()
                if (text.isNotEmpty()) {
                    add(buildJsonObject {
                        put("role", role)
                        put("content", text)
                    })
                }
            }
            if (images.isNotEmpty()) {
                add(buildJsonObject {
                    put("role", "user")
                    put("content", buildJsonArray {
                        images.forEach { bmp ->
                            val b64 = bitmapToBase64Jpeg(bmp)
                            add(buildJsonObject {
                                put("type", "image")
                                put("source", buildJsonObject {
                                    put("type", "base64")
                                    put("media_type", "image/jpeg")
                                    put("data", b64)
                                })
                            })
                        }
                        add(buildJsonObject {
                            put("type", "text")
                            put("text", userPrompt.ifBlank { "Describe these images." })
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
        val call = client.newCall(req)
        activeCalls.add(call)
        try {
            call.execute().use { resp ->
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
        } finally {
            activeCalls.remove(call)
        }
    }

    private fun applyAuthHeaders(builder: Request.Builder, provider: ProviderProfileEntity) {
        val key = provider.apiKey.trim()
        builder.header("User-Agent", "Cel.Cellium-Android/2611.22.0")
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
        target.compress(Bitmap.CompressFormat.JPEG, 80, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    companion object {
        private val ILLUME_BLOCK_REGEX = Regex(
            """(?:```[a-zA-Z]*\s*)?\[(?:ILLUME_GEN|ILLUME|IMAGE_GEN|IMAGINE)]([\s\S]*?)\[/(?:ILLUME_GEN|ILLUME|IMAGE_GEN|IMAGINE)](?:\s*```)?""",
            RegexOption.IGNORE_CASE,
        )
        private val ILLUME_INLINE_REGEX = Regex(
            """\[(?:ILLUME_GEN|ILLUME|IMAGE_GEN|IMAGINE)\s*:\s*([^\]]+)]""",
            RegexOption.IGNORE_CASE,
        )
        private val ILLUME_UNCLOSED_REGEX = Regex(
            """(?:```[a-zA-Z]*\s*)?\[(?:ILLUME_GEN|ILLUME|IMAGE_GEN)]([\s\S]+)$""",
            RegexOption.IGNORE_CASE,
        )
        private val WEB_SEARCH_REGEX = Regex(
            """(?:```[a-zA-Z]*\s*)?\[WEB_SEARCH]([\s\S]*?)\[/WEB_SEARCH](?:\s*```)?""",
            RegexOption.IGNORE_CASE,
        )
        private val WEB_IMAGE_REGEX = Regex(
            """(?:```[a-zA-Z]*\s*)?\[WEB_IMAGE]([\s\S]*?)\[/WEB_IMAGE](?:\s*```)?""",
            RegexOption.IGNORE_CASE,
        )

        /**
         * Extracts up to [maxCount] inline [ILLUME_GEN] prompts, replacing each one in-place with
         * `[[CELLIUM_IMG_SLOT:<index>]]` so generated images render right where Cel placed them!
         */
        fun extractAllIllumeBlocks(
            assistantBodyOnly: String,
            maxCount: Int = 5,
        ): Pair<List<String>, String> {
            val prompts = mutableListOf<String>()
            var working = ILLUME_BLOCK_REGEX.replace(assistantBodyOnly) { match ->
                val p = match.groupValues[1].trim().trim('`', '"', '\'')
                if (p.isNotBlank() && prompts.size < maxCount) {
                    val idx = prompts.size
                    prompts.add(p)
                    "\n[[CELLIUM_IMG_SLOT:$idx]]\n"
                } else ""
            }
            if (prompts.size < maxCount) {
                working = ILLUME_INLINE_REGEX.replace(working) { match ->
                    val p = match.groupValues[1].trim().trim('`', '"', '\'')
                    if (p.isNotBlank() && prompts.size < maxCount) {
                        val idx = prompts.size
                        prompts.add(p)
                        "\n[[CELLIUM_IMG_SLOT:$idx]]\n"
                    } else ""
                }
            }
            if (prompts.isEmpty()) {
                ILLUME_UNCLOSED_REGEX.find(working)?.let { match ->
                    val p = match.groupValues[1].replace("```", "").trim().trim('"', '\'')
                    if (p.isNotBlank()) {
                        prompts.add(p)
                        working = working.replace(ILLUME_UNCLOSED_REGEX, "\n[[CELLIUM_IMG_SLOT:0]]\n")
                    }
                }
            }
            return prompts to working.trim()
        }

        fun extractWebSearchQuery(assistantBodyOnly: String): Pair<String?, String> {
            val match = WEB_SEARCH_REGEX.find(assistantBodyOnly) ?: return null to assistantBodyOnly
            val q = match.groupValues[1].trim().trim('`', '"', '\'')
            val cleaned = assistantBodyOnly.replace(WEB_SEARCH_REGEX, "").trim()
            return q.ifBlank { null } to cleaned
        }

        fun extractAllWebImageBlocks(
            assistantBodyOnly: String,
            maxCount: Int = 5,
        ): Pair<List<String>, String> {
            val queries = mutableListOf<String>()
            val working = WEB_IMAGE_REGEX.replace(assistantBodyOnly) { match ->
                val q = match.groupValues[1].trim().trim('`', '"', '\'')
                if (q.isNotBlank() && queries.size < maxCount) {
                    val idx = queries.size
                    queries.add(q)
                    "\n[[CELLIUM_WEBIMG_SLOT:$idx]]\n"
                } else ""
            }
            return queries to working.trim()
        }

        fun extractIllumePrompt(assistantBodyOnly: String): Pair<String?, String> {
            ILLUME_BLOCK_REGEX.find(assistantBodyOnly)?.let { match ->
                val prompt = match.groupValues[1].trim().trim('`', '"', '\'')
                val cleaned = assistantBodyOnly.replace(ILLUME_BLOCK_REGEX, "").trim()
                return (prompt.ifBlank { null }) to cleaned
            }
            ILLUME_INLINE_REGEX.find(assistantBodyOnly)?.let { match ->
                val prompt = match.groupValues[1].trim().trim('`', '"', '\'')
                val cleaned = assistantBodyOnly.replace(ILLUME_INLINE_REGEX, "").trim()
                return (prompt.ifBlank { null }) to cleaned
            }
            ILLUME_UNCLOSED_REGEX.find(assistantBodyOnly)?.let { match ->
                val prompt = match.groupValues[1].replace("```", "").trim().trim('"', '\'')
                val cleaned = assistantBodyOnly.replace(ILLUME_UNCLOSED_REGEX, "").trim()
                return (prompt.ifBlank { null }) to cleaned
            }
            return null to assistantBodyOnly
        }

        fun isRetryableError(err: Throwable): Boolean {
            val msg = err.localizedMessage.orEmpty().lowercase()
            return msg.contains("http 429") ||
                msg.contains("rate limit") ||
                msg.contains("too many requests") ||
                msg.contains("http 500") ||
                msg.contains("http 502") ||
                msg.contains("http 503") ||
                msg.contains("http 504") ||
                msg.contains("http 529") ||
                msg.contains("overloaded") ||
                msg.contains("timeout") ||
                msg.contains("timed out") ||
                msg.contains("connection reset") ||
                msg.contains("unable to resolve host")
        }
    }
}

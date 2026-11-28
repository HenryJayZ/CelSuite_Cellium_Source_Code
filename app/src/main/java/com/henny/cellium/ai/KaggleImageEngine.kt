package com.henny.cellium.ai

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.SecureKaggleStore
import com.henny.cellium.data.local.ProviderProfileEntity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import com.henny.cellium.core.CelliumHttp
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream
import kotlin.math.max

/**
 * Full PC-parity Kaggle Cloud GPU Image Pipeline for Cel.Cellium Android:
 *  - 4 exact presets (DreamShaper XL Turbo v2, Nova Cartoon XL + LoRA 1524099,
 *    Juggernaut XL Ragnarok, Custom)
 *  - Script mode (POST /kernels/push, POST->GET /kernels/status, 30s log tail,
 *    paginated /kernels/output + JPEG magic-byte fallback, serialized CPU-only Stealth Wipe)
 *  - Phase-5 Server-Side Model Cache (CPU-only builder kernel + /blobs/upload + /datasets/create/new
 *    + /datasets/view health probe + /dataset/{user}/{slug}/delete)
 *  - img2img ("edit last image") downscaled to <=1024px JPEG base64
 *  - Offline Danbooru Local Enhancer + LLM Enhancer with 2s/4s/8s 429 retry
 */
class KaggleImageEngine(
    private val context: Context,
    private val secureStore: SecureKaggleStore,
) {
    private val appContext = context.applicationContext
    private val json = Json { ignoreUnknownKeys = true; isLenient = true; encodeDefaults = true }
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val renderSlugMutex = Mutex()

    private val client = CelliumHttp.clientWithTimeouts(
        connectSec = 25L,
        readSec = 90L,
        writeSec = 45L,
        followRedirects = true,
    )

    data class ModelPreset(
        val label: String,
        val mode: String, // "hf" | "civitai" | "custom"
        val hfModel: String = "",
        val civitaiUrl: String = "",
        val loraUrl: String = "",
        val steps: Int = 28,
        val guidance: Float = 6.5f,
        val notes: String = "",
    )

    data class QuickStyle(
        val label: String,
        val tags: String,
    )

    data class ModelConfig(
        val mode: String, // "hf" | "civitai"
        val hfModel: String,
        val hfToken: String,
        val civitaiUrl: String,
        val civitaiToken: String,
        val loraUrl: String,
        val loraStrength: Float,
        val datasetSlug: String = "",
        val presetLabel: String = "",
    )

    data class GenerationRequest(
        val prompt: String,
        val negativePrompt: String = DEFAULT_NEGATIVE_PROMPT,
        val steps: Int = 28,
        val width: Int = 832,
        val height: Int = 1216,
        val seed: Long = -1L,
        val guidanceScale: Float = 6.5f,
        val batch: Int = 1,
        val initB64: String = "",
        val denoise: Float = 0.75f,
    )

    data class KaggleProgress(
        val stage: String,
        val detail: String,
    )

    data class KaggleGenerationResult(
        val primaryFile: File,
        val allFiles: List<File>,
        val seeds: List<Long>,
        val elapsedSeconds: Float,
        val presetLabel: String,
    )

    @Serializable
    data class CacheEntry(
        val slug: String,
        val exists: Boolean,
        val healthy: Boolean,
        val bytes: Long = 0L,
        val updated: String = "",
        val ref: String = "",
    )

    companion object {
        const val API_BASE = "https://www.kaggle.com/api/v1"
        const val USER_AGENT = "Cellium/1.0"
        const val DEFAULT_KERNEL_SLUG = "cloud-render-w1"
        const val DEFAULT_NEGATIVE_PROMPT =
            "worst quality, low quality, ugly, blurry, deformed, bad anatomy, watermark, signature"

        const val PRESET_DREAMSHAPER = "✨ DreamShaper XL Turbo v2 (fast, public HF)"
        const val PRESET_NOVA_CARTOON = "🎨 Nova Cartoon XL (Civitai)"
        const val PRESET_JUGGERNAUT = "📸 Juggernaut XL Ragnarok (Civitai)"
        const val PRESET_CUSTOM = "🔧 Custom (from Settings)"

        val MODEL_PRESETS: List<ModelPreset> = listOf(
            ModelPreset(
                label = PRESET_DREAMSHAPER,
                mode = "hf",
                hfModel = "lykon/dreamshaper-xl-v2-turbo",
                steps = 8,
                guidance = 2.0f,
                notes = "Fastest public SDXL Turbo fine-tune (~7 GB HF, no token needed)",
            ),
            ModelPreset(
                label = PRESET_NOVA_CARTOON,
                mode = "civitai",
                civitaiUrl = "https://civitai.com/api/download/models/2329740",
                loraUrl = "https://civitai.com/api/download/models/1524099",
                steps = 33,
                guidance = 7.0f,
                notes = "Illustrious cartoon/anime engine (6.94 GB) + Cartoony LoRA",
            ),
            ModelPreset(
                label = PRESET_JUGGERNAUT,
                mode = "civitai",
                civitaiUrl = "https://civitai.com/api/download/models/1759168",
                loraUrl = "",
                steps = 33,
                guidance = 7.0f,
                notes = "Photoreal SDXL 1.0 engine (7.11 GB, no cartoon LoRA)",
            ),
            ModelPreset(
                label = PRESET_CUSTOM,
                mode = "custom",
                steps = 28,
                guidance = 6.5f,
                notes = "Uses your manual HF repo / Civitai URL / LoRA settings",
            ),
        )

        val SIZE_PRESETS: List<String> = listOf(
            "512x512 (1:1)",
            "768x768 (1:1)",
            "832x1216 (9:16)",
            "1216x832 (16:9)",
            "1024x1024 (1:1)",
            "896x1152 (3:4)",
            "1152x896 (4:3)",
            "768x1344 (9:16)",
            "1344x768 (16:9)",
            "1536x640 (21:9)",
        )

        val QUICK_STYLES: List<QuickStyle> = listOf(
            QuickStyle(
                "🌸 Masterpiece Anime (Clean)",
                "masterpiece, best quality, ultra-detailed anime aesthetic, expressive eyes, vibrant colors, clean lineart",
            ),
            QuickStyle(
                "📼 Retro 90s Cel Animation (Nostalgic)",
                "retro anime aesthetic, 1990s cel animation style, nostalgic color palette, retro anime screengrab, grain texture",
            ),
            QuickStyle(
                "🧸 Chibi Kawaii (Super Cute)",
                "chibi style, kawaii aesthetic, rounded soft proportions, pastel palette, super cute, adorable expression",
            ),
            QuickStyle(
                "⚔️ Dark Cinematic Fantasy (Epic)",
                "cinematic fantasy, dramatic dark atmosphere, volumetric lighting, hyper-detailed, epic composition, unreal engine render",
            ),
            QuickStyle(
                "🌆 Cyberpunk Neon (Futuristic)",
                "cyberpunk aesthetic, vibrant neon lighting, reflections, rainy night city, high-tech glow, volumetric haze",
            ),
            QuickStyle(
                "🎨 Soft Watercolor (Dreamy)",
                "soft watercolor painting, delicate brushstrokes, watercolor wash, ethereal lighting, gentle pastel tones",
            ),
        )

        private val LOCAL_ENHANCE_PREFIX =
            "score_9, score_8_up, score_7_up, source_cartoon, masterpiece, best quality, vibrant colors, full color, "
        private val LOCAL_ENHANCE_SHORT_SUFFIX =
            ", detailed illustration, cinematic lighting, sharp focus, 8k, highly detailed"

        private val LLM_ENHANCER_SYSTEM_PROMPT = """
            You are a prompt engineer for SDXL image generation. Convert the user's
            idea into ONE comma-separated Danbooru-style tag list: style/quality prefix
            (score_9, score_8_up, masterpiece, best quality), subject, hair/eyes/clothes,
            pose, background, lighting, camera framing. Keep every content tag the user
            gave. Output ONLY the tag list - no sentences, no markdown, no numbering.
        """.trimIndent()

        fun findPreset(label: String): ModelPreset =
            MODEL_PRESETS.firstOrNull { it.label == label } ?: MODEL_PRESETS.first()

        fun parseSize(sizeLabel: String): Pair<Int, Int> {
            val dims = sizeLabel.substringBefore(" (").trim().lowercase()
            val parts = dims.split("x")
            if (parts.size == 2) {
                val w = parts[0].trim().toIntOrNull()
                val h = parts[1].trim().toIntOrNull()
                if (w != null && h != null && w in 256..2048 && h in 256..2048) {
                    return w to h
                }
            }
            return 832 to 1216
        }

        fun presetSlug(presetLabel: String): String {
            val noParens = presetLabel.lowercase().replace(Regex("\\([^)]*\\)"), "")
            val cleaned = noParens.replace(Regex("[^a-z0-9]+"), "-")
            val parts = cleaned.split("-").filter { it.length > 1 }
            val joined = parts.joinToString("-").take(40).trim('-')
            return "cellium-cache-${joined.ifBlank { "model" }}"
        }

        /** Offline deterministic Danbooru-style enhancer (zero API key needed). */
        fun enhancePromptLocal(rawPrompt: String): String {
            val clean = rawPrompt.trim()
            if (clean.isBlank()) return clean
            val low = clean.lowercase()
            if (low.startsWith("score_") || low.startsWith("masterpiece")) return clean
            var out = LOCAL_ENHANCE_PREFIX + clean
            val wordCount = clean.split(Regex("\\s+")).count { it.isNotBlank() }
            if (wordCount <= 6 && !clean.endsWith("...") && !clean.endsWith("…")) {
                out += LOCAL_ENHANCE_SHORT_SUFFIX
            }
            return out
        }

        /** Escapes a Kotlin String into a safe Python single-quoted string literal (repr). */
        fun pyRepr(value: String): String {
            val sb = StringBuilder(value.length + 8)
            sb.append('\'')
            for (ch in value) {
                when (ch) {
                    '\\' -> sb.append("\\\\")
                    '\'' -> sb.append("\\'")
                    '\n' -> sb.append("\\n")
                    '\r' -> sb.append("\\r")
                    '\t' -> sb.append("\\t")
                    else -> sb.append(ch)
                }
            }
            sb.append('\'')
            return sb.toString()
        }

        fun formatStage(stage: String, detail: String): String {
            val icon = when (stage) {
                "checking_status" -> "🔍"
                "waiting_for_slot", "queued" -> "⏳"
                "pushing" -> "📤"
                "running" -> "🎨"
                "downloading" -> "📥"
                "complete", "done" -> "✅"
                "rate_limited" -> "🐌"
                "error" -> "❌"
                else -> "⚡"
            }
            return if (detail.isNotBlank()) "$icon $detail" else "$icon $stage"
        }

        fun encodeInitImageBase64(file: File): String? = runCatching {
            if (!file.exists() || !file.isFile) return@runCatching null
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.absolutePath, bounds)
            val w = bounds.outWidth
            val h = bounds.outHeight
            if (w <= 0 || h <= 0) return@runCatching null
            var sample = 1
            while (w / sample > 2048 || h / sample > 2048) sample *= 2
            val decoded = BitmapFactory.decodeFile(
                file.absolutePath,
                BitmapFactory.Options().apply { inSampleSize = sample },
            ) ?: return@runCatching null
            val scale = minOf(1024f / decoded.width, 1024f / decoded.height, 1f)
            val resized = if (scale < 1f) {
                Bitmap.createScaledBitmap(
                    decoded,
                    (decoded.width * scale).toInt().coerceAtLeast(64),
                    (decoded.height * scale).toInt().coerceAtLeast(64),
                    true,
                )
            } else decoded
            val baos = ByteArrayOutputStream()
            resized.compress(Bitmap.CompressFormat.JPEG, 85, baos)
            if (resized !== decoded) resized.recycle()
            decoded.recycle()
            Base64.encodeToString(baos.toByteArray(), Base64.NO_WRAP)
        }.getOrNull()
    }

    fun getCredentials(prefs: CelliumPreferences): Pair<String, String> {
        val u = secureStore.getUsername().ifBlank { prefs.kaggleUsername.trim() }
        val k = secureStore.getApiKey().ifBlank { prefs.kaggleKey.trim() }
        return u to k
    }

    fun isConfigured(prefs: CelliumPreferences): Boolean {
        val (u, k) = getCredentials(prefs)
        return u.isNotBlank() && k.isNotBlank()
    }

    fun saveCredentialsFromJson(rawJson: String): Result<Pair<String, String>> = runCatching {
        val obj = json.parseToJsonElement(rawJson.trim()).jsonObject
        val user = obj["username"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        val key = obj["key"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        require(user.isNotBlank() && key.isNotBlank()) {
            "Invalid kaggle.json: expected {\"username\":\"...\",\"key\":\"...\"}."
        }
        secureStore.saveCredentials(user, key)
        user to key
    }

    private fun basicAuthHeader(username: String, apiKey: String): String =
        "Basic " + Base64.encodeToString("$username:$apiKey".toByteArray(Charsets.UTF_8), Base64.NO_WRAP)

    fun galleryDir(): File {
        val dir = appContext.getExternalFilesDir(Environment.DIRECTORY_PICTURES)
            ?.let { File(it, "Cellium") }
            ?: File(appContext.filesDir, "generated_images")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    /** Step A — Validate Kaggle Legacy API credentials against /datasets/list. */
    suspend fun validateCredentials(username: String, apiKey: String): Pair<Boolean, String> = withContext(Dispatchers.IO) {
        val u = username.trim()
        val k = apiKey.trim()
        if (u.isBlank() || k.isBlank()) {
            return@withContext false to "❌ Enter your Kaggle username and Legacy API key first."
        }
        runCatching {
            val req = Request.Builder()
                .url("$API_BASE/datasets/list?user=${URLEncoder.encode(u, "UTF-8")}&page=1")
                .header("Authorization", basicAuthHeader(u, k))
                .header("User-Agent", USER_AGENT)
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                when (resp.code) {
                    200 -> true to "✅ Connected! GPU quota available."
                    401 -> false to "❌ Invalid Kaggle username or API key"
                    403 -> false to "⚠️ Connected but no GPU quota (verify phone on Kaggle)"
                    else -> false to "❌ Unexpected: HTTP ${resp.code}"
                }
            }
        }.getOrElse { err ->
            false to "❌ Network error: ${err.localizedMessage}"
        }
    }

    /** Build resolved ModelConfig from active preset + preferences + encrypted tokens. */
    fun buildModelConfig(
        prefs: CelliumPreferences,
        presetOverride: String? = null,
    ): ModelConfig {
        val chosenPresetLabel = presetOverride?.takeIf { it.isNotBlank() } ?: prefs.kagglePreset
        val preset = findPreset(chosenPresetLabel)
        val hfToken = secureStore.getHfToken()
        val civitaiToken = secureStore.getCivitaiToken()
        val cacheMap = parseCacheMap(prefs.kaggleCacheMapJson)
        val cachedEntry = cacheMap[preset.label]
        val mountedSlug = if (cachedEntry?.healthy == true) cachedEntry.slug else ""

        return if (preset.mode != "custom") {
            ModelConfig(
                mode = preset.mode,
                hfModel = preset.hfModel,
                hfToken = hfToken,
                civitaiUrl = preset.civitaiUrl,
                civitaiToken = civitaiToken,
                loraUrl = preset.loraUrl,
                loraStrength = prefs.kaggleLoraStrength.coerceIn(0.1f, 2.0f),
                datasetSlug = mountedSlug,
                presetLabel = preset.label,
            )
        } else {
            ModelConfig(
                mode = prefs.kaggleModelMode.ifBlank { "hf" },
                hfModel = prefs.kaggleHfModel.ifBlank { "lykon/dreamshaper-xl-v2-turbo" },
                hfToken = hfToken,
                civitaiUrl = prefs.kaggleCivitaiUrl,
                civitaiToken = civitaiToken,
                loraUrl = prefs.kaggleLoraUrl,
                loraStrength = prefs.kaggleLoraStrength.coerceIn(0.1f, 2.0f),
                datasetSlug = "",
                presetLabel = PRESET_CUSTOM,
            )
        }
    }

    /** Optional LLM Prompt Enhancer with 2s/4s/8s 429 retry (falls back gracefully to offline local enhancer). */
    suspend fun enhancePromptWithLlm(
        rawPrompt: String,
        provider: ProviderProfileEntity?,
        modelOverride: String = "",
    ): Result<String> = withContext(Dispatchers.IO) {
        val clean = rawPrompt.trim()
        if (clean.isBlank()) return@withContext Result.failure(IllegalArgumentException("Enter a prompt first."))
        if (provider == null || provider.protocol == "on_device" || provider.baseUrl.isBlank()) {
            return@withContext Result.success(enhancePromptLocal(clean))
        }
        val cleanBase = provider.baseUrl.trim().trimEnd('/')
        val modelName = modelOverride.trim().ifBlank { provider.selectedModel.trim() }.ifBlank { "openai-fast" }
        val endpoint = if (cleanBase.endsWith("/chat/completions")) cleanBase else "$cleanBase/chat/completions"

        val payload = buildJsonObject {
            put("model", modelName)
            put("max_tokens", 700)
            put("temperature", 0.7)
            put("stream", false)
            put("messages", buildJsonArray {
                add(buildJsonObject {
                    put("role", "system")
                    put("content", LLM_ENHANCER_SYSTEM_PROMPT)
                })
                add(buildJsonObject {
                    put("role", "user")
                    put("content", clean)
                })
            })
        }.toString()

        val delays = longArrayOf(2000L, 4000L, 8000L)
        var lastErr: Throwable? = null
        for (attempt in 0..3) {
            val rb = Request.Builder()
                .url(endpoint)
                .header("User-Agent", USER_AGENT)
                .post(payload.toRequestBody(jsonMedia))
            if (provider.apiKey.isNotBlank()) {
                rb.header("Authorization", "Bearer ${provider.apiKey.trim()}")
            }
            val result = runCatching {
                client.newCall(rb.build()).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (resp.code == 429) {
                        throw IllegalStateException("RATE_LIMIT_429")
                    }
                    if (resp.code == 401 || resp.code == 403) {
                        throw IllegalStateException("Auth error (HTTP ${resp.code})")
                    }
                    if (!resp.isSuccessful) {
                        throw IllegalStateException("Enhancer HTTP ${resp.code}: ${body.take(140)}")
                    }
                    val root = json.parseToJsonElement(body).jsonObject
                    val content = root["choices"]?.jsonArray?.firstOrNull()?.jsonObject
                        ?.get("message")?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull
                        ?.trim().orEmpty()
                    val stripped = content
                        .removePrefix("```").removeSuffix("```")
                        .replace(Regex("^```[a-zA-Z]*\\s*"), "")
                        .replace(Regex("\\s*```$"), "")
                        .trim()
                    if (stripped.isBlank()) throw IllegalStateException("Enhancer returned empty output.")
                    stripped
                }
            }
            if (result.isSuccess) return@withContext result
            lastErr = result.exceptionOrNull()
            if (lastErr?.message == "RATE_LIMIT_429" && attempt < delays.size) {
                delay(delays[attempt])
                continue
            }
            break
        }
        Result.failure(lastErr ?: IllegalStateException("Prompt enhancement failed."))
    }

    /** Full Script Mode render pipeline (serialized per render slug so Stealth Wipe never races). */
    suspend fun render(
        prefs: CelliumPreferences,
        request: GenerationRequest,
        presetOverride: String? = null,
        onProgress: (KaggleProgress) -> Unit = {},
    ): Result<KaggleGenerationResult> = withContext(Dispatchers.IO) {
        val (username, apiKey) = getCredentials(prefs)
        if (username.isBlank() || apiKey.isBlank()) {
            return@withContext Result.failure(
                IllegalStateException("Kaggle credentials missing. Import kaggle.json in Settings or Illume Studio.")
            )
        }
        val auth = basicAuthHeader(username, apiKey)
        var modelCfg = buildModelConfig(prefs, presetOverride)

        renderSlugMutex.withLock {
            runCatching {
                val tStart = System.currentTimeMillis()
                // Re-probe Phase-5 cloud cache dynamically (cheap JSON GET) so "Cache now" works immediately
                if (modelCfg.mode == "civitai" && modelCfg.presetLabel.isNotBlank() && modelCfg.presetLabel != PRESET_CUSTOM) {
                    val expectedSlug = presetSlug(modelCfg.presetLabel)
                    val probe = checkCacheStatusSync(username, auth, expectedSlug)
                    modelCfg = modelCfg.copy(datasetSlug = if (probe.healthy) probe.slug else "")
                }

                // Step B — wait if a previous job is still active on cloud-render-w1
                onProgress(KaggleProgress("checking_status", "Checking Kaggle GPU slot..."))
                waitForIdleSlug(username, auth, DEFAULT_KERNEL_SLUG, onProgress)

                // Step C — build Python script & push private GPU kernel
                val script = buildRenderKernelScript(request, modelCfg)
                val datasetSources = if (modelCfg.datasetSlug.isNotBlank()) {
                    listOf("$username/${modelCfg.datasetSlug}")
                } else emptyList()

                onProgress(KaggleProgress("pushing", "Pushing SDXL GPU job (${modelCfg.presetLabel.ifBlank { modelCfg.mode }})..."))
                val actualSlug = pushKernelWithRetry(
                    username = username,
                    auth = auth,
                    requestedSlug = DEFAULT_KERNEL_SLUG,
                    title = "Cloud Render W1",
                    script = script,
                    enableGpu = true,
                    enableInternet = true,
                    datasetSources = datasetSources,
                    sessionTimeoutSeconds = 2700,
                    onRateLimit = { waitSec ->
                        onProgress(KaggleProgress("rate_limited", "Kaggle rate limit — retrying in ${waitSec}s..."))
                    },
                )
                DevLogBuffer.add("INFO", "KaggleGPU", "Pushed kernel $username/$actualSlug (cache=${datasetSources.isNotEmpty()})")

                // Step D — poll status every 5s + log tail every 30s
                val batch = request.batch.coerceIn(1, 20)
                val timeoutSec = max(900L, batch * 90L + 360L)
                val pollStartMs = System.currentTimeMillis()
                var runningStartMs = 0L
                var lastLogFetchMs = 0L
                var lastDetail = "Queued for Kaggle NVIDIA GPU..."
                var completed = false

                while (currentCoroutineContext().isActive) {
                    val elapsedSec = (System.currentTimeMillis() - pollStartMs) / 1000L
                    if (elapsedSec > timeoutSec) {
                        throw IllegalStateException("Kaggle GPU job timed out after ${timeoutSec / 60}m.")
                    }
                    delay(5000L)
                    val st = fetchKernelStatus(username, auth, actualSlug)
                    when (st.normalized) {
                        "queued" -> {
                            lastDetail = "Queued for GPU (${elapsedSec}s)..."
                            onProgress(KaggleProgress("queued", lastDetail))
                        }
                        "running" -> {
                            val now = System.currentTimeMillis()
                            if (runningStartMs == 0L) runningStartMs = now
                            val runSec = (now - runningStartMs) / 1000L
                            if (now - lastLogFetchMs >= 30_000L) {
                                lastLogFetchMs = now
                                val logLine = fetchLatestLogLine(username, auth, actualSlug)
                                if (!logLine.isNullOrBlank()) {
                                    lastDetail = logLine
                                }
                            }
                            val display = if (lastDetail.startsWith("Queued")) {
                                if (runSec < 60L) {
                                    "Booting GPU & loading model (${runSec}s)..."
                                } else {
                                    val estPerImg = max(30f, request.steps * 2.2f)
                                    val pct = (((runSec - 60f) / (estPerImg * batch)) * 100f).toInt().coerceIn(5, 96)
                                    if (batch > 1) "Rendering $batch images (~$pct%)" else "Sampling steps (~$pct%)"
                                }
                            } else {
                                lastDetail
                            }
                            onProgress(KaggleProgress("running", display))
                        }
                        "complete" -> {
                            completed = true
                            break
                        }
                        "cancelled" -> {
                            throw IllegalStateException("Kaggle job was cancelled.")
                        }
                        "error" -> {
                            val tail = fetchLogTail(username, auth, actualSlug).takeLast(1800)
                            val combined = "${st.failureMessage}\n$tail".lowercase()
                            val friendly = when {
                                "quota" in combined || "accelerator" in combined ->
                                    "Kaggle weekly GPU quota exhausted (~30h/wk resets Monday). ${st.failureMessage}"
                                else ->
                                    "Kaggle error: ${st.failureMessage.ifBlank { "Script failed" }}\n${tail.takeLast(450)}"
                            }
                            throw IllegalStateException(friendly.trim())
                        }
                        else -> {
                            onProgress(KaggleProgress("queued", "Status: ${st.rawStatus} (${elapsedSec}s)..."))
                        }
                    }
                }
                if (!completed) throw CancellationException("Render cancelled.")

                // Step E — download outputs (paginated) + meta.json + MediaStore publish
                onProgress(KaggleProgress("downloading", "Downloading rendered JPEG(s)..."))
                val outResult = downloadOutputs(
                    username = username,
                    auth = auth,
                    kernelSlug = actualSlug,
                    prompt = request.prompt,
                )

                // Publish primary image to MediaStore Pictures/Cellium for gallery access
                outResult.first.forEach { file ->
                    runCatching { publishToMediaStore(file) }
                }

                // Step F — serialized CPU-only Stealth Wipe (0 GPU quota) AFTER files are safely saved
                if (prefs.kaggleAutoClean) {
                    runCatching {
                        pushStealthWipe(username, auth, actualSlug)
                        DevLogBuffer.add("INFO", "KaggleGPU", "Stealth wipe pushed (CPU-only) for $actualSlug")
                    }.onFailure { err ->
                        DevLogBuffer.add("WARN", "KaggleGPU", "Stealth wipe skipped: ${err.localizedMessage}")
                    }
                }

                val totalSec = outResult.third ?: ((System.currentTimeMillis() - tStart) / 1000f)
                onProgress(KaggleProgress("done", "Done in ${"%.1f".format(totalSec)}s · seed ${outResult.second.joinToString(", ")}"))
                KaggleGenerationResult(
                    primaryFile = outResult.first.first(),
                    allFiles = outResult.first,
                    seeds = outResult.second,
                    elapsedSeconds = totalSec,
                    presetLabel = modelCfg.presetLabel.ifBlank { modelCfg.mode },
                )
            }
        }
    }

    // ── Phase 5: Server-Side Cloud Model Cache (CPU-Only, 0 GPU Quota, 0 Model Bytes on Phone) ──

    suspend fun refreshCacheMap(prefs: CelliumPreferences): Result<Map<String, CacheEntry>> = withContext(Dispatchers.IO) {
        val (u, k) = getCredentials(prefs)
        if (u.isBlank() || k.isBlank()) {
            return@withContext Result.failure(IllegalStateException("Kaggle credentials required."))
        }
        val auth = basicAuthHeader(u, k)
        runCatching {
            val civitaiPresets = MODEL_PRESETS.filter { it.mode == "civitai" }
            val pairs = coroutineScope {
                civitaiPresets.map { preset ->
                    async {
                        val slug = presetSlug(preset.label)
                        preset.label to checkCacheStatusSync(u, auth, slug)
                    }
                }.awaitAll()
            }
            pairs.toMap()
        }
    }

    fun encodeCacheMap(map: Map<String, CacheEntry>): String =
        runCatching { json.encodeToString(map) }.getOrDefault("{}")

    fun parseCacheMap(raw: String): Map<String, CacheEntry> =
        runCatching { json.decodeFromString<Map<String, CacheEntry>>(raw) }.getOrDefault(emptyMap())

    suspend fun deleteCacheDataset(prefs: CelliumPreferences, slug: String): Result<Unit> = withContext(Dispatchers.IO) {
        val (u, k) = getCredentials(prefs)
        if (u.isBlank() || k.isBlank()) {
            return@withContext Result.failure(IllegalStateException("Kaggle credentials required."))
        }
        val auth = basicAuthHeader(u, k)
        runCatching {
            deleteDatasetSync(u, auth, slug)
            Unit
        }
    }

    suspend fun buildCloudCacheForPreset(
        prefs: CelliumPreferences,
        presetLabel: String,
        onStatus: (String) -> Unit = {},
    ): Result<CacheEntry> = withContext(Dispatchers.IO) {
        val (u, k) = getCredentials(prefs)
        if (u.isBlank() || k.isBlank()) {
            return@withContext Result.failure(IllegalStateException("Kaggle credentials required."))
        }
        val preset = findPreset(presetLabel)
        if (preset.mode != "civitai" || preset.civitaiUrl.isBlank()) {
            return@withContext Result.failure(IllegalArgumentException("Cloud model cache applies to Civitai presets."))
        }
        val auth = basicAuthHeader(u, k)
        val dsSlug = presetSlug(preset.label)
        val civitaiTok = secureStore.getCivitaiToken()

        runCatching {
            onStatus("Checking existing cloud cache...")
            val existing = checkCacheStatusSync(u, auth, dsSlug)
            if (existing.exists) {
                onStatus("Removing old cache shell before rebuilding...")
                runCatching { deleteDatasetSync(u, auth, dsSlug) }
                delay(2000L)
            }

            val hex6 = (System.currentTimeMillis() and 0xFFFFFF).toString(16).padStart(6, '0')
            val builderSlug = "cellium-cache-builder-$hex6"
            val builderTitle = "Cellium cache builder $hex6"
            val builderScript = buildCacheBuilderScript(
                kaggleUser = u,
                kaggleKey = k,
                datasetSlug = dsSlug,
                datasetTitle = "Cellium cache ${preset.label.replace(Regex("[^a-zA-Z0-9 ]"), "").trim().take(30)}",
                civitaiUrl = preset.civitaiUrl,
                loraUrl = preset.loraUrl,
                civitaiToken = civitaiTok,
            )

            onStatus("Pushing CPU-only cache builder (0 GPU quota)...")
            val actualSlug = pushKernelWithRetry(
                username = u,
                auth = auth,
                requestedSlug = builderSlug,
                title = builderTitle,
                script = builderScript,
                enableGpu = false,
                enableInternet = true,
                datasetSources = emptyList(),
                sessionTimeoutSeconds = 3600,
                onRateLimit = { onStatus("Rate limited, retrying in ${it}s...") },
            )

            val startMs = System.currentTimeMillis()
            while (currentCoroutineContext().isActive) {
                val elapsed = (System.currentTimeMillis() - startMs) / 1000L
                if (elapsed > 3500L) throw IllegalStateException("Cache builder timed out.")
                delay(8000L)
                val st = fetchKernelStatus(u, auth, actualSlug)
                when (st.normalized) {
                    "queued" -> onStatus("Cache builder queued (${elapsed}s, CPU-only)...")
                    "running" -> {
                        val line = fetchLatestLogLine(u, auth, actualSlug)
                        onStatus(line ?: "Streaming checkpoint to Kaggle cloud dataset (${elapsed}s)...")
                    }
                    "complete" -> break
                    "error", "cancelled" -> {
                        val tail = fetchLogTail(u, auth, actualSlug).takeLast(500)
                        throw IllegalStateException("Cache builder failed: ${st.failureMessage}\n$tail")
                    }
                }
            }
            onStatus("Verifying private Kaggle cache dataset...")
            delay(3000L)
            val entry = checkCacheStatusSync(u, auth, dsSlug)
            if (!entry.healthy) {
                throw IllegalStateException("Cache dataset finished but appears empty (<1 MB).")
            }
            entry
        }
    }

    private fun checkCacheStatusSync(username: String, auth: String, slug: String): CacheEntry {
        return runCatching {
            val req = Request.Builder()
                .url("$API_BASE/datasets/view/${URLEncoder.encode(username, "UTF-8")}/${URLEncoder.encode(slug, "UTF-8")}")
                .header("Authorization", auth)
                .header("User-Agent", USER_AGENT)
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    return@runCatching CacheEntry(slug = slug, exists = false, healthy = false)
                }
                val body = resp.body?.string().orEmpty()
                val obj = json.parseToJsonElement(body).jsonObject
                val bytes = obj["totalBytes"]?.jsonPrimitive?.longOrNull ?: 0L
                val updated = obj["lastUpdated"]?.jsonPrimitive?.contentOrNull.orEmpty()
                val ref = obj["ref"]?.jsonPrimitive?.contentOrNull.orEmpty()
                CacheEntry(
                    slug = slug,
                    exists = true,
                    healthy = bytes >= 1_000_000L,
                    bytes = bytes,
                    updated = updated,
                    ref = ref,
                )
            }
        }.getOrDefault(CacheEntry(slug = slug, exists = false, healthy = false))
    }

    private fun deleteDatasetSync(username: String, auth: String, slug: String) {
        val url = "$API_BASE/dataset/${URLEncoder.encode(username, "UTF-8")}/${URLEncoder.encode(slug, "UTF-8")}/delete"
        val req = Request.Builder()
            .url(url)
            .header("Authorization", auth)
            .header("User-Agent", USER_AGENT)
            .post("{}".toRequestBody(jsonMedia))
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful && resp.code != 404) {
                throw IllegalStateException("Delete cache HTTP ${resp.code}: ${resp.body?.string().orEmpty().take(160)}")
            }
        }
    }

    // ── Internal Kaggle REST Protocol Helpers ──

    private data class KernelStatus(
        val rawStatus: String,
        val normalized: String,
        val failureMessage: String,
    )

    private suspend fun waitForIdleSlug(
        username: String,
        auth: String,
        slug: String,
        onProgress: (KaggleProgress) -> Unit,
    ) {
        val deadlineMs = System.currentTimeMillis() + 15 * 60 * 1000L
        while (currentCoroutineContext().isActive && System.currentTimeMillis() < deadlineMs) {
            val st = fetchKernelStatus(username, auth, slug)
            if (st.normalized == "queued" || st.normalized == "running") {
                onProgress(KaggleProgress("waiting_for_slot", "Waiting for previous Kaggle job to finish..."))
                delay(5000L)
            } else {
                return
            }
        }
    }

    private suspend fun pushKernelWithRetry(
        username: String,
        auth: String,
        requestedSlug: String,
        title: String,
        script: String,
        enableGpu: Boolean,
        enableInternet: Boolean,
        datasetSources: List<String>,
        sessionTimeoutSeconds: Int,
        onRateLimit: (Int) -> Unit = {},
    ): String {
        val fullSlug = "$username/$requestedSlug"
        val payload = buildJsonObject {
            put("slug", fullSlug)
            put("newTitle", title)
            put("text", script)
            put("language", "python")
            put("kernelType", "script")
            put("isPrivate", true)
            put("enableGpu", enableGpu)
            put("enableInternet", enableInternet)
            put("datasetDataSources", buildJsonArray { datasetSources.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } })
            put("competitionDataSources", buildJsonArray {})
            put("kernelDataSources", buildJsonArray {})
            put("modelDataSources", buildJsonArray {})
            put("categoryIds", buildJsonArray {})
            put("sessionTimeoutSeconds", sessionTimeoutSeconds)
        }.toString()

        val backoffs = longArrayOf(1000L, 2000L, 4000L)
        var lastError: Throwable? = null
        for (attempt in 0..3) {
            val req = Request.Builder()
                .url("$API_BASE/kernels/push")
                .header("Authorization", auth)
                .header("User-Agent", USER_AGENT)
                .post(payload.toRequestBody(jsonMedia))
                .build()
            val res = runCatching {
                client.newCall(req).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (resp.code == 429) throw IllegalStateException("HTTP_429")
                    if (!resp.isSuccessful) {
                        throw IllegalStateException("Kaggle push HTTP ${resp.code}: ${body.take(240)}")
                    }
                    val obj = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull()
                    val ref = obj?.get("ref")?.jsonPrimitive?.contentOrNull
                        ?: obj?.get("refNullable")?.jsonPrimitive?.contentOrNull
                        ?: ""
                    if (ref.contains("/")) ref.substringAfterLast("/") else requestedSlug
                }
            }
            if (res.isSuccess) return res.getOrThrow()
            lastError = res.exceptionOrNull()
            if (attempt < backoffs.size) {
                val waitMs = backoffs[attempt]
                if (lastError?.message == "HTTP_429") {
                    onRateLimit((waitMs / 1000L).toInt())
                }
                delay(waitMs)
                continue
            }
            break
        }
        throw lastError ?: IllegalStateException("Kaggle kernel push failed.")
    }

    private fun fetchKernelStatus(username: String, auth: String, kernelSlug: String): KernelStatus {
        val payload = buildJsonObject {
            put("userName", username)
            put("kernelSlug", kernelSlug)
        }.toString()
        val postReq = Request.Builder()
            .url("$API_BASE/kernels/status")
            .header("Authorization", auth)
            .header("User-Agent", USER_AGENT)
            .post(payload.toRequestBody(jsonMedia))
            .build()

        val rawBody: String = runCatching {
            client.newCall(postReq).execute().use { resp ->
                if (resp.code == 404 || resp.code == 405) {
                    val getUrl = "$API_BASE/kernels/status?userName=${URLEncoder.encode(username, "UTF-8")}&kernelSlug=${URLEncoder.encode(kernelSlug, "UTF-8")}"
                    val getReq = Request.Builder()
                        .url(getUrl)
                        .header("Authorization", auth)
                        .header("User-Agent", USER_AGENT)
                        .get()
                        .build()
                    client.newCall(getReq).execute().use { gResp -> gResp.body?.string().orEmpty() }
                } else {
                    resp.body?.string().orEmpty()
                }
            }
        }.getOrDefault("")

        val obj = runCatching { json.parseToJsonElement(rawBody).jsonObject }.getOrNull()
        val raw = obj?.get("status")?.jsonPrimitive?.contentOrNull?.lowercase().orEmpty()
        val fail = obj?.get("failureMessage")?.jsonPrimitive?.contentOrNull.orEmpty()
        val normalized = when (raw) {
            "queued", "new_script" -> "queued"
            "running" -> "running"
            "complete" -> "complete"
            "error" -> "error"
            "cancel_requested", "cancel_acknowledged", "cancelrequested", "cancelacknowledged" -> "cancelled"
            else -> "unknown"
        }
        return KernelStatus(rawStatus = raw.ifBlank { "unknown" }, normalized = normalized, failureMessage = fail)
    }

    private fun fetchOutputJson(username: String, auth: String, kernelSlug: String, pageToken: String? = null): Pair<String, JsonObject?> {
        val payload = buildJsonObject {
            put("userName", username)
            put("kernelSlug", kernelSlug)
            put("pageSize", 100)
            if (!pageToken.isNullOrBlank()) put("pageToken", pageToken)
        }.toString()
        val postReq = Request.Builder()
            .url("$API_BASE/kernels/output")
            .header("Authorization", auth)
            .header("User-Agent", USER_AGENT)
            .post(payload.toRequestBody(jsonMedia))
            .build()
        return runCatching {
            client.newCall(postReq).execute().use { resp ->
                if (resp.code == 404 || resp.code == 405) {
                    val q = buildString {
                        append("$API_BASE/kernels/output?userName=${URLEncoder.encode(username, "UTF-8")}&kernelSlug=${URLEncoder.encode(kernelSlug, "UTF-8")}&pageSize=100")
                        if (!pageToken.isNullOrBlank()) append("&pageToken=${URLEncoder.encode(pageToken, "UTF-8")}")
                    }
                    val getReq = Request.Builder().url(q).header("Authorization", auth).header("User-Agent", USER_AGENT).get().build()
                    client.newCall(getReq).execute().use { gResp ->
                        val ct = gResp.header("Content-Type").orEmpty()
                        val b = gResp.body?.string().orEmpty()
                        ct to runCatching { json.parseToJsonElement(b).jsonObject }.getOrNull()
                    }
                } else {
                    val ct = resp.header("Content-Type").orEmpty()
                    val b = resp.body?.string().orEmpty()
                    ct to runCatching { json.parseToJsonElement(b).jsonObject }.getOrNull()
                }
            }
        }.getOrDefault("" to null)
    }

    private fun fetchLogTail(username: String, auth: String, kernelSlug: String): String {
        val (_, obj) = fetchOutputJson(username, auth, kernelSlug)
        return obj?.get("log")?.jsonPrimitive?.contentOrNull.orEmpty()
    }

    private fun fetchLatestLogLine(username: String, auth: String, kernelSlug: String): String? {
        val log = fetchLogTail(username, auth, kernelSlug)
        if (log.isBlank()) return null
        return log.lineSequence()
            .map { it.trim() }
            .filter { it.isNotBlank() && ("[render]" in it || "[cache]" in it || "Step " in it || "Downloading" in it || "Loading" in it) }
            .lastOrNull()
            ?.removePrefix("[render]")
            ?.removePrefix("[cache]")
            ?.trim()
            ?.take(96)
    }

    private fun downloadOutputs(
        username: String,
        auth: String,
        kernelSlug: String,
        prompt: String,
    ): Triple<List<File>, List<Long>, Float?> {
        val allFileEntries = mutableListOf<Pair<String, String>>()
        var nextToken: String? = null
        var pages = 0
        do {
            val (_, obj) = fetchOutputJson(username, auth, kernelSlug, nextToken)
            val filesArr = obj?.get("files")?.jsonArray
            filesArr?.forEach { el ->
                val fObj = el as? JsonObject ?: return@forEach
                val name = fObj["fileName"]?.jsonPrimitive?.contentOrNull
                    ?: fObj["file_name"]?.jsonPrimitive?.contentOrNull
                    ?: ""
                val url = fObj["url"]?.jsonPrimitive?.contentOrNull.orEmpty()
                if (name.isNotBlank() && url.isNotBlank()) {
                    allFileEntries.add(name to url)
                }
            }
            nextToken = obj?.get("nextPageToken")?.jsonPrimitive?.contentOrNull
                ?: obj?.get("next_page_token")?.jsonPrimitive?.contentOrNull
            pages++
        } while (!nextToken.isNullOrBlank() && pages < 5)

        val imgRegex = Regex("""^out(_\d+)?\.(jpg|jpeg|png)$""", RegexOption.IGNORE_CASE)
        val imageEntries = allFileEntries
            .filter { imgRegex.matches(it.first) || it.first.endsWith(".jpg", true) || it.first.endsWith(".png", true) }
            .sortedBy { it.first }
        val metaEntry = allFileEntries.firstOrNull { it.first.equals("meta.json", ignoreCase = true) }

        if (imageEntries.isEmpty()) {
            throw IllegalStateException("Kaggle kernel completed without generating an image file.")
        }

        val ts = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(Date())
        val safePrompt = prompt.take(50).replace(Regex("[^a-zA-Z0-9 _-]"), "").trim().replace(Regex("\\s+"), "_").take(40).ifBlank { "render" }
        val outDir = galleryDir()
        val savedFiles = mutableListOf<File>()

        imageEntries.forEachIndexed { idx, (fileName, dlUrl) ->
            val rawBytes = downloadSignedBytes(dlUrl, auth)
            val cleanBytes = extractImageBytesSafe(rawBytes)
            val ext = fileName.substringAfterLast('.', "jpg").lowercase()
            val suffix = if (imageEntries.size > 1) "_${(idx + 1).toString().padStart(2, '0')}" else ""
            val dest = File(outDir, "kaggle_${ts}_${safePrompt}${suffix}.$ext")
            FileOutputStream(dest).use { it.write(cleanBytes) }
            savedFiles.add(dest)
        }

        var seeds: List<Long> = emptyList()
        var metaSeconds: Float? = null
        if (metaEntry != null) {
            runCatching {
                val metaBytes = downloadSignedBytes(metaEntry.second, auth)
                val metaTxt = String(metaBytes, Charsets.UTF_8)
                val metaFile = File(outDir, "${savedFiles.first().nameWithoutExtension}.meta.json")
                metaFile.writeText(metaTxt)
                val metaObj = json.parseToJsonElement(metaTxt).jsonObject
                seeds = metaObj["seeds"]?.jsonArray?.mapNotNull { it.jsonPrimitive.longOrNull }.orEmpty()
                metaSeconds = metaObj["seconds"]?.jsonPrimitive?.doubleOrNull?.toFloat()
            }
        }
        return Triple(savedFiles, seeds.ifEmpty { listOf(-1L) }, metaSeconds)
    }

    private fun downloadSignedBytes(url: String, auth: String): ByteArray {
        // Signed GCS URLs reject Authorization headers; try clean GET first, fallback with auth
        val cleanReq = Request.Builder().url(url).header("User-Agent", USER_AGENT).get().build()
        client.newCall(cleanReq).execute().use { resp ->
            if (resp.isSuccessful) {
                return resp.body?.bytes() ?: throw IllegalStateException("Empty download body.")
            }
        }
        val authReq = Request.Builder().url(url).header("Authorization", auth).header("User-Agent", USER_AGENT).get().build()
        client.newCall(authReq).execute().use { resp ->
            if (!resp.isSuccessful) throw IllegalStateException("Download HTTP ${resp.code}")
            return resp.body?.bytes() ?: throw IllegalStateException("Empty download body.")
        }
    }

    private fun extractImageBytesSafe(raw: ByteArray): ByteArray {
        // Handle Kaggle single-file ZIP wrapper
        if (raw.size > 4 && raw[0] == 0x50.toByte() && raw[1] == 0x4B.toByte()) {
            ZipInputStream(raw.inputStream()).use { zis ->
                var entry = zis.nextEntry
                while (entry != null) {
                    if (entry.name.endsWith(".jpg", true) || entry.name.endsWith(".jpeg", true) || entry.name.endsWith(".png", true)) {
                        return zis.readBytes()
                    }
                    entry = zis.nextEntry
                }
            }
        }
        // JPEG magic-byte sanitization (FF D8 FF ... FF D9) if wrapped
        var startIdx = -1
        for (i in 0 until raw.size - 2) {
            if (raw[i] == 0xFF.toByte() && raw[i + 1] == 0xD8.toByte() && raw[i + 2] == 0xFF.toByte()) {
                startIdx = i
                break
            }
        }
        if (startIdx > 0) {
            var endIdx = raw.size
            for (i in raw.size - 2 downTo startIdx + 2) {
                if (raw[i] == 0xFF.toByte() && raw[i + 1] == 0xD9.toByte()) {
                    endIdx = i + 2
                    break
                }
            }
            return raw.copyOfRange(startIdx, endIdx)
        }
        return raw
    }

    private suspend fun pushStealthWipe(username: String, auth: String, kernelSlug: String) {
        val wipeScript = """
import os, shutil
print('[stealth] Sanitizing cloud session...')
w = '/kaggle/working'
if os.path.exists(w):
    for f in os.listdir(w):
        p = os.path.join(w, f)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
            elif os.path.isdir(p):
                shutil.rmtree(p)
        except Exception:
            pass
print('[stealth] Cloud traces cleared.')
        """.trimIndent()
        pushKernelWithRetry(
            username = username,
            auth = auth,
            requestedSlug = kernelSlug,
            title = "Cloud Render W1",
            script = wipeScript,
            enableGpu = false,
            enableInternet = false,
            datasetSources = emptyList(),
            sessionTimeoutSeconds = 300,
        )
    }

    private fun publishToMediaStore(file: File) {
        val mime = if (file.extension.equals("png", true)) "image/png" else "image/jpeg"
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, file.name)
            put(MediaStore.Images.Media.MIME_TYPE, mime)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/Cellium")
            }
        }
        val resolver = appContext.contentResolver
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values) ?: return
        resolver.openOutputStream(uri)?.use { out ->
            file.inputStream().use { input -> input.copyTo(out) }
        }
    }

    // ── Exact PC-Parity Python Kernel Script Builders (str.replace + pyRepr, never String.format) ──

    private fun buildRenderKernelScript(req: GenerationRequest, modelCfg: ModelConfig): String {
        val cfgJson = buildJsonObject {
            put("prompt", req.prompt)
            put("neg", req.negativePrompt)
            put("steps", req.steps.coerceIn(1, 100))
            put("w", req.width.coerceIn(256, 2048))
            put("h", req.height.coerceIn(256, 2048))
            put("seed", req.seed)
            put("guidance", req.guidanceScale.coerceIn(0f, 20f).toDouble())
            put("batch", req.batch.coerceIn(1, 20))
            put("init_b64", req.initB64)
            put("denoise", req.denoise.coerceIn(0.1f, 0.98f).toDouble())
            put("dataset_slug", modelCfg.datasetSlug)
            put("model", modelCfg.hfModel)
            put("civitai_url", modelCfg.civitaiUrl)
            put("lora_url", modelCfg.loraUrl)
            put("lora_strength", modelCfg.loraStrength.coerceIn(0.1f, 2.0f).toDouble())
        }.toString()

        val loaderCode = buildString {
            if (modelCfg.mode == "hf") {
                val repoRepr = pyRepr(modelCfg.hfModel)
                appendLine("klog('Loading HuggingFace model ' + $repoRepr + '...')")
                if (modelCfg.hfToken.isNotBlank()) {
                    appendLine("pipe = StableDiffusionXLPipeline.from_pretrained($repoRepr, torch_dtype=torch.float16, token=${pyRepr(modelCfg.hfToken)})")
                } else {
                    appendLine("pipe = StableDiffusionXLPipeline.from_pretrained($repoRepr, torch_dtype=torch.float16)")
                }
                appendLine("klog('HuggingFace model loaded.')")
            } else {
                val tokRepr = if (modelCfg.civitaiToken.isNotBlank()) pyRepr(modelCfg.civitaiToken) else "None"
                append(
                    """
import requests, re, glob as _glob
TOK = $tokRepr

def _cv_headers():
    return {"Authorization": "Bearer " + TOK} if TOK else {}

def _cv_resolve(url):
    if re.search(r'civitai.com/api/download/models/[0-9]+', url or ''):
        return url
    m = re.search(r'civitai.com/models/([0-9]+)', url or '')
    if not m:
        return url
    mid = m.group(1)
    direct = 'https://civitai.com/api/download/models/' + mid
    try:
        r = requests.get('https://civitai.com/api/v1/models/' + mid, headers=_cv_headers(), timeout=20)
        r.raise_for_status()
        vers = (r.json() or {}).get('modelVersions', []) or []
        def good(v):
            b = (v.get('baseModel') or '').upper()
            n = (v.get('name') or '').lower()
            return ('SDXL' in b or 'ILLUSTRIOUS' in b) and 'inpaint' not in n
        pick = next((v for v in vers if good(v)), None)
        if pick is None:
            pick = next((v for v in vers if 'inpaint' not in (v.get('name') or '').lower()), None)
        if pick is None and vers:
            pick = vers[0]
        if pick is not None:
            for f in (pick.get('files') or []):
                if (f.get('name') or '').lower().endswith('.safetensors'):
                    return f.get('downloadUrl') or f.get('url') or direct
            if pick.get('id'):
                return 'https://civitai.com/api/download/models/' + str(pick['id'])
    except Exception as e:
        print('Civitai API resolve failed, using direct download:', e)
    return direct

_slug = CFG.get('dataset_slug') or ''
_mounted = []
if _slug:
    _cands = [p for p in _glob.glob('/kaggle/input/**/*.safetensors', recursive=True)
              if _slug in p and 'lora' not in p.lower()]
    if _cands:
        _mounted = _cands
if _mounted:
    MODEL_PATH = _mounted[0]
    klog('Loaded model from mounted cloud cache:', MODEL_PATH)
else:
    URL = _cv_resolve(CFG["civitai_url"])
    klog('Civitai resolved ->', URL[:120])
    r = requests.get(URL, headers=_cv_headers(), stream=True, timeout=300)
    r.raise_for_status()
    _dl_total = 0
    with open("/kaggle/working/model.safetensors", "wb") as f:
        for chunk in r.iter_content(1 << 22):
            f.write(chunk)
            _dl_total += len(chunk)
            if _dl_total % (200 * 1024 * 1024) < len(chunk):
                klog(f'Downloading model: {_dl_total // (1024*1024)} MB')
    klog('Model downloaded successfully.')
    MODEL_PATH = '/kaggle/working/model.safetensors'
klog('Loading SDXL pipeline from safetensors...')
pipe = StableDiffusionXLPipeline.from_single_file(MODEL_PATH, torch_dtype=torch.float16)
klog('SDXL pipeline loaded into memory.')
                    """.trimIndent()
                )
            }

            if (modelCfg.loraUrl.isNotBlank()) {
                val loraHeaderLine = if (modelCfg.civitaiToken.isNotBlank()) {
                    "headers = {'Authorization': 'Bearer ' + ${pyRepr(modelCfg.civitaiToken)}}"
                } else {
                    "headers = {}"
                }
                appendLine()
                append(
                    """
if CFG.get("lora_url"):
    try:
        import glob as _lg
        _sl = CFG.get('dataset_slug') or ''
        _lm = [p for p in _lg.glob('/kaggle/input/**/lora.safetensors', recursive=True)
               if _sl and _sl in p] if _sl else []
        if _lm:
            _lora_path = _lm[0]
            klog("LoRA from mounted cloud cache:", _lora_path)
        else:
            import requests
            $loraHeaderLine
            r = requests.get(CFG["lora_url"], headers=headers, stream=True, timeout=180)
            r.raise_for_status()
            with open("/kaggle/working/lora.safetensors", "wb") as f:
                for chunk in r.iter_content(1 << 22):
                    f.write(chunk)
            _lora_path = "/kaggle/working/lora.safetensors"
        pipe.load_lora_weights(_lora_path)
        _names = set()
        try:
            for _v in pipe.get_list_adapters().values():
                _names.update(_v)
        except Exception:
            pass
        if not _names:
            try:
                pipe.unload_lora_weights()
            except Exception:
                pass
            klog("LoRA registered ZERO adapters (arch mismatch) - unloaded")
        else:
            _names = sorted(_names)
            pipe.set_adapters(_names, adapter_weights=[CFG.get('lora_strength', 0.9)] * len(_names))
            klog("LoRA applied", _names)
    except Exception as e:
        klog("LoRA skipped (download/load failed):", e)
                    """.trimIndent()
                )
            }
        }

        val template = """
import json, time, subprocess, sys
try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
    sys.stderr.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

def klog(*a):
    print("[render]", *a, flush=True)

t0 = time.time()
klog("Initializing cloud render environment...")
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q",
    "diffusers>=0.34", "transformers>=4.41,<5", "accelerate", "safetensors"])
klog("Dependencies verified and ready.")

import torch
from diffusers import StableDiffusionXLPipeline

CFG = json.loads(__CFG_JSON__)
klog(f"Config loaded (steps: {CFG.get('steps')}, size: {CFG.get('w')}x{CFG.get('h')}, batch: {CFG.get('batch')})")

__MODEL_LOADER__

try:
    pipe.vae.config.force_upcast = True
except Exception:
    pass
try:
    pipe.enable_vae_slicing()
    pipe.enable_vae_tiling()
except Exception:
    pass

device = "cuda" if torch.cuda.is_available() else "cpu"
klog(f"Targeting device: {device}")
if device == "cuda":
    pipe = pipe.to("cuda")
else:
    pipe.enable_model_cpu_offload()

active_pipe = pipe
init_image = None
if CFG.get("init_b64"):
    import base64, io as _io
    from PIL import Image as _PILImage
    from diffusers import StableDiffusionXLImg2ImgPipeline
    init_image = _PILImage.open(_io.BytesIO(base64.b64decode(CFG["init_b64"]))).convert("RGB")
    active_pipe = StableDiffusionXLImg2ImgPipeline(**pipe.components)
    if device == "cuda":
        active_pipe = active_pipe.to("cuda")
    else:
        active_pipe.enable_model_cpu_offload()
    klog("img2img mode active, strength", CFG.get("denoise", 0.75))

batch = max(1, int(CFG.get("batch", 1)))
seeds = []
total_steps = int(CFG.get("steps", 28))

for i in range(batch):
    seed = (CFG["seed"] + i) if CFG["seed"] >= 0 else (int(time.time() * 1000) + i) % (2**32)
    klog(f"Starting image {i+1}/{batch} (seed: {seed})...")

    def _step_cb(p, s_idx, ts, cb_kwargs):
        step_num = s_idx + 1
        if step_num % 2 == 0 or step_num == total_steps or step_num == 1:
            klog(f"Step {step_num}/{total_steps} [img {i+1}/{batch}]")
        return cb_kwargs

    kwargs = dict(
        prompt=CFG["prompt"],
        negative_prompt=CFG.get("neg", ""),
        num_inference_steps=total_steps,
        guidance_scale=CFG.get("guidance", 6.5),
        generator=torch.Generator(device).manual_seed(seed),
        callback_on_step_end=_step_cb,
    )
    if init_image is not None:
        kwargs["image"] = init_image
        kwargs["strength"] = CFG.get("denoise", 0.75)
    else:
        kwargs["width"] = CFG["w"]
        kwargs["height"] = CFG["h"]
    img = active_pipe(**kwargs).images[0]
    name = "out.jpg" if batch == 1 else f"out_{i+1:02d}.jpg"
    img.convert("RGB").save(f"/kaggle/working/{name}", "JPEG", quality=88, optimize=True)
    seeds.append(seed)
    klog(f"Saved {name} ({i+1}/{batch}) [88% quality JPEG]")

json.dump({"seeds": seeds, "seconds": round(time.time() - t0, 1)},
          open("/kaggle/working/meta.json", "w"))
klog("ALLDONE", seeds)
        """.trimIndent()

        return template
            .replace("__CFG_JSON__", pyRepr(cfgJson))
            .replace("__MODEL_LOADER__", loaderCode)
    }

    private fun buildCacheBuilderScript(
        kaggleUser: String,
        kaggleKey: String,
        datasetSlug: String,
        datasetTitle: String,
        civitaiUrl: String,
        loraUrl: String,
        civitaiToken: String,
    ): String {
        val tokLine = if (civitaiToken.isNotBlank()) pyRepr(civitaiToken) else "None"
        return """
import os, sys, json, base64, requests
try:
    sys.stdout.reconfigure(line_buffering=True, write_through=True)
except Exception:
    pass

def clog(*a):
    print("[cache]", *a, flush=True)

USER = ${pyRepr(kaggleUser)}
KEY = ${pyRepr(kaggleKey)}
SLUG = ${pyRepr(datasetSlug)}
TITLE = ${pyRepr(datasetTitle)}
MODEL_URL = ${pyRepr(civitaiUrl)}
LORA_URL = ${pyRepr(loraUrl)}
CV_TOK = $tokLine

AUTH = "Basic " + base64.b64encode((USER + ":" + KEY).encode("utf-8")).decode("ascii")
KHEADERS = {"Authorization": AUTH, "User-Agent": "Cellium/1.0"}
CVHEADERS = {"Authorization": "Bearer " + CV_TOK} if CV_TOK else {}

def download_file(url, dest):
    clog("Downloading", dest)
    r = requests.get(url, headers=CVHEADERS, stream=True, timeout=600)
    r.raise_for_status()
    total = 0
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 22):
            f.write(chunk)
            total += len(chunk)
            if total % (200 * 1024 * 1024) < len(chunk):
                clog(f"{os.path.basename(dest)}: {total // (1024*1024)} MB")
    clog(f"Downloaded {os.path.basename(dest)} ({total // (1024*1024)} MB)")
    return total

def upload_blob(path, name):
    size = os.path.getsize(path)
    clog(f"Requesting Kaggle blob for {name} ({size // (1024*1024)} MB)...")
    r = requests.post(
        "https://www.kaggle.com/api/v1/blobs/upload",
        headers={**KHEADERS, "Content-Type": "application/json"},
        json={"type": "DATASET", "name": name, "contentType": "application/octet-stream", "contentLength": size},
        timeout=60,
    )
    r.raise_for_status()
    meta = r.json()
    token = meta["token"]
    create_url = meta["createUrl"]
    clog(f"Streaming {name} to Kaggle blob storage...")
    with open(path, "rb") as f:
        up = requests.put(
            create_url,
            data=f,
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)},
            timeout=1800,
        )
        up.raise_for_status()
    clog(f"Blob uploaded for {name}.")
    return token

files_payload = []
download_file(MODEL_URL, "/kaggle/working/model.safetensors")
files_payload.append({"token": upload_blob("/kaggle/working/model.safetensors", "model.safetensors")})
os.remove("/kaggle/working/model.safetensors")

if LORA_URL:
    try:
        download_file(LORA_URL, "/kaggle/working/lora.safetensors")
        files_payload.append({"token": upload_blob("/kaggle/working/lora.safetensors", "lora.safetensors")})
        os.remove("/kaggle/working/lora.safetensors")
    except Exception as e:
        clog("Optional LoRA skipped:", e)

clog("Creating private Kaggle dataset", SLUG)
cr = requests.post(
    "https://www.kaggle.com/api/v1/datasets/create/new",
    headers={**KHEADERS, "Content-Type": "application/json"},
    json={
        "ownerSlug": USER,
        "slug": SLUG,
        "title": TITLE,
        "licenseName": "CC0-1.0",
        "isPrivate": True,
        "files": files_payload,
        "categoryIds": [],
    },
    timeout=120,
)
cr.raise_for_status()
clog("CACHE_READY", SLUG)
        """.trimIndent()
    }
}

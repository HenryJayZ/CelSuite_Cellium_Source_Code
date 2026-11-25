package com.henny.cellium.ai

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Base64
import com.henny.cellium.core.DevLogBuffer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
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
import java.io.File
import java.io.FileOutputStream
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream
import kotlin.random.Random

data class ImagineProviderOption(
    val id: String,
    val label: String,
    val requiresKey: Boolean,
    val defaultModels: List<String>,
)

data class KaggleCredentials(
    val username: String,
    val key: String,
)

data class GeneratedImageResult(
    val localFile: File,
    val bitmap: Bitmap,
    val seed: Long,
    val provider: String,
    val model: String,
)

/**
 * Multi-Provider Image Generation Studio client:
 * - Pollinations.ai (Free · No Key)
 * - Kaggle GPU Diffusers Runner (via imported kaggle.json + Kaggle REST API v1)
 * - HuggingFace Inference (BYOK)
 * - OpenAI Images (BYOK)
 * - Custom OpenAI-compatible Images endpoint
 */
class MultiImagineClient(private val context: Context) {
    private val appContext = context.applicationContext
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(150, TimeUnit.SECONDS)
        .build()

    fun galleryDir(): File {
        val dir = appContext.getExternalFilesDir("artworks") ?: File(appContext.filesDir, "gallery")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun parseKaggleJson(rawJson: String): Result<KaggleCredentials> = runCatching {
        val obj = json.parseToJsonElement(rawJson.trim()).jsonObject
        val user = obj["username"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        val key = obj["key"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        require(user.isNotBlank() && key.isNotBlank()) {
            "Invalid kaggle.json: expected {\"username\":\"...\",\"key\":\"...\"}."
        }
        KaggleCredentials(user, key)
    }

    suspend fun fetchAiHordeImageModels(): Result<List<String>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder()
                .url("https://aihorde.net/api/v2/status/models?type=image&model_state=known")
                .header("Client-Agent", "CelCellium:2611.23.0:android")
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("AI Horde HTTP ${resp.code}")
                val body = resp.body?.string().orEmpty()
                val arr = json.parseToJsonElement(body).jsonArray
                val ranked = arr.mapNotNull { el ->
                    val obj = el.jsonObject
                    val name = obj["name"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
                    val count = obj["count"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 0
                    val eta = obj["eta"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 999
                    val low = name.lowercase()
                    if (name.isBlank() || count < 1 || "nsfw" in low || "hentai" in low || "porn" in low || "nude" in low) {
                        null
                    } else {
                        Triple(name, count, eta)
                    }
                }.sortedWith(compareByDescending<Triple<String, Int, Int>> { it.second }.thenBy { it.third })
                    .map { it.first }
                    .take(14)
                listOf("Auto (Fastest)") + ranked
            }
        }
    }

    suspend fun fetchPollinationsImageModels(): Result<List<String>> = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder()
                .url("https://image.pollinations.ai/models")
                .header("User-Agent", "Cel.Cellium-Android/2611.23.0")
                .get()
                .build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) throw IllegalStateException("HTTP ${resp.code}")
                val body = resp.body?.string().orEmpty()
                val arr = json.parseToJsonElement(body).jsonArray
                arr.mapNotNull { el ->
                    el.jsonPrimitive.contentOrNull?.trim()
                }.filter { it.isNotBlank() }.ifEmpty { listOf("flux", "turbo") }
            }
        }
    }

    suspend fun generateImage(
        prompt: String,
        negativePrompt: String = "",
        provider: String = "aihorde",
        model: String = "Auto (Fastest)",
        aspectRatio: String = "1:1",
        apiKey: String = "",
        customUrl: String = "",
        kaggleUsername: String = "",
        kaggleKey: String = "",
        kaggleKernelSlug: String = "cellium-gpu-imagine",
        seedInput: Long? = null,
        onStatusUpdate: ((String) -> Unit)? = null,
    ): Result<GeneratedImageResult> = withContext(Dispatchers.IO) {
        val cleanPrompt = prompt.trim()
        if (cleanPrompt.isEmpty()) {
            return@withContext Result.failure(IllegalArgumentException("Enter an image prompt first."))
        }
        val seed = seedInput ?: Random.nextLong(1, 999_999_999L)
        val (width, height) = dimensionsFor(aspectRatio)
        val fullPrompt = if (negativePrompt.isNotBlank()) {
            "$cleanPrompt (avoid: ${negativePrompt.trim()})"
        } else cleanPrompt

        runCatching {
            val resolvedModel = when (provider) {
                "aihorde" -> model.trim().ifBlank { "Auto (Fastest)" }
                "pollinations" -> model.trim().ifBlank { "flux" }
                else -> model.trim()
            }
            var usedProvider = provider
            var usedModel = resolvedModel
            val bytes: ByteArray = when (provider) {
                "aihorde" -> fetchAiHorde(
                    prompt = cleanPrompt,
                    negativePrompt = negativePrompt,
                    model = resolvedModel,
                    aspectRatio = aspectRatio,
                    seed = seed,
                    apiKey = apiKey,
                    onStatusUpdate = onStatusUpdate,
                )
                "pollinations" -> {
                    onStatusUpdate?.invoke("Generating via Pollinations ($resolvedModel)...")
                    try {
                        fetchPollinations(fullPrompt, resolvedModel, width, height, seed, apiKey)
                    } catch (e: Exception) {
                        val msg = e.localizedMessage.orEmpty()
                        if (apiKey.isBlank() && (msg.contains("402") || msg.contains("503") || msg.contains("429"))) {
                            DevLogBuffer.add("WARN", "Illume", "Pollinations keyless failed ($msg); auto-falling back to AI Horde free cluster.")
                            onStatusUpdate?.invoke("Pollinations busy — switching to free AI Horde GPU...")
                            usedProvider = "aihorde"
                            usedModel = "Auto (Fastest)"
                            fetchAiHorde(
                                prompt = cleanPrompt,
                                negativePrompt = negativePrompt,
                                model = "Auto (Fastest)",
                                aspectRatio = aspectRatio,
                                seed = seed,
                                apiKey = "",
                                onStatusUpdate = onStatusUpdate,
                            )
                        } else {
                            throw e
                        }
                    }
                }
                "kaggle" -> fetchKaggleGpu(
                    prompt = cleanPrompt,
                    negativePrompt = negativePrompt,
                    modelId = resolvedModel.ifBlank { "stabilityai/sdxl-turbo" },
                    width = width,
                    height = height,
                    seed = seed,
                    username = kaggleUsername,
                    key = kaggleKey,
                    slug = kaggleKernelSlug.ifBlank { "cellium-gpu-imagine" },
                    onStatusUpdate = onStatusUpdate,
                )
                "huggingface" -> {
                    onStatusUpdate?.invoke("Calling HuggingFace Router...")
                    fetchHuggingFace(fullPrompt, resolvedModel.ifBlank { "black-forest-labs/FLUX.1-schnell" }, apiKey)
                }
                "openai" -> {
                    onStatusUpdate?.invoke("Calling OpenAI Images...")
                    fetchOpenAiImages(
                        url = "https://api.openai.com/v1/images/generations",
                        prompt = fullPrompt,
                        model = resolvedModel.ifBlank { "gpt-image-1" },
                        aspectRatio = aspectRatio,
                        apiKey = apiKey,
                    )
                }
                "custom" -> {
                    onStatusUpdate?.invoke("Calling Custom Endpoint...")
                    val base = customUrl.trim().trimEnd('/')
                    require(base.isNotBlank()) { "Set your Custom Image Endpoint URL first." }
                    val url = if (base.endsWith("/images/generations")) base else "$base/images/generations"
                    fetchOpenAiImages(url, fullPrompt, resolvedModel.ifBlank { "sana" }, aspectRatio, apiKey)
                }
                else -> fetchAiHorde(
                    prompt = cleanPrompt,
                    negativePrompt = negativePrompt,
                    model = "Auto (Fastest)",
                    aspectRatio = aspectRatio,
                    seed = seed,
                    apiKey = apiKey,
                    onStatusUpdate = onStatusUpdate,
                )
            }
            val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: throw IllegalStateException("Provider returned a non-image payload.")
            val outFile = File(galleryDir(), "cel_illume_${System.currentTimeMillis()}_$seed.png")
            FileOutputStream(outFile).use { fos ->
                bmp.compress(Bitmap.CompressFormat.PNG, 96, fos)
            }
            DevLogBuffer.add("INFO", "Illume", "Generated ${width}x$height via $usedProvider ($usedModel)")
            GeneratedImageResult(
                localFile = outFile,
                bitmap = bmp,
                seed = seed,
                provider = usedProvider,
                model = usedModel,
            )
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "Illume", "Generation failed ($provider): ${err.localizedMessage}")
        }
    }

    /**
     * Free keyless community GPU generation via AI Horde (https://aihorde.net).
     * Uses anonymous key "0000000000" (0 kudos needed for <=576px, <=25 steps) or user's free Horde key.
     */
    private suspend fun fetchAiHorde(
        prompt: String,
        negativePrompt: String,
        model: String,
        aspectRatio: String,
        seed: Long,
        apiKey: String,
        onStatusUpdate: ((String) -> Unit)?,
    ): ByteArray {
        val hordeKey = apiKey.trim().ifBlank { "0000000000" }
        val (w, h) = when (aspectRatio) {
            "16:9" -> 576 to 384
            "9:16" -> 384 to 576
            "4:3" -> 576 to 448
            "3:4" -> 448 to 576
            else -> 512 to 512
        }
        val combinedPrompt = if (negativePrompt.isNotBlank()) {
            "$prompt ### ${negativePrompt.trim()}"
        } else prompt

        val modelList = if (model.isBlank() || model.equals("Auto (Fastest)", ignoreCase = true)) {
            listOf("Deliberate", "ICBINP - I Can't Believe It's Not Photography", "Realistic Vision", "stable_diffusion")
        } else {
            listOf(model)
        }

        val payload = buildJsonObject {
            put("prompt", combinedPrompt)
            put("params", buildJsonObject {
                put("width", w)
                put("height", h)
                put("steps", 22)
                put("cfg_scale", 7.0)
                put("sampler_name", "k_euler_a")
                put("seed", seed.toString())
                put("n", 1)
            })
            put("nsfw", false)
            put("censor_nsfw", true)
            put("trusted_workers", false)
            put("r2", true)
            put("models", buildJsonArray { modelList.forEach { add(kotlinx.serialization.json.JsonPrimitive(it)) } })
        }.toString()

        onStatusUpdate?.invoke("AI Horde: submitting to free GPU cluster...")
        val submitReq = Request.Builder()
            .url("https://aihorde.net/api/v2/generate/async")
            .header("apikey", hordeKey)
            .header("Client-Agent", "CelCellium:2611.23.0:android")
            .post(payload.toRequestBody(jsonMedia))
            .build()

        val jobId = client.newCall(submitReq).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("AI Horde submit HTTP ${resp.code}: ${body.take(220)}")
            }
            val obj = json.parseToJsonElement(body).jsonObject
            obj["id"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
                ?: throw IllegalStateException("AI Horde returned no job ID.")
        }

        // Poll every 2.5s up to ~110 seconds
        for (attempt in 1..44) {
            delay(2500L)
            val statusReq = Request.Builder()
                .url("https://aihorde.net/api/v2/generate/status/$jobId")
                .header("apikey", hordeKey)
                .header("Client-Agent", "CelCellium:2611.23.0:android")
                .get()
                .build()
            client.newCall(statusReq).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) return@use
                val obj = runCatching { json.parseToJsonElement(body).jsonObject }.getOrNull() ?: return@use
                val faulted = obj["faulted"]?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull() == true
                if (faulted) throw IllegalStateException("AI Horde worker faulted. Please tap Generate again.")
                val isPossible = obj["is_possible"]?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull() ?: true
                if (!isPossible) throw IllegalStateException("No online AI Horde worker currently supports '$model'. Pick 'Auto (Fastest)'.")
                val done = obj["done"]?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull() == true
                if (done) {
                    val gens = obj["generations"]?.jsonArray
                    val first = gens?.firstOrNull()?.jsonObject
                        ?: throw IllegalStateException("AI Horde finished without returning an image.")
                    val imgVal = first["img"]?.jsonPrimitive?.contentOrNull.orEmpty()
                    if (imgVal.startsWith("http://") || imgVal.startsWith("https://")) {
                        onStatusUpdate?.invoke("AI Horde: downloading artwork...")
                        client.newCall(Request.Builder().url(imgVal).get().build()).execute().use { dl ->
                            if (!dl.isSuccessful) throw IllegalStateException("AI Horde image download HTTP ${dl.code}")
                            return dl.body?.bytes() ?: throw IllegalStateException("Empty AI Horde image stream.")
                        }
                    } else if (imgVal.isNotBlank()) {
                        return Base64.decode(imgVal, Base64.DEFAULT)
                    } else {
                        throw IllegalStateException("AI Horde returned empty image field.")
                    }
                } else {
                    val pos = obj["queue_position"]?.jsonPrimitive?.contentOrNull ?: "?"
                    val waitSec = obj["wait_time"]?.jsonPrimitive?.contentOrNull ?: "?"
                    onStatusUpdate?.invoke("AI Horde GPU: queue #$pos (~${waitSec}s)...")
                }
            }
        }
        throw IllegalStateException("AI Horde timed out waiting for a free worker. Please try again.")
    }

    /**
     * Pushes a lightweight Diffusers Python kernel to Kaggle via REST v1 using HTTP Basic Auth
     * from the user's imported kaggle.json, polls GPU execution status, and downloads output.png.
     */
    private suspend fun fetchKaggleGpu(
        prompt: String,
        negativePrompt: String,
        modelId: String,
        width: Int,
        height: Int,
        seed: Long,
        username: String,
        key: String,
        slug: String,
        onStatusUpdate: ((String) -> Unit)?,
    ): ByteArray {
        val user = username.trim()
        val token = key.trim()
        require(user.isNotBlank() && token.isNotBlank()) {
            "Import your kaggle.json file first (tap 'Import kaggle.json' in Imagine Studio)."
        }
        val cleanSlug = slug.trim().lowercase().replace(Regex("[^a-z0-9-]"), "-").ifBlank { "cellium-gpu-imagine" }
        val fullSlug = "$user/$cleanSlug"
        val basicAuth = "Basic " + Base64.encodeToString("$user:$token".toByteArray(), Base64.NO_WRAP)

        val escapedPrompt = prompt.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ")
        val escapedNeg = negativePrompt.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", " ")
        val pythonScript = """
import torch
from diffusers import AutoPipelineForText2Image
pipe = AutoPipelineForText2Image.from_pretrained("$modelId", torch_dtype=torch.float16, variant="fp16").to("cuda")
gen = torch.Generator("cuda").manual_seed($seed)
img = pipe(prompt="$escapedPrompt", negative_prompt="$escapedNeg", width=$width, height=$height, num_inference_steps=6 if "turbo" in "$modelId".lower() or "schnell" in "$modelId".lower() else 24, generator=gen).images[0]
img.save("cellium_output.png")
print("CELLIUM_DONE")
        """.trimIndent()

        val pushPayload = buildJsonObject {
            put("id", fullSlug)
            put("slug", fullSlug)
            put("newTitle", "Cellium GPU Imagine")
            put("text", pythonScript)
            put("language", "python")
            put("kernelType", "script")
            put("isPrivate", true)
            put("enableGpu", true)
            put("enableInternet", true)
            put("datasetDataSources", buildJsonArray {})
            put("competitionDataSources", buildJsonArray {})
            put("kernelDataSources", buildJsonArray {})
        }.toString()

        onStatusUpdate?.invoke("Submitting GPU job to Kaggle ($fullSlug)...")
        val pushReq = Request.Builder()
            .url("https://www.kaggle.com/api/v1/kernels/push")
            .header("Authorization", basicAuth)
            .post(pushPayload.toRequestBody(jsonMedia))
            .build()
        client.newCall(pushReq).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("Kaggle Push HTTP ${resp.code}: ${body.take(240)}")
            }
            DevLogBuffer.add("INFO", "KaggleGPU", "Kernel pushed: $fullSlug")
        }

        // Poll kernel execution up to ~3.5 minutes (42 * 5s)
        var completed = false
        for (attempt in 1..42) {
            delay(5000L)
            onStatusUpdate?.invoke("Kaggle GPU rendering (${attempt * 5}s)...")
            val statusUrl = "https://www.kaggle.com/api/v1/kernels/status?userName=${URLEncoder.encode(user, "UTF-8")}&kernelSlug=${URLEncoder.encode(cleanSlug, "UTF-8")}"
            val statusReq = Request.Builder().url(statusUrl).header("Authorization", basicAuth).get().build()
            client.newCall(statusReq).execute().use { resp ->
                val txt = resp.body?.string().orEmpty()
                if (resp.isSuccessful) {
                    val obj = runCatching { json.parseToJsonElement(txt).jsonObject }.getOrNull()
                    val status = obj?.get("status")?.jsonPrimitive?.contentOrNull?.lowercase().orEmpty()
                    val failMsg = obj?.get("failureMessage")?.jsonPrimitive?.contentOrNull.orEmpty()
                    if (status == "complete") {
                        completed = true
                    } else if (status == "error" || status == "cancelacknowledged") {
                        throw IllegalStateException("Kaggle kernel failed: ${failMsg.ifBlank { status }}")
                    }
                }
            }
            if (completed) break
        }
        if (!completed) {
            throw IllegalStateException("Kaggle GPU job timed out. Check kaggle.com/code/$fullSlug for output.")
        }

        onStatusUpdate?.invoke("Downloading Kaggle PNG output...")
        val outputUrl = "https://www.kaggle.com/api/v1/kernels/output?userName=${URLEncoder.encode(user, "UTF-8")}&kernelSlug=${URLEncoder.encode(cleanSlug, "UTF-8")}"
        val outReq = Request.Builder().url(outputUrl).header("Authorization", basicAuth).get().build()
        client.newCall(outReq).execute().use { resp ->
            val bodyStr = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("Kaggle Output HTTP ${resp.code}: ${bodyStr.take(220)}")
            }
            val obj = json.parseToJsonElement(bodyStr).jsonObject
            val files = obj["files"]?.jsonArray ?: throw IllegalStateException("Kaggle returned no output files.")
            val imgFile = files.firstOrNull { el ->
                val name = el.jsonObject["fileName"]?.jsonPrimitive?.contentOrNull.orEmpty()
                name.endsWith(".png", true) || name.endsWith(".jpg", true) || name.endsWith(".webp", true)
            }?.jsonObject ?: throw IllegalStateException("No PNG/JPG image found in Kaggle kernel output.")
            val dlUrl = imgFile["url"]?.jsonPrimitive?.contentOrNull
                ?: throw IllegalStateException("Kaggle output file missing download URL.")
            client.newCall(Request.Builder().url(dlUrl).header("Authorization", basicAuth).get().build()).execute().use { dlResp ->
                if (!dlResp.isSuccessful) throw IllegalStateException("Kaggle file download HTTP ${dlResp.code}")
                val rawBytes = dlResp.body?.bytes() ?: throw IllegalStateException("Empty Kaggle image bytes.")
                // Some Kaggle endpoints wrap single outputs in ZIP
                if (rawBytes.size > 4 && rawBytes[0] == 0x50.toByte() && rawBytes[1] == 0x4B.toByte()) {
                    ZipInputStream(rawBytes.inputStream()).use { zis ->
                        var entry = zis.nextEntry
                        while (entry != null) {
                            if (entry.name.endsWith(".png", true) || entry.name.endsWith(".jpg", true)) {
                                return zis.readBytes()
                            }
                            entry = zis.nextEntry
                        }
                    }
                }
                return rawBytes
            }
        }
    }

    private fun fetchPollinations(
        prompt: String,
        model: String,
        width: Int,
        height: Int,
        seed: Long,
        apiKey: String = "",
    ): ByteArray {
        val encoded = URLEncoder.encode(prompt, "UTF-8").replace("+", "%20")
        val cleanKey = apiKey.trim()
        val tryModels = if (cleanKey.isBlank() && !model.equals("sana", ignoreCase = true)) {
            listOf(model, "sana")
        } else {
            listOf(model)
        }
        var lastCode = 0
        for (candidateModel in tryModels) {
            val baseHost = if (cleanKey.isNotBlank()) "https://gen.pollinations.ai/image" else "https://image.pollinations.ai/prompt"
            val url = "$baseHost/$encoded?model=$candidateModel&width=$width&height=$height&seed=$seed&nologo=true"
            val rb = Request.Builder()
                .url(url)
                .header("User-Agent", "Cel.Cellium-Android/2611.22.0")
                .get()
            if (cleanKey.isNotBlank()) {
                rb.header("Authorization", "Bearer $cleanKey")
            }
            client.newCall(rb.build()).execute().use { resp ->
                if (resp.isSuccessful) {
                    return resp.body?.bytes() ?: throw IllegalStateException("Empty image stream from Pollinations.")
                }
                lastCode = resp.code
                if (resp.code == 402 && candidateModel != "sana") {
                    DevLogBuffer.add("WARN", "Illume", "Pollinations '$candidateModel' returned 402 without key; retrying with open-access 'sana'.")
                    return@use
                }
                if (resp.code == 402) {
                    throw IllegalStateException("Pollinations HTTP 402: '$candidateModel' requires a Pollinations API key. Use open-access model 'sana' or add a Pollinations key in Illume Config.")
                }
                throw IllegalStateException("Pollinations HTTP ${resp.code}. Try again or switch provider.")
            }
        }
        throw IllegalStateException("Pollinations HTTP $lastCode. Try open-access model 'sana' or add an API key.")
    }

    private fun fetchHuggingFace(prompt: String, model: String, apiKey: String): ByteArray {
        require(apiKey.isNotBlank()) { "HuggingFace requires your HF API token (Settings or Illume config)." }
        val payload = buildJsonObject { put("inputs", prompt) }.toString()
        val req = Request.Builder()
            .url("https://router.huggingface.co/hf-inference/models/${model.trim()}")
            .header("Authorization", "Bearer ${apiKey.trim()}")
            .header("Accept", "image/png")
            .post(payload.toRequestBody(jsonMedia))
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                val txt = resp.body?.string().orEmpty().take(200)
                throw IllegalStateException("HuggingFace HTTP ${resp.code}: $txt")
            }
            return resp.body?.bytes() ?: throw IllegalStateException("Empty HuggingFace image payload.")
        }
    }

    private fun fetchOpenAiImages(
        url: String,
        prompt: String,
        model: String,
        aspectRatio: String,
        apiKey: String,
    ): ByteArray {
        val sizeStr = when (aspectRatio) {
            "16:9" -> "1792x1024"
            "9:16" -> "1024x1792"
            else -> "1024x1024"
        }
        val payload = buildJsonObject {
            put("model", model)
            put("prompt", prompt)
            put("n", 1)
            put("size", sizeStr)
            put("response_format", "b64_json")
        }.toString()
        val rb = Request.Builder().url(url).post(payload.toRequestBody(jsonMedia))
        if (apiKey.isNotBlank()) rb.header("Authorization", "Bearer ${apiKey.trim()}")
        client.newCall(rb.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw IllegalStateException("Images HTTP ${resp.code}: ${body.take(220)}")
            }
            val root = json.parseToJsonElement(body).jsonObject
            val first = root["data"]?.jsonArray?.firstOrNull()?.jsonObject
                ?: throw IllegalStateException("No image data returned.")
            val b64 = first["b64_json"]?.jsonPrimitive?.contentOrNull
            if (!b64.isNullOrBlank()) {
                return Base64.decode(b64, Base64.DEFAULT)
            }
            val imgUrl = first["url"]?.jsonPrimitive?.contentOrNull
                ?: throw IllegalStateException("Image response missing b64_json and url.")
            client.newCall(Request.Builder().url(imgUrl).get().build()).execute().use { imgResp ->
                if (!imgResp.isSuccessful) throw IllegalStateException("Failed downloading image URL.")
                return imgResp.body?.bytes() ?: throw IllegalStateException("Empty image URL response.")
            }
        }
    }

    suspend fun saveToDevicePhotos(file: File): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val fileName = "Cellium_${System.currentTimeMillis()}.png"
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, fileName)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    put(MediaStore.Images.Media.RELATIVE_PATH, "${Environment.DIRECTORY_PICTURES}/Cellium")
                }
            }
            val resolver = appContext.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw IllegalStateException("Unable to create MediaStore entry.")
            resolver.openOutputStream(uri)?.use { out ->
                file.inputStream().use { input -> input.copyTo(out) }
            } ?: throw IllegalStateException("Unable to open MediaStore stream.")
            "Saved to Pictures/Cellium/$fileName"
        }
    }

    private fun dimensionsFor(aspectRatio: String): Pair<Int, Int> = when (aspectRatio) {
        "16:9" -> 1024 to 576
        "9:16" -> 576 to 1024
        "4:3" -> 960 to 720
        "3:4" -> 720 to 960
        else -> 768 to 768
    }

    companion object {
        val PROVIDERS = listOf(
            ImagineProviderOption(
                id = "aihorde",
                label = "AI Horde (Free · Keyless)",
                requiresKey = false,
                defaultModels = listOf(
                    "Auto (Fastest)",
                    "Deliberate",
                    "ICBINP - I Can't Believe It's Not Photography",
                    "Realistic Vision",
                    "Nova Anime XL",
                    "AlbedoBase XL (SDXL)",
                    "AIO Pixel Art",
                ),
            ),
            ImagineProviderOption(
                id = "pollinations",
                label = "Pollinations (Key / Fallback)",
                requiresKey = false,
                defaultModels = listOf("flux", "turbo", "sana"),
            ),
            ImagineProviderOption(
                id = "kaggle",
                label = "Kaggle GPU (Free 30h/wk)",
                requiresKey = true,
                defaultModels = listOf(
                    "stabilityai/sdxl-turbo",
                    "black-forest-labs/FLUX.1-schnell",
                    "stabilityai/stable-diffusion-xl-base-1.0",
                ),
            ),
            ImagineProviderOption(
                id = "huggingface",
                label = "HuggingFace (BYOK)",
                requiresKey = true,
                defaultModels = listOf(
                    "black-forest-labs/FLUX.1-schnell",
                    "stabilityai/stable-diffusion-xl-base-1.0",
                ),
            ),
            ImagineProviderOption(
                id = "openai",
                label = "OpenAI Images (BYOK)",
                requiresKey = true,
                defaultModels = listOf("gpt-image-1", "dall-e-3"),
            ),
            ImagineProviderOption(
                id = "custom",
                label = "Custom Endpoint",
                requiresKey = false,
                defaultModels = listOf("flux"),
            ),
        )
    }
}

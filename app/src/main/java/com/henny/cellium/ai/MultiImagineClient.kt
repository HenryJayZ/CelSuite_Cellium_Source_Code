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
        val dir = File(appContext.filesDir, "gallery")
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

    suspend fun generateImage(
        prompt: String,
        negativePrompt: String = "",
        provider: String = "pollinations",
        model: String = "flux",
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
            val bytes: ByteArray = when (provider) {
                "pollinations" -> {
                    onStatusUpdate?.invoke("Generating via Pollinations ($model)...")
                    fetchPollinations(fullPrompt, model.ifBlank { "flux" }, width, height, seed)
                }
                "kaggle" -> fetchKaggleGpu(
                    prompt = cleanPrompt,
                    negativePrompt = negativePrompt,
                    modelId = model.ifBlank { "stabilityai/sdxl-turbo" },
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
                    fetchHuggingFace(fullPrompt, model.ifBlank { "black-forest-labs/FLUX.1-schnell" }, apiKey)
                }
                "openai" -> {
                    onStatusUpdate?.invoke("Calling OpenAI Images...")
                    fetchOpenAiImages(
                        url = "https://api.openai.com/v1/images/generations",
                        prompt = fullPrompt,
                        model = model.ifBlank { "dall-e-3" },
                        aspectRatio = aspectRatio,
                        apiKey = apiKey,
                    )
                }
                "custom" -> {
                    onStatusUpdate?.invoke("Calling Custom Endpoint...")
                    val base = customUrl.trim().trimEnd('/')
                    require(base.isNotBlank()) { "Set your Custom Image Endpoint URL first." }
                    val url = if (base.endsWith("/images/generations")) base else "$base/images/generations"
                    fetchOpenAiImages(url, fullPrompt, model.ifBlank { "flux" }, aspectRatio, apiKey)
                }
                else -> fetchPollinations(fullPrompt, "flux", width, height, seed)
            }
            val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: throw IllegalStateException("Provider returned a non-image payload.")
            val outFile = File(galleryDir(), "cel_art_${System.currentTimeMillis()}_$seed.png")
            FileOutputStream(outFile).use { fos ->
                bmp.compress(Bitmap.CompressFormat.PNG, 96, fos)
            }
            DevLogBuffer.add("INFO", "Imagine", "Generated ${width}x$height via $provider ($model)")
            GeneratedImageResult(
                localFile = outFile,
                bitmap = bmp,
                seed = seed,
                provider = provider,
                model = model,
            )
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "Imagine", "Generation failed ($provider): ${err.localizedMessage}")
        }
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
    ): ByteArray {
        val encoded = URLEncoder.encode(prompt, "UTF-8").replace("+", "%20")
        val url = "https://image.pollinations.ai/prompt/$encoded?model=$model&width=$width&height=$height&seed=$seed&nologo=true"
        val req = Request.Builder()
            .url(url)
            .header("User-Agent", "Cel.Cellium-Android/2611.21.0")
            .get()
            .build()
        client.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IllegalStateException("Pollinations HTTP ${resp.code}. Try again or switch provider.")
            }
            return resp.body?.bytes() ?: throw IllegalStateException("Empty image stream from Pollinations.")
        }
    }

    private fun fetchHuggingFace(prompt: String, model: String, apiKey: String): ByteArray {
        require(apiKey.isNotBlank()) { "HuggingFace requires your HF API token (Settings or Imagine config)." }
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
                id = "pollinations",
                label = "Pollinations (Free)",
                requiresKey = false,
                defaultModels = listOf("flux", "turbo", "flux-realism", "flux-anime", "flux-3d"),
            ),
            ImagineProviderOption(
                id = "kaggle",
                label = "Kaggle GPU (kaggle.json)",
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
                defaultModels = listOf("dall-e-3", "gpt-image-1"),
            ),
            ImagineProviderOption(
                id = "custom",
                label = "Custom Endpoint",
                requiresKey = false,
                defaultModels = listOf("flux", "sdxl"),
            ),
        )
    }
}

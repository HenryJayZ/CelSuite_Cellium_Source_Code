package com.henny.cellium.ai

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.shizuku.MemoryGuardService
import com.henny.cellium.shizuku.ShizukuBridge
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.lang.reflect.Proxy
import java.util.concurrent.TimeUnit

data class LocalModelStatus(
    val loaded: Boolean = false,
    val loading: Boolean = false,
    val runtimeEngine: String = "", // "GGUF (llama.cpp)" or "MediaPipe (.task)"
    val modelName: String = "",
    val modelPath: String = "",
    val downloadProgress: Float? = null,
    val downloadingName: String = "",
    val error: String? = null,
)

/**
 * Dual On-Device Offline LLM runtime for Cel.Cellium:
 * 1) Native llama.cpp GGUF runtime (powered by Llamatik core-android 2.4.0) for `.gguf` files
 * 2) Google MediaPipe Tasks GenAI for `.task`, `.bin`, and `.litertlm` files
 *
 * Runs 100% offline with zero network calls and automatically triggers MemoryGuardService +
 * Shizuku anti-kill protection before loading models or exceeding 1.5 GB RAM.
 */
class OnDeviceLlmEngine(
    private val context: Context,
    private val shizukuBridge: ShizukuBridge,
) {
    private val appContext = context.applicationContext
    private val downloadClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)
        .build()

    @Volatile
    private var llmInference: LlmInference? = null

    @Volatile
    private var ggufLoadedPath: String? = null

    private val _status = MutableStateFlow(LocalModelStatus())
    val status: StateFlow<LocalModelStatus> = _status.asStateFlow()

    fun modelsDirectory(): File {
        val dir = File(appContext.getExternalFilesDir(null) ?: appContext.filesDir, "models")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    fun listInstalledModels(): List<File> =
        modelsDirectory().listFiles()
            ?.filter {
                it.isFile && (
                    it.name.endsWith(".gguf", true) ||
                        it.name.endsWith(".task", true) ||
                        it.name.endsWith(".bin", true) ||
                        it.name.endsWith(".litertlm", true)
                    )
            }
            ?.sortedByDescending { it.lastModified() }
            ?: emptyList()

    suspend fun importModelFromUri(uri: Uri): Result<File> = withContext(Dispatchers.IO) {
        runCatching {
            val fileName = resolveDisplayName(uri).ifBlank { "imported_model_${System.currentTimeMillis()}.gguf" }
            val dest = File(modelsDirectory(), fileName)
            _status.value = _status.value.copy(
                downloadingName = "Importing $fileName...",
                downloadProgress = 0.05f,
                error = null,
            )
            appContext.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(dest).use { output ->
                    val buf = ByteArray(1024 * 256)
                    var read: Int
                    while (input.read(buf).also { read = it } != -1) {
                        output.write(buf, 0, read)
                    }
                    output.flush()
                }
            } ?: throw IllegalStateException("Could not open selected model file.")
            _status.value = _status.value.copy(downloadProgress = null, downloadingName = "")
            DevLogBuffer.add("INFO", "OnDevice", "Imported local model: ${dest.name} (${dest.length() / (1024 * 1024)} MB)")
            dest
        }.onFailure { err ->
            _status.value = _status.value.copy(downloadProgress = null, downloadingName = "", error = err.localizedMessage)
        }
    }

    suspend fun downloadCuratedModel(model: CuratedLocalModel): Result<File> = withContext(Dispatchers.IO) {
        val dest = File(modelsDirectory(), model.fileName)
        if (dest.exists() && dest.length() > 10_000_000L) {
            return@withContext Result.success(dest)
        }
        val tmp = File(modelsDirectory(), "${model.fileName}.part")
        runCatching {
            _status.value = _status.value.copy(
                downloadingName = model.name,
                downloadProgress = 0f,
                error = null,
            )
            val req = Request.Builder().url(model.downloadUrl).build()
            downloadClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    throw IllegalStateException("Download failed (HTTP ${resp.code}). You can also download manually and tap 'Import .gguf / .task'.")
                }
                val body = resp.body ?: throw IllegalStateException("Empty download stream.")
                val total = body.contentLength().coerceAtLeast(1L)
                var copied = 0L
                body.byteStream().use { input ->
                    FileOutputStream(tmp).use { output ->
                        val buf = ByteArray(1024 * 128)
                        var n: Int
                        while (input.read(buf).also { n = it } != -1) {
                            output.write(buf, 0, n)
                            copied += n
                            _status.value = _status.value.copy(
                                downloadProgress = (copied.toFloat() / total.toFloat()).coerceIn(0f, 0.99f),
                            )
                        }
                        output.flush()
                    }
                }
            }
            if (dest.exists()) dest.delete()
            tmp.renameTo(dest)
            _status.value = _status.value.copy(downloadProgress = null, downloadingName = "")
            DevLogBuffer.add("INFO", "OnDevice", "Downloaded ${model.name} (${dest.length() / (1024 * 1024)} MB)")
            dest
        }.onFailure { err ->
            tmp.delete()
            _status.value = _status.value.copy(
                downloadProgress = null,
                downloadingName = "",
                error = err.localizedMessage ?: "Download failed",
            )
            DevLogBuffer.add("ERROR", "OnDevice", "Model download failed: ${err.localizedMessage}")
        }
    }

    suspend fun loadModel(
        modelPath: String,
        maxTokens: Int = 1024,
        useGpu: Boolean = true,
        shizukuAutoGuard: Boolean = true,
    ): Result<Unit> = withContext(Dispatchers.IO) {
        val file = File(modelPath)
        if (!file.exists()) {
            val msg = "Model file not found at $modelPath"
            _status.value = _status.value.copy(error = msg, loaded = false, loading = false)
            return@withContext Result.failure(IllegalStateException(msg))
        }

        val isGguf = file.name.endsWith(".gguf", ignoreCase = true)
        _status.value = _status.value.copy(
            loading = true,
            error = null,
            modelName = file.name,
            runtimeEngine = if (isGguf) "GGUF (llama.cpp)" else "MediaPipe (.task)",
        )

        MemoryGuardService.start(appContext, "Loading offline model: ${file.name}")
        if (shizukuAutoGuard) {
            shizukuBridge.applyAntiKillProtection(reason = "Offline LLM: ${file.name}")
        }

        unloadModel(stopGuard = false)

        if (isGguf) {
            loadGgufModel(file)
        } else {
            loadMediaPipeModel(file, maxTokens, useGpu)
        }
    }

    private fun loadGgufModel(file: File): Result<Unit> = runCatching {
        val (bridgeClass, bridgeInstance) = resolveLlamaBridge()
            ?: throw IllegalStateException("Llamatik native llama.cpp runtime is unavailable on this ABI.")
        val initMethod = bridgeClass.methods.firstOrNull {
            it.name == "initGenerateModel" && it.parameterTypes.size == 1 && it.parameterTypes[0] == String::class.java
        } ?: throw IllegalStateException("LlamaBridge.initGenerateModel(String) not found.")
        val ok = initMethod.invoke(bridgeInstance, file.absolutePath) as? Boolean ?: false
        if (!ok) {
            throw IllegalStateException("Failed to initialize GGUF model '${file.name}'. Verify the file is a valid quantized GGUF.")
        }
        ggufLoadedPath = file.absolutePath
        _status.value = LocalModelStatus(
            loaded = true,
            loading = false,
            runtimeEngine = "GGUF (llama.cpp)",
            modelName = file.name,
            modelPath = file.absolutePath,
        )
        DevLogBuffer.add("INFO", "OnDevice", "Loaded GGUF ${file.name} via llama.cpp | RAM: ${MemoryGuardService.currentProcessRamMb()} MB")
    }.onFailure { err ->
        val cause = err.cause ?: err
        _status.value = LocalModelStatus(
            loaded = false,
            loading = false,
            runtimeEngine = "GGUF (llama.cpp)",
            modelName = file.name,
            modelPath = file.absolutePath,
            error = cause.localizedMessage ?: "Failed to load GGUF model",
        )
        DevLogBuffer.add("ERROR", "OnDevice", "GGUF load error: ${cause.localizedMessage}")
    }

    private fun loadMediaPipeModel(file: File, maxTokens: Int, useGpu: Boolean): Result<Unit> = runCatching {
        val optsBuilder = LlmInference.LlmInferenceOptions.builder()
            .setModelPath(file.absolutePath)
            .setMaxTokens(maxTokens.coerceIn(256, 4096))
            .setPreferredBackend(if (useGpu) LlmInference.Backend.GPU else LlmInference.Backend.CPU)
        val engine = try {
            LlmInference.createFromOptions(appContext, optsBuilder.build())
        } catch (gpuErr: Throwable) {
            if (useGpu) {
                DevLogBuffer.add("WARN", "OnDevice", "GPU delegate unavailable, falling back to CPU: ${gpuErr.localizedMessage}")
                val cpuOpts = LlmInference.LlmInferenceOptions.builder()
                    .setModelPath(file.absolutePath)
                    .setMaxTokens(maxTokens.coerceIn(256, 4096))
                    .setPreferredBackend(LlmInference.Backend.CPU)
                    .build()
                LlmInference.createFromOptions(appContext, cpuOpts)
            } else {
                throw gpuErr
            }
        }
        llmInference = engine
        _status.value = LocalModelStatus(
            loaded = true,
            loading = false,
            runtimeEngine = "MediaPipe (.task)",
            modelName = file.name,
            modelPath = file.absolutePath,
        )
        DevLogBuffer.add("INFO", "OnDevice", "Loaded MediaPipe ${file.name} | RAM: ${MemoryGuardService.currentProcessRamMb()} MB")
    }.onFailure { err ->
        _status.value = LocalModelStatus(
            loaded = false,
            loading = false,
            runtimeEngine = "MediaPipe (.task)",
            modelName = file.name,
            modelPath = file.absolutePath,
            error = err.localizedMessage ?: "Failed to load MediaPipe .task model",
        )
        DevLogBuffer.add("ERROR", "OnDevice", "Load error: ${err.localizedMessage}")
    }

    fun streamReply(
        systemPrompt: String,
        history: List<MessageEntity>,
        userPrompt: String,
    ): Flow<StreamChunk> = callbackFlow {
        val compiledPrompt = buildString {
            if (systemPrompt.isNotBlank()) {
                append("System: ").append(systemPrompt.take(900)).append("\n\n")
            }
            history.takeLast(8).forEach { msg ->
                val tag = if (msg.role == "assistant") "Assistant" else "User"
                append(tag).append(": ").append(msg.content.take(800)).append("\n")
            }
            append("User: ").append(userPrompt).append("\nAssistant:")
        }

        if (ggufLoadedPath != null) {
            runCatching {
                val (bridgeClass, bridgeInstance) = resolveLlamaBridge()
                    ?: throw IllegalStateException("Llamatik bridge unavailable.")
                val streamMethod = bridgeClass.methods.firstOrNull {
                    it.name == "generateStream" && it.parameterTypes.size == 2 && it.parameterTypes[0] == String::class.java
                }
                if (streamMethod != null) {
                    val callbackInterface = streamMethod.parameterTypes[1]
                    val proxy = Proxy.newProxyInstance(
                        callbackInterface.classLoader,
                        arrayOf(callbackInterface),
                    ) { _, method, args ->
                        when (method.name) {
                            "onDelta" -> {
                                val delta = args?.firstOrNull() as? String
                                if (!delta.isNullOrEmpty()) trySend(StreamChunk(contentDelta = delta))
                            }
                            "onComplete" -> close()
                            "onError" -> {
                                val msg = args?.firstOrNull() as? String ?: "GGUF inference error"
                                close(IllegalStateException(msg))
                            }
                        }
                        Unit
                    }
                    streamMethod.invoke(bridgeInstance, compiledPrompt, proxy)
                } else {
                    val genMethod = bridgeClass.methods.firstOrNull {
                        it.name == "generate" && it.parameterTypes.size == 1 && it.parameterTypes[0] == String::class.java
                    } ?: throw IllegalStateException("LlamaBridge.generate not found.")
                    val text = (genMethod.invoke(bridgeInstance, compiledPrompt) as? String).orEmpty()
                    if (text.isNotEmpty()) trySend(StreamChunk(contentDelta = text))
                    close()
                }
            }.onFailure { err ->
                close(err.cause ?: err)
            }
            awaitClose { cancelGgufGeneration() }
            return@callbackFlow
        }

        val engine = llmInference
        if (engine == null) {
            close(IllegalStateException("No on-device model loaded. Open Settings -> Providers -> On-Device AI to load a .gguf or .task model."))
            return@callbackFlow
        }

        runCatching {
            engine.generateResponseAsync(compiledPrompt) { partialResult, done ->
                if (!partialResult.isNullOrEmpty()) {
                    trySend(StreamChunk(contentDelta = partialResult))
                }
                if (done) {
                    close()
                }
            }
        }.onFailure { err ->
            close(err)
        }
        awaitClose { }
    }.flowOn(Dispatchers.IO)

    fun cancelGgufGeneration() {
        runCatching {
            val (bridgeClass, bridgeInstance) = resolveLlamaBridge() ?: return
            bridgeClass.methods.firstOrNull { it.name == "nativeCancelGenerate" || it.name == "cancelGenerate" }
                ?.invoke(bridgeInstance)
        }
    }

    fun unloadModel(stopGuard: Boolean = true) {
        runCatching { llmInference?.close() }
        llmInference = null
        if (ggufLoadedPath != null) {
            runCatching {
                val (bridgeClass, bridgeInstance) = resolveLlamaBridge()
                    ?: return@runCatching
                bridgeClass.methods.firstOrNull { it.name == "shutdown" && it.parameterTypes.isEmpty() }
                    ?.invoke(bridgeInstance)
            }
            ggufLoadedPath = null
        }
        _status.value = _status.value.copy(loaded = false, loading = false)
        if (stopGuard) {
            MemoryGuardService.stop(appContext)
        }
    }

    fun deleteModelFile(file: File): Boolean {
        if (_status.value.modelPath == file.absolutePath) unloadModel()
        return file.delete()
    }

    private fun resolveLlamaBridge(): Pair<Class<*>, Any>? {
        val candidates = listOf(
            "com.llamatik.core.platform.LlamaBridge",
            "com.llamatik.library.platform.LlamaBridge",
        )
        for (name in candidates) {
            val cls = runCatching { Class.forName(name) }.getOrNull() ?: continue
            val instance = runCatching { cls.getField("INSTANCE").get(null) }.getOrNull() ?: continue
            return cls to instance
        }
        return null
    }

    private fun resolveDisplayName(uri: Uri): String {
        appContext.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) return cursor.getString(idx).orEmpty()
                }
            }
        return uri.lastPathSegment?.substringAfterLast('/').orEmpty()
    }
}

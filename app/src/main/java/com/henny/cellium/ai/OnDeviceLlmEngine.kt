package com.henny.cellium.ai

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import coil.imageLoader
import com.google.mediapipe.tasks.genai.llminference.LlmInference
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.RegisteredLocalModel
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
import com.henny.cellium.core.CelliumHttp
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
    val operationLabel: String = "", // "Downloading", "Mounting", "Importing"
    val downloadingName: String = "",
    val error: String? = null,
)

/**
 * Dual On-Device Offline LLM runtime for Cel.Cellium:
 * 1) Native llama.cpp GGUF runtime (Llamatik) supporting ZERO-COPY direct SAF mount via
 *    ParcelFileDescriptor (/proc/self/fd/<fd> + mmap) with persisted URI permissions across restarts.
 * 2) Google MediaPipe Tasks GenAI for `.task`, `.bin`, and `.litertlm` files.
 *
 * Includes 4GB RAM OOM survival tactics: pre-load Coil/GC/Shizuku RAM trim, conservative default
 * KV-cache context sizing, mmap streaming directly from flash storage, and configurable GGUF params.
 */
class OnDeviceLlmEngine(
    private val context: Context,
    private val shizukuBridge: ShizukuBridge,
) {
    private val appContext = context.applicationContext
    private val downloadClient = CelliumHttp.clientWithTimeouts(
        connectSec = 30L,
        readSec = 0L,
    )

    @Volatile
    private var llmInference: LlmInference? = null

    @Volatile
    private var ggufLoadedPath: String? = null

    @Volatile
    private var activeMountedPfd: ParcelFileDescriptor? = null

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

    fun listAllAvailableModels(registered: List<RegisteredLocalModel>): List<RegisteredLocalModel> {
        val byKey = LinkedHashMap<String, RegisteredLocalModel>()
        // 1. Persisted zero-copy mounted URIs / external files
        registered.forEach { item ->
            val exists = if (item.isContentUri) {
                runCatching {
                    appContext.contentResolver.openFileDescriptor(Uri.parse(item.uriOrPath), "r")?.use { true } ?: false
                }.getOrDefault(false)
            } else {
                File(item.uriOrPath).exists()
            }
            if (exists) {
                byKey[item.uriOrPath] = item
            }
        }
        // 2. Files inside app models directory
        listInstalledModels().forEach { f ->
            byKey.putIfAbsent(
                f.absolutePath,
                RegisteredLocalModel(
                    uriOrPath = f.absolutePath,
                    displayName = f.name,
                    sizeBytes = f.length(),
                    isContentUri = false,
                ),
            )
        }
        return byKey.values.toList()
    }

    /**
     * Zero-Copy Mount for `.gguf` files (reads straight from phone storage via SAF FD + mmap,
     * zero duplication, survives app restart/crash via persistable URI permission!).
     * For `.task` MediaPipe files where MediaPipe C++ requires a real path, attempts direct path
     * first and only copies if Android scoped storage hides the raw path.
     */
    suspend fun mountOrImportModelFromUri(uri: Uri): Result<RegisteredLocalModel> = withContext(Dispatchers.IO) {
        runCatching {
            val fileName = resolveDisplayName(uri).ifBlank { "local_model_${System.currentTimeMillis()}.gguf" }
            val sizeBytes = resolveFileSize(uri)
            val isGguf = fileName.endsWith(".gguf", ignoreCase = true)

            // Take persistent read permission so Android NEVER forgets this model after reboot or crash!
            runCatching {
                appContext.contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }

            if (isGguf) {
                // Verify we can open read-only FD immediately (zero copy!)
                val pfd = appContext.contentResolver.openFileDescriptor(uri, "r")
                    ?: throw IllegalStateException("Cannot open file descriptor for $fileName.")
                pfd.close()
                DevLogBuffer.add("INFO", "OnDevice", "Mounted zero-copy GGUF: $fileName (${sizeBytes / (1024 * 1024)} MB)")
                RegisteredLocalModel(
                    uriOrPath = uri.toString(),
                    displayName = fileName,
                    sizeBytes = sizeBytes,
                    isContentUri = true,
                )
            } else {
                // MediaPipe .task requires a filesystem path; copy with accurate "Importing" label
                val dest = File(modelsDirectory(), fileName)
                _status.value = _status.value.copy(
                    operationLabel = "Importing",
                    downloadingName = fileName,
                    downloadProgress = 0.02f,
                    error = null,
                )
                val total = sizeBytes.coerceAtLeast(1L)
                var copied = 0L
                appContext.contentResolver.openInputStream(uri)?.use { input ->
                    FileOutputStream(dest).use { output ->
                        val buf = ByteArray(1024 * 256)
                        var read: Int
                        while (input.read(buf).also { read = it } != -1) {
                            output.write(buf, 0, read)
                            copied += read
                            _status.value = _status.value.copy(
                                downloadProgress = (copied.toFloat() / total.toFloat()).coerceIn(0.02f, 0.99f),
                            )
                        }
                        output.flush()
                    }
                } ?: throw IllegalStateException("Could not open selected model file.")
                _status.value = _status.value.copy(downloadProgress = null, operationLabel = "", downloadingName = "")
                DevLogBuffer.add("INFO", "OnDevice", "Imported local model: ${dest.name} (${dest.length() / (1024 * 1024)} MB)")
                RegisteredLocalModel(
                    uriOrPath = dest.absolutePath,
                    displayName = dest.name,
                    sizeBytes = dest.length(),
                    isContentUri = false,
                )
            }
        }.onFailure { err ->
            _status.value = _status.value.copy(
                downloadProgress = null,
                operationLabel = "",
                downloadingName = "",
                error = err.localizedMessage,
            )
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
                operationLabel = "Downloading",
                downloadingName = model.name,
                downloadProgress = 0f,
                error = null,
            )
            val req = Request.Builder().url(model.downloadUrl).build()
            downloadClient.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    throw IllegalStateException("Download failed (HTTP ${resp.code}). You can also download manually and tap 'Mount / Import'.")
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
            _status.value = _status.value.copy(downloadProgress = null, operationLabel = "", downloadingName = "")
            DevLogBuffer.add("INFO", "OnDevice", "Downloaded ${model.name} (${dest.length() / (1024 * 1024)} MB)")
            dest
        }.onFailure { err ->
            tmp.delete()
            _status.value = _status.value.copy(
                downloadProgress = null,
                operationLabel = "",
                downloadingName = "",
                error = err.localizedMessage ?: "Download failed",
            )
            DevLogBuffer.add("ERROR", "OnDevice", "Model download failed: ${err.localizedMessage}")
        }
    }

    fun totalDeviceRamMb(): Long {
        val am = appContext.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return 4096L
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return mi.totalMem / (1024L * 1024L)
    }

    fun availableDeviceRamMb(): Long {
        val am = appContext.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return 1024L
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return mi.availMem / (1024L * 1024L)
    }

    /**
     * Frees internal app caches & triggers GC before loading large models on 4GB RAM devices.
     */
    suspend fun reclaimInternalRam(includeShizuku: Boolean = false): Long = withContext(Dispatchers.IO) {
        val beforeAvail = availableDeviceRamMb()
        runCatching { appContext.imageLoader.memoryCache?.clear() }
        runCatching { AvatarLibrary.clearCache() }
        System.gc()
        Runtime.getRuntime().gc()
        if (includeShizuku) {
            shizukuBridge.freeSystemRam()
        }
        val afterAvail = availableDeviceRamMb()
        (afterAvail - beforeAvail).coerceAtLeast(0L)
    }

    suspend fun loadModel(
        uriOrPath: String,
        displayName: String = "",
        maxTokens: Int = 512,
        useGpu: Boolean = true,
        shizukuAutoGuard: Boolean = true,
        ggufConfig: ContextModifyConfig = ContextModifyConfig(),
    ): Result<Unit> = withContext(Dispatchers.IO) {
        if (_status.value.loading) {
            return@withContext Result.failure(IllegalStateException("A local model is already loading."))
        }
        val isContentUri = uriOrPath.startsWith("content://")
        val resolvedName = displayName.ifBlank {
            if (isContentUri) resolveDisplayName(Uri.parse(uriOrPath)) else File(uriOrPath).name
        }.ifBlank { "local_model" }
        val isGguf = resolvedName.endsWith(".gguf", ignoreCase = true)

        if (!isContentUri && !File(uriOrPath).exists()) {
            val msg = "Model file not found at $uriOrPath"
            _status.value = _status.value.copy(error = msg, loaded = false, loading = false)
            return@withContext Result.failure(IllegalStateException(msg))
        }

        _status.value = _status.value.copy(
            loading = true,
            error = null,
            modelName = resolvedName,
            modelPath = uriOrPath,
            runtimeEngine = if (isGguf) "GGUF (llama.cpp)" else "MediaPipe (.task)",
        )

        // 4GB RAM OOM Survival Pipeline: unload previous -> reclaim caches -> Shizuku anti-kill & trim -> mmap load!
        unloadModel(stopGuard = false)
        MemoryGuardService.start(appContext, "Protecting RAM for $resolvedName")
        val totalRamMb = totalDeviceRamMb()
        reclaimInternalRam(includeShizuku = shizukuAutoGuard && totalRamMb <= 4800L)
        if (shizukuAutoGuard) {
            shizukuBridge.applyAntiKillProtection(reason = "Offline LLM: $resolvedName")
        }

        if (isGguf) {
            loadGgufModel(
                uriOrPath = uriOrPath,
                isContentUri = isContentUri,
                displayName = resolvedName,
                ggufConfig = ggufConfig,
            )
        } else {
            loadMediaPipeModel(File(uriOrPath), maxTokens, useGpu)
        }
    }

    private fun loadGgufModel(
        uriOrPath: String,
        isContentUri: Boolean,
        displayName: String,
        ggufConfig: ContextModifyConfig,
    ): Result<Unit> = runCatching {
        val (bridgeClass, bridgeInstance) = resolveLlamaBridge()
            ?: throw IllegalStateException("Llamatik native llama.cpp runtime is unavailable on this ABI.")

        // 1. Apply exact user-configured GGUF parameters via LlamaBridge.updateGenerateParams (zero artificial GB/RAM caps!)
        val targetCtx = ggufConfig.ggufContextLength
        val targetThreads = ggufConfig.ggufThreads
        applyLlamaGenerateParams(
            bridgeClass = bridgeClass,
            bridgeInstance = bridgeInstance,
            temperature = ggufConfig.ggufTemperature,
            maxTokens = ggufConfig.ggufMaxTokens,
            topP = ggufConfig.ggufTopP,
            topK = ggufConfig.ggufTopK,
            repeatPenalty = ggufConfig.ggufRepeatPenalty,
            contextLength = targetCtx,
            numThreads = targetThreads,
            useMmap = ggufConfig.ggufUseMmap,
            flashAttention = ggufConfig.ggufFlashAttention,
            gpuLayers = ggufConfig.ggufGpuLayers,
        )

        // 2. Zero-Copy SAF file descriptor mount -> /proc/self/fd/<fd> so llama.cpp mmaps directly from storage!
        val nativePath = if (isContentUri) {
            val pfd = appContext.contentResolver.openFileDescriptor(Uri.parse(uriOrPath), "r")
                ?: throw IllegalStateException("Storage permission expired for $displayName. Please re-select the file once.")
            activeMountedPfd = pfd
            "/proc/self/fd/${pfd.fd}"
        } else {
            uriOrPath
        }

        val initMethod = bridgeClass.methods.firstOrNull {
            it.name == "initGenerateModel" && it.parameterTypes.size == 1 && it.parameterTypes[0] == String::class.java
        } ?: throw IllegalStateException("LlamaBridge.initGenerateModel(String) not found.")

        val ok = initMethod.invoke(bridgeInstance, nativePath) as? Boolean ?: false
        if (!ok) {
            runCatching { activeMountedPfd?.close() }
            activeMountedPfd = null
            throw IllegalStateException("Failed to initialize GGUF '$displayName'. Verify the file is a valid GGUF model, or try enabling mmap / adjusting Context Length in Modify.")
        }

        ggufLoadedPath = uriOrPath
        _status.value = LocalModelStatus(
            loaded = true,
            loading = false,
            runtimeEngine = if (isContentUri) "GGUF Zero-Copy (mmap)" else "GGUF (llama.cpp)",
            modelName = displayName,
            modelPath = uriOrPath,
        )
        DevLogBuffer.add(
            "INFO",
            "OnDevice",
            "Loaded GGUF $displayName (ctx=$targetCtx, threads=$targetThreads, mmap=${ggufConfig.ggufUseMmap}) | Avail RAM: ${availableDeviceRamMb()} MB",
        )
    }.onFailure { err ->
        runCatching { activeMountedPfd?.close() }
        activeMountedPfd = null
        val cause = err.cause ?: err
        _status.value = LocalModelStatus(
            loaded = false,
            loading = false,
            runtimeEngine = "GGUF (llama.cpp)",
            modelName = displayName,
            modelPath = uriOrPath,
            error = cause.localizedMessage ?: "Failed to load GGUF model",
        )
        DevLogBuffer.add("ERROR", "OnDevice", "GGUF load error: ${cause.localizedMessage}")
    }

    private fun applyLlamaGenerateParams(
        bridgeClass: Class<*>,
        bridgeInstance: Any,
        temperature: Float,
        maxTokens: Int,
        topP: Float,
        topK: Int,
        repeatPenalty: Float,
        contextLength: Int,
        numThreads: Int,
        useMmap: Boolean,
        flashAttention: Boolean,
        gpuLayers: Int,
    ) {
        val methods = bridgeClass.methods.filter { it.name == "updateGenerateParams" }
        for (m in methods) {
            val types = m.parameterTypes
            val invoked = runCatching {
                when (types.size) {
                    10 -> m.invoke(
                        bridgeInstance,
                        temperature, maxTokens, topP, topK, repeatPenalty,
                        contextLength, numThreads, useMmap, flashAttention, gpuLayers,
                    )
                    8 -> m.invoke(
                        bridgeInstance,
                        temperature, maxTokens, topP, topK, repeatPenalty,
                        contextLength, numThreads, useMmap,
                    )
                    6 -> m.invoke(
                        bridgeInstance,
                        temperature, maxTokens, topP, topK, repeatPenalty, contextLength,
                    )
                    5 -> m.invoke(
                        bridgeInstance,
                        temperature, maxTokens, topP, topK, repeatPenalty,
                    )
                    else -> return@runCatching false
                }
                true
            }.getOrDefault(false)
            if (invoked) {
                DevLogBuffer.add("INFO", "OnDevice", "Applied updateGenerateParams(${types.size} args): ctx=$contextLength, maxTok=$maxTokens, temp=$temperature, mmap=$useMmap")
                return
            }
        }
    }

    private fun loadMediaPipeModel(file: File, maxTokens: Int, useGpu: Boolean): Result<Unit> = runCatching {
        val optsBuilder = LlmInference.LlmInferenceOptions.builder()
            .setModelPath(file.absolutePath)
            .setMaxTokens(maxTokens.coerceIn(256, 16384))
            .setPreferredBackend(if (useGpu) LlmInference.Backend.GPU else LlmInference.Backend.CPU)
        val engine = try {
            LlmInference.createFromOptions(appContext, optsBuilder.build())
        } catch (gpuErr: Throwable) {
            if (useGpu) {
                DevLogBuffer.add("WARN", "OnDevice", "GPU delegate unavailable, falling back to CPU: ${gpuErr.localizedMessage}")
                val cpuOpts = LlmInference.LlmInferenceOptions.builder()
                    .setModelPath(file.absolutePath)
                    .setMaxTokens(maxTokens.coerceIn(256, 16384))
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
        historyLimit: Int = 8,
    ): Flow<StreamChunk> = callbackFlow {
        val compiledPrompt = buildString {
            if (systemPrompt.isNotBlank()) {
                append("System: ").append(systemPrompt.take(1200)).append("\n\n")
            }
            history.takeLast(historyLimit.coerceIn(2, 24)).forEach { msg ->
                val tag = if (msg.role == "assistant") "Assistant" else "User"
                append(tag).append(": ").append(msg.content.take(900)).append("\n")
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
            close(IllegalStateException("No on-device model loaded. Open Settings -> Offline AI & RAM to load a .gguf or .task model."))
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
        cancelGgufGeneration()
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
        runCatching { activeMountedPfd?.close() }
        activeMountedPfd = null
        _status.value = _status.value.copy(
            loaded = false,
            loading = false,
            modelName = "",
            modelPath = "",
            runtimeEngine = "",
        )
        if (stopGuard) {
            MemoryGuardService.stop(appContext)
        }
    }

    fun deleteLocalModel(item: RegisteredLocalModel): Boolean {
        if (_status.value.modelPath == item.uriOrPath) unloadModel()
        return if (item.isContentUri) {
            // Unmount only — never delete the user's original file in Downloads/Documents!
            runCatching {
                appContext.contentResolver.releasePersistableUriPermission(
                    Uri.parse(item.uriOrPath),
                    Intent.FLAG_GRANT_READ_URI_PERMISSION,
                )
            }
            true
        } else {
            File(item.uriOrPath).delete()
        }
    }

    private fun resolveLlamaBridge(): Pair<Class<*>, Any>? {
        val candidates = listOf(
            "com.llamatik.core.platform.LlamaBridge",
            "com.llamatik.core.LlamaBridge",
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
        runCatching {
            appContext.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (idx >= 0) return cursor.getString(idx).orEmpty()
                    }
                }
        }
        return uri.lastPathSegment?.substringAfterLast('/').orEmpty()
    }

    private fun resolveFileSize(uri: Uri): Long {
        runCatching {
            appContext.contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)
                ?.use { cursor ->
                    if (cursor.moveToFirst()) {
                        val idx = cursor.getColumnIndex(OpenableColumns.SIZE)
                        if (idx >= 0) return cursor.getLong(idx)
                    }
                }
        }
        return 0L
    }
}

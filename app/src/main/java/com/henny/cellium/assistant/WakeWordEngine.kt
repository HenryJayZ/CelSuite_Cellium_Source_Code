package com.henny.cellium.assistant

import android.content.Context
import android.util.Log
import org.tensorflow.lite.Interpreter
import java.io.File
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel

private const val TAG = "WakeWordEngine"

/**
 * 3-stage openWakeWord LiteRT (TFLite) inference pipeline for "Okay Cel":
 *   Stage 1: melspectrogram.tflite   [1, 1280] -> [1, 1, 5, 32] (norm = raw / 10 + 2)
 *   Stage 2: embedding_model.tflite  [1, 76, 32, 1] -> [1, 1, 1, 96] (sliding by 8 frames)
 *   Stage 3: oh_kay_sell.tflite      [1, 16, 96] -> [1, 1] (confidence 0..1)
 *
 * Pre-allocates all input/output buffers so the 80ms real-time audio loop performs zero GC churn.
 */
class WakeWordEngine(
    private val context: Context,
    private val customModelPath: String = "",
) {
    private var melInterpreter: Interpreter? = null
    private var embInterpreter: Interpreter? = null
    private var wakeInterpreter: Interpreter? = null

    private var melRing = Array(76) { FloatArray(32) }
    private var melFramesAccumulated = 0
    private var melFramesSinceLastEmb = 0

    private var embRing = Array(16) { FloatArray(96) }
    private var embFramesFilled = 0
    private var wakeInputFrames = 16

    // Pre-allocated inference buffers
    private val melInput = Array(1) { FloatArray(1280) }
    private val melOutput = Array(1) { Array(1) { Array(5) { FloatArray(32) } } }
    private val embInput = Array(1) { Array(76) { Array(32) { FloatArray(1) } } }
    private val embOutput = Array(1) { Array(1) { Array(1) { FloatArray(96) } } }
    private lateinit var wakeInput: Array<Array<FloatArray>>
    private val wakeOutput = Array(1) { FloatArray(1) }

    @Volatile
    var ready: Boolean = false
        private set

    fun initialize(): Boolean {
        return runCatching {
            val opts = Interpreter.Options().apply {
                setNumThreads(2)
            }
            melInterpreter = Interpreter(loadAssetBuffer("melspectrogram.tflite"), opts)
            embInterpreter = Interpreter(loadAssetBuffer("embedding_model.tflite"), opts)

            val wakeBuf = if (customModelPath.isNotBlank() && File(customModelPath).exists()) {
                loadFileBuffer(File(customModelPath))
            } else {
                loadAssetBuffer("oh_kay_sell.tflite")
            }
            val wInterp = Interpreter(wakeBuf, opts)
            wakeInterpreter = wInterp

            // Dynamically inspect classifier input shape (default [1, 16, 96])
            val inShape = wInterp.getInputTensor(0).shape()
            wakeInputFrames = if (inShape.size >= 2 && inShape[1] in 1..64) inShape[1] else 16
            val embDim = if (inShape.size >= 3 && inShape[2] in 16..512) inShape[2] else 96
            embRing = Array(wakeInputFrames) { FloatArray(embDim) }
            wakeInput = Array(1) { Array(wakeInputFrames) { FloatArray(embDim) } }

            resetState()
            ready = true
            true
        }.onFailure { err ->
            Log.e(TAG, "Failed initializing openWakeWord LiteRT pipeline", err)
            ready = false
        }.getOrDefault(false)
    }

    fun resetState() {
        melFramesAccumulated = 0
        melFramesSinceLastEmb = 0
        embFramesFilled = 0
        melRing.forEach { it.fill(0f) }
        embRing.forEach { it.fill(0f) }
    }

    /**
     * Feeds one 80ms chunk (1280 samples @ 16kHz PCM16) and returns wake-word score [0..1].
     */
    fun processChunk(pcm16: ShortArray): Float {
        if (!ready || pcm16.size < 1280) return 0f
        val mel = melInterpreter ?: return 0f
        val emb = embInterpreter ?: return 0f
        val wake = wakeInterpreter ?: return 0f

        // 1. Copy PCM shorts as float (-32768..32767) per openWakeWord specification
        val inBuf = melInput[0]
        for (i in 0 until 1280) {
            inBuf[i] = pcm16[i].toFloat()
        }

        // 2. Run melspectrogram stage -> 5 frames of 32 mel bins
        mel.run(melInput, melOutput)
        val newFrames = melOutput[0][0]
        for (f in 0 until 5) {
            // Shift melRing left by 1
            val recycled = melRing[0]
            System.arraycopy(melRing, 1, melRing, 0, 75)
            melRing[75] = recycled
            for (b in 0 until 32) {
                // openWakeWord normalization: x / 10 + 2
                recycled[b] = newFrames[f][b] / 10.0f + 2.0f
            }
            melFramesAccumulated = (melFramesAccumulated + 1).coerceAtMost(76)
            melFramesSinceLastEmb++
        }

        if (melFramesAccumulated < 76 || melFramesSinceLastEmb < 8) {
            return 0f
        }
        melFramesSinceLastEmb = 0

        // 3. Run speech embedding stage -> 96-dim feature vector
        val embIn = embInput[0]
        for (t in 0 until 76) {
            val row = melRing[t]
            val dst = embIn[t]
            for (b in 0 until 32) {
                dst[b][0] = row[b]
            }
        }
        emb.run(embInput, embOutput)
        val vec = embOutput[0][0][0]

        // Shift embRing left by 1
        val recycledEmb = embRing[0]
        System.arraycopy(embRing, 1, embRing, 0, wakeInputFrames - 1)
        embRing[wakeInputFrames - 1] = recycledEmb
        val copyLen = minOf(vec.size, recycledEmb.size)
        System.arraycopy(vec, 0, recycledEmb, 0, copyLen)
        embFramesFilled = (embFramesFilled + 1).coerceAtMost(wakeInputFrames)

        if (embFramesFilled < wakeInputFrames) return 0f

        // 4. Run wake word classifier
        val wIn = wakeInput[0]
        for (t in 0 until wakeInputFrames) {
            System.arraycopy(embRing[t], 0, wIn[t], 0, embRing[t].size)
        }
        wakeOutput[0][0] = 0f
        wake.run(wakeInput, wakeOutput)
        val score = wakeOutput[0][0]
        return if (score.isFinite()) score.coerceIn(0f, 1f) else 0f
    }

    fun close() {
        ready = false
        runCatching { wakeInterpreter?.close() }
        runCatching { embInterpreter?.close() }
        runCatching { melInterpreter?.close() }
        wakeInterpreter = null
        embInterpreter = null
        melInterpreter = null
    }

    private fun loadAssetBuffer(assetName: String): MappedByteBuffer {
        context.assets.openFd(assetName).use { fd ->
            FileInputStream(fd.fileDescriptor).use { fis ->
                return fis.channel.map(FileChannel.MapMode.READ_ONLY, fd.startOffset, fd.declaredLength)
            }
        }
    }

    private fun loadFileBuffer(file: File): ByteBuffer {
        val bytes = file.readBytes()
        return ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.nativeOrder()).apply {
            put(bytes)
            rewind()
        }
    }
}

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
private const val CHUNK_SAMPLES = 1280       // 80ms @ 16kHz
private const val OVERLAP_SAMPLES = 480      // 160 * 3 overlap required by openWakeWord melspectrogram STFT
private const val MEL_INPUT_SAMPLES = CHUNK_SAMPLES + OVERLAP_SAMPLES // 1760 samples -> 8 mel frames

/**
 * Exact 3-stage openWakeWord LiteRT (TFLite) inference pipeline for "Okay Cel":
 *   Stage 1: melspectrogram.tflite   [1, 1760] (480 overlap + 1280 chunk) -> [1, 1, 8, 32] (norm = raw / 10 + 2)
 *   Stage 2: embedding_model.tflite  [1, 76, 32, 1] -> [1, 1, 1, 96] (1 embedding per 8 mel frames = 80ms)
 *   Stage 3: oh_kay_sell.tflite      [1, 16, 96] -> [1, 1] (confidence 0..1)
 *
 * Pre-allocates all buffers so the 80ms real-time audio loop produces zero heap churn.
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
    private var melOutputFrameCount = 8

    // 480-sample overlap ring carrying tail of previous 80ms chunk into next melspectrogram call
    private val prevOverlap = ShortArray(OVERLAP_SAMPLES)
    private var hasOverlap = false

    // Pre-allocated inference buffers
    private val melInput = Array(1) { FloatArray(MEL_INPUT_SAMPLES) }
    private var melOutput = Array(1) { Array(1) { Array(8) { FloatArray(32) } } }
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
            val mInterp = Interpreter(loadAssetBuffer("melspectrogram.tflite"), opts)
            // Resize melspectrogram input to [1, 1760] matching official openWakeWord (1280 + 480 overlap)
            mInterp.resizeInput(0, intArrayOf(1, MEL_INPUT_SAMPLES))
            mInterp.allocateTensors()
            val melOutShape = mInterp.getOutputTensor(0).shape()
            melOutputFrameCount = if (melOutShape.size >= 3 && melOutShape[2] in 1..32) melOutShape[2] else 8
            val melBins = if (melOutShape.size >= 4 && melOutShape[3] in 16..128) melOutShape[3] else 32
            melOutput = Array(1) { Array(1) { Array(melOutputFrameCount) { FloatArray(melBins) } } }
            melInterpreter = mInterp

            embInterpreter = Interpreter(loadAssetBuffer("embedding_model.tflite"), opts)

            val wakeBuf = if (customModelPath.isNotBlank() && File(customModelPath).exists()) {
                loadFileBuffer(File(customModelPath))
            } else {
                loadAssetBuffer("oh_kay_sell.tflite")
            }
            val wInterp = Interpreter(wakeBuf, opts)
            wakeInterpreter = wInterp

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
        hasOverlap = false
        prevOverlap.fill(0)
        melRing.forEach { it.fill(0f) }
        embRing.forEach { it.fill(0f) }
    }

    /**
     * Feeds one 80ms chunk (1280 samples @ 16kHz PCM16) with exact 480-sample overlap
     * and returns wake-word confidence score in [0..1].
     */
    fun processChunk(pcm16: ShortArray): Float {
        if (!ready || pcm16.size < CHUNK_SAMPLES) return 0f
        val mel = melInterpreter ?: return 0f
        val emb = embInterpreter ?: return 0f
        val wake = wakeInterpreter ?: return 0f

        // 1. Build 1760-sample overlapped frame: [480 previous tail] + [1280 current chunk]
        val inBuf = melInput[0]
        if (hasOverlap) {
            for (i in 0 until OVERLAP_SAMPLES) {
                inBuf[i] = prevOverlap[i].toFloat()
            }
        } else {
            for (i in 0 until OVERLAP_SAMPLES) {
                inBuf[i] = 0f
            }
        }
        for (i in 0 until CHUNK_SAMPLES) {
            inBuf[OVERLAP_SAMPLES + i] = pcm16[i].toFloat()
        }
        // Save tail 480 samples for the next chunk
        System.arraycopy(pcm16, CHUNK_SAMPLES - OVERLAP_SAMPLES, prevOverlap, 0, OVERLAP_SAMPLES)
        hasOverlap = true

        // 2. Run melspectrogram stage -> 8 frames of 32 mel bins per 80ms chunk
        mel.run(melInput, melOutput)
        val newFrames = melOutput[0][0]
        var maxScore = 0f

        for (f in 0 until melOutputFrameCount) {
            val recycled = melRing[0]
            System.arraycopy(melRing, 1, melRing, 0, 75)
            melRing[75] = recycled
            val srcRow = newFrames[f]
            val binCount = minOf(32, srcRow.size)
            for (b in 0 until binCount) {
                // openWakeWord normalization: x / 10 + 2
                recycled[b] = srcRow[b] / 10.0f + 2.0f
            }
            melFramesAccumulated = (melFramesAccumulated + 1).coerceAtMost(76)
            melFramesSinceLastEmb++

            // Frame-exact 8-frame sliding stride matching official openWakeWord reference!
            if (melFramesAccumulated >= 76 && melFramesSinceLastEmb >= 8) {
                melFramesSinceLastEmb -= 8

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

                val recycledEmb = embRing[0]
                System.arraycopy(embRing, 1, embRing, 0, wakeInputFrames - 1)
                embRing[wakeInputFrames - 1] = recycledEmb
                val copyLen = minOf(vec.size, recycledEmb.size)
                System.arraycopy(vec, 0, recycledEmb, 0, copyLen)
                embFramesFilled = (embFramesFilled + 1).coerceAtMost(wakeInputFrames)

                if (embFramesFilled >= wakeInputFrames) {
                    // 4. Run wake word classifier
                    val wIn = wakeInput[0]
                    for (t in 0 until wakeInputFrames) {
                        System.arraycopy(embRing[t], 0, wIn[t], 0, embRing[t].size)
                    }
                    wakeOutput[0][0] = 0f
                    wake.run(wakeInput, wakeOutput)
                    val score = wakeOutput[0][0]
                    if (score.isFinite() && score > maxScore) {
                        maxScore = score.coerceIn(0f, 1f)
                    }
                }
            }
        }
        return maxScore
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

package com.henny.cellium.ai

import com.henny.cellium.data.local.PromptTemplateEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

data class CuratedLocalModel(
    val id: String,
    val name: String,
    val format: String, // "GGUF" or "TASK"
    val sizeLabel: String,
    val ramNeededMb: Int,
    val description: String,
    val fileName: String,
    val downloadUrl: String,
)

object ProviderPresets {
    private val json = Json { ignoreUnknownKeys = true }

    const val ID_POLLINATIONS_FREE = "preset_pollinations_free"
    const val ID_OPENROUTER = "preset_openrouter"
    const val ID_GROQ = "preset_groq"
    const val ID_OPENAI = "preset_openai"
    const val ID_GEMINI = "preset_gemini"
    const val ID_DEEPSEEK = "preset_deepseek"
    const val ID_ANTHROPIC = "preset_anthropic"
    const val ID_MISTRAL = "preset_mistral"
    const val ID_XAI = "preset_xai"
    const val ID_TOGETHER = "preset_together"
    const val ID_CEREBRAS = "preset_cerebras"
    const val ID_SAMBANOVA = "preset_sambanova"
    const val ID_HUGGINGFACE = "preset_huggingface"
    const val ID_CUSTOM = "preset_custom"
    const val ID_ON_DEVICE = "preset_on_device"
    const val ID_COMPACT_TEMPLATE = "tpl_compact_builtin"

    fun defaultProfiles(): List<ProviderProfileEntity> =
        ProviderCatalog.POPULAR_PROVIDERS.map { it.toEntity() }

    fun defaultPromptTemplates(): List<PromptTemplateEntity> = listOf(
        PromptTemplateEntity(
            id = ID_COMPACT_TEMPLATE,
            slashKey = "/compact",
            title = "Compact Conversation Context",
            promptBody = "Create a dense, accurate continuity summary of our entire conversation so far. Preserve all key decisions, user preferences, names, code snippets/paths, facts, and open tasks in clean bullet points so we can seamlessly continue from this checkpoint without losing context.",
        ),
        PromptTemplateEntity(
            id = "tpl_summarize",
            slashKey = "/summarize",
            title = "Summarize",
            promptBody = "Summarize the following text into crisp, high-signal bullet points with key takeaways:\n\n",
        ),
        PromptTemplateEntity(
            id = "tpl_code_review",
            slashKey = "/review",
            title = "Code Review",
            promptBody = "Review this code for bugs, performance bottlenecks, edge cases, and clean refactors:\n\n",
        ),
        PromptTemplateEntity(
            id = "tpl_explain",
            slashKey = "/explain",
            title = "Explain Simply",
            promptBody = "Explain this concept clearly from first principles with a concrete example:\n\n",
        ),
        PromptTemplateEntity(
            id = "tpl_rewrite",
            slashKey = "/polish",
            title = "Polish Writing",
            promptBody = "Rewrite the following text so it is sharper, clearer, and natural while keeping my intent:\n\n",
        ),
        PromptTemplateEntity(
            id = "tpl_brainstorm",
            slashKey = "/ideas",
            title = "Brainstorm 10 Ideas",
            promptBody = "Generate 10 creative, practical, non-obvious ideas for:\n\n",
        ),
    )

    val CURATED_LOCAL_MODELS: List<CuratedLocalModel> = listOf(
        CuratedLocalModel(
            id = "qwen25_05b_gguf",
            name = "Qwen 2.5 0.5B Instruct (Q4_K_M .gguf)",
            format = "GGUF",
            sizeLabel = "~398 MB",
            ramNeededMb = 750,
            description = "Ultra-fast llama.cpp GGUF model that runs smoothly on 3–4 GB RAM Android phones.",
            fileName = "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            downloadUrl = "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        ),
        CuratedLocalModel(
            id = "smollm2_360m_gguf",
            name = "SmolLM2 360M Instruct (Q8_0 .gguf)",
            format = "GGUF",
            sizeLabel = "~386 MB",
            ramNeededMb = 680,
            description = "Compact HuggingFace SmolLM2 GGUF model with rapid token speed.",
            fileName = "smollm2-360m-instruct-q8_0.gguf",
            downloadUrl = "https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/resolve/main/smollm2-360m-instruct-q8_0.gguf",
        ),
        CuratedLocalModel(
            id = "qwen25_15b_gguf",
            name = "Qwen 2.5 1.5B Instruct (Q4_K_M .gguf)",
            format = "GGUF",
            sizeLabel = "~986 MB",
            ramNeededMb = 1650,
            description = "Strong offline coding & chat GGUF model. Auto-triggers Shizuku >1.5 GB RAM guard.",
            fileName = "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            downloadUrl = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        ),
        CuratedLocalModel(
            id = "gemma3_1b_int4_task",
            name = "Gemma 3 1B Instruct (INT4 .task)",
            format = "TASK",
            sizeLabel = "~550 MB",
            ramNeededMb = 1200,
            description = "MediaPipe LiteRT .task model with optional GPU delegate acceleration.",
            fileName = "gemma3-1b-it-int4.task",
            downloadUrl = "https://huggingface.co/litert-community/Gemma3-1B-IT/resolve/main/gemma3-1b-it-int4.task",
        ),
        CuratedLocalModel(
            id = "smollm_135m_task",
            name = "SmolLM 135M Instruct (.task)",
            format = "TASK",
            sizeLabel = "~240 MB",
            ramNeededMb = 550,
            description = "Featherweight MediaPipe .task model for instant offline testing.",
            fileName = "SmolLM-135M-Instruct_multi-prefill-seq_q8_ekv1280.task",
            downloadUrl = "https://huggingface.co/litert-community/SmolLM-135M-Instruct/resolve/main/SmolLM-135M-Instruct_multi-prefill-seq_q8_ekv1280.task",
        ),
    )

    fun encodeModels(models: List<String>): String =
        runCatching { json.encodeToString(models.distinct()) }.getOrDefault("[]")

    fun decodeModels(rawJson: String): List<String> =
        runCatching { json.decodeFromString<List<String>>(rawJson) }.getOrDefault(emptyList())

    private val THOUGHT_CLOSED_REGEX = Regex(
        """<(think|thought|thinking|reasoning)\b[^>]*>([\s\S]*?)</\1>""",
        RegexOption.IGNORE_CASE,
    )
    private val THOUGHT_OPEN_REGEX = Regex(
        """<(think|thought|thinking|reasoning)\b[^>]*>""",
        RegexOption.IGNORE_CASE,
    )

    /**
     * Parses reasoning/thinking blocks from DeepSeek (<think>), Gemma (<thought>),
     * Claude/Qwen (<thinking>), and Reasoning models (<reasoning>), both complete and streaming.
     */
    fun parseThoughts(raw: String): Pair<String, String> {
        val thoughts = StringBuilder()
        var cleaned = raw
        THOUGHT_CLOSED_REGEX.findAll(raw).forEach { match ->
            val t = match.groupValues[2].trim()
            if (t.isNotEmpty()) {
                if (thoughts.isNotEmpty()) thoughts.append("\n\n")
                thoughts.append(t)
            }
        }
        cleaned = cleaned.replace(THOUGHT_CLOSED_REGEX, "")
        val openMatch = THOUGHT_OPEN_REGEX.find(cleaned)
        if (openMatch != null) {
            val partial = cleaned.substring(openMatch.range.last + 1).trim()
            if (partial.isNotEmpty()) {
                if (thoughts.isNotEmpty()) thoughts.append("\n\n")
                thoughts.append(partial)
            }
            cleaned = cleaned.substring(0, openMatch.range.first)
        }
        // Strip any stray closing tag if model opened implicitly
        cleaned = cleaned.replace(Regex("""</(think|thought|thinking|reasoning)>""", RegexOption.IGNORE_CASE), "")
        return Pair(thoughts.toString().trim(), cleaned.trim())
    }

    fun estimateTokens(text: String): Long =
        ((text.length + 3) / 4).toLong().coerceAtLeast(if (text.isBlank()) 0L else 1L)

    /**
     * Approximate blended USD cost per reply based on public per-1M token pricing.
     * Free / keyless / on-device / local models return 0.0.
     */
    fun estimateCostUsd(model: String, totalTokens: Long, requiresKey: Boolean, protocol: String): Double {
        if (!requiresKey || protocol == "on_device" || totalTokens <= 0L) return 0.0
        val m = model.lowercase()
        if (m.contains(":free") || m.contains("local")) return 0.0
        val usdPerMillion = when {
            m.contains("claude-opus") || m.contains("o1") -> 18.0
            m.contains("claude-sonnet") || m.contains("claude-3-7") -> 6.0
            m.contains("gpt-4.1") && !m.contains("mini") -> 5.0
            m.contains("gpt-4o") && !m.contains("mini") -> 5.0
            m.contains("gemini-2.5-pro") -> 3.5
            m.contains("grok-3") && !m.contains("mini") -> 5.0
            m.contains("deepseek-reasoner") || m.contains("deepseek-r1") -> 1.2
            m.contains("claude-3-5-haiku") -> 1.5
            m.contains("gpt-4o-mini") || m.contains("gpt-4.1-mini") || m.contains("o3-mini") -> 0.40
            m.contains("gemini-2.5-flash") || m.contains("gemini-2.0-flash") -> 0.25
            m.contains("deepseek") -> 0.45
            m.contains("llama-3.3-70b") || m.contains("qwen") -> 0.60
            m.contains("8b") || m.contains("mini") || m.contains("lite") || m.contains("small") -> 0.12
            else -> 0.50
        }
        return (totalTokens.toDouble() / 1_000_000.0) * usdPerMillion
    }
}

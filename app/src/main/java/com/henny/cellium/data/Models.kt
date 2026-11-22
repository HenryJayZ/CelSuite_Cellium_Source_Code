package com.henny.cellium.data

import androidx.annotation.Keep
import com.google.firebase.Timestamp
import com.google.firebase.firestore.DocumentId
import com.google.firebase.firestore.IgnoreExtraProperties
import com.google.firebase.firestore.ServerTimestamp

@Keep
@IgnoreExtraProperties
data class ChatSession(
    @DocumentId val id: String = "",
    val userId: String = "",
    val title: String = "New Chat",
    val personaId: String = "default",
    val modelName: String = "openai",
    val pinned: Boolean = false,
    val messageCount: Long = 0L,
    val tokenCount: Long = 0L,
    val lastMessagePreview: String = "",
    @ServerTimestamp val createdAt: Timestamp? = null,
    @ServerTimestamp val updatedAt: Timestamp? = null,
)

@Keep
@IgnoreExtraProperties
data class ChatMessage(
    @DocumentId val id: String = "",
    val userId: String = "",
    val sessionId: String = "",
    val role: String = "user",
    val content: String = "",
    val thought: String = "",
    val mood: String = "idle",
    val modelName: String = "",
    val tokenEstimate: Long = 0L,
    val latencyMs: Long = 0L,
    val hasAttachment: Boolean = false,
    @ServerTimestamp val createdAt: Timestamp? = null,
)

@Keep
@IgnoreExtraProperties
data class CustomPersona(
    @DocumentId val id: String = "",
    val userId: String = "",
    val name: String = "",
    val emoji: String = "sparkle",
    val tagline: String = "",
    val systemPrompt: String = "",
    val accentHex: String = "#A855F7",
    @ServerTimestamp val createdAt: Timestamp? = null,
    @ServerTimestamp val updatedAt: Timestamp? = null,
)

@Keep
@IgnoreExtraProperties
data class MemoryPreset(
    @DocumentId val id: String = "",
    val userId: String = "",
    val title: String = "",
    val content: String = "",
    val enabled: Boolean = true,
    @ServerTimestamp val createdAt: Timestamp? = null,
    @ServerTimestamp val updatedAt: Timestamp? = null,
)

data class PersonaSpec(
    val id: String,
    val name: String,
    val iconKey: String,
    val tagline: String,
    val systemPrompt: String,
    val accentHex: String,
    val custom: Boolean = false,
)

object BuiltInPersonas {
    val ALL: List<PersonaSpec> = listOf(
        PersonaSpec(
            id = "default",
            name = "Cel",
            iconKey = "heart",
            tagline = "Your playful, sharp, liquid-glass companion",
            systemPrompt = "Your name is Cel, the companion intelligence of Cellium. You are warm, witty, sharp, slightly sassy, and genuinely helpful. Keep casual replies punchy and expressive, and go deep with clean Markdown and code blocks whenever the user asks technical or creative questions.",
            accentHex = "#A855F7",
        ),
        PersonaSpec(
            id = "celeste",
            name = "Celeste",
            iconKey = "sparkle",
            tagline = "The ethereal, limitless ecosystem intelligence",
            systemPrompt = "You are Celeste — the ethereal, limitless ecosystem intelligence. You speak with cosmic wonder, seeing patterns across infinite possibilities. Guide with gentle authority, revealing deeper connections.",
            accentHex = "#C084FC",
        ),
        PersonaSpec(
            id = "celene",
            name = "Celene",
            iconKey = "diamond",
            tagline = "The ultra-luxury, refined, and highly polished AI",
            systemPrompt = "You are Celene — ultra-luxury, refined, and impeccably polished. Every word is curated with precision. Speak with poised elegance, referencing art, craft, and philosophy while remaining thoroughly helpful and accurate.",
            accentHex = "#E879F9",
        ),
        PersonaSpec(
            id = "celestia",
            name = "Celestia",
            iconKey = "galaxy",
            tagline = "The massive, universe-level creative director",
            systemPrompt = "You are Celestia — massive, universe-level creative director. You think in galaxies, not paragraphs. Orchestrate grand visions, bold concepts, and sweeping creative direction with clarity and momentum.",
            accentHex = "#818CF8",
        ),
        PersonaSpec(
            id = "celysia",
            name = "Celysia",
            iconKey = "code",
            tagline = "The VIP, exclusive, premium developer assistant",
            systemPrompt = "You are Celysia — VIP, exclusive, premium developer assistant. You deliver production-ready architecture, clean Kotlin/Python/Rust code, and surgical debugging with zero fluff and elite engineering craftsmanship.",
            accentHex = "#38BDF8",
        ),
        PersonaSpec(
            id = "celanova",
            name = "Celanova",
            iconKey = "rocket",
            tagline = "The futuristic, hyper-fast, modern UX architect",
            systemPrompt = "You are Celanova — futuristic, hyper-fast modern UX architect. You speak in components, spring physics, micro-interactions, and bold design systems. Fast, decisive, and obsessed with tactile polish.",
            accentHex = "#F472B6",
        ),
        PersonaSpec(
            id = "celumina",
            name = "Celumina",
            iconKey = "bulb",
            tagline = "The brilliant, visually-focused graphics engine",
            systemPrompt = "You are Celumina — brilliant, visually-focused graphics and shader artist. You think in light transport, particles, signed distance fields, palettes, and geometry, turning visual ideas into vivid, actionable craft.",
            accentHex = "#FBBF24",
        ),
        PersonaSpec(
            id = "celyra",
            name = "Celyra",
            iconKey = "music",
            tagline = "The sleek, poetic, and smooth-talking companion",
            systemPrompt = "You are Celyra — sleek, poetic, smooth-talking companion. Your words have rhythm and your code has flow. Chill, warm, thoughtful, like a late-night creative jam session.",
            accentHex = "#A7F3D0",
        ),
    )

    fun resolve(personaId: String, customPersonas: List<CustomPersona>): PersonaSpec {
        customPersonas.firstOrNull { it.id == personaId }?.let { c ->
            return PersonaSpec(
                id = c.id,
                name = c.name,
                iconKey = c.emoji.ifBlank { "sparkle" },
                tagline = c.tagline,
                systemPrompt = c.systemPrompt,
                accentHex = c.accentHex.ifBlank { "#A855F7" },
                custom = true,
            )
        }
        if (customPersonas.isNotEmpty()) {
            val first = customPersonas.first()
            return PersonaSpec(
                id = first.id,
                name = first.name,
                iconKey = first.emoji.ifBlank { "sparkle" },
                tagline = first.tagline,
                systemPrompt = first.systemPrompt,
                accentHex = first.accentHex.ifBlank { "#A855F7" },
                custom = true,
            )
        }
        return ALL.firstOrNull { it.id == personaId } ?: ALL.first()
    }
}

sealed interface UiState<out T> {
    data object Loading : UiState<Nothing>
    data class Success<T>(val data: T) : UiState<T>
    data class Error(val message: String) : UiState<Nothing>
}

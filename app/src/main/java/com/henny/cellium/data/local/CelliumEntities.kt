package com.henny.cellium.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "providers")
data class ProviderProfileEntity(
    @PrimaryKey val id: String,
    val name: String,
    val badge: String,
    val protocol: String, // "openai", "anthropic", "on_device"
    val baseUrl: String,
    val apiKey: String,
    val selectedModel: String,
    val cachedModelsJson: String = "[]",
    val temperature: Float = 0.7f,
    val topP: Float = 0.95f,
    val maxTokens: Int = 2048,
    val requiresKey: Boolean = true,
    val isCustom: Boolean = false,
    val usageCount: Int = 0,
    val updatedAtMs: Long = System.currentTimeMillis(),
)

@Entity(tableName = "sessions")
data class SessionEntity(
    @PrimaryKey val id: String,
    val title: String,
    val personaId: String = "default",
    val providerId: String = "preset_pollinations_free",
    val modelName: String = "",
    val pinned: Boolean = false,
    val archived: Boolean = false,
    val isLocked: Boolean = false,
    val isArena: Boolean = false,
    val arenaProviderA: String = "preset_pollinations_free",
    val arenaModelA: String = "openai-fast",
    val arenaPersonaA: String = "default",
    val arenaProviderB: String = "preset_pollinations_free",
    val arenaModelB: String = "openai-fast",
    val arenaPersonaB: String = "celysia",
    val activeLeafId: String = "",
    val messageCount: Int = 0,
    val tokenCount: Long = 0L,
    val lastMessagePreview: String = "",
    val createdAtMs: Long = System.currentTimeMillis(),
    val updatedAtMs: Long = System.currentTimeMillis(),
)

@Entity(
    tableName = "messages",
    indices = [
        Index(value = ["sessionId"]),
        Index(value = ["parentId"]),
    ],
)
data class MessageEntity(
    @PrimaryKey val id: String,
    val sessionId: String,
    val parentId: String? = null,
    val role: String, // "user", "assistant", "tool"
    val speakerLabel: String = "",
    val content: String,
    val thought: String = "",
    val toolCommand: String = "",
    val toolOutput: String = "",
    val toolStatus: String = "", // "", "pending", "approved", "denied", "blocked"
    val mood: String = "idle",
    val providerName: String = "",
    val modelName: String = "",
    val attachmentPath: String = "",
    val attachmentFileName: String = "",
    val attachmentFileContent: String = "",
    val tokenEstimate: Long = 0L,
    val latencyMs: Long = 0L,
    val tokensPerSec: Float = 0f,
    val estimatedCostUsd: Double = 0.0,
    val isError: Boolean = false,
    val isCompactSummary: Boolean = false,
    val createdAtMs: Long = System.currentTimeMillis(),
)

@Entity(tableName = "custom_personas")
data class CustomPersonaEntity(
    @PrimaryKey val id: String,
    val name: String,
    val iconKey: String = "sparkles",
    val tagline: String = "",
    val systemPrompt: String,
    val accentHex: String = "#A855F7",
    val createdAtMs: Long = System.currentTimeMillis(),
)

@Entity(tableName = "memories")
data class MemoryEntity(
    @PrimaryKey val id: String,
    val title: String,
    val content: String,
    val enabled: Boolean = true,
    val createdAtMs: Long = System.currentTimeMillis(),
)

@Entity(tableName = "prompt_templates")
data class PromptTemplateEntity(
    @PrimaryKey val id: String,
    val slashKey: String,
    val title: String,
    val promptBody: String,
    val createdAtMs: Long = System.currentTimeMillis(),
)

@Entity(tableName = "artworks")
data class ArtworkEntity(
    @PrimaryKey val id: String,
    val prompt: String,
    val negativePrompt: String = "",
    val provider: String,
    val model: String,
    val aspectRatio: String = "1:1",
    val seed: Long = 0L,
    val localPath: String,
    val createdAtMs: Long = System.currentTimeMillis(),
)

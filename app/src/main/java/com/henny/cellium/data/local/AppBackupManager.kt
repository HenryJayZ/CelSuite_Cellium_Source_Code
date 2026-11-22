package com.henny.cellium.data.local

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

@Serializable
data class CelliumBackupPayload(
    val formatVersion: Int = 2,
    val appVersion: String = "v2611.21.0",
    val exportedAtMs: Long = System.currentTimeMillis(),
    val includesApiKeys: Boolean = false,
    val sessions: List<BackupSession> = emptyList(),
    val messages: List<BackupMessage> = emptyList(),
    val personas: List<BackupPersona> = emptyList(),
    val memories: List<BackupMemory> = emptyList(),
    val templates: List<BackupTemplate> = emptyList(),
    val providers: List<BackupProvider> = emptyList(),
)

@Serializable
data class BackupSession(
    val id: String,
    val title: String,
    val personaId: String,
    val providerId: String,
    val modelName: String,
    val pinned: Boolean = false,
    val archived: Boolean = false,
    val isArena: Boolean = false,
    val messageCount: Int = 0,
    val tokenCount: Long = 0L,
    val lastMessagePreview: String = "",
    val createdAtMs: Long = 0L,
    val updatedAtMs: Long = 0L,
)

@Serializable
data class BackupMessage(
    val id: String,
    val sessionId: String,
    val parentId: String? = null,
    val role: String,
    val speakerLabel: String = "",
    val content: String,
    val thought: String = "",
    val mood: String = "idle",
    val providerName: String = "",
    val modelName: String = "",
    val tokenEstimate: Long = 0L,
    val latencyMs: Long = 0L,
    val tokensPerSec: Float = 0f,
    val estimatedCostUsd: Double = 0.0,
    val createdAtMs: Long = 0L,
)

@Serializable
data class BackupPersona(
    val id: String,
    val name: String,
    val iconKey: String = "sparkle",
    val tagline: String = "",
    val systemPrompt: String = "",
    val accentHex: String = "#A855F7",
)

@Serializable
data class BackupMemory(
    val id: String,
    val title: String,
    val content: String,
    val enabled: Boolean = true,
)

@Serializable
data class BackupTemplate(
    val id: String,
    val slashTrigger: String,
    val title: String,
    val promptBody: String,
)

@Serializable
data class BackupProvider(
    val id: String,
    val name: String,
    val badge: String = "hub",
    val protocol: String = "openai",
    val baseUrl: String,
    val apiKey: String = "",
    val selectedModel: String = "",
    val temperature: Float = 0.7f,
    val topP: Float = 0.95f,
    val maxTokens: Int = 2048,
    val requiresKey: Boolean = true,
    val isCustom: Boolean = false,
)

data class BackupRestoreSummary(
    val sessionsRestored: Int,
    val messagesRestored: Int,
    val personasRestored: Int,
    val memoriesRestored: Int,
    val templatesRestored: Int,
    val providersRestored: Int,
)

class AppBackupManager(private val dao: CelliumDao) {
    private val json = Json {
        prettyPrint = true
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    suspend fun exportToJson(includeApiKeys: Boolean): String = withContext(Dispatchers.IO) {
        val sessions = dao.getAllSessionsOnce().map {
            BackupSession(
                id = it.id,
                title = it.title,
                personaId = it.personaId,
                providerId = it.providerId,
                modelName = it.modelName,
                pinned = it.pinned,
                archived = it.archived,
                isArena = it.isArena,
                messageCount = it.messageCount,
                tokenCount = it.tokenCount,
                lastMessagePreview = it.lastMessagePreview,
                createdAtMs = it.createdAtMs,
                updatedAtMs = it.updatedAtMs,
            )
        }
        val messages = dao.getAllMessagesOnce().map {
            BackupMessage(
                id = it.id,
                sessionId = it.sessionId,
                parentId = it.parentId,
                role = it.role,
                speakerLabel = it.speakerLabel,
                content = it.content,
                thought = it.thought,
                mood = it.mood,
                providerName = it.providerName,
                modelName = it.modelName,
                tokenEstimate = it.tokenEstimate,
                latencyMs = it.latencyMs,
                tokensPerSec = it.tokensPerSec,
                estimatedCostUsd = it.estimatedCostUsd,
                createdAtMs = it.createdAtMs,
            )
        }
        val personas = dao.getAllPersonasOnce().map {
            BackupPersona(it.id, it.name, it.iconKey, it.tagline, it.systemPrompt, it.accentHex)
        }
        val memories = dao.getAllMemoriesOnce().map {
            BackupMemory(it.id, it.title, it.content, it.enabled)
        }
        val templates = dao.getAllPromptTemplatesOnce().map {
            BackupTemplate(it.id, it.slashKey, it.title, it.promptBody)
        }
        val providers = dao.getAllProviders().map {
            BackupProvider(
                id = it.id,
                name = it.name,
                badge = it.badge,
                protocol = it.protocol,
                baseUrl = it.baseUrl,
                apiKey = if (includeApiKeys) it.apiKey else "",
                selectedModel = it.selectedModel,
                temperature = it.temperature,
                topP = it.topP,
                maxTokens = it.maxTokens,
                requiresKey = it.requiresKey,
                isCustom = it.isCustom,
            )
        }
        json.encodeToString(
            CelliumBackupPayload(
                includesApiKeys = includeApiKeys,
                sessions = sessions,
                messages = messages,
                personas = personas,
                memories = memories,
                templates = templates,
                providers = providers,
            )
        )
    }

    suspend fun importFromJson(rawJson: String): Result<BackupRestoreSummary> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = json.decodeFromString<CelliumBackupPayload>(rawJson)
            payload.sessions.forEach { s ->
                dao.upsertSession(
                    SessionEntity(
                        id = s.id,
                        title = s.title,
                        personaId = s.personaId,
                        providerId = s.providerId,
                        modelName = s.modelName,
                        pinned = s.pinned,
                        archived = s.archived,
                        isArena = s.isArena,
                        messageCount = s.messageCount,
                        tokenCount = s.tokenCount,
                        lastMessagePreview = s.lastMessagePreview,
                        createdAtMs = s.createdAtMs,
                        updatedAtMs = s.updatedAtMs,
                    )
                )
            }
            payload.messages.forEach { m ->
                dao.upsertMessage(
                    MessageEntity(
                        id = m.id,
                        sessionId = m.sessionId,
                        parentId = m.parentId,
                        role = m.role,
                        speakerLabel = m.speakerLabel,
                        content = m.content,
                        thought = m.thought,
                        mood = m.mood,
                        providerName = m.providerName,
                        modelName = m.modelName,
                        tokenEstimate = m.tokenEstimate,
                        latencyMs = m.latencyMs,
                        tokensPerSec = m.tokensPerSec,
                        estimatedCostUsd = m.estimatedCostUsd,
                        createdAtMs = m.createdAtMs,
                    )
                )
            }
            payload.personas.forEach { p ->
                dao.upsertPersona(
                    CustomPersonaEntity(
                        id = p.id,
                        name = p.name,
                        iconKey = p.iconKey,
                        tagline = p.tagline,
                        systemPrompt = p.systemPrompt,
                        accentHex = p.accentHex,
                    )
                )
            }
            payload.memories.forEach { m ->
                dao.upsertMemory(MemoryEntity(m.id, m.title, m.content, m.enabled))
            }
            payload.templates.forEach { t ->
                dao.upsertPromptTemplate(PromptTemplateEntity(t.id, t.slashTrigger, t.title, t.promptBody))
            }
            val existingProviders = dao.getAllProviders().associateBy { it.id }
            var restoredProviders = 0
            payload.providers.forEach { p ->
                val prev = existingProviders[p.id]
                val finalKey = p.apiKey.ifBlank { prev?.apiKey.orEmpty() }
                dao.upsertProvider(
                    ProviderProfileEntity(
                        id = p.id,
                        name = p.name,
                        badge = p.badge,
                        protocol = p.protocol,
                        baseUrl = p.baseUrl,
                        apiKey = finalKey,
                        selectedModel = p.selectedModel,
                        cachedModelsJson = prev?.cachedModelsJson ?: "[]",
                        temperature = p.temperature,
                        topP = p.topP,
                        maxTokens = p.maxTokens,
                        requiresKey = p.requiresKey,
                        isCustom = p.isCustom,
                    )
                )
                restoredProviders++
            }
            BackupRestoreSummary(
                sessionsRestored = payload.sessions.size,
                messagesRestored = payload.messages.size,
                personasRestored = payload.personas.size,
                memoriesRestored = payload.memories.size,
                templatesRestored = payload.templates.size,
                providersRestored = restoredProviders,
            )
        }
    }
}

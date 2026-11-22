package com.henny.cellium.data.sync

import com.google.firebase.Firebase
import com.google.firebase.auth.auth
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.SetOptions
import com.google.firebase.firestore.firestore
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.PreferencesStore
import com.henny.cellium.data.local.CelliumDao
import com.henny.cellium.data.local.CustomPersonaEntity
import com.henny.cellium.data.local.MemoryEntity
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.PromptTemplateEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.data.local.SessionEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withContext

data class SyncReport(
    val uploadedSessions: Int = 0,
    val downloadedSessions: Int = 0,
    val syncedProviders: Int = 0,
    val syncedPersonas: Int = 0,
    val syncedMemories: Int = 0,
    val syncedTemplates: Int = 0,
    val message: String = "",
)

/**
 * Full Google Account Cloud Sync Manager.
 * Local Room SQLite remains fast and offline-first; when signed in with Google,
 * this bidirectionally backs up and restores:
 * - All configured AI Providers & BYOK API keys (and live fetched models)
 * - Account stats, preferences, Imagine API key, and Kaggle credentials
 * - Slash prompt templates, custom personas, and persistent memories
 * - Chat & Arena sessions and their full message trees
 * Strictly isolated under users/{uid} with owner-only Firestore rules.
 */
class CloudSyncManager(
    private val dao: CelliumDao,
    private val prefsStore: PreferencesStore,
) {
    private val db by lazy { Firebase.firestore }

    suspend fun syncNow(currentPrefs: CelliumPreferences): Result<SyncReport> = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser
            ?: return@withContext Result.failure(
                IllegalStateException("Guest Mode active. Sign in with Google in Settings to sync your keys, stats, and chats.")
            )
        val uid = user.uid
        val userDoc = db.collection("users").document(uid)

        runCatching {
            // 1. Providers & API Keys (bidirectional merge)
            var syncedProviders = 0
            val localProviders = dao.getAllProviders().associateBy { it.id }
            val remoteProvSnap = userDoc.collection("providers").get().await()
            val remoteProvMap = remoteProvSnap.documents.associateBy { it.id }

            for (doc in remoteProvSnap.documents) {
                val id = doc.id
                val remoteUpdated = doc.getLong("updatedAtMs") ?: 0L
                val remoteKey = doc.getString("apiKey").orEmpty()
                val local = localProviders[id]
                if (local == null || remoteUpdated > local.updatedAtMs || (local.apiKey.isBlank() && remoteKey.isNotBlank())) {
                    dao.upsertProvider(
                        ProviderProfileEntity(
                            id = id,
                            name = doc.getString("name") ?: local?.name ?: id,
                            badge = doc.getString("badge") ?: local?.badge ?: "sparkle",
                            protocol = doc.getString("protocol") ?: local?.protocol ?: "openai",
                            baseUrl = doc.getString("baseUrl") ?: local?.baseUrl.orEmpty(),
                            apiKey = remoteKey.ifBlank { local?.apiKey.orEmpty() },
                            selectedModel = doc.getString("selectedModel") ?: local?.selectedModel.orEmpty(),
                            cachedModelsJson = doc.getString("cachedModelsJson") ?: local?.cachedModelsJson ?: "[]",
                            temperature = (doc.getDouble("temperature") ?: local?.temperature?.toDouble() ?: 0.7).toFloat(),
                            topP = (doc.getDouble("topP") ?: local?.topP?.toDouble() ?: 0.95).toFloat(),
                            maxTokens = (doc.getLong("maxTokens") ?: local?.maxTokens?.toLong() ?: 2048L).toInt(),
                            requiresKey = doc.getBoolean("requiresKey") ?: local?.requiresKey ?: true,
                            isCustom = doc.getBoolean("isCustom") ?: local?.isCustom ?: false,
                            updatedAtMs = maxOf(remoteUpdated, local?.updatedAtMs ?: 0L),
                        )
                    )
                    syncedProviders++
                }
            }

            // Upload all local providers that have keys, custom URLs, or newer changes
            for (lp in localProviders.values) {
                val shouldUpload = lp.apiKey.isNotBlank() || lp.isCustom || lp.cachedModelsJson.length > 2 || lp.id == currentPrefs.activeProviderId
                val remoteDoc = remoteProvMap[lp.id]
                val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                val remoteKey = remoteDoc?.getString("apiKey").orEmpty()
                if (shouldUpload && (remoteDoc == null || lp.updatedAtMs > remoteUpdated || (remoteKey.isBlank() && lp.apiKey.isNotBlank()))) {
                    val payload = mapOf(
                        "userId" to uid,
                        "name" to lp.name.take(120),
                        "badge" to lp.badge,
                        "protocol" to lp.protocol,
                        "baseUrl" to lp.baseUrl,
                        "apiKey" to lp.apiKey,
                        "selectedModel" to lp.selectedModel,
                        "cachedModelsJson" to lp.cachedModelsJson.take(400_000),
                        "temperature" to lp.temperature.toDouble(),
                        "topP" to lp.topP.toDouble(),
                        "maxTokens" to lp.maxTokens,
                        "requiresKey" to lp.requiresKey,
                        "isCustom" to lp.isCustom,
                        "updatedAtMs" to lp.updatedAtMs,
                        "syncedAt" to FieldValue.serverTimestamp(),
                    )
                    userDoc.collection("providers").document(lp.id).set(payload, SetOptions.merge()).await()
                    syncedProviders++
                }
            }

            // 2. Account Profile State: Stats, Settings, Imagine Key & Kaggle Credentials
            val allSessions = dao.getAllSessionsOnce()
            val allMessages = dao.getAllMessagesOnce()
            val localTotalTokens = allSessions.sumOf { it.tokenCount }
            val localTotalCost = allMessages.sumOf { it.estimatedCostUsd }

            val accountRef = userDoc.collection("account").document("profile_state")
            val remoteAccount = runCatching { accountRef.get().await() }.getOrNull()
            if (remoteAccount != null && remoteAccount.exists()) {
                prefsStore.applyCloudSnapshot(
                    activeProviderId = currentPrefs.activeProviderId.ifBlank { remoteAccount.getString("activeProviderId") }
                        .takeIf { it != "preset_pollinations_free" }
                        ?: remoteAccount.getString("activeProviderId"),
                    defaultPersonaId = remoteAccount.getString("defaultPersonaId"),
                    themePresetId = remoteAccount.getString("themePresetId"),
                    customPrimaryHex = remoteAccount.getString("customPrimaryHex"),
                    avatarGender = remoteAccount.getString("avatarGender"),
                    imagineProvider = remoteAccount.getString("imagineProvider"),
                    imagineModel = remoteAccount.getString("imagineModel"),
                    imagineApiKey = currentPrefs.imagineApiKey.ifBlank { remoteAccount.getString("imagineApiKey").orEmpty() },
                    imagineCustomUrl = currentPrefs.imagineCustomUrl.ifBlank { remoteAccount.getString("imagineCustomUrl").orEmpty() },
                    kaggleUsername = currentPrefs.kaggleUsername.ifBlank { remoteAccount.getString("kaggleUsername").orEmpty() },
                    kaggleKey = currentPrefs.kaggleKey.ifBlank { remoteAccount.getString("kaggleKey").orEmpty() },
                    kaggleKernelSlug = remoteAccount.getString("kaggleKernelSlug"),
                    kaggleModelId = remoteAccount.getString("kaggleModelId"),
                    soundsEnabled = remoteAccount.getBoolean("soundsEnabled"),
                    animaleseEnabled = remoteAccount.getBoolean("animaleseEnabled"),
                    hapticsEnabled = remoteAccount.getBoolean("hapticsEnabled"),
                    notificationsEnabled = remoteAccount.getBoolean("notificationsEnabled"),
                )
            }

            val mergedTokens = maxOf(localTotalTokens, remoteAccount?.getLong("totalTokens") ?: 0L)
            val mergedMessagesCount = maxOf(allMessages.size.toLong(), remoteAccount?.getLong("totalMessages") ?: 0L)
            val mergedCost = maxOf(localTotalCost, remoteAccount?.getDouble("totalEstimatedCostUsd") ?: 0.0)

            val accountPayload = mapOf(
                "userId" to uid,
                "email" to (user.email ?: ""),
                "onboardingCompleted" to true,
                "activeProviderId" to currentPrefs.activeProviderId,
                "defaultPersonaId" to currentPrefs.defaultPersonaId,
                "themePresetId" to currentPrefs.themePresetId,
                "customPrimaryHex" to currentPrefs.customPrimaryHex,
                "avatarGender" to currentPrefs.avatarGender,
                "imagineProvider" to currentPrefs.imagineProvider,
                "imagineModel" to currentPrefs.imagineModel,
                "imagineApiKey" to currentPrefs.imagineApiKey.ifBlank { remoteAccount?.getString("imagineApiKey").orEmpty() },
                "imagineCustomUrl" to currentPrefs.imagineCustomUrl.ifBlank { remoteAccount?.getString("imagineCustomUrl").orEmpty() },
                "kaggleUsername" to currentPrefs.kaggleUsername.ifBlank { remoteAccount?.getString("kaggleUsername").orEmpty() },
                "kaggleKey" to currentPrefs.kaggleKey.ifBlank { remoteAccount?.getString("kaggleKey").orEmpty() },
                "kaggleKernelSlug" to currentPrefs.kaggleKernelSlug,
                "kaggleModelId" to currentPrefs.kaggleModelId,
                "soundsEnabled" to currentPrefs.soundsEnabled,
                "animaleseEnabled" to currentPrefs.animaleseEnabled,
                "hapticsEnabled" to currentPrefs.hapticsEnabled,
                "notificationsEnabled" to currentPrefs.notificationsEnabled,
                "totalSessions" to maxOf(allSessions.size.toLong(), remoteAccount?.getLong("totalSessions") ?: 0L),
                "totalMessages" to mergedMessagesCount,
                "totalTokens" to mergedTokens,
                "totalEstimatedCostUsd" to mergedCost,
                "updatedAtMs" to System.currentTimeMillis(),
                "syncedAt" to FieldValue.serverTimestamp(),
            )
            accountRef.set(accountPayload, SetOptions.merge()).await()

            // 3. Custom Personas
            var syncedPersonas = 0
            val localPersonas = dao.getAllPersonasOnce().associateBy { it.id }
            val remotePersonasSnap = userDoc.collection("personas").get().await()
            val remotePersonaIds = remotePersonasSnap.documents.map { it.id }.toSet()
            for (doc in remotePersonasSnap.documents) {
                if (doc.id !in localPersonas) {
                    dao.upsertPersona(
                        CustomPersonaEntity(
                            id = doc.id,
                            name = doc.getString("name").orEmpty().ifBlank { "Persona" },
                            iconKey = doc.getString("iconKey") ?: doc.getString("emoji") ?: "sparkle",
                            tagline = doc.getString("tagline").orEmpty(),
                            systemPrompt = doc.getString("systemPrompt").orEmpty(),
                            accentHex = doc.getString("accentHex") ?: "#A855F7",
                            createdAtMs = doc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                        )
                    )
                    syncedPersonas++
                }
            }
            for (lp in localPersonas.values) {
                if (lp.id !in remotePersonaIds) {
                    userDoc.collection("personas").document(lp.id).set(
                        mapOf(
                            "userId" to uid,
                            "name" to lp.name.take(80),
                            "iconKey" to lp.iconKey,
                            "emoji" to lp.iconKey,
                            "tagline" to lp.tagline,
                            "systemPrompt" to lp.systemPrompt.take(16000),
                            "accentHex" to lp.accentHex,
                            "createdAtMs" to lp.createdAtMs,
                        ),
                        SetOptions.merge(),
                    ).await()
                    syncedPersonas++
                }
            }

            // 4. Persistent Memories
            var syncedMemories = 0
            val localMemories = dao.getAllMemoriesOnce().associateBy { it.id }
            val remoteMemoriesSnap = userDoc.collection("memories").get().await()
            val remoteMemoryIds = remoteMemoriesSnap.documents.map { it.id }.toSet()
            for (doc in remoteMemoriesSnap.documents) {
                if (doc.id !in localMemories) {
                    dao.upsertMemory(
                        MemoryEntity(
                            id = doc.id,
                            title = doc.getString("title").orEmpty().ifBlank { "Memory" },
                            content = doc.getString("content").orEmpty(),
                            enabled = doc.getBoolean("enabled") ?: true,
                            createdAtMs = doc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                        )
                    )
                    syncedMemories++
                }
            }
            for (lm in localMemories.values) {
                if (lm.id !in remoteMemoryIds) {
                    userDoc.collection("memories").document(lm.id).set(
                        mapOf(
                            "userId" to uid,
                            "title" to lm.title.take(120),
                            "content" to lm.content.take(8000),
                            "enabled" to lm.enabled,
                            "createdAtMs" to lm.createdAtMs,
                        ),
                        SetOptions.merge(),
                    ).await()
                    syncedMemories++
                }
            }

            // 5. Slash Prompt Templates
            var syncedTemplates = 0
            val localTemplates = dao.getAllPromptTemplatesOnce().associateBy { it.id }
            val remoteTemplatesSnap = userDoc.collection("templates").get().await()
            val remoteTemplateIds = remoteTemplatesSnap.documents.map { it.id }.toSet()
            for (doc in remoteTemplatesSnap.documents) {
                if (doc.id !in localTemplates) {
                    dao.upsertPromptTemplate(
                        PromptTemplateEntity(
                            id = doc.id,
                            slashKey = doc.getString("slashKey") ?: "/custom",
                            title = doc.getString("title") ?: "Template",
                            promptBody = doc.getString("promptBody").orEmpty(),
                            createdAtMs = doc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                        )
                    )
                    syncedTemplates++
                }
            }
            for (lt in localTemplates.values) {
                if (lt.id !in remoteTemplateIds) {
                    userDoc.collection("templates").document(lt.id).set(
                        mapOf(
                            "userId" to uid,
                            "slashKey" to lt.slashKey,
                            "title" to lt.title,
                            "promptBody" to lt.promptBody.take(16000),
                            "createdAtMs" to lt.createdAtMs,
                        ),
                        SetOptions.merge(),
                    ).await()
                    syncedTemplates++
                }
            }

            // 6. Sessions & Full Messages (bidirectional)
            val localSessionsById = allSessions.associateBy { it.id }
            val remoteSessionsSnap = userDoc.collection("sessions").get().await()
            val remoteSessionsById = remoteSessionsSnap.documents.associateBy { it.id }
            var downloaded = 0
            var uploaded = 0

            for (doc in remoteSessionsSnap.documents) {
                val sid = doc.id
                val remoteUpdated = doc.getLong("updatedAtMs") ?: 0L
                val local = localSessionsById[sid]
                if (local == null || remoteUpdated > local.updatedAtMs) {
                    dao.upsertSession(
                        SessionEntity(
                            id = sid,
                            title = doc.getString("title") ?: "Chat",
                            personaId = doc.getString("personaId") ?: "default",
                            providerId = doc.getString("providerId") ?: "preset_pollinations_free",
                            modelName = doc.getString("modelName").orEmpty(),
                            pinned = doc.getBoolean("pinned") ?: false,
                            archived = doc.getBoolean("archived") ?: false,
                            isArena = doc.getBoolean("isArena") ?: false,
                            activeLeafId = doc.getString("activeLeafId").orEmpty(),
                            messageCount = (doc.getLong("messageCount") ?: 0L).toInt(),
                            tokenCount = doc.getLong("tokenCount") ?: 0L,
                            lastMessagePreview = doc.getString("lastMessagePreview").orEmpty(),
                            createdAtMs = doc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                            updatedAtMs = remoteUpdated.takeIf { it > 0L } ?: System.currentTimeMillis(),
                        )
                    )
                    val remoteMsgs = userDoc.collection("sessions").document(sid).collection("messages").get().await()
                    val localMsgIds = dao.getMessagesForSessionOnce(sid).map { it.id }.toSet()
                    for (mdoc in remoteMsgs.documents) {
                        if (mdoc.id !in localMsgIds) {
                            dao.upsertMessage(
                                MessageEntity(
                                    id = mdoc.id,
                                    sessionId = sid,
                                    parentId = mdoc.getString("parentId"),
                                    role = mdoc.getString("role") ?: "assistant",
                                    speakerLabel = mdoc.getString("speakerLabel").orEmpty(),
                                    content = mdoc.getString("content").orEmpty(),
                                    thought = mdoc.getString("thought").orEmpty(),
                                    mood = mdoc.getString("mood") ?: "idle",
                                    providerName = mdoc.getString("providerName").orEmpty(),
                                    modelName = mdoc.getString("modelName").orEmpty(),
                                    tokenEstimate = mdoc.getLong("tokenEstimate") ?: 0L,
                                    latencyMs = mdoc.getLong("latencyMs") ?: 0L,
                                    tokensPerSec = (mdoc.getDouble("tokensPerSec") ?: 0.0).toFloat(),
                                    estimatedCostUsd = mdoc.getDouble("estimatedCostUsd") ?: 0.0,
                                    createdAtMs = mdoc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                                )
                            )
                        }
                    }
                    downloaded++
                }
            }

            // Upload local sessions (newest 30) & their messages if newer than remote
            for (ls in allSessions.take(30)) {
                if (ls.messageCount <= 0) continue
                val remoteDoc = remoteSessionsById[ls.id]
                val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                if (remoteDoc == null || ls.updatedAtMs > remoteUpdated) {
                    val sessRef = userDoc.collection("sessions").document(ls.id)
                    sessRef.set(
                        mapOf(
                            "userId" to uid,
                            "title" to ls.title.take(200),
                            "personaId" to ls.personaId,
                            "providerId" to ls.providerId,
                            "modelName" to ls.modelName,
                            "pinned" to ls.pinned,
                            "archived" to ls.archived,
                            "isArena" to ls.isArena,
                            "activeLeafId" to ls.activeLeafId,
                            "messageCount" to ls.messageCount,
                            "tokenCount" to ls.tokenCount,
                            "lastMessagePreview" to ls.lastMessagePreview.take(300),
                            "createdAtMs" to ls.createdAtMs,
                            "updatedAtMs" to ls.updatedAtMs,
                        ),
                        SetOptions.merge(),
                    ).await()
                    val msgs = dao.getMessagesForSessionOnce(ls.id).takeLast(60)
                    for (m in msgs) {
                        sessRef.collection("messages").document(m.id).set(
                            mapOf(
                                "userId" to uid,
                                "sessionId" to ls.id,
                                "parentId" to m.parentId,
                                "role" to m.role,
                                "speakerLabel" to m.speakerLabel,
                                "content" to m.content.take(120000),
                                "thought" to m.thought.take(20000),
                                "mood" to m.mood,
                                "providerName" to m.providerName,
                                "modelName" to m.modelName,
                                "tokenEstimate" to m.tokenEstimate,
                                "latencyMs" to m.latencyMs,
                                "tokensPerSec" to m.tokensPerSec.toDouble(),
                                "estimatedCostUsd" to m.estimatedCostUsd,
                                "createdAtMs" to m.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                    }
                    uploaded++
                }
            }

            val summary = "Synced to Google Account: $syncedProviders keys/providers · ↑$uploaded ↓$downloaded chats · $syncedPersonas personas · $syncedMemories memories · stats saved"
            DevLogBuffer.add("INFO", "CloudSync", summary)
            SyncReport(uploaded, downloaded, syncedProviders, syncedPersonas, syncedMemories, syncedTemplates, summary)
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "CloudSync", err.localizedMessage ?: "Cloud sync failed")
        }
    }
}

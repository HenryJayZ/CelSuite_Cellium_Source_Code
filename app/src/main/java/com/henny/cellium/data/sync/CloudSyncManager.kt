package com.henny.cellium.data.sync

import android.content.Context
import com.google.firebase.Firebase
import com.google.firebase.auth.auth
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.SetOptions
import com.google.firebase.firestore.firestore
import com.henny.cellium.R
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

enum class CloudSyncMode {
    MERGE_BOTH,
    KEEP_LOCAL_REPLACE_CLOUD,
    KEEP_CLOUD_REPLACE_LOCAL,
}

data class SyncReport(
    val uploadedSessions: Int = 0,
    val downloadedSessions: Int = 0,
    val syncedProviders: Int = 0,
    val syncedPersonas: Int = 0,
    val syncedMemories: Int = 0,
    val syncedTemplates: Int = 0,
    val usedBytes: Long = 0L,
    val quotaBytes: Long = CloudSyncManager.USER_QUOTA_BYTES,
    val message: String = "",
)

data class CloudStorageItem(
    val collection: String, // "sessions", "providers", "personas", "memories", "templates", "account"
    val docId: String,
    val title: String,
    val subtitle: String,
    val sizeBytes: Long,
)

data class CloudStorageSummary(
    val usedBytes: Long = 0L,
    val quotaBytes: Long = CloudSyncManager.USER_QUOTA_BYTES,
    val items: List<CloudStorageItem> = emptyList(),
)

/**
 * Full Google Account Cloud Sync Manager with:
 * - 3-mode Guest -> Google Sign-In conflict resolution (Merge / Replace Cloud / Replace Local)
 * - Firebase Spark free-tier 1 GiB quota enforcement (0.01% per user = 107,374 bytes / ~104.9 KB)
 * - Full Cloud Storage Inspector & per-item delete menu
 * - Syncs providers/keys, starred models, hidden providers, personas, memories, templates & chats
 */
class CloudSyncManager(
    private val context: Context,
    private val dao: CelliumDao,
    private val prefsStore: PreferencesStore,
) {
    private val db by lazy {
        val dbId = runCatching { context.getString(R.string.firestore_database_id).trim() }.getOrDefault("")
        if (dbId.isNotEmpty() && dbId != "(default)") Firebase.firestore(dbId) else Firebase.firestore
    }

    companion object {
        // Firebase Spark free Firestore storage = 1 GiB (1,073,741,824 bytes).
        // 0.01% per user = 107,374 bytes (~104.9 KB), safely supporting 10,000 free users!
        const val FIREBASE_SPARK_TOTAL_BYTES: Long = 1_073_741_824L
        const val USER_QUOTA_BYTES: Long = 107_374L
    }

    suspend fun hasCloudData(): Boolean = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser ?: return@withContext false
        val userDoc = db.collection("users").document(user.uid)
        runCatching {
            val acc = userDoc.collection("account").document("profile_state").get().await()
            if (acc.exists()) return@runCatching true
            val sessions = userDoc.collection("sessions").limit(1).get().await()
            if (!sessions.isEmpty) return@runCatching true
            val providers = userDoc.collection("providers").limit(1).get().await()
            !providers.isEmpty
        }.getOrDefault(false)
    }

    suspend fun inspectCloudStorage(): Result<CloudStorageSummary> = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser
            ?: return@withContext Result.failure(IllegalStateException("Sign in with Google first to inspect cloud storage."))
        val userDoc = db.collection("users").document(user.uid)
        runCatching {
            val items = mutableListOf<CloudStorageItem>()
            var totalBytes = 0L

            fun estimateDocBytes(data: Map<String, Any>?): Long {
                if (data == null) return 64L
                var sum = 64L
                data.forEach { (k, v) ->
                    sum += k.toByteArray().size + v.toString().toByteArray().size + 16L
                }
                return sum
            }

            // Account preferences & starred models
            val accDoc = runCatching { userDoc.collection("account").document("profile_state").get().await() }.getOrNull()
            if (accDoc != null && accDoc.exists()) {
                val sz = estimateDocBytes(accDoc.data)
                totalBytes += sz
                items.add(CloudStorageItem("account", "profile_state", "Preferences, Stars & Stats", "Theme, voice, starred models, usage stats", sz))
            }

            // Providers
            val provSnap = userDoc.collection("providers").get().await()
            for (d in provSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(
                    CloudStorageItem(
                        collection = "providers",
                        docId = d.id,
                        title = "Provider: ${d.getString("name") ?: d.id}",
                        subtitle = d.getString("selectedModel").orEmpty().ifBlank { "Saved API profile" },
                        sizeBytes = sz,
                    )
                )
            }

            // Sessions + nested messages
            val sessSnap = userDoc.collection("sessions").get().await()
            for (d in sessSnap.documents) {
                var sz = estimateDocBytes(d.data)
                val msgs = userDoc.collection("sessions").document(d.id).collection("messages").get().await()
                msgs.documents.forEach { m -> sz += estimateDocBytes(m.data) }
                totalBytes += sz
                items.add(
                    CloudStorageItem(
                        collection = "sessions",
                        docId = d.id,
                        title = "Chat: ${d.getString("title") ?: "Untitled"}",
                        subtitle = "${msgs.size()} messages",
                        sizeBytes = sz,
                    )
                )
            }

            // Personas
            val perSnap = userDoc.collection("personas").get().await()
            for (d in perSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(CloudStorageItem("personas", d.id, "Persona: ${d.getString("name") ?: d.id}", d.getString("tagline").orEmpty(), sz))
            }

            // Memories
            val memSnap = userDoc.collection("memories").get().await()
            for (d in memSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(CloudStorageItem("memories", d.id, "Memory: ${d.getString("title") ?: d.id}", d.getString("content").orEmpty().take(60), sz))
            }

            // Templates
            val tplSnap = userDoc.collection("templates").get().await()
            for (d in tplSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(CloudStorageItem("templates", d.id, "Command: ${d.getString("slashKey") ?: d.id}", d.getString("title").orEmpty(), sz))
            }

            CloudStorageSummary(
                usedBytes = totalBytes,
                quotaBytes = USER_QUOTA_BYTES,
                items = items.sortedByDescending { it.sizeBytes },
            )
        }
    }

    suspend fun deleteCloudItem(collection: String, docId: String): Result<Unit> = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser
            ?: return@withContext Result.failure(IllegalStateException("Not signed in."))
        val userDoc = db.collection("users").document(user.uid)
        runCatching {
            if (collection == "sessions") {
                val msgs = userDoc.collection("sessions").document(docId).collection("messages").get().await()
                msgs.documents.forEach { it.reference.delete().await() }
            }
            userDoc.collection(collection).document(docId).delete().await()
            DevLogBuffer.add("INFO", "CloudSync", "Deleted cloud item $collection/$docId")
        }
    }

    private suspend fun wipeAllCloudData(uid: String) {
        val userDoc = db.collection("users").document(uid)
        val sessions = userDoc.collection("sessions").get().await()
        for (s in sessions.documents) {
            val msgs = s.reference.collection("messages").get().await()
            msgs.documents.forEach { it.reference.delete().await() }
            s.reference.delete().await()
        }
        listOf("providers", "personas", "memories", "templates", "account").forEach { col ->
            val snap = userDoc.collection(col).get().await()
            snap.documents.forEach { it.reference.delete().await() }
        }
    }

    suspend fun syncNow(
        currentPrefs: CelliumPreferences,
        mode: CloudSyncMode = CloudSyncMode.MERGE_BOTH,
    ): Result<SyncReport> = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser
            ?: return@withContext Result.failure(
                IllegalStateException("Guest Mode active. Sign in with Google in Settings to sync your keys, stars, and chats.")
            )
        val uid = user.uid
        val userDoc = db.collection("users").document(uid)

        runCatching {
            if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD) {
                wipeAllCloudData(uid)
            } else if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL) {
                dao.deleteAllMessages()
                dao.deleteAllSessions()
                dao.deleteAllMemories()
                dao.deleteAllPersonas()
                dao.deleteAllPromptTemplates()
            }

            var byteBudgetRemaining = USER_QUOTA_BYTES
            val allowDownload = mode != CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD
            val allowUpload = mode != CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL

            // 1. Providers & API Keys
            var syncedProviders = 0
            val localProviders = dao.getAllProviders().associateBy { it.id }
            val remoteProvSnap = userDoc.collection("providers").get().await()
            val remoteProvMap = remoteProvSnap.documents.associateBy { it.id }

            if (allowDownload) {
                for (doc in remoteProvSnap.documents) {
                    val id = doc.id
                    val remoteUpdated = doc.getLong("updatedAtMs") ?: 0L
                    val remoteKey = doc.getString("apiKey").orEmpty()
                    val local = localProviders[id]
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || local == null || remoteUpdated > local.updatedAtMs || (local.apiKey.isBlank() && remoteKey.isNotBlank())) {
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
                                usageCount = maxOf((doc.getLong("usageCount") ?: 0L).toInt(), local?.usageCount ?: 0),
                                updatedAtMs = maxOf(remoteUpdated, local?.updatedAtMs ?: 0L),
                            )
                        )
                        syncedProviders++
                    }
                }
            }

            if (allowUpload) {
                for (lp in localProviders.values) {
                    val shouldUpload = lp.apiKey.isNotBlank() || lp.isCustom || lp.usageCount > 0 || lp.id == currentPrefs.activeProviderId
                    val remoteDoc = remoteProvMap[lp.id]
                    val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                    val remoteKey = remoteDoc?.getString("apiKey").orEmpty()
                    if (shouldUpload && (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || remoteDoc == null || lp.updatedAtMs > remoteUpdated || (remoteKey.isBlank() && lp.apiKey.isNotBlank()))) {
                        // Trim cachedModelsJson to fit within 0.01% Spark quota cleanly
                        val trimmedModels = lp.cachedModelsJson.take(4096)
                        val estSize = 320L + lp.apiKey.length + trimmedModels.length
                        if (byteBudgetRemaining < estSize) continue
                        byteBudgetRemaining -= estSize
                        val payload = mapOf(
                            "userId" to uid,
                            "name" to lp.name.take(120),
                            "badge" to lp.badge,
                            "protocol" to lp.protocol,
                            "baseUrl" to lp.baseUrl,
                            "apiKey" to lp.apiKey,
                            "selectedModel" to lp.selectedModel,
                            "cachedModelsJson" to trimmedModels,
                            "temperature" to lp.temperature.toDouble(),
                            "topP" to lp.topP.toDouble(),
                            "maxTokens" to lp.maxTokens,
                            "requiresKey" to lp.requiresKey,
                            "isCustom" to lp.isCustom,
                            "usageCount" to lp.usageCount,
                            "updatedAtMs" to lp.updatedAtMs,
                            "syncedAt" to FieldValue.serverTimestamp(),
                        )
                        userDoc.collection("providers").document(lp.id).set(payload, SetOptions.merge()).await()
                        syncedProviders++
                    }
                }
            }

            // 2. Account Profile State: Stats, Settings, Starred Models, Hidden Providers, Illume & Kaggle
            val allSessions = dao.getAllSessionsOnce()
            val allMessages = dao.getAllMessagesOnce()
            val localTotalTokens = allSessions.sumOf { it.tokenCount }
            val localTotalCost = allMessages.sumOf { it.estimatedCostUsd }

            val accountRef = userDoc.collection("account").document("profile_state")
            val remoteAccount = runCatching { accountRef.get().await() }.getOrNull()
            if (allowDownload && remoteAccount != null && remoteAccount.exists()) {
                @Suppress("UNCHECKED_CAST")
                val remoteHidden = (remoteAccount.get("hiddenProviderIds") as? List<*>)
                    ?.mapNotNull { it as? String }?.toSet()
                val mergedHidden = if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL) {
                    remoteHidden ?: emptySet()
                } else {
                    currentPrefs.hiddenProviderIds + (remoteHidden ?: emptySet())
                }
                prefsStore.applyCloudSnapshot(
                    activeProviderId = if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL) {
                        remoteAccount.getString("activeProviderId")
                    } else {
                        currentPrefs.activeProviderId.takeIf { it != "preset_pollinations_free" }
                            ?: remoteAccount.getString("activeProviderId")
                    },
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
                    starredModelsJson = remoteAccount.getString("starredModelsJson")
                        ?.takeIf { mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || currentPrefs.starredModelsJson == "[]" }
                        ?: currentPrefs.starredModelsJson,
                    hiddenProviderIds = mergedHidden,
                    moodMethod = remoteAccount.getString("moodMethod"),
                    typingSoundStyle = remoteAccount.getString("typingSoundStyle"),
                    typingSpeed = remoteAccount.getString("typingSpeed"),
                    ttsEngine = remoteAccount.getString("ttsEngine"),
                    ttsVoiceName = remoteAccount.getString("ttsVoiceName"),
                    sttEngine = remoteAccount.getString("sttEngine"),
                    sttApiKey = currentPrefs.sttApiKey.ifBlank { remoteAccount.getString("sttApiKey").orEmpty() },
                    sttModel = remoteAccount.getString("sttModel"),
                    arenaProviderA = remoteAccount.getString("arenaProviderA"),
                    arenaModelA = remoteAccount.getString("arenaModelA"),
                    arenaPersonaA = remoteAccount.getString("arenaPersonaA"),
                    arenaProviderB = remoteAccount.getString("arenaProviderB"),
                    arenaModelB = remoteAccount.getString("arenaModelB"),
                    arenaPersonaB = remoteAccount.getString("arenaPersonaB"),
                    maxAutoRetries = remoteAccount.getLong("maxAutoRetries")?.toInt(),
                    codeWordWrap = remoteAccount.getBoolean("codeWordWrap"),
                )
            }

            if (allowUpload) {
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
                    "imagineApiKey" to currentPrefs.imagineApiKey,
                    "imagineCustomUrl" to currentPrefs.imagineCustomUrl,
                    "kaggleUsername" to currentPrefs.kaggleUsername,
                    "kaggleKey" to currentPrefs.kaggleKey,
                    "kaggleKernelSlug" to currentPrefs.kaggleKernelSlug,
                    "kaggleModelId" to currentPrefs.kaggleModelId,
                    "soundsEnabled" to currentPrefs.soundsEnabled,
                    "animaleseEnabled" to currentPrefs.animaleseEnabled,
                    "hapticsEnabled" to currentPrefs.hapticsEnabled,
                    "notificationsEnabled" to currentPrefs.notificationsEnabled,
                    "starredModelsJson" to currentPrefs.starredModelsJson.take(8192),
                    "hiddenProviderIds" to currentPrefs.hiddenProviderIds.toList(),
                    "moodMethod" to currentPrefs.moodMethod,
                    "typingSoundStyle" to currentPrefs.typingSoundStyle,
                    "typingSpeed" to currentPrefs.typingSpeed,
                    "ttsEngine" to currentPrefs.ttsEngine,
                    "ttsVoiceName" to currentPrefs.ttsVoiceName,
                    "sttEngine" to currentPrefs.sttEngine,
                    "sttApiKey" to currentPrefs.sttApiKey,
                    "sttModel" to currentPrefs.sttModel,
                    "arenaProviderA" to currentPrefs.arenaProviderA,
                    "arenaModelA" to currentPrefs.arenaModelA,
                    "arenaPersonaA" to currentPrefs.arenaPersonaA,
                    "arenaProviderB" to currentPrefs.arenaProviderB,
                    "arenaModelB" to currentPrefs.arenaModelB,
                    "arenaPersonaB" to currentPrefs.arenaPersonaB,
                    "maxAutoRetries" to currentPrefs.maxAutoRetries,
                    "codeWordWrap" to currentPrefs.codeWordWrap,
                    "totalSessions" to maxOf(allSessions.size.toLong(), remoteAccount?.getLong("totalSessions") ?: 0L),
                    "totalMessages" to maxOf(allMessages.size.toLong(), remoteAccount?.getLong("totalMessages") ?: 0L),
                    "totalTokens" to maxOf(localTotalTokens, remoteAccount?.getLong("totalTokens") ?: 0L),
                    "totalEstimatedCostUsd" to maxOf(localTotalCost, remoteAccount?.getDouble("totalEstimatedCostUsd") ?: 0.0),
                    "updatedAtMs" to System.currentTimeMillis(),
                    "syncedAt" to FieldValue.serverTimestamp(),
                )
                accountRef.set(accountPayload, SetOptions.merge()).await()
                byteBudgetRemaining = (byteBudgetRemaining - 2048L).coerceAtLeast(0L)
            }

            // 3. Personas
            var syncedPersonas = 0
            val localPersonas = dao.getAllPersonasOnce().associateBy { it.id }
            val remotePersonasSnap = userDoc.collection("personas").get().await()
            val remotePersonaIds = remotePersonasSnap.documents.map { it.id }.toSet()
            if (allowDownload) {
                for (doc in remotePersonasSnap.documents) {
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || doc.id !in localPersonas) {
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
            }
            if (allowUpload) {
                for (lp in localPersonas.values) {
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || lp.id !in remotePersonaIds) {
                        val est = 256L + lp.systemPrompt.take(4000).length
                        if (byteBudgetRemaining < est) break
                        byteBudgetRemaining -= est
                        userDoc.collection("personas").document(lp.id).set(
                            mapOf(
                                "userId" to uid,
                                "name" to lp.name.take(80),
                                "iconKey" to lp.iconKey,
                                "tagline" to lp.tagline.take(200),
                                "systemPrompt" to lp.systemPrompt.take(4000),
                                "accentHex" to lp.accentHex,
                                "createdAtMs" to lp.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        syncedPersonas++
                    }
                }
            }

            // 4. Memories
            var syncedMemories = 0
            val localMemories = dao.getAllMemoriesOnce().associateBy { it.id }
            val remoteMemoriesSnap = userDoc.collection("memories").get().await()
            val remoteMemoryIds = remoteMemoriesSnap.documents.map { it.id }.toSet()
            if (allowDownload) {
                for (doc in remoteMemoriesSnap.documents) {
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || doc.id !in localMemories) {
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
            }
            if (allowUpload) {
                for (lm in localMemories.values) {
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || lm.id !in remoteMemoryIds) {
                        val est = 180L + lm.content.take(2000).length
                        if (byteBudgetRemaining < est) break
                        byteBudgetRemaining -= est
                        userDoc.collection("memories").document(lm.id).set(
                            mapOf(
                                "userId" to uid,
                                "title" to lm.title.take(120),
                                "content" to lm.content.take(2000),
                                "enabled" to lm.enabled,
                                "createdAtMs" to lm.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        syncedMemories++
                    }
                }
            }

            // 5. Slash Prompt Templates
            var syncedTemplates = 0
            val localTemplates = dao.getAllPromptTemplatesOnce().associateBy { it.id }
            val remoteTemplatesSnap = userDoc.collection("templates").get().await()
            val remoteTemplateIds = remoteTemplatesSnap.documents.map { it.id }.toSet()
            if (allowDownload) {
                for (doc in remoteTemplatesSnap.documents) {
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || doc.id !in localTemplates) {
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
            }
            if (allowUpload) {
                for (lt in localTemplates.values) {
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || lt.id !in remoteTemplateIds) {
                        val est = 180L + lt.promptBody.take(2000).length
                        if (byteBudgetRemaining < est) break
                        byteBudgetRemaining -= est
                        userDoc.collection("templates").document(lt.id).set(
                            mapOf(
                                "userId" to uid,
                                "slashKey" to lt.slashKey,
                                "title" to lt.title,
                                "promptBody" to lt.promptBody.take(2000),
                                "createdAtMs" to lt.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        syncedTemplates++
                    }
                }
            }

            // 6. Sessions & Messages (within remaining 104.9 KB quota budget!)
            val localSessionsById = allSessions.associateBy { it.id }
            val remoteSessionsSnap = userDoc.collection("sessions").get().await()
            val remoteSessionsById = remoteSessionsSnap.documents.associateBy { it.id }
            var downloaded = 0
            var uploaded = 0

            if (allowDownload) {
                for (doc in remoteSessionsSnap.documents) {
                    val sid = doc.id
                    val remoteUpdated = doc.getLong("updatedAtMs") ?: 0L
                    val local = localSessionsById[sid]
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || local == null || remoteUpdated > local.updatedAtMs) {
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
                                arenaProviderA = doc.getString("arenaProviderA") ?: local?.arenaProviderA ?: "preset_pollinations_free",
                                arenaModelA = doc.getString("arenaModelA") ?: local?.arenaModelA ?: "openai-fast",
                                arenaPersonaA = doc.getString("arenaPersonaA") ?: local?.arenaPersonaA ?: "default",
                                arenaProviderB = doc.getString("arenaProviderB") ?: local?.arenaProviderB ?: "preset_pollinations_free",
                                arenaModelB = doc.getString("arenaModelB") ?: local?.arenaModelB ?: "openai-fast",
                                arenaPersonaB = doc.getString("arenaPersonaB") ?: local?.arenaPersonaB ?: "celeste",
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
                                        isCompactSummary = mdoc.getBoolean("isCompactSummary") ?: false,
                                        createdAtMs = mdoc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                                    )
                                )
                            }
                        }
                        downloaded++
                    }
                }
            }

            if (allowUpload) {
                for (ls in allSessions.take(20)) {
                    if (ls.messageCount <= 0) continue
                    val remoteDoc = remoteSessionsById[ls.id]
                    val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || remoteDoc == null || ls.updatedAtMs > remoteUpdated) {
                        if (byteBudgetRemaining < 512L) break
                        val sessRef = userDoc.collection("sessions").document(ls.id)
                        sessRef.set(
                            mapOf(
                                "userId" to uid,
                                "title" to ls.title.take(160),
                                "personaId" to ls.personaId,
                                "providerId" to ls.providerId,
                                "modelName" to ls.modelName,
                                "pinned" to ls.pinned,
                                "archived" to ls.archived,
                                "isArena" to ls.isArena,
                                "arenaProviderA" to ls.arenaProviderA,
                                "arenaModelA" to ls.arenaModelA,
                                "arenaPersonaA" to ls.arenaPersonaA,
                                "arenaProviderB" to ls.arenaProviderB,
                                "arenaModelB" to ls.arenaModelB,
                                "arenaPersonaB" to ls.arenaPersonaB,
                                "activeLeafId" to ls.activeLeafId,
                                "messageCount" to ls.messageCount,
                                "tokenCount" to ls.tokenCount,
                                "lastMessagePreview" to ls.lastMessagePreview.take(200),
                                "createdAtMs" to ls.createdAtMs,
                                "updatedAtMs" to ls.updatedAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        byteBudgetRemaining -= 384L
                        val msgs = dao.getMessagesForSessionOnce(ls.id).takeLast(24)
                        for (m in msgs) {
                            val contentSnippet = m.content.take(2500)
                            val est = 256L + contentSnippet.length
                            if (byteBudgetRemaining < est) break
                            byteBudgetRemaining -= est
                            sessRef.collection("messages").document(m.id).set(
                                mapOf(
                                    "userId" to uid,
                                    "sessionId" to ls.id,
                                    "parentId" to m.parentId,
                                    "role" to m.role,
                                    "speakerLabel" to m.speakerLabel,
                                    "content" to contentSnippet,
                                    "thought" to m.thought.take(600),
                                    "mood" to m.mood,
                                    "providerName" to m.providerName,
                                    "modelName" to m.modelName,
                                    "tokenEstimate" to m.tokenEstimate,
                                    "latencyMs" to m.latencyMs,
                                    "tokensPerSec" to m.tokensPerSec.toDouble(),
                                    "estimatedCostUsd" to m.estimatedCostUsd,
                                    "isCompactSummary" to m.isCompactSummary,
                                    "createdAtMs" to m.createdAtMs,
                                ),
                                SetOptions.merge(),
                            ).await()
                        }
                        uploaded++
                    }
                }
            }

            val used = (USER_QUOTA_BYTES - byteBudgetRemaining).coerceIn(0L, USER_QUOTA_BYTES)
            val usedKb = "%.1f".format(used / 1024.0)
            val maxKb = "%.1f".format(USER_QUOTA_BYTES / 1024.0)
            val summary = "Cloud Synced ($usedKb / $maxKb KB quota): $syncedProviders providers · ↑$uploaded ↓$downloaded chats · $syncedPersonas personas · $syncedMemories memories"
            DevLogBuffer.add("INFO", "CloudSync", summary)
            SyncReport(uploaded, downloaded, syncedProviders, syncedPersonas, syncedMemories, syncedTemplates, used, USER_QUOTA_BYTES, summary)
        }.onFailure { err ->
            DevLogBuffer.add("ERROR", "CloudSync", err.localizedMessage ?: "Cloud sync failed")
        }
    }
}

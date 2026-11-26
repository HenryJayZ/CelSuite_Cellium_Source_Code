package com.henny.cellium.data.sync

import android.content.Context
import com.google.firebase.Firebase
import com.google.firebase.FirebaseApp
import com.google.firebase.auth.auth
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.SetOptions
import com.google.firebase.firestore.Source
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
 * Google Account Cloud Sync Manager using official Firebase Android SDK named-database initialization
 * and strict Source.SERVER reads so offline/permission issues surface cleanly instead of silently
 * returning empty local cache ("0 chats, 0 providers").
 */
class CloudSyncManager(
    private val context: Context,
    private val dao: CelliumDao,
    private val prefsStore: PreferencesStore,
) {
    private val databaseId: String by lazy {
        runCatching { context.getString(R.string.firestore_database_id).trim() }.getOrDefault("")
    }

    private val db: FirebaseFirestore by lazy {
        val app = FirebaseApp.getInstance()
        if (databaseId.isNotEmpty() && databaseId != "(default)") {
            FirebaseFirestore.getInstance(app, databaseId)
        } else {
            FirebaseFirestore.getInstance(app)
        }
    }

    companion object {
        // Firebase Spark free Firestore storage = 1 GiB (1,073,741,824 bytes).
        // 0.01% per user = 107,374 bytes (~104.9 KB).
        const val FIREBASE_SPARK_TOTAL_BYTES: Long = 1_073_741_824L
        const val USER_QUOTA_BYTES: Long = 107_374L

        private val DOC_ID_BAD_CHARS = Regex("[^a-zA-Z0-9_.\\-]")

        private fun safeDocId(raw: String, fallbackPrefix: String): String {
            val cleaned = DOC_ID_BAD_CHARS.replace(raw.trim(), "_").take(150)
            return cleaned.ifBlank { "${fallbackPrefix}_${System.currentTimeMillis()}" }
        }

        private fun estimateDocBytes(data: Map<String, Any>?): Long {
            if (data == null) return 64L
            var sum = 64L
            data.forEach { (k, v) ->
                sum += k.toByteArray().size + v.toString().toByteArray().size + 16L
            }
            return sum
        }
    }

    suspend fun hasCloudData(): Boolean = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser ?: return@withContext false
        val userDoc = db.collection("users").document(user.uid)
        runCatching {
            user.getIdToken(false).await()
            val acc = userDoc.collection("account").document("profile_state").get(Source.SERVER).await()
            if (acc.exists()) return@runCatching true
            val sessions = userDoc.collection("sessions").limit(1).get(Source.SERVER).await()
            if (!sessions.isEmpty) return@runCatching true
            val providers = userDoc.collection("providers").limit(1).get(Source.SERVER).await()
            !providers.isEmpty
        }.getOrDefault(false)
    }

    suspend fun inspectCloudStorage(): Result<CloudStorageSummary> = withContext(Dispatchers.IO) {
        val user = Firebase.auth.currentUser
            ?: return@withContext Result.failure(IllegalStateException("Sign in with Google first to inspect cloud storage."))
        val userDoc = db.collection("users").document(user.uid)
        runCatching {
            user.getIdToken(false).await()
            val items = mutableListOf<CloudStorageItem>()
            var totalBytes = 0L

            val accDoc = userDoc.collection("account").document("profile_state").get(Source.SERVER).await()
            if (accDoc.exists()) {
                val sz = estimateDocBytes(accDoc.data)
                totalBytes += sz
                items.add(CloudStorageItem("account", "profile_state", "Preferences, Stars & Stats", "Theme, voice, starred models, usage stats", sz))
            }

            val provSnap = userDoc.collection("providers").get(Source.SERVER).await()
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

            val sessSnap = userDoc.collection("sessions").get(Source.SERVER).await()
            for (d in sessSnap.documents) {
                var sz = estimateDocBytes(d.data)
                val msgs = userDoc.collection("sessions").document(d.id).collection("messages").get(Source.SERVER).await()
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

            val perSnap = userDoc.collection("personas").get(Source.SERVER).await()
            for (d in perSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(CloudStorageItem("personas", d.id, "Persona: ${d.getString("name") ?: d.id}", d.getString("tagline").orEmpty(), sz))
            }

            val memSnap = userDoc.collection("memories").get(Source.SERVER).await()
            for (d in memSnap.documents) {
                val sz = estimateDocBytes(d.data)
                totalBytes += sz
                items.add(CloudStorageItem("memories", d.id, "Memory: ${d.getString("title") ?: d.id}", d.getString("content").orEmpty().take(60), sz))
            }

            val tplSnap = userDoc.collection("templates").get(Source.SERVER).await()
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
            user.getIdToken(false).await()
            if (collection == "sessions") {
                val msgs = userDoc.collection("sessions").document(docId).collection("messages").get(Source.SERVER).await()
                msgs.documents.forEach { it.reference.delete().await() }
            }
            userDoc.collection(collection).document(docId).delete().await()
            DevLogBuffer.add("INFO", "CloudSync", "Deleted cloud item $collection/$docId")
        }
    }

    private suspend fun wipeAllCloudData(uid: String) {
        val userDoc = db.collection("users").document(uid)
        val sessions = userDoc.collection("sessions").get(Source.SERVER).await()
        for (s in sessions.documents) {
            val msgs = s.reference.collection("messages").get(Source.SERVER).await()
            msgs.documents.forEach { it.reference.delete().await() }
            s.reference.delete().await()
        }
        listOf("providers", "personas", "memories", "templates", "account").forEach { col ->
            val snap = userDoc.collection(col).get(Source.SERVER).await()
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
            // Ensure Firebase Auth token is valid before issuing Firestore server operations
            user.getIdToken(false).await()

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
            var deltaProviders = 0
            val localProviders = dao.getAllProviders().associateBy { it.id }
            val remoteProvSnap = userDoc.collection("providers").get(Source.SERVER).await()
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
                                name = doc.getString("name").orEmpty().ifBlank { local?.name ?: id },
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
                        deltaProviders++
                    }
                }
            }

            if (allowUpload) {
                for (lp in localProviders.values) {
                    val docId = safeDocId(lp.id, "prov")
                    val shouldUpload = lp.apiKey.isNotBlank() || lp.isCustom || lp.usageCount > 0 ||
                        lp.id == currentPrefs.activeProviderId
                    val remoteDoc = remoteProvMap[docId]
                    val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                    val remoteKey = remoteDoc?.getString("apiKey").orEmpty()
                    if (shouldUpload && (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || remoteDoc == null || lp.updatedAtMs > remoteUpdated || (remoteKey.isBlank() && lp.apiKey.isNotBlank()))) {
                        val estSize = 240L + lp.apiKey.length
                        if (byteBudgetRemaining < estSize) continue
                        byteBudgetRemaining -= estSize
                        val safeName = lp.name.trim().ifBlank { docId }.take(120)
                        val payload = mapOf(
                            "userId" to uid,
                            "name" to safeName,
                            "badge" to lp.badge,
                            "protocol" to lp.protocol,
                            "baseUrl" to lp.baseUrl,
                            "apiKey" to lp.apiKey,
                            "selectedModel" to lp.selectedModel,
                            "cachedModelsJson" to "[]",
                            "temperature" to lp.temperature.toDouble(),
                            "topP" to lp.topP.toDouble(),
                            "maxTokens" to lp.maxTokens,
                            "requiresKey" to lp.requiresKey,
                            "isCustom" to lp.isCustom,
                            "usageCount" to lp.usageCount,
                            "updatedAtMs" to lp.updatedAtMs,
                            "syncedAt" to FieldValue.serverTimestamp(),
                        )
                        userDoc.collection("providers").document(docId).set(payload, SetOptions.merge()).await()
                        deltaProviders++
                    }
                }
            }

            // 2. Account Profile State: Stats, Settings, Starred Models, Hidden Providers, Illume & Kaggle
            val allSessions = dao.getAllSessionsOnce()
            val allMessages = dao.getAllMessagesOnce()
            val localTotalTokens = allSessions.sumOf { it.tokenCount }
            val localTotalCost = allMessages.sumOf { it.estimatedCostUsd }

            val accountRef = userDoc.collection("account").document("profile_state")
            val remoteAccount = accountRef.get(Source.SERVER).await()
            val remoteAccountUpdatedMs = remoteAccount.getLong("updatedAtMs") ?: 0L
            val shouldApplyRemotePrefs = mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL ||
                currentPrefs.prefsUpdatedAtMs == 0L ||
                remoteAccountUpdatedMs > currentPrefs.prefsUpdatedAtMs

            if (allowDownload && remoteAccount.exists() && shouldApplyRemotePrefs) {
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
                    typingSoundPitch = remoteAccount.getDouble("typingSoundPitch")?.toFloat(),
                    typingSoundCadence = remoteAccount.getString("typingSoundCadence"),
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
                    remoteUpdatedAtMs = remoteAccountUpdatedMs,
                )
                val remoteLiveEngine = remoteAccount.getString("liveTtsEngine")
                val remoteLiveVoice = remoteAccount.getString("liveTtsVoiceName")
                if (!remoteLiveEngine.isNullOrBlank()) {
                    prefsStore.updateLiveVoiceSettings(
                        engine = remoteLiveEngine,
                        voice = remoteLiveVoice.orEmpty(),
                        pitch = remoteAccount.getDouble("liveTtsPitch")?.toFloat() ?: currentPrefs.liveTtsPitch,
                        rate = remoteAccount.getDouble("liveTtsSpeechRate")?.toFloat() ?: currentPrefs.liveTtsSpeechRate,
                    )
                }
                remoteAccount.getString("startupSoundId")?.takeIf { it.isNotBlank() }?.let { sid ->
                    prefsStore.updateStartupSound(sid)
                }
            }

            if (allowUpload) {
                val uploadUpdatedMs = maxOf(System.currentTimeMillis(), currentPrefs.prefsUpdatedAtMs)
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
                    "starredModelsJson" to currentPrefs.starredModelsJson.take(4096),
                    "hiddenProviderIds" to currentPrefs.hiddenProviderIds.toList(),
                    "moodMethod" to currentPrefs.moodMethod,
                    "typingSoundStyle" to currentPrefs.typingSoundStyle,
                    "typingSoundPitch" to currentPrefs.typingSoundPitch.toDouble(),
                    "typingSoundCadence" to currentPrefs.typingSoundCadence,
                    "typingSpeed" to currentPrefs.typingSpeed,
                    "ttsEngine" to currentPrefs.ttsEngine,
                    "ttsVoiceName" to currentPrefs.ttsVoiceName,
                    "liveTtsEngine" to currentPrefs.liveTtsEngine,
                    "liveTtsVoiceName" to currentPrefs.liveTtsVoiceName,
                    "liveTtsPitch" to currentPrefs.liveTtsPitch.toDouble(),
                    "liveTtsSpeechRate" to currentPrefs.liveTtsSpeechRate.toDouble(),
                    "startupSoundId" to currentPrefs.startupSoundId,
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
                    "totalSessions" to maxOf(allSessions.size.toLong(), remoteAccount.getLong("totalSessions") ?: 0L),
                    "totalMessages" to maxOf(allMessages.size.toLong(), remoteAccount.getLong("totalMessages") ?: 0L),
                    "totalTokens" to maxOf(localTotalTokens, remoteAccount.getLong("totalTokens") ?: 0L),
                    "totalEstimatedCostUsd" to maxOf(localTotalCost, remoteAccount.getDouble("totalEstimatedCostUsd") ?: 0.0),
                    "updatedAtMs" to uploadUpdatedMs,
                    "syncedAt" to FieldValue.serverTimestamp(),
                )
                accountRef.set(accountPayload, SetOptions.merge()).await()
                byteBudgetRemaining = (byteBudgetRemaining - 1536L).coerceAtLeast(0L)
            }

            // 3. Custom Personas
            val builtInPersonaIds = setOf("default", "celysia", "celeste", "coder", "researcher", "writer", "coach", "anime", "roaster")
            var deltaPersonas = 0
            val localPersonas = dao.getAllPersonasOnce().associateBy { it.id }
            val remotePersonasSnap = userDoc.collection("personas").get(Source.SERVER).await()
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
                        deltaPersonas++
                    }
                }
            }
            if (allowUpload) {
                for (lp in localPersonas.values) {
                    if (lp.id in builtInPersonaIds) continue
                    val docId = safeDocId(lp.id, "persona")
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || docId !in remotePersonaIds) {
                        val est = 220L + lp.systemPrompt.take(2000).length
                        if (byteBudgetRemaining < est + 32_000L) break
                        byteBudgetRemaining -= est
                        userDoc.collection("personas").document(docId).set(
                            mapOf(
                                "userId" to uid,
                                "name" to lp.name.trim().ifBlank { "Custom Persona" }.take(80),
                                "iconKey" to lp.iconKey.ifBlank { "sparkle" },
                                "tagline" to lp.tagline.take(200),
                                "systemPrompt" to lp.systemPrompt.take(2000),
                                "accentHex" to lp.accentHex.ifBlank { "#A855F7" },
                                "createdAtMs" to lp.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        deltaPersonas++
                    }
                }
            }

            // 4. Memories
            var deltaMemories = 0
            val localMemories = dao.getAllMemoriesOnce().associateBy { it.id }
            val remoteMemoriesSnap = userDoc.collection("memories").get(Source.SERVER).await()
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
                        deltaMemories++
                    }
                }
            }
            if (allowUpload) {
                for (lm in localMemories.values) {
                    val docId = safeDocId(lm.id, "mem")
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || docId !in remoteMemoryIds) {
                        val est = 180L + lm.content.take(2000).length
                        if (byteBudgetRemaining < est) break
                        byteBudgetRemaining -= est
                        userDoc.collection("memories").document(docId).set(
                            mapOf(
                                "userId" to uid,
                                "title" to lm.title.trim().ifBlank { "Memory" }.take(120),
                                "content" to lm.content.take(2000),
                                "enabled" to lm.enabled,
                                "createdAtMs" to lm.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        deltaMemories++
                    }
                }
            }

            // 5. Slash Prompt Templates
            var deltaTemplates = 0
            val localTemplates = dao.getAllPromptTemplatesOnce().associateBy { it.id }
            val remoteTemplatesSnap = userDoc.collection("templates").get(Source.SERVER).await()
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
                        deltaTemplates++
                    }
                }
            }
            if (allowUpload) {
                for (lt in localTemplates.values) {
                    val docId = safeDocId(lt.id, "tpl")
                    if (mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD || docId !in remoteTemplateIds) {
                        val est = 180L + lt.promptBody.take(2000).length
                        if (byteBudgetRemaining < est) break
                        byteBudgetRemaining -= est
                        userDoc.collection("templates").document(docId).set(
                            mapOf(
                                "userId" to uid,
                                "slashKey" to lt.slashKey.trim().ifBlank { "/custom" },
                                "title" to lt.title.trim().ifBlank { "Template" },
                                "promptBody" to lt.promptBody.take(2000),
                                "createdAtMs" to lt.createdAtMs,
                            ),
                            SetOptions.merge(),
                        ).await()
                        deltaTemplates++
                    }
                }
            }

            // 6. Sessions & Messages (Fair Two-Pass Sync using ACTUAL message rows, not stale messageCount!)
            val localSessionsById = allSessions.associateBy { it.id }
            val remoteSessionsSnap = userDoc.collection("sessions").get(Source.SERVER).await()
            val remoteSessionsById = remoteSessionsSnap.documents.associateBy { it.id }
            var downloaded = 0
            var uploaded = 0

            if (allowDownload) {
                for (doc in remoteSessionsSnap.documents) {
                    val sid = doc.id
                    val remoteUpdated = doc.getLong("updatedAtMs") ?: 0L
                    val local = localSessionsById[sid]
                    val remoteMsgs = userDoc.collection("sessions").document(sid).collection("messages").get(Source.SERVER).await()
                    val localMsgIds = dao.getMessagesForSessionOnce(sid).map { it.id }.toSet()
                    val hasMissingMsgs = remoteMsgs.documents.any { it.id !in localMsgIds }
                    if (mode == CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL || local == null || remoteUpdated > local.updatedAtMs || hasMissingMsgs) {
                        dao.upsertSession(
                            SessionEntity(
                                id = sid,
                                title = doc.getString("title").orEmpty().ifBlank { "Chat" },
                                personaId = doc.getString("personaId") ?: "default",
                                providerId = doc.getString("providerId") ?: "preset_pollinations_free",
                                modelName = doc.getString("modelName").orEmpty(),
                                pinned = doc.getBoolean("pinned") ?: false,
                                archived = doc.getBoolean("archived") ?: false,
                                isLocked = local?.isLocked ?: false,
                                isArena = doc.getBoolean("isArena") ?: false,
                                arenaProviderA = doc.getString("arenaProviderA") ?: local?.arenaProviderA ?: "preset_pollinations_free",
                                arenaModelA = doc.getString("arenaModelA") ?: local?.arenaModelA ?: "openai-fast",
                                arenaPersonaA = doc.getString("arenaPersonaA") ?: local?.arenaPersonaA ?: "default",
                                arenaProviderB = doc.getString("arenaProviderB") ?: local?.arenaProviderB ?: "preset_pollinations_free",
                                arenaModelB = doc.getString("arenaModelB") ?: local?.arenaModelB ?: "openai-fast",
                                arenaPersonaB = doc.getString("arenaPersonaB") ?: local?.arenaPersonaB ?: "celeste",
                                activeLeafId = doc.getString("activeLeafId").orEmpty(),
                                messageCount = maxOf((doc.getLong("messageCount") ?: 0L).toInt(), remoteMsgs.size()),
                                tokenCount = doc.getLong("tokenCount") ?: 0L,
                                lastMessagePreview = doc.getString("lastMessagePreview").orEmpty(),
                                createdAtMs = doc.getLong("createdAtMs") ?: System.currentTimeMillis(),
                                updatedAtMs = remoteUpdated.takeIf { it > 0L } ?: System.currentTimeMillis(),
                            )
                        )
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
                val candidateSessions = allSessions
                    .filter { !it.isLocked }
                    .sortedByDescending { it.updatedAtMs }
                    .take(50)

                val sessionsToSyncMessages = mutableListOf<Pair<String, List<MessageEntity>>>()

                for (ls in candidateSessions) {
                    val realMsgs = dao.getMessagesForSessionOnce(ls.id)
                    if (realMsgs.isEmpty()) continue
                    val sessDocId = safeDocId(ls.id, "chat")
                    val remoteDoc = remoteSessionsById[sessDocId]
                    val remoteUpdated = remoteDoc?.getLong("updatedAtMs") ?: -1L
                    val remoteMsgCount = (remoteDoc?.getLong("messageCount") ?: 0L).toInt()
                    val needsUpload = mode == CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD ||
                        remoteDoc == null ||
                        ls.updatedAtMs > remoteUpdated ||
                        realMsgs.size > remoteMsgCount
                    if (!needsUpload) continue
                    if (byteBudgetRemaining < 320L) break

                    val safeTitle = ls.title.trim().ifBlank { "Untitled Chat" }.take(140)
                    val sessRef = userDoc.collection("sessions").document(sessDocId)
                    sessRef.set(
                        mapOf(
                            "userId" to uid,
                            "title" to safeTitle,
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
                            "messageCount" to realMsgs.size,
                            "tokenCount" to ls.tokenCount,
                            "lastMessagePreview" to ls.lastMessagePreview.take(160),
                            "createdAtMs" to ls.createdAtMs,
                            "updatedAtMs" to maxOf(ls.updatedAtMs, System.currentTimeMillis()),
                        ),
                        SetOptions.merge(),
                    ).await()
                    byteBudgetRemaining -= 280L
                    uploaded++
                    sessionsToSyncMessages.add(sessDocId to realMsgs.takeLast(16).reversed())
                }

                // Pass 2: round-robin messages across all uploaded sessions until byte budget is spent
                var depth = 0
                var madeProgress = true
                while (madeProgress && byteBudgetRemaining >= 260L && depth < 16) {
                    madeProgress = false
                    for ((sessDocId, msgs) in sessionsToSyncMessages) {
                        if (depth >= msgs.size) continue
                        val m = msgs[depth]
                        val msgDocId = safeDocId(m.id, "msg")
                        val contentSnippet = m.content.take(1100)
                        val thoughtSnippet = m.thought.take(240)
                        val est = 220L + contentSnippet.length + thoughtSnippet.length
                        if (byteBudgetRemaining < est) continue
                        byteBudgetRemaining -= est
                        madeProgress = true
                        val sessRef = userDoc.collection("sessions").document(sessDocId)
                        sessRef.collection("messages").document(msgDocId).set(
                            mapOf(
                                "userId" to uid,
                                "sessionId" to sessDocId,
                                "parentId" to m.parentId,
                                "role" to m.role,
                                "speakerLabel" to m.speakerLabel,
                                "content" to contentSnippet,
                                "thought" to thoughtSnippet,
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
                    depth++
                }
            }

            // Compute REAL live cloud totals after sync so UI never misleadingly prints "0 everything"
            val storageSummary = inspectCloudStorage().getOrNull()
            val totalCloudBytes = storageSummary?.usedBytes ?: (USER_QUOTA_BYTES - byteBudgetRemaining).coerceIn(0L, USER_QUOTA_BYTES)
            val totalCloudChats = storageSummary?.items?.count { it.collection == "sessions" }
                ?: maxOf(remoteSessionsById.size, uploaded)
            val totalCloudProviders = storageSummary?.items?.count { it.collection == "providers" }
                ?: maxOf(remoteProvMap.size, deltaProviders)
            val totalCloudPersonas = storageSummary?.items?.count { it.collection == "personas" }
                ?: maxOf(remotePersonaIds.size, deltaPersonas)
            val totalCloudMemories = storageSummary?.items?.count { it.collection == "memories" }
                ?: maxOf(remoteMemoryIds.size, deltaMemories)

            val usedKb = "%.1f".format(totalCloudBytes / 1024.0)
            val maxKb = "%.1f".format(USER_QUOTA_BYTES / 1024.0)
            val summary = "Cloud Synced ($usedKb / $maxKb KB): $totalCloudChats chats (↑$uploaded ↓$downloaded) · $totalCloudProviders providers · $totalCloudPersonas personas · $totalCloudMemories memories"
            DevLogBuffer.add("INFO", "CloudSync", summary)
            SyncReport(
                uploadedSessions = uploaded,
                downloadedSessions = downloaded,
                syncedProviders = totalCloudProviders,
                syncedPersonas = totalCloudPersonas,
                syncedMemories = totalCloudMemories,
                syncedTemplates = deltaTemplates,
                usedBytes = totalCloudBytes,
                quotaBytes = USER_QUOTA_BYTES,
                message = summary,
            )
        }.onFailure { err ->
            val detail = err.localizedMessage ?: err.javaClass.simpleName
            DevLogBuffer.add("ERROR", "CloudSync", "Sync failed (db=${databaseId.ifBlank { "(default)" }}): $detail")
        }
    }
}

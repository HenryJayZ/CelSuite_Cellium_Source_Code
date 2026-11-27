package com.henny.cellium.ui.chat

import android.app.Application
import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Base64
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.security.MessageDigest
import com.google.firebase.Firebase
import com.google.firebase.auth.auth
import com.henny.cellium.ai.CuratedLocalModel
import com.henny.cellium.ai.KaggleImageEngine
import com.henny.cellium.ai.LocalModelStatus
import com.henny.cellium.ai.MultiImagineClient
import com.henny.cellium.ai.OnDeviceLlmEngine
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderCatalogEntry
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.ai.WebToolsClient
import com.henny.cellium.assistant.AndroidDeviceActions
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumNotificationManager
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.core.CelliumSttEngine
import com.henny.cellium.core.CelliumTtsEngine
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.PreferencesStore
import com.henny.cellium.core.RegisteredLocalModel
import com.henny.cellium.core.SecureKaggleStore
import com.henny.cellium.core.StarredModelEntry
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.data.CustomPersona
import com.henny.cellium.data.PersonaSpec
import com.henny.cellium.data.local.AppBackupManager
import com.henny.cellium.data.local.ArtworkEntity
import com.henny.cellium.data.local.CelliumDatabase
import com.henny.cellium.data.local.CustomPersonaEntity
import com.henny.cellium.data.local.MemoryEntity
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.PromptTemplateEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.data.local.SessionEntity
import com.henny.cellium.data.sync.CloudStorageSummary
import com.henny.cellium.data.sync.CloudSyncManager
import com.henny.cellium.data.sync.CloudSyncMode
import com.henny.cellium.shizuku.CommandAssessment
import com.henny.cellium.shizuku.CommandGuard
import com.henny.cellium.shizuku.CommandSafetyTier
import com.henny.cellium.shizuku.MemoryGuardService
import com.henny.cellium.shizuku.ShizukuBridge
import com.henny.cellium.shizuku.ShizukuStatus
import com.henny.cellium.ui.arena.ArenaController
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream
import java.util.UUID

data class PendingAgentGuard(
    val sessionId: String,
    val sourceMessageId: String,
    val assessment: CommandAssessment,
)

data class AttachedTextFile(
    val fileName: String,
    val content: String,
)

data class CelliumUiState(
    val providers: List<ProviderProfileEntity> = emptyList(),
    val activeProvider: ProviderProfileEntity? = null,
    val sessions: List<SessionEntity> = emptyList(),
    val activeSessionId: String? = null,
    val activeMessages: List<MessageEntity> = emptyList(),
    val branchInfoById: Map<String, BranchSlotInfo> = emptyMap(),
    val customPersonas: List<CustomPersonaEntity> = emptyList(),
    val memories: List<MemoryEntity> = emptyList(),
    val promptTemplates: List<PromptTemplateEntity> = emptyList(),
    val artworks: List<ArtworkEntity> = emptyList(),
    val totalMessageCount: Int = 0,
    val activePersonaId: String = "default",
    val isStreaming: Boolean = false,
    val streamingContent: String = "",
    val streamingThought: String = "",
    val streamingParentMessageId: String? = null,
    val retryStatusText: String = "",
    val currentMood: String = "idle",
    val pendingGuard: PendingAgentGuard? = null,
    val shizukuStatus: ShizukuStatus = ShizukuStatus.NOT_RUNNING,
    val shizukuAntiKill: Boolean = false,
    val shizukuReport: String = "Shizuku standby",
    val localModelStatus: LocalModelStatus = LocalModelStatus(),
    val installedLocalModels: List<File> = emptyList(),
    val registeredLocalModels: List<RegisteredLocalModel> = emptyList(),
    val isGeneratingImage: Boolean = false,
    val imagineStatusText: String = "",
    val isSyncingCloud: Boolean = false,
    val pendingSyncConflict: Boolean = false,
    val cloudStorageSummary: CloudStorageSummary? = null,
    val cloudStorageLoading: Boolean = false,
    val cloudStorageError: String? = null,
    val kaggleCacheStatusMap: Map<String, KaggleImageEngine.CacheEntry> = emptyMap(),
    val kaggleCacheBusyPreset: String? = null,
    val kaggleCacheStatusText: String = "",
    val kaggleTestResult: String? = null,
    val lastGeneratedImagePath: String? = null,
    val bannerMessage: String? = null,
    val errorMessage: String? = null,
    val settingsFeedbackMessage: String? = null,
    val settingsFeedbackIsError: Boolean = false,
) {
    val activeSession: SessionEntity?
        get() = sessions.firstOrNull { it.id == activeSessionId }

    val allPersonaSpecs: List<PersonaSpec>
        get() = if (customPersonas.isNotEmpty()) {
            customPersonas.map {
                PersonaSpec(
                    id = it.id,
                    name = it.name,
                    iconKey = it.iconKey.ifBlank { "sparkle" },
                    tagline = it.tagline,
                    systemPrompt = it.systemPrompt,
                    accentHex = it.accentHex.ifBlank { "#A855F7" },
                    custom = true,
                )
            }
        } else {
            BuiltInPersonas.ALL
        }

    val resolvedPersona: PersonaSpec
        get() = BuiltInPersonas.resolve(
            activePersonaId,
            customPersonas.map {
                CustomPersona(
                    id = it.id,
                    name = it.name,
                    emoji = it.iconKey,
                    tagline = it.tagline,
                    systemPrompt = it.systemPrompt,
                    accentHex = it.accentHex,
                )
            },
        )
}

@OptIn(ExperimentalCoroutinesApi::class)
class CelliumViewModel(application: Application) : AndroidViewModel(application) {
    private val appContext = application.applicationContext
    private val db = CelliumDatabase.getInstance(appContext)
    private val dao = db.dao()

    val prefsStore = PreferencesStore(appContext)
    val soundEngine = CelliumSoundEngine(appContext)
    val ttsEngine = CelliumTtsEngine(appContext, sharedSoundEngine = soundEngine)
    val sttEngine = CelliumSttEngine(appContext)
    val shizukuBridge = ShizukuBridge(appContext)
    val llmClient = UniversalLlmClient()
    val webTools = WebToolsClient()
    val onDeviceEngine = OnDeviceLlmEngine(appContext, shizukuBridge)
    val imagineClient = MultiImagineClient(appContext)
    val secureKaggleStore = SecureKaggleStore(appContext)
    val kaggleEngine = KaggleImageEngine(appContext, secureKaggleStore)
    val backupManager = AppBackupManager(dao)
    private val cloudSync = CloudSyncManager(appContext, dao, prefsStore)

    private val _preferencesLoaded = MutableStateFlow(false)
    val preferencesLoaded: StateFlow<Boolean> = _preferencesLoaded.asStateFlow()

    val preferences: StateFlow<CelliumPreferences> = prefsStore.preferencesFlow
        .onEach { _preferencesLoaded.value = true }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.Eagerly,
            initialValue = prefsStore.readCachedInitialPreferences(),
        )

    private val _processRamMb = MutableStateFlow(0)
    val processRamMb: StateFlow<Int> = _processRamMb.asStateFlow()

    private val _chatDraftText = MutableStateFlow("")
    val chatDraftText: StateFlow<String> = _chatDraftText.asStateFlow()

    fun updateChatDraftText(text: String) {
        if (_chatDraftText.value != text) {
            _chatDraftText.value = text
        }
    }

    private val _activeSessionId = MutableStateFlow<String?>(null)
    private val _selectedLeafBySession = MutableStateFlow<Map<String, String>>(emptyMap())
    private val _streamingParentId = MutableStateFlow<String?>(null)
    private val _uiState = MutableStateFlow(CelliumUiState())
    val uiState: StateFlow<CelliumUiState> = _uiState.asStateFlow()

    @Volatile private var appInForeground = true
    @Volatile private var currentVisibleTab = "chat"

    // Track active stream context so stopStreaming() can persist partial text cleanly
    @Volatile private var activeStreamSessionId: String? = null
    @Volatile private var activeStreamParentId: String? = null
    @Volatile private var activeStreamProviderName: String = ""
    @Volatile private var activeStreamModelName: String = ""
    @Volatile private var activeStreamSpeakerName: String = "Cel"

    val arenaController = ArenaController(
        scope = viewModelScope,
        dao = dao,
        prefsStore = prefsStore,
        preferencesProvider = { preferences.value },
        llmClient = llmClient,
        onDeviceEngine = onDeviceEngine,
        soundEngine = soundEngine,
        providersProvider = { _uiState.value.providers },
        customPersonasProvider = { _uiState.value.customPersonas },
        memoriesProvider = { _uiState.value.memories },
        maxAutoRetriesProvider = { preferences.value.maxAutoRetries },
        onArenaConfigChanged = { scheduleBackgroundCloudSync() },
        onNotifyIfBackground = { sid, title, speaker, text ->
            maybePostReplyNotification(sid, title, speaker, text, isArena = true)
        },
    )

    fun speakText(
        text: String,
        onStart: (() -> Unit)? = null,
        onComplete: (() -> Unit)? = null,
        onSynthCharProgress: ((Int) -> Unit)? = null,
    ) {
        val p = preferences.value
        ttsEngine.speak(
            rawText = text,
            engine = p.ttsEngine,
            voiceName = p.ttsVoiceName,
            pitch = p.ttsPitch,
            speechRate = p.ttsSpeechRate,
            onStart = onStart,
            onComplete = onComplete,
            onSynthCharProgress = onSynthCharProgress,
        )
    }

    fun speakLiveText(
        text: String,
        onStart: (() -> Unit)? = null,
        onComplete: (() -> Unit)? = null,
        onSynthCharProgress: ((Int) -> Unit)? = null,
    ) {
        val p = preferences.value
        ttsEngine.speak(
            rawText = text,
            engine = p.liveTtsEngine,
            voiceName = p.liveTtsVoiceName,
            pitch = p.liveTtsPitch,
            speechRate = p.liveTtsSpeechRate,
            onStart = onStart,
            onComplete = onComplete,
            onSynthCharProgress = onSynthCharProgress,
        )
    }

    fun speakPreviewWithVoice(
        engine: String,
        voiceId: String,
        pitch: Float,
        rate: Float,
        text: String,
    ) {
        ttsEngine.speak(
            rawText = text,
            engine = engine,
            voiceName = voiceId,
            pitch = pitch,
            speechRate = rate,
            onFallback = { notice ->
                showSettingsFeedback(notice, isError = true)
            },
        )
    }

    fun notifyPrefsChangedForSync() {
        scheduleBackgroundCloudSync()
    }

    fun resolveSttApiKey(engineId: String = preferences.value.sttEngine): String {
        val explicit = preferences.value.sttApiKey.trim()
        if (explicit.isNotBlank()) return explicit
        val providers = _uiState.value.providers
        return when (engineId) {
            CelliumSttEngine.ENGINE_GROQ ->
                providers.firstOrNull { it.id == ProviderPresets.ID_GROQ || it.name.contains("groq", ignoreCase = true) }?.apiKey.orEmpty()
            CelliumSttEngine.ENGINE_OPENAI ->
                providers.firstOrNull { it.id == ProviderPresets.ID_OPENAI || it.name.equals("OpenAI", ignoreCase = true) }?.apiKey.orEmpty()
            CelliumSttEngine.ENGINE_HUGGINGFACE ->
                providers.firstOrNull { it.id == ProviderPresets.ID_HUGGINGFACE || it.name.contains("hugging", ignoreCase = true) }?.apiKey.orEmpty()
            else -> ""
        }
    }

    suspend fun discoverSttModels(
        engineId: String,
        explicitKeyOverride: String = "",
        forceRefresh: Boolean = true,
    ): Result<List<String>> {
        val key = explicitKeyOverride.trim().ifBlank { resolveSttApiKey(engineId) }
        return sttEngine.fetchAvailableSttModels(engineId, key, forceRefresh)
    }

    fun persistAutoSelectedSttModel(engineId: String, model: String) {
        val trimmed = model.trim()
        if (trimmed.isBlank()) return
        val cur = preferences.value
        if (cur.sttEngine == engineId && cur.sttModel == trimmed) return
        viewModelScope.launch {
            prefsStore.updateSttSettings(
                engine = engineId,
                apiKey = cur.sttApiKey,
                model = trimmed,
            )
            notifyPrefsChangedForSync()
        }
    }

    private var streamJob: Job? = null
    private var liveStreamJob: Job? = null
    private var autoSyncJob: Job? = null
    private var autoGuardTriggeredForPeak = false

    init {
        shizukuBridge.registerListeners()
        seedDefaultsIfNeeded()
        observeCoreFlows()
        observeDirectReplies()
        startRamWatchdog()
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { com.henny.cellium.avatar.AvatarLibrary.load(appContext) }
        }
    }

    fun setAppInForeground(foreground: Boolean) {
        appInForeground = foreground
        if (foreground) {
            _activeSessionId.value?.let { CelliumNotificationManager.clearSessionNotification(appContext, it) }
        }
    }

    fun setCurrentVisibleTab(tabKey: String) {
        currentVisibleTab = tabKey
        if (tabKey == "chat") {
            _activeSessionId.value?.let { CelliumNotificationManager.clearSessionNotification(appContext, it) }
        }
    }

    private fun maybePostReplyNotification(
        sessionId: String,
        title: String,
        sender: String,
        text: String,
        isArena: Boolean = false,
    ) {
        if (!preferences.value.notificationsEnabled) return
        val viewingThisChat = appInForeground && (
            (!isArena && currentVisibleTab == "chat" && _activeSessionId.value == sessionId) ||
                (isArena && currentVisibleTab == "arena")
            )
        if (!viewingThisChat) {
            CelliumNotificationManager.notifyAssistantReply(
                context = appContext,
                sessionId = sessionId,
                sessionTitle = title,
                senderName = sender,
                messageText = text,
            )
        }
    }

    private fun observeDirectReplies() {
        viewModelScope.launch {
            CelliumNotificationManager.directReplies.collect { event ->
                val all = dao.getMessagesForSessionOnce(event.sessionId)
                val lastId = all.lastOrNull()?.id
                sendMessageInternal(
                    prompt = event.replyText,
                    attachmentBitmaps = emptyList(),
                    attachedFile = null,
                    explicitParentId = lastId,
                    sessionIdOverride = event.sessionId,
                )
            }
        }
    }

    private fun seedDefaultsIfNeeded() {
        viewModelScope.launch(Dispatchers.IO) {
            dao.insertProvidersIfMissing(ProviderPresets.defaultProfiles())
            // Migrate legacy Pollinations URL / stale model name if needed
            val polli = dao.getProvider(ProviderPresets.ID_POLLINATIONS_FREE)
            if (polli != null) {
                val needsUrl = polli.baseUrl.trimEnd('/') == "https://text.pollinations.ai"
                val needsModel = polli.selectedModel.isBlank() || polli.selectedModel == "openai" || polli.selectedModel == "mistral"
                if (needsUrl || needsModel) {
                    dao.upsertProvider(
                        polli.copy(
                            baseUrl = "https://text.pollinations.ai/openai",
                            selectedModel = if (needsModel) "openai-fast" else polli.selectedModel,
                        )
                    )
                }
            }
            // Always ensure built-in /compact and default templates exist
            dao.insertPromptTemplatesIfMissing(ProviderPresets.defaultPromptTemplates())

            // Seed built-in personas into Room once so ALL personas are editable & deletable
            val existingPersonas = dao.getAllPersonasOnce()
            if (!preferences.value.personasSeeded && existingPersonas.isEmpty()) {
                val seeded = BuiltInPersonas.ALL.mapIndexed { idx, p ->
                    CustomPersonaEntity(
                        id = p.id,
                        name = p.name,
                        iconKey = p.iconKey,
                        tagline = p.tagline,
                        systemPrompt = p.systemPrompt,
                        accentHex = p.accentHex,
                        createdAtMs = 1_700_000_000_000L + idx * 1000L,
                    )
                }
                dao.insertPersonasIfMissing(seeded)
                prefsStore.markPersonasSeeded()
            } else if (!preferences.value.personasSeeded && existingPersonas.isNotEmpty()) {
                // User upgraded from older version with custom personas: insert built-ins if missing
                val seeded = BuiltInPersonas.ALL.mapIndexed { idx, p ->
                    CustomPersonaEntity(
                        id = p.id,
                        name = p.name,
                        iconKey = p.iconKey,
                        tagline = p.tagline,
                        systemPrompt = p.systemPrompt,
                        accentHex = p.accentHex,
                        createdAtMs = 1_700_000_000_000L + idx * 1000L,
                    )
                }
                dao.insertPersonasIfMissing(seeded)
                prefsStore.markPersonasSeeded()
            }
            refreshLocalModelsList()
        }
    }

    private fun observeCoreFlows() {
        viewModelScope.launch {
            var lastRegisteredModelsJson: String? = null
            var lastActiveProviderId: String? = null
            var lastKaggleCacheJson: String? = null
            preferences.collectLatest { p ->
                soundEngine.enabled = p.soundsEnabled
                soundEngine.animaleseEnabled = p.animaleseEnabled
                soundEngine.hapticsEnabled = p.hapticsEnabled
                soundEngine.masterVolume = p.sfxVolume
                soundEngine.typingSoundStyle = p.typingSoundStyle
                soundEngine.typingSoundPitch = p.typingSoundPitch
                soundEngine.startupSoundId = p.startupSoundId
                soundEngine.startupSoundCustomPath = p.startupSoundCustomPath
                soundEngine.startupSoundShuffleEnabled = p.startupSoundShuffleEnabled
                soundEngine.startupSoundExcludedIds = p.startupSoundExcludedIds
                soundEngine.deletedStartupSoundIds = p.deletedStartupSoundIds

                if (p.kaggleCacheMapJson != lastKaggleCacheJson) {
                    lastKaggleCacheJson = p.kaggleCacheMapJson
                    val parsedCache = kaggleEngine.parseCacheMap(p.kaggleCacheMapJson)
                    if (parsedCache.isNotEmpty() || _uiState.value.kaggleCacheStatusMap.isEmpty()) {
                        _uiState.value = _uiState.value.copy(kaggleCacheStatusMap = parsedCache)
                    }
                }

                if (p.activeProviderId != lastActiveProviderId) {
                    lastActiveProviderId = p.activeProviderId
                    val currentProviders = _uiState.value.providers
                    val activeProv = currentProviders.firstOrNull { it.id == p.activeProviderId }
                        ?: currentProviders.firstOrNull()
                    if (activeProv != _uiState.value.activeProvider) {
                        _uiState.value = _uiState.value.copy(activeProvider = activeProv)
                    }
                }
                if (p.registeredLocalModelsJson != lastRegisteredModelsJson) {
                    lastRegisteredModelsJson = p.registeredLocalModelsJson
                    refreshLocalModelsList(p.registeredLocalModelsJson)
                }
            }
        }

        viewModelScope.launch {
            dao.observeProviders().collectLatest { providers ->
                val activeId = preferences.value.activeProviderId
                val active = providers.firstOrNull { it.id == activeId }
                    ?: providers.firstOrNull { it.id == ProviderPresets.ID_POLLINATIONS_FREE }
                    ?: providers.firstOrNull()
                _uiState.value = _uiState.value.copy(providers = providers, activeProvider = active)
            }
        }

        viewModelScope.launch {
            dao.observeSessions().collectLatest { sessions ->
                val regular = sessions.filter { !it.isArena }
                val currentId = _activeSessionId.value
                val nextId = if (currentId != null && sessions.any { it.id == currentId }) {
                    currentId
                } else {
                    regular.firstOrNull { !it.archived && !it.isLocked }?.id
                        ?: regular.firstOrNull { !it.isLocked }?.id
                }
                if (nextId != currentId) _activeSessionId.value = nextId
                val activeSess = sessions.firstOrNull { it.id == nextId }
                _uiState.value = _uiState.value.copy(
                    sessions = sessions,
                    activeSessionId = nextId,
                    activePersonaId = activeSess?.personaId ?: preferences.value.defaultPersonaId,
                )
            }
        }

        viewModelScope.launch {
            combine(
                _activeSessionId.flatMapLatest { sid ->
                    if (sid.isNullOrBlank()) flowOf(emptyList()) else dao.observeMessagesForSession(sid)
                },
                _activeSessionId,
                _selectedLeafBySession,
                _streamingParentId,
            ) { allMsgs, sid, leafMap, streamParent ->
                if (!streamParent.isNullOrBlank() && allMsgs.any { it.id == streamParent }) {
                    // While regenerating/streaming under streamParent, show strict ancestor chain up to streamParent
                    // so the old assistant bubble vanishes IMMEDIATELY without waiting for the new reply!
                    val truncated = ChatTreeHelper.buildAncestorPath(allMsgs, streamParent)
                    val childrenByParent = allMsgs.groupBy { it.parentId }
                    val branchInfo = mutableMapOf<String, BranchSlotInfo>()
                    for (msg in truncated) {
                        val siblings = childrenByParent[msg.parentId]?.sortedBy { it.createdAtMs }?.map { it.id }
                            ?: listOf(msg.id)
                        if (siblings.size > 1) {
                            branchInfo[msg.id] = BranchSlotInfo(siblings, siblings.indexOf(msg.id).coerceAtLeast(0))
                        }
                    }
                    ActiveBranchView(truncated, branchInfo, streamParent)
                } else {
                    val sessionLeaf = sid?.let {
                        leafMap[it] ?: _uiState.value.sessions.firstOrNull { s -> s.id == it }?.activeLeafId
                    }
                    ChatTreeHelper.buildActivePath(allMsgs, sessionLeaf)
                }
            }.collectLatest { branchView ->
                _uiState.value = _uiState.value.copy(
                    activeMessages = branchView.messages,
                    branchInfoById = branchView.branchInfoById,
                )
            }
        }

        viewModelScope.launch { dao.observePersonas().collectLatest { _uiState.value = _uiState.value.copy(customPersonas = it) } }
        viewModelScope.launch { dao.observeMemories().collectLatest { _uiState.value = _uiState.value.copy(memories = it) } }
        viewModelScope.launch { dao.observePromptTemplates().collectLatest { _uiState.value = _uiState.value.copy(promptTemplates = it) } }
        viewModelScope.launch { dao.observeArtworks().collectLatest { _uiState.value = _uiState.value.copy(artworks = it) } }
        viewModelScope.launch { dao.observeTotalMessageCount().collectLatest { _uiState.value = _uiState.value.copy(totalMessageCount = it) } }

        viewModelScope.launch {
            combine(
                shizukuBridge.status,
                shizukuBridge.antiKillApplied,
                shizukuBridge.lastReport,
                onDeviceEngine.status,
            ) { st, antiKill, report, localSt ->
                Quad(st, antiKill, report, localSt)
            }.collectLatest { (st, antiKill, report, localSt) ->
                _uiState.value = _uiState.value.copy(
                    shizukuStatus = st,
                    shizukuAntiKill = antiKill,
                    shizukuReport = report,
                    localModelStatus = localSt,
                )
            }
        }
    }

    private data class Quad<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)

    private fun startRamWatchdog() {
        viewModelScope.launch(Dispatchers.IO) {
            while (true) {
                val ramMb = MemoryGuardService.currentProcessRamMb()
                _processRamMb.value = ramMb
                val prefs = preferences.value
                if (prefs.shizukuAutoGuard && ramMb >= prefs.ramGuardThresholdMb && !autoGuardTriggeredForPeak) {
                    autoGuardTriggeredForPeak = true
                    MemoryGuardService.start(appContext, "RAM ${ramMb}MB >= ${prefs.ramGuardThresholdMb}MB — Anti-Kill Active")
                    shizukuBridge.applyAntiKillProtection(reason = "RAM ${ramMb}MB threshold")
                } else if (ramMb < (prefs.ramGuardThresholdMb * 0.75).toInt()) {
                    autoGuardTriggeredForPeak = false
                }
                delay(5000L)
            }
        }
    }

    // ── Session, Archive, Search & Branching ─────────────────────────────

    fun selectSession(sessionId: String) {
        soundEngine.playClick()
        _activeSessionId.value = sessionId
        CelliumNotificationManager.clearSessionNotification(appContext, sessionId)
        val sess = _uiState.value.sessions.firstOrNull { it.id == sessionId }
        _uiState.value = _uiState.value.copy(
            activeSessionId = sessionId,
            activePersonaId = sess?.personaId ?: preferences.value.defaultPersonaId,
            pendingGuard = null,
            errorMessage = null,
        )
    }

    /** Opens an exact session handed off from Assistant Pop-up or Floating Cel. */
    fun openSessionFromExternal(sessionId: String) {
        val cleanId = sessionId.trim()
        if (cleanId.isBlank()) return
        viewModelScope.launch {
            val sess = dao.getSession(cleanId)
            _activeSessionId.value = cleanId
            CelliumNotificationManager.clearSessionNotification(appContext, cleanId)
            if (sess != null && sess.activeLeafId.isNotBlank()) {
                _selectedLeafBySession.value = _selectedLeafBySession.value + (cleanId to sess.activeLeafId)
            }
            _uiState.value = _uiState.value.copy(
                activeSessionId = cleanId,
                activePersonaId = sess?.personaId ?: preferences.value.defaultPersonaId,
                pendingGuard = null,
                errorMessage = null,
            )
        }
    }

    fun startNewSession(title: String = "New Chat") {
        soundEngine.playOpen()
        viewModelScope.launch {
            val prov = _uiState.value.activeProvider
            val id = UUID.randomUUID().toString()
            val entity = SessionEntity(
                id = id,
                title = title,
                personaId = preferences.value.defaultPersonaId,
                providerId = prov?.id ?: ProviderPresets.ID_POLLINATIONS_FREE,
                modelName = prov?.selectedModel.orEmpty(),
            )
            dao.upsertSession(entity)
            _activeSessionId.value = id
            _uiState.value = _uiState.value.copy(
                activeSessionId = id,
                activePersonaId = entity.personaId,
                currentMood = "idle",
                pendingGuard = null,
                errorMessage = null,
            )
        }
    }

    fun renameSession(sessionId: String, newTitle: String) {
        viewModelScope.launch {
            val existing = dao.getSession(sessionId) ?: return@launch
            dao.upsertSession(existing.copy(title = newTitle.trim().ifBlank { "Untitled" }.take(120), updatedAtMs = System.currentTimeMillis()))
        }
    }

    fun togglePinSession(session: SessionEntity) {
        soundEngine.playClick()
        viewModelScope.launch { dao.upsertSession(session.copy(pinned = !session.pinned)) }
    }

    fun toggleArchiveSession(session: SessionEntity) {
        soundEngine.playClick()
        viewModelScope.launch { dao.upsertSession(session.copy(archived = !session.archived)) }
    }

    // ── Locked Chats Vault (Variable-Length PIN, Zero Length Leak) ──────

    private fun hashVaultPin(digits: String): String {
        val salted = "cel_cellium_vault_pin_v1:$digits"
        val digest = MessageDigest.getInstance("SHA-256").digest(salted.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun setVaultPin(digits: String) {
        val clean = digits.filter { it.isDigit() }
        if (clean.isEmpty()) return
        soundEngine.playPop()
        viewModelScope.launch {
            prefsStore.updateVaultPinHash(hashVaultPin(clean))
            showBanner("Vault PIN updated.")
        }
    }

    fun verifyVaultPin(digits: String): Boolean {
        val stored = preferences.value.vaultPinHash
        if (stored.isBlank() || digits.isBlank()) return false
        return hashVaultPin(digits) == stored
    }

    fun toggleLockSession(session: SessionEntity) {
        soundEngine.playClick()
        val nextLocked = !session.isLocked
        viewModelScope.launch {
            dao.upsertSession(session.copy(isLocked = nextLocked, updatedAtMs = System.currentTimeMillis()))
            if (nextLocked && _activeSessionId.value == session.id) {
                val fallback = _uiState.value.sessions.firstOrNull {
                    it.id != session.id && !it.isArena && !it.isLocked && !it.archived
                } ?: _uiState.value.sessions.firstOrNull {
                    it.id != session.id && !it.isArena && !it.isLocked
                }
                _activeSessionId.value = fallback?.id
            }
            showBanner(if (nextLocked) "Chat moved to Locked Vault." else "Chat unlocked.")
        }
    }

    fun wipeLockedChatsAndResetPin() {
        soundEngine.playClick()
        viewModelScope.launch {
            val activeLocked = _uiState.value.activeSession?.isLocked == true
            dao.deleteMessagesForLockedSessions()
            dao.deleteLockedSessions()
            prefsStore.updateVaultPinHash("")
            if (activeLocked) {
                val fallback = _uiState.value.sessions.firstOrNull { !it.isArena && !it.isLocked && !it.archived }
                _activeSessionId.value = fallback?.id
            }
            showBanner("All locked chats erased and Vault PIN reset.")
        }
    }

    suspend fun searchSessionIdsByContent(query: String): Set<String> = withContext(Dispatchers.IO) {
        val q = query.trim()
        if (q.isEmpty()) emptySet() else dao.searchSessionIdsByMessageContent(q).toSet()
    }

    fun deleteSession(sessionId: String) {
        soundEngine.playClick()
        viewModelScope.launch {
            dao.deleteMessagesForSession(sessionId)
            dao.deleteSession(sessionId)
            if (_activeSessionId.value == sessionId) {
                _activeSessionId.value = _uiState.value.sessions.firstOrNull {
                    it.id != sessionId && !it.isArena && !it.isLocked
                }?.id
            }
        }
    }

    fun selectPersona(personaId: String) {
        soundEngine.playPop()
        _uiState.value = _uiState.value.copy(activePersonaId = personaId)
        viewModelScope.launch {
            prefsStore.updateDefaultPersona(personaId)
            val sid = _activeSessionId.value ?: return@launch
            val existing = dao.getSession(sid) ?: return@launch
            dao.upsertSession(existing.copy(personaId = personaId, updatedAtMs = System.currentTimeMillis()))
        }
    }

    fun selectProvider(providerId: String, modelOverride: String? = null) {
        soundEngine.playClick()
        viewModelScope.launch {
            var prov = dao.getProvider(providerId)
            if (prov == null) {
                val catEntry = ProviderCatalog.byId(providerId) ?: return@launch
                prov = catEntry.toEntity()
                dao.upsertProvider(prov)
            }
            val updatedProv = if (!modelOverride.isNullOrBlank()) {
                prov.copy(selectedModel = modelOverride.trim(), updatedAtMs = System.currentTimeMillis()).also {
                    dao.upsertProvider(it)
                }
            } else prov
            prefsStore.updateActiveProviderId(updatedProv.id)
            val sid = _activeSessionId.value ?: return@launch
            val existing = dao.getSession(sid) ?: return@launch
            dao.upsertSession(
                existing.copy(
                    providerId = updatedProv.id,
                    modelName = updatedProv.selectedModel,
                    updatedAtMs = System.currentTimeMillis(),
                )
            )
        }
    }

    fun activateCatalogProvider(entry: ProviderCatalogEntry) {
        soundEngine.playPop()
        viewModelScope.launch {
            val existing = dao.getProvider(entry.id)
            if (existing == null) {
                dao.upsertProvider(entry.toEntity())
            }
            selectProvider(entry.id)
            showBanner("Switched to ${entry.name}")
        }
    }

    fun ensureCatalogProviderSaved(entry: ProviderCatalogEntry) {
        soundEngine.playClick()
        viewModelScope.launch {
            val existing = dao.getProvider(entry.id)
            if (existing == null) {
                dao.upsertProvider(entry.toEntity())
            }
        }
    }

    fun toggleHideProvider(providerId: String) {
        soundEngine.playClick()
        viewModelScope.launch {
            val current = preferences.value.hiddenProviderIds
            val updated = if (providerId in current) current - providerId else current + providerId
            prefsStore.updateHiddenProviderIds(updated)
            scheduleBackgroundCloudSync()
        }
    }

    fun toggleStarModel(providerId: String, providerName: String, modelName: String) {
        if (modelName.isBlank()) return
        soundEngine.playPop()
        viewModelScope.launch {
            val current = prefsStore.decodeStarredModels(preferences.value.starredModelsJson).toMutableList()
            val existingIdx = current.indexOfFirst { it.providerId == providerId && it.modelName == modelName }
            if (existingIdx >= 0) {
                current.removeAt(existingIdx)
            } else {
                current.add(0, StarredModelEntry(providerId, providerName, modelName))
            }
            prefsStore.updateStarredModelsJson(prefsStore.encodeStarredModels(current))
            scheduleBackgroundCloudSync()
        }
    }

    fun switchBranch(targetMessageId: String) {
        val sid = _activeSessionId.value ?: return
        soundEngine.playClick()
        _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to targetMessageId)
        viewModelScope.launch {
            val s = dao.getSession(sid) ?: return@launch
            dao.upsertSession(s.copy(activeLeafId = targetMessageId))
        }
    }

    fun deleteMessage(message: MessageEntity) {
        soundEngine.playClick()
        viewModelScope.launch {
            dao.deleteMessage(message.id)
            val sid = message.sessionId
            if (message.parentId != null) {
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to message.parentId)
            }
            refreshSessionStats(sid)
        }
    }

    fun forkSessionFromMessage(message: MessageEntity) {
        soundEngine.playPop()
        viewModelScope.launch {
            val path = _uiState.value.activeMessages
            val cutIdx = path.indexOfFirst { it.id == message.id }
            if (cutIdx < 0) return@launch
            val slice = path.subList(0, cutIdx + 1)
            val origSession = dao.getSession(message.sessionId)
            val newSessionId = UUID.randomUUID().toString()
            var prevNewId: String? = null
            slice.forEach { old ->
                val newId = UUID.randomUUID().toString()
                dao.upsertMessage(old.copy(id = newId, sessionId = newSessionId, parentId = prevNewId))
                prevNewId = newId
            }
            dao.upsertSession(
                SessionEntity(
                    id = newSessionId,
                    title = "${origSession?.title ?: "Chat"} (Branch)",
                    personaId = origSession?.personaId ?: _uiState.value.activePersonaId,
                    providerId = origSession?.providerId ?: preferences.value.activeProviderId,
                    modelName = origSession?.modelName.orEmpty(),
                    activeLeafId = prevNewId.orEmpty(),
                    messageCount = slice.size,
                    tokenCount = slice.sumOf { it.tokenEstimate },
                    lastMessagePreview = slice.lastOrNull()?.content?.take(140).orEmpty(),
                )
            )
            _activeSessionId.value = newSessionId
            showBanner("Branched into new chat session.")
        }
    }

    /**
     * Edit ANY message (User OR Cel Assistant) in-place without creating a new branch.
     * Uses strict buildAncestorPath so the edited user prompt is NEVER double-sent.
     */
    fun editMessageInPlace(original: MessageEntity, editedText: String, regenerateIfUser: Boolean = false) {
        val clean = editedText.trim()
        if (clean.isEmpty()) return
        soundEngine.playClick()
        val shouldRegenerate = original.role == "user" && regenerateIfUser && !_uiState.value.isStreaming
        if (shouldRegenerate) {
            _streamingParentId.value = original.id
        }
        viewModelScope.launch {
            dao.upsertMessage(
                original.copy(
                    content = clean,
                    tokenEstimate = ProviderPresets.estimateTokens(clean),
                    isError = false,
                )
            )
            refreshSessionStats(original.sessionId)
            if (shouldRegenerate) {
                val all = dao.getMessagesForSessionOnce(original.sessionId)
                val historyBefore = ChatTreeHelper.buildAncestorPath(all, original.parentId)
                val file = if (original.attachmentFileName.isNotBlank()) {
                    AttachedTextFile(original.attachmentFileName, original.attachmentFileContent)
                } else null
                val reloadedBitmaps = withContext(Dispatchers.IO) {
                    loadBitmapsFromAttachmentPaths(original.attachmentPath)
                }
                runAssistantGeneration(
                    sessionId = original.sessionId,
                    parentMessageId = original.id,
                    historyBeforePrompt = historyBefore,
                    promptText = clean,
                    attachmentBitmaps = reloadedBitmaps,
                    attachedFile = file,
                )
            }
        }
    }

    fun editMessageAsBranch(original: MessageEntity, editedText: String, regenerateIfUser: Boolean = true) {
        val clean = editedText.trim()
        if (clean.isEmpty()) return
        soundEngine.playPop()
        if (original.role == "user") {
            if (regenerateIfUser && !_uiState.value.isStreaming) {
                sendMessageInternal(
                    prompt = clean,
                    attachmentBitmaps = emptyList(),
                    attachedFile = null,
                    explicitParentId = original.parentId,
                    sessionIdOverride = original.sessionId,
                )
            } else {
                viewModelScope.launch {
                    val newId = UUID.randomUUID().toString()
                    dao.upsertMessage(
                        original.copy(
                            id = newId,
                            content = clean,
                            tokenEstimate = ProviderPresets.estimateTokens(clean),
                            createdAtMs = System.currentTimeMillis(),
                        )
                    )
                    _selectedLeafBySession.value = _selectedLeafBySession.value + (original.sessionId to newId)
                    refreshSessionStats(original.sessionId)
                }
            }
        } else {
            viewModelScope.launch {
                val newId = UUID.randomUUID().toString()
                dao.upsertMessage(
                    original.copy(
                        id = newId,
                        content = clean,
                        tokenEstimate = ProviderPresets.estimateTokens(clean),
                        isError = false,
                        createdAtMs = System.currentTimeMillis(),
                    )
                )
                _selectedLeafBySession.value = _selectedLeafBySession.value + (original.sessionId to newId)
                refreshSessionStats(original.sessionId)
                showBanner("Created new response branch.")
            }
        }
    }

    fun regenerateAssistantMessage(assistantMsg: MessageEntity) {
        if (_uiState.value.isStreaming) return
        soundEngine.playClick()
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(errorMessage = null)
            // If retrying a failed error bubble, delete the error bubble FIRST so it NEVER creates a 1/2 branch!
            if (assistantMsg.isError) {
                dao.deleteMessage(assistantMsg.id)
            }
            val all = dao.getMessagesForSessionOnce(assistantMsg.sessionId)
            val parentUser = all.firstOrNull { it.id == assistantMsg.parentId } ?: return@launch
            val branchBeforeUser = ChatTreeHelper.buildAncestorPath(all, parentUser.parentId)
            val file = if (parentUser.attachmentFileName.isNotBlank()) {
                AttachedTextFile(parentUser.attachmentFileName, parentUser.attachmentFileContent)
            } else null
            val reloadedBitmaps = withContext(Dispatchers.IO) {
                loadBitmapsFromAttachmentPaths(parentUser.attachmentPath)
            }
            runAssistantGeneration(
                sessionId = assistantMsg.sessionId,
                parentMessageId = parentUser.id,
                historyBeforePrompt = branchBeforeUser,
                promptText = parentUser.content,
                attachmentBitmaps = reloadedBitmaps,
                attachedFile = file,
            )
        }
    }

    fun retryLastUserTurn() {
        val lastUser = _uiState.value.activeMessages.lastOrNull { it.role == "user" } ?: return
        if (_uiState.value.isStreaming) return
        soundEngine.playClick()
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(errorMessage = null)
            // Delete any failed error reply right under lastUser so retrying an error NEVER branches!
            val existingMsgs = dao.getMessagesForSessionOnce(lastUser.sessionId)
            existingMsgs.filter { it.parentId == lastUser.id && it.isError }.forEach { errChild ->
                dao.deleteMessage(errChild.id)
            }
            val all = dao.getMessagesForSessionOnce(lastUser.sessionId)
            val before = ChatTreeHelper.buildAncestorPath(all, lastUser.parentId)
            val file = if (lastUser.attachmentFileName.isNotBlank()) {
                AttachedTextFile(lastUser.attachmentFileName, lastUser.attachmentFileContent)
            } else null
            val reloadedBitmaps = withContext(Dispatchers.IO) {
                loadBitmapsFromAttachmentPaths(lastUser.attachmentPath)
            }
            runAssistantGeneration(
                sessionId = lastUser.sessionId,
                parentMessageId = lastUser.id,
                historyBeforePrompt = before,
                promptText = lastUser.content,
                attachmentBitmaps = reloadedBitmaps,
                attachedFile = file,
            )
        }
    }

    // ── Chat Sending, Slash Commands, /compact, /illume, Web Tools & Streaming ──

    fun sendMessage(
        prompt: String,
        attachmentBitmap: Bitmap? = null,
        attachedFile: AttachedTextFile? = null,
    ) {
        sendMessage(
            prompt = prompt,
            attachmentBitmaps = if (attachmentBitmap != null) listOf(attachmentBitmap) else emptyList(),
            attachedFile = attachedFile,
        )
    }

    fun sendMessage(
        prompt: String,
        attachmentBitmaps: List<Bitmap>,
        attachedFile: AttachedTextFile? = null,
    ) {
        val trimmed = prompt.trim()
        if ((trimmed.isEmpty() && attachmentBitmaps.isEmpty() && attachedFile == null) || _uiState.value.isStreaming) return

        // /clear
        if (trimmed.equals("/clear", ignoreCase = true)) {
            startNewSession()
            return
        }

        // /compact — summarizes conversation history and sets a fresh compact boundary
        if (trimmed.equals("/compact", ignoreCase = true) || trimmed.startsWith("/compact ", ignoreCase = true)) {
            val extraFocus = trimmed.removePrefix("/compact").trim()
            runCompactCommand(extraFocus)
            return
        }

        // /web <query>
        if (trimmed.startsWith("/web ", ignoreCase = true)) {
            val query = trimmed.removePrefix("/web ").trim()
            if (query.isNotEmpty()) {
                runWebSearchInChat(query)
                return
            }
        }

        // /url <link>
        if (trimmed.startsWith("/url ", ignoreCase = true)) {
            val raw = trimmed.removePrefix("/url ").trim()
            if (raw.isNotEmpty()) {
                runUrlReaderInChat(raw)
                return
            }
        }

        // /illume <prompt> OR /imagine <prompt>
        if (trimmed.startsWith("/illume ", ignoreCase = true) || trimmed.startsWith("/imagine ", ignoreCase = true)) {
            val rawImgPrompt = trimmed
                .removePrefix("/illume ").removePrefix("/ILLUME ")
                .removePrefix("/imagine ").removePrefix("/IMAGINE ")
                .trim()
            if (rawImgPrompt.isNotEmpty()) {
                viewModelScope.launch {
                    val prefs = preferences.value
                    val useKaggle = prefs.imagineProvider == "kaggle" ||
                        (trimmed.startsWith("/imagine ", ignoreCase = true) && kaggleEngine.isConfigured(prefs))
                    if (useKaggle) {
                        val batchRes = generateKaggleBatch(
                            prompt = rawImgPrompt,
                            stickyPrompt = prefs.kaggleStickyPrompt,
                            negativePrompt = prefs.kaggleNegativePrompt,
                            presetLabel = prefs.kagglePreset,
                            sizeLabel = prefs.kaggleSize,
                            steps = prefs.kaggleSteps,
                            guidance = prefs.kaggleGuidance,
                            batch = 1,
                            seed = prefs.kaggleSeed,
                        )
                        batchRes.onSuccess { arts ->
                            arts.firstOrNull()?.let { sendArtworkToChat(it) }
                        }.onFailure { err ->
                            _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                        }
                    } else {
                        val res = generateArtwork(rawImgPrompt)
                        res.onSuccess { art -> sendArtworkToChat(art) }
                            .onFailure { err -> _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage) }
                    }
                }
                return
            }
        }

        // /agent <command>
        if (trimmed.startsWith("/agent ", ignoreCase = true)) {
            val cmd = trimmed.removePrefix("/agent ").trim()
            if (cmd.isNotEmpty()) {
                viewModelScope.launch {
                    val sid = ensureActiveSession(trimmed)
                    val parentId = _uiState.value.activeMessages.lastOrNull()?.id
                    val userId = UUID.randomUUID().toString()
                    dao.upsertMessage(
                        MessageEntity(
                            id = userId,
                            sessionId = sid,
                            parentId = parentId,
                            role = "user",
                            content = trimmed,
                            tokenEstimate = ProviderPresets.estimateTokens(trimmed),
                        )
                    )
                    _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to userId)
                    val assessment = CommandGuard.assess(cmd)
                    _uiState.value = _uiState.value.copy(pendingGuard = PendingAgentGuard(sid, userId, assessment))
                }
                return
            }
        }

        val lastId = _uiState.value.activeMessages.lastOrNull()?.id
        sendMessageInternal(trimmed, attachmentBitmaps, attachedFile, explicitParentId = lastId, sessionIdOverride = null)
    }

    private fun runCompactCommand(extraFocus: String) {
        val currentMsgs = _uiState.value.activeMessages
        val sid = _activeSessionId.value
        if (sid.isNullOrBlank() || currentMsgs.size < 2) {
            showBanner("Need at least 2 messages in this chat before compacting.")
            return
        }
        soundEngine.playSend()
        viewModelScope.launch {
            val compactTpl = _uiState.value.promptTemplates.firstOrNull {
                it.id == ProviderPresets.ID_COMPACT_TEMPLATE || it.slashKey.equals("/compact", ignoreCase = true)
            }
            val basePrompt = compactTpl?.promptBody?.ifBlank { null }
                ?: "Summarize our entire conversation above into a dense, accurate context brief preserving key facts, decisions, code, preferences, and open tasks so we can continue seamlessly."
            val fullPrompt = if (extraFocus.isNotBlank()) "$basePrompt\n\nFocus especially on: $extraFocus" else basePrompt
            val parentId = currentMsgs.last().id
            runAssistantGeneration(
                sessionId = sid,
                parentMessageId = parentId,
                historyBeforePrompt = currentMsgs,
                promptText = fullPrompt,
                attachmentBitmaps = emptyList(),
                attachedFile = null,
                saveAsCompactSummary = true,
            )
        }
    }

    private fun runWebSearchInChat(query: String) {
        soundEngine.playSend()
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isStreaming = true, streamingContent = "Searching web for \"$query\"...", errorMessage = null)
            val res = webTools.searchWeb(query)
            _uiState.value = _uiState.value.copy(isStreaming = false, streamingContent = "")
            val contextBlock = res.fold(
                onSuccess = { items ->
                    if (items.isEmpty()) "No web search results found for \"$query\"."
                    else buildString {
                        append("[Web Search Results for \"$query\"]\n")
                        items.forEachIndexed { idx, r ->
                            append("${idx + 1}. ${r.title}\nURL: ${r.url}\nSnippet: ${r.snippet}\n\n")
                        }
                    }
                },
                onFailure = { "Web search error: ${it.localizedMessage}" },
            )
            val lastId = _uiState.value.activeMessages.lastOrNull()?.id
            sendMessageInternal(
                prompt = "Using the web search results attached below, answer thoroughly and cite sources: $query",
                attachmentBitmaps = emptyList(),
                attachedFile = AttachedTextFile("web_search_${query.take(24)}.txt", contextBlock),
                explicitParentId = lastId,
                sessionIdOverride = null,
            )
        }
    }

    private fun runUrlReaderInChat(rawInput: String) {
        soundEngine.playSend()
        val parts = rawInput.split(" ", limit = 2)
        val url = parts[0]
        val question = parts.getOrNull(1)?.trim().orEmpty().ifBlank { "Summarize this page clearly with key takeaways." }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isStreaming = true, streamingContent = "Reading $url...", errorMessage = null)
            val res = webTools.readUrl(url)
            _uiState.value = _uiState.value.copy(isStreaming = false, streamingContent = "")
            val body = res.getOrElse { "Failed reading $url: ${it.localizedMessage}" }
            val lastId = _uiState.value.activeMessages.lastOrNull()?.id
            sendMessageInternal(
                prompt = "$question ($url)",
                attachmentBitmaps = emptyList(),
                attachedFile = AttachedTextFile("webpage_extract.txt", body),
                explicitParentId = lastId,
                sessionIdOverride = null,
            )
        }
    }

    private fun sendMessageInternal(
        prompt: String,
        attachmentBitmaps: List<Bitmap>,
        attachedFile: AttachedTextFile?,
        explicitParentId: String?,
        sessionIdOverride: String?,
    ) {
        soundEngine.playSend()
        viewModelScope.launch {
            val fallbackTitle = attachedFile?.fileName ?: if (attachmentBitmaps.size > 1) "${attachmentBitmaps.size} Images" else "Image Analysis"
            val sid = sessionIdOverride ?: ensureActiveSession(prompt.ifBlank { fallbackTitle })
            val savedPaths = attachmentBitmaps.mapNotNull { bmp ->
                saveAttachmentLocally(bmp).takeIf { it.isNotBlank() }
            }
            val attachPaths = savedPaths.joinToString("\n")
            val agentCopiedPaths = if (preferences.value.agentModeEnabled && savedPaths.isNotEmpty()) {
                savedPaths.mapNotNull { copyImageToAgentWorkspace(File(it)) }
            } else emptyList()

            val userMsgId = UUID.randomUUID().toString()
            val allBefore = dao.getMessagesForSessionOnce(sid)
            val historyBefore = ChatTreeHelper.buildAncestorPath(allBefore, explicitParentId)

            val displayContent = prompt.ifBlank {
                when {
                    attachedFile != null -> "Analyze attached file: ${attachedFile.fileName}"
                    attachmentBitmaps.size > 1 -> "[Attached ${attachmentBitmaps.size} Images]"
                    else -> "[Attached Image]"
                }
            }
            val userMsg = MessageEntity(
                id = userMsgId,
                sessionId = sid,
                parentId = explicitParentId,
                role = "user",
                content = displayContent,
                attachmentPath = attachPaths,
                attachmentFileName = attachedFile?.fileName.orEmpty(),
                attachmentFileContent = attachedFile?.content.orEmpty(),
                tokenEstimate = ProviderPresets.estimateTokens(displayContent),
            )
            dao.upsertMessage(userMsg)
            _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to userMsgId)
            refreshSessionStats(sid, firstPromptHint = displayContent)

            val promptForModel = if (agentCopiedPaths.isNotEmpty()) {
                "$displayContent\n\n[Agent Mode Note: The attached image(s) have been copied to your project workspace for inspection anytime: ${agentCopiedPaths.joinToString(", ")}]"
            } else displayContent

            runAssistantGeneration(
                sessionId = sid,
                parentMessageId = userMsgId,
                historyBeforePrompt = historyBefore,
                promptText = promptForModel,
                attachmentBitmaps = attachmentBitmaps,
                attachedFile = attachedFile,
            )
        }
    }

    private fun sliceHistoryFromLatestCompact(history: List<MessageEntity>): List<MessageEntity> {
        val lastCompactIdx = history.indexOfLast { it.isCompactSummary }
        return if (lastCompactIdx >= 0) history.subList(lastCompactIdx, history.size) else history
    }

    private fun runAssistantGeneration(
        sessionId: String,
        parentMessageId: String,
        historyBeforePrompt: List<MessageEntity>,
        promptText: String,
        attachmentBitmaps: List<Bitmap>,
        attachedFile: AttachedTextFile?,
        saveAsCompactSummary: Boolean = false,
    ) {
        val prov = _uiState.value.activeProvider ?: ProviderPresets.defaultProfiles().first()
        val prefs = preferences.value
        val persona = _uiState.value.resolvedPersona
        val shizukuConnected = _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_SHELL ||
            _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_ROOT
        val ctxCfg = prefs.contextModify
        val effectiveHistory = sliceHistoryFromLatestCompact(historyBeforePrompt)

        val systemPrompt = llmClient.buildSystemPrompt(
            persona = persona,
            memories = _uiState.value.memories,
            agentModeEnabled = prefs.agentModeEnabled && !saveAsCompactSummary,
            shizukuConnected = shizukuConnected,
            agentWorkspacePath = prefs.agentWorkspacePath,
            moodMethod = if (saveAsCompactSummary) "none" else prefs.moodMethod,
            contextConfig = ctxCfg,
            includeDeviceActions = !saveAsCompactSummary,
            imageGenEnabled = prefs.imageGenEnabled && !saveAsCompactSummary,
            kaggleConfigured = kaggleEngine.isConfigured(prefs),
        )

        activeStreamSessionId = sessionId
        activeStreamParentId = parentMessageId
        activeStreamProviderName = prov.name
        activeStreamModelName = if (prov.protocol == "on_device") {
            onDeviceEngine.status.value.modelName.ifBlank { prov.selectedModel }
        } else prov.selectedModel
        activeStreamSpeakerName = persona.name

        streamJob?.cancel()
        _streamingParentId.value = parentMessageId
        streamJob = viewModelScope.launch {
            dao.incrementProviderUsage(prov.id)
            _uiState.value = _uiState.value.copy(
                isStreaming = true,
                streamingContent = "",
                streamingThought = "",
                streamingParentMessageId = parentMessageId,
                retryStatusText = "",
                currentMood = "thinking",
                errorMessage = null,
            )
            val startMs = System.currentTimeMillis()
            val rawContent = StringBuilder()
            val rawThought = StringBuilder()
            var chirpCounter = 0
            var lastUiFlushMs = 0L

            // Decoupled typewriter reveal pacing with Word-by-Word (default) or Letter-by-Letter cadence
            val typingSpeed = prefs.typingSpeed
            val typingCadence = prefs.typingSoundCadence
            val isWordCadence = typingCadence != "letter"
            val isInstantTyping = typingSpeed == "instant"
            val charsPerTick = when (typingSpeed) {
                "super_slow" -> 1
                "slow" -> 1
                "medium" -> 2
                "fast" -> 4
                "very_fast" -> 9
                else -> Int.MAX_VALUE
            }
            val tickDelayMs = when (typingSpeed) {
                "super_slow" -> 52L
                "slow" -> 30L
                "medium" -> 30L
                "fast" -> 26L
                "very_fast" -> 22L
                else -> 0L
            }

            val targetBodyText = java.util.concurrent.atomic.AtomicReference("")
            val targetThoughtText = java.util.concurrent.atomic.AtomicReference("")
            val targetMood = java.util.concurrent.atomic.AtomicReference("thinking")
            val networkDone = java.util.concurrent.atomic.AtomicBoolean(false)
            var displayedLength = 0

            var revealJob: Job? = null
            if (!isInstantTyping) {
                revealJob = viewModelScope.launch {
                    var inWord = false
                    while (!networkDone.get() || displayedLength < targetBodyText.get().length) {
                        val full = targetBodyText.get()
                        val thoughtSnap = targetThoughtText.get()
                        val moodSnap = targetMood.get()
                        if (displayedLength < full.length) {
                            val nextLen = (displayedLength + charsPerTick).coerceAtMost(full.length)
                            val newlyRevealed = full.substring(displayedLength, nextLen)
                            displayedLength = nextLen
                            var chirpSeed: Int? = null
                            for (ch in newlyRevealed) {
                                val isWordChar = ch.isLetterOrDigit()
                                if (isWordCadence) {
                                    if (isWordChar && !inWord && chirpSeed == null) {
                                        chirpSeed = ch.code
                                    }
                                    inWord = isWordChar
                                } else {
                                    if (isWordChar && chirpSeed == null) {
                                        chirpSeed = ch.code
                                    }
                                }
                            }
                            if (chirpSeed != null) {
                                soundEngine.playAnimaleseChirp(
                                    chirpSeed,
                                    isQuestion = full.endsWith("?"),
                                )
                            }
                            _uiState.value = _uiState.value.copy(
                                streamingContent = full.substring(0, displayedLength),
                                streamingThought = thoughtSnap,
                                retryStatusText = "",
                                currentMood = moodSnap,
                            )
                        } else if (thoughtSnap.isNotEmpty() && _uiState.value.streamingThought != thoughtSnap) {
                            _uiState.value = _uiState.value.copy(
                                streamingThought = thoughtSnap,
                                currentMood = moodSnap,
                            )
                        }
                        delay(tickDelayMs)
                    }
                }
            }

            suspend fun streamSinglePass(
                passHistory: List<MessageEntity>,
                passPrompt: String,
                passBitmaps: List<Bitmap>,
                passFile: AttachedTextFile?,
                resetDisplay: Boolean,
            ) {
                val maxRetries = if (prov.protocol == "on_device") 0 else prefs.maxAutoRetries.coerceIn(0, 15)
                var attempt = 0
                var lastErr: Exception? = null

                while (attempt <= maxRetries) {
                    rawContent.clear()
                    rawThought.clear()
                    if (resetDisplay) {
                        targetBodyText.set("")
                        targetThoughtText.set("")
                        displayedLength = 0
                    }
                    lastUiFlushMs = 0L
                    try {
                        val flow = if (prov.protocol == "on_device") {
                            onDeviceEngine.streamReply(
                                systemPrompt = systemPrompt,
                                history = passHistory,
                                userPrompt = passPrompt,
                                historyLimit = ctxCfg.historyLimit,
                            )
                        } else {
                            llmClient.streamChat(
                                provider = prov,
                                systemPrompt = systemPrompt,
                                history = passHistory,
                                userPrompt = passPrompt,
                                imageBitmaps = passBitmaps,
                                attachedFileName = passFile?.fileName.orEmpty(),
                                attachedFileContent = passFile?.content.orEmpty(),
                                historyLimit = ctxCfg.historyLimit,
                            )
                        }
                        flow.collect { chunk ->
                            if (chunk.thoughtDelta.isNotEmpty()) rawThought.append(chunk.thoughtDelta)
                            if (chunk.contentDelta.isNotEmpty()) {
                                rawContent.append(chunk.contentDelta)
                                if (isInstantTyping) {
                                    chirpCounter++
                                    val stride = if (isWordCadence) 6 else 3
                                    if (chirpCounter % stride == 0) {
                                        val seed = chunk.contentDelta.firstOrNull { it.isLetterOrDigit() }?.code ?: chirpCounter
                                        soundEngine.playAnimaleseChirp(seed)
                                    }
                                }
                            }
                            val now = System.currentTimeMillis()
                            if (now - lastUiFlushMs >= 32L) {
                                lastUiFlushMs = now
                                val (inlineThought, cleanBody) = ProviderPresets.parseThoughts(rawContent.toString())
                                val (inlineMood, bodyNoMood) = MoodDetector.extractInlineMoodTag(cleanBody)
                                val mergedThought = listOf(rawThought.toString().trim(), inlineThought)
                                    .filter { it.isNotEmpty() }.joinToString("\n\n")
                                val liveMood = inlineMood
                                    ?: if (bodyNoMood.isNotBlank()) MoodDetector.detectMood(bodyNoMood) else "thinking"
                                targetBodyText.set(bodyNoMood)
                                targetThoughtText.set(mergedThought)
                                targetMood.set(liveMood)
                                if (isInstantTyping) {
                                    _uiState.value = _uiState.value.copy(
                                        streamingContent = bodyNoMood,
                                        streamingThought = mergedThought,
                                        retryStatusText = "",
                                        currentMood = liveMood,
                                    )
                                }
                            }
                        }
                        lastErr = null
                        break
                    } catch (e: CancellationException) {
                        revealJob?.cancel()
                        throw e
                    } catch (e: Exception) {
                        lastErr = e
                        val retryable = prov.protocol != "on_device" && UniversalLlmClient.isRetryableError(e)
                        if (!retryable || attempt >= maxRetries) {
                            revealJob?.cancel()
                            throw e
                        }
                        attempt++
                        val backoffMs = (1200L * attempt).coerceAtMost(6000L)
                        _uiState.value = _uiState.value.copy(
                            streamingContent = "",
                            streamingThought = "",
                            retryStatusText = "Rate limited / busy — retrying ($attempt/$maxRetries)...",
                        )
                        delay(backoffMs)
                    }
                }
                if (lastErr != null) {
                    revealJob?.cancel()
                    throw lastErr
                }
            }

            try {
                streamSinglePass(
                    passHistory = effectiveHistory,
                    passPrompt = promptText,
                    passBitmaps = attachmentBitmaps,
                    passFile = attachedFile,
                    resetDisplay = true,
                )

                var parsedThoughtAndBody = ProviderPresets.parseThoughts(rawContent.toString())
                var parsedMoodAndBody = MoodDetector.extractInlineMoodTag(parsedThoughtAndBody.second)
                var mergedThought = listOf(rawThought.toString().trim(), parsedThoughtAndBody.first)
                    .filter { it.isNotEmpty() }.joinToString("\n\n")
                var inlineMood = parsedMoodAndBody.first
                var finalBody = parsedMoodAndBody.second.ifBlank { parsedThoughtAndBody.second.ifBlank { rawContent.toString().trim() } }

                // Autonomous keyless agentic [WEB_SEARCH] loop (up to 2 rounds)
                if (!saveAsCompactSummary) {
                    var webRound = 0
                    val accumulatedWebBlocks = StringBuilder()
                    while (webRound < 2) {
                        val (searchQuery, _) = UniversalLlmClient.extractWebSearchQuery(finalBody)
                        if (searchQuery.isNullOrBlank()) break
                        webRound++
                        _uiState.value = _uiState.value.copy(
                            retryStatusText = "Searching web for \"$searchQuery\"...",
                        )
                        val searchRes = webTools.searchWeb(searchQuery, maxResults = 5)
                        val searchBlock = searchRes.fold(
                            onSuccess = { items ->
                                if (items.isEmpty()) "No web search results found for \"$searchQuery\"."
                                else buildString {
                                    append("[Live Web Search Results for \"$searchQuery\"]\n")
                                    items.forEachIndexed { idx, r ->
                                        append("${idx + 1}. ${r.title}\nURL: ${r.url}\nSnippet: ${r.snippet}\n\n")
                                    }
                                }
                            },
                            onFailure = { "Web search failed for \"$searchQuery\": ${it.localizedMessage}" },
                        )
                        accumulatedWebBlocks.append(searchBlock).append("\n")
                        val groundedPrompt = buildString {
                            append(promptText)
                            append("\n\n")
                            append(accumulatedWebBlocks.toString())
                            append("Use the live web search results above to answer thoroughly, naturally, and accurately. Do NOT emit another [WEB_SEARCH] tag unless a completely different follow-up query is strictly needed.")
                        }
                        streamSinglePass(
                            passHistory = effectiveHistory,
                            passPrompt = groundedPrompt,
                            passBitmaps = emptyList(), // Never re-send image bytes on follow-up web search turn
                            passFile = attachedFile,
                            resetDisplay = true,
                        )
                        parsedThoughtAndBody = ProviderPresets.parseThoughts(rawContent.toString())
                        parsedMoodAndBody = MoodDetector.extractInlineMoodTag(parsedThoughtAndBody.second)
                        mergedThought = listOf(rawThought.toString().trim(), parsedThoughtAndBody.first)
                            .filter { it.isNotEmpty() }.joinToString("\n\n")
                        inlineMood = parsedMoodAndBody.first
                        finalBody = parsedMoodAndBody.second.ifBlank { parsedThoughtAndBody.second.ifBlank { rawContent.toString().trim() } }
                    }
                    // Strip any leftover [WEB_SEARCH] tag if the model still emitted one after max rounds
                    finalBody = UniversalLlmClient.extractWebSearchQuery(finalBody).second

                    // Autonomous multi-image local inspection loop ([VIEW_IMAGE], up to 2 rounds, 5 images per round)
                    var viewRound = 0
                    while (viewRound < 2 && prov.protocol != "on_device") {
                        val (imgPaths, bodyWithoutViewTags) = UniversalLlmClient.extractViewImagePaths(finalBody, maxCount = 5)
                        if (imgPaths.isEmpty()) break
                        viewRound++
                        _uiState.value = _uiState.value.copy(
                            retryStatusText = "Inspecting ${imgPaths.size} local image(s)...",
                        )
                        val loaded = mutableListOf<Pair<String, Bitmap>>()
                        val missing = mutableListOf<String>()
                        for (rawPath in imgPaths) {
                            val bmp = withContext(Dispatchers.IO) {
                                loadLocalOrShizukuBitmap(rawPath, shizukuConnected)
                            }
                            if (bmp != null) loaded.add(rawPath to bmp) else missing.add(rawPath)
                        }
                        if (loaded.isEmpty()) {
                            finalBody = bodyWithoutViewTags
                            break
                        }
                        val inspectPrompt = buildString {
                            append(promptText)
                            append("\n\n[Visual Image Inspection Loaded]\n")
                            append("Attached are ${loaded.size} requested image(s) in exact order:\n")
                            loaded.forEachIndexed { idx, (p, _) ->
                                append("${idx + 1}. $p\n")
                            }
                            if (missing.isNotEmpty()) {
                                append("Unreadable/missing paths: ${missing.joinToString(", ")}\n")
                            }
                            append("Directly inspect the attached image pixels and answer the user naturally and thoroughly. Do NOT emit another [VIEW_IMAGE] tag for these already-loaded images.")
                        }
                        streamSinglePass(
                            passHistory = effectiveHistory,
                            passPrompt = inspectPrompt,
                            passBitmaps = loaded.map { it.second },
                            passFile = attachedFile,
                            resetDisplay = true,
                        )
                        parsedThoughtAndBody = ProviderPresets.parseThoughts(rawContent.toString())
                        parsedMoodAndBody = MoodDetector.extractInlineMoodTag(parsedThoughtAndBody.second)
                        mergedThought = listOf(rawThought.toString().trim(), parsedThoughtAndBody.first)
                            .filter { it.isNotEmpty() }.joinToString("\n\n")
                        inlineMood = parsedMoodAndBody.first
                        finalBody = parsedMoodAndBody.second.ifBlank { parsedThoughtAndBody.second.ifBlank { rawContent.toString().trim() } }
                    }
                    finalBody = UniversalLlmClient.extractViewImagePaths(finalBody, maxCount = 5).second

                    // Native Android SDK [DEVICE_ACTION] execution loop (up to 2 rounds, no Shizuku required)
                    var actionRound = 0
                    val accumulatedActionBlocks = StringBuilder()
                    while (actionRound < 2) {
                        val actionPayloads = AndroidDeviceActions.extractActionPayloads(finalBody)
                        if (actionPayloads.isEmpty()) break
                        actionRound++
                        _uiState.value = _uiState.value.copy(
                            retryStatusText = "Running Android action...",
                        )
                        for (payload in actionPayloads.take(3)) {
                            val res = AndroidDeviceActions.executePayload(appContext, payload, webTools)
                            accumulatedActionBlocks.append("[Device Action Result (${res.action}): ${if (res.success) "OK" else "FAILED"}] ${res.output}\n")
                        }
                        val groundedPrompt = buildString {
                            append(promptText)
                            append("\n\n")
                            append(accumulatedActionBlocks.toString())
                            append("Use the real device action results above to reply naturally and concisely. Do NOT emit another [DEVICE_ACTION] tag unless another distinct action is needed.")
                        }
                        streamSinglePass(
                            passHistory = effectiveHistory,
                            passPrompt = groundedPrompt,
                            passBitmaps = emptyList(),
                            passFile = attachedFile,
                            resetDisplay = true,
                        )
                        parsedThoughtAndBody = ProviderPresets.parseThoughts(rawContent.toString())
                        parsedMoodAndBody = MoodDetector.extractInlineMoodTag(parsedThoughtAndBody.second)
                        mergedThought = listOf(rawThought.toString().trim(), parsedThoughtAndBody.first)
                            .filter { it.isNotEmpty() }.joinToString("\n\n")
                        inlineMood = parsedMoodAndBody.first
                        finalBody = parsedMoodAndBody.second.ifBlank { parsedThoughtAndBody.second.ifBlank { rawContent.toString().trim() } }
                    }
                    finalBody = AndroidDeviceActions.stripActionTags(finalBody)
                }

                // Let typewriter finish revealing the remaining buffered text cleanly before finalizing
                targetBodyText.set(finalBody)
                targetThoughtText.set(mergedThought)
                targetMood.set(inlineMood ?: MoodDetector.detectMood(finalBody))
                networkDone.set(true)
                revealJob?.join()

                // Inline Multi-Image Illume (up to 5), [GENERATE_IMAGE] JSON tool (supports img2img edit_last), & Keyless Web/Stock Images
                if (!saveAsCompactSummary) {
                    val (genImgCall, bodyAfterGenTag) = UniversalLlmClient.extractGenerateImageCall(finalBody)
                    if (genImgCall != null && prefs.imageGenEnabled) {
                        val marker = "[[CELLIUM_IMG_LOADING:Generating: ${genImgCall.prompt.take(44)}]]"
                        finalBody = if (bodyAfterGenTag.isNotBlank()) "$bodyAfterGenTag\n\n$marker" else marker
                        _uiState.value = _uiState.value.copy(
                            streamingContent = finalBody,
                            retryStatusText = if (genImgCall.editLast) "Editing previous image on GPU..." else "Generating image...",
                        )
                        val initPath = if (genImgCall.editLast) {
                            _uiState.value.lastGeneratedImagePath
                                ?: _uiState.value.artworks.firstOrNull()?.localPath
                        } else null
                        val useKaggleTool = kaggleEngine.isConfigured(prefs) &&
                            (prefs.imagineProvider == "kaggle" || genImgCall.editLast)
                        val sizeRaw = genImgCall.size.trim().lowercase()
                        val toolResult = if (useKaggleTool) {
                            val sizeForCall = when {
                                sizeRaw.contains("x") -> KaggleImageEngine.SIZE_PRESETS.firstOrNull { it.startsWith(sizeRaw.substringBefore(" ")) } ?: prefs.kaggleSize
                                sizeRaw == "square" || sizeRaw == "1:1" -> "1024x1024 (1:1)"
                                sizeRaw == "landscape" || sizeRaw == "16:9" -> "1216x832 (16:9)"
                                sizeRaw == "portrait" || sizeRaw == "9:16" -> "832x1216 (9:16)"
                                else -> prefs.kaggleSize
                            }
                            generateKaggleBatch(
                                prompt = genImgCall.prompt,
                                stickyPrompt = prefs.kaggleStickyPrompt,
                                negativePrompt = prefs.kaggleNegativePrompt,
                                presetLabel = prefs.kagglePreset,
                                sizeLabel = sizeForCall,
                                steps = prefs.kaggleSteps,
                                guidance = prefs.kaggleGuidance,
                                batch = genImgCall.batch.coerceIn(1, 4),
                                seed = prefs.kaggleSeed,
                                initImagePath = initPath,
                                denoise = 0.75f,
                                onStatus = { st: String -> _uiState.value = _uiState.value.copy(retryStatusText = st) },
                            ).map { it.first() }
                        } else {
                            val ar = when {
                                sizeRaw == "landscape" || sizeRaw.contains("16:9") || sizeRaw.startsWith("1216x832") -> "16:9"
                                sizeRaw == "portrait" || sizeRaw.contains("9:16") || sizeRaw.startsWith("832x1216") -> "9:16"
                                else -> "1:1"
                            }
                            generateArtwork(
                                prompt = genImgCall.prompt,
                                negativePrompt = prefs.kaggleNegativePrompt,
                                aspectRatio = ar,
                            )
                        }
                        toolResult.onSuccess { art ->
                            if (prefs.agentModeEnabled) copyImageToAgentWorkspace(File(art.localPath))
                            finalBody = finalBody.replace(marker, "[[CELLIUM_IMG:${art.localPath}]]")
                        }.onFailure { err ->
                            finalBody = finalBody.replace(marker, "*(Image generation failed: ${err.localizedMessage})*")
                        }
                        _uiState.value = _uiState.value.copy(streamingContent = finalBody)
                    }

                    val (illumePrompts, bodyWithIllumeSlots) = UniversalLlmClient.extractAllIllumeBlocks(finalBody, maxCount = 5)
                    val (webImgQueries, bodyWithAllSlots) = UniversalLlmClient.extractAllWebImageBlocks(bodyWithIllumeSlots, maxCount = 5)

                    if (illumePrompts.isNotEmpty() || webImgQueries.isNotEmpty()) {
                        var workingBody = bodyWithAllSlots
                        illumePrompts.forEachIndexed { idx, p ->
                            workingBody = workingBody.replace(
                                "[[CELLIUM_IMG_SLOT:$idx]]",
                                "[[CELLIUM_IMG_LOADING:Illume #${idx + 1}: ${p.take(44)}]]",
                            )
                        }
                        webImgQueries.forEachIndexed { idx, q ->
                            workingBody = workingBody.replace(
                                "[[CELLIUM_WEBIMG_SLOT:$idx]]",
                                "[[CELLIUM_IMG_LOADING:Web Photo #${idx + 1}: ${q.take(44)}]]",
                            )
                        }
                        finalBody = workingBody
                        _uiState.value = _uiState.value.copy(
                            streamingContent = finalBody,
                            retryStatusText = if (illumePrompts.isNotEmpty()) {
                                "Rendering ${illumePrompts.size} artwork(s) via Illume..."
                            } else {
                                "Fetching ${webImgQueries.size} web photo(s)..."
                            },
                        )

                        illumePrompts.forEachIndexed { idx, imgPrompt ->
                            val loadingMarker = "[[CELLIUM_IMG_LOADING:Illume #${idx + 1}: ${imgPrompt.take(44)}]]"
                            _uiState.value = _uiState.value.copy(
                                retryStatusText = "Rendering artwork ${idx + 1}/${illumePrompts.size} via Illume...",
                            )
                            val artRes = generateArtwork(imgPrompt)
                            artRes.onSuccess { art ->
                                if (prefs.agentModeEnabled) {
                                    copyImageToAgentWorkspace(File(art.localPath))
                                }
                                finalBody = finalBody.replace(loadingMarker, "[[CELLIUM_IMG:${art.localPath}]]")
                            }.onFailure { err ->
                                finalBody = finalBody.replace(
                                    loadingMarker,
                                    "*(Illume #${idx + 1} failed: ${err.localizedMessage})*",
                                )
                            }
                            _uiState.value = _uiState.value.copy(streamingContent = finalBody)
                        }

                        val webDir = webImagesDir()
                        webImgQueries.forEachIndexed { idx, q ->
                            val loadingMarker = "[[CELLIUM_IMG_LOADING:Web Photo #${idx + 1}: ${q.take(44)}]]"
                            _uiState.value = _uiState.value.copy(
                                retryStatusText = "Searching stock photo ${idx + 1}/${webImgQueries.size}: $q...",
                            )
                            val imgSearch = webTools.searchWebImages(q, maxResults = 3)
                            var downloadedPath: String? = null
                            val hits = imgSearch.getOrNull().orEmpty()
                            for (hit in hits) {
                                val dl = webTools.downloadImageToFile(hit.imageUrl, webDir, filePrefix = "web_photo")
                                val file = dl.getOrNull()
                                if (file != null && file.exists()) {
                                    downloadedPath = file.absolutePath
                                    if (prefs.agentModeEnabled) {
                                        copyImageToAgentWorkspace(file)
                                    }
                                    break
                                }
                            }
                            finalBody = if (!downloadedPath.isNullOrBlank()) {
                                finalBody.replace(loadingMarker, "[[CELLIUM_IMG:$downloadedPath]]")
                            } else {
                                finalBody.replace(loadingMarker, "*(No stock photo found for \"$q\")*")
                            }
                            _uiState.value = _uiState.value.copy(streamingContent = finalBody)
                        }
                    }
                }

                finalBody = UniversalLlmClient.sanitizeVisibleReply(finalBody)

                val latency = (System.currentTimeMillis() - startMs).coerceAtLeast(1L)
                val detectedMood = inlineMood ?: MoodDetector.detectMood(finalBody)
                val estTokens = ProviderPresets.estimateTokens(finalBody + mergedThought)
                val tps = (estTokens.toFloat() / (latency.toFloat() / 1000f)).coerceAtMost(999f)
                val modelUsed = if (prov.protocol == "on_device") {
                    onDeviceEngine.status.value.modelName.ifBlank { prov.selectedModel }
                } else prov.selectedModel
                val estCost = ProviderPresets.estimateCostUsd(modelUsed, estTokens, prov.requiresKey, prov.protocol)

                val assistantId = UUID.randomUUID().toString()
                val assistantEntity = MessageEntity(
                    id = assistantId,
                    sessionId = sessionId,
                    parentId = parentMessageId,
                    role = "assistant",
                    speakerLabel = if (saveAsCompactSummary) "Context Compact" else persona.name,
                    content = finalBody.ifBlank { "(Empty response)" },
                    thought = mergedThought,
                    mood = detectedMood,
                    providerName = prov.name,
                    modelName = modelUsed,
                    attachmentPath = "",
                    tokenEstimate = estTokens,
                    latencyMs = latency,
                    tokensPerSec = tps,
                    estimatedCostUsd = estCost,
                    isCompactSummary = saveAsCompactSummary,
                )
                _streamingParentId.value = null
                dao.upsertMessage(assistantEntity)
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sessionId to assistantId)
                refreshSessionStats(sessionId)
                soundEngine.playRecv()
                if (prefs.autoReadReplies && !saveAsCompactSummary && appInForeground) {
                    speakText(assistantEntity.content)
                }

                val sessTitle = dao.getSession(sessionId)?.title ?: "Cel.Cellium"
                maybePostReplyNotification(sessionId, sessTitle, persona.name, assistantEntity.content)

                _uiState.value = _uiState.value.copy(
                    isStreaming = false,
                    streamingContent = "",
                    streamingThought = "",
                    streamingParentMessageId = null,
                    retryStatusText = "",
                    currentMood = detectedMood,
                )

                // Mood Engine Method 2: fast background AI mood classification when selected
                val isKeylessPollinations = prov.id == ProviderPresets.ID_POLLINATIONS_FREE && prov.apiKey.isBlank()
                if (!saveAsCompactSummary && prefs.moodMethod == "background_ai" && prov.protocol != "on_device" && !isKeylessPollinations) {
                    viewModelScope.launch {
                        val refined = llmClient.classifyMoodFast(prov, finalBody)
                        if (!refined.isNullOrBlank()) {
                            _uiState.value = _uiState.value.copy(currentMood = refined)
                            dao.upsertMessage(assistantEntity.copy(mood = refined))
                        }
                    }
                }

                if (saveAsCompactSummary) {
                    showBanner("Conversation compacted! Future messages use this summary as fresh context.")
                }

                if (prefs.agentModeEnabled && !saveAsCompactSummary) {
                    val agentCmd = CommandGuard.extractAgentCommand(finalBody)
                    if (!agentCmd.isNullOrBlank()) {
                        val assessment = CommandGuard.assess(agentCmd)
                        if (assessment.tier == CommandSafetyTier.SAFE && prefs.agentAutoApproveSafe) {
                            executeAgentCommand(sessionId, assistantId, assessment.command)
                        } else {
                            _uiState.value = _uiState.value.copy(
                                pendingGuard = PendingAgentGuard(sessionId, assistantId, assessment)
                            )
                        }
                    }
                }
            } catch (e: CancellationException) {
                _streamingParentId.value = null
                _uiState.value = _uiState.value.copy(
                    isStreaming = false,
                    streamingContent = "",
                    streamingThought = "",
                    streamingParentMessageId = null,
                    retryStatusText = "",
                )
                throw e
            } catch (e: Exception) {
                _streamingParentId.value = null
                val errMsg = e.localizedMessage ?: "Failed to get response from ${prov.name}."
                DevLogBuffer.add("ERROR", "Chat", errMsg)
                val errId = UUID.randomUUID().toString()
                dao.upsertMessage(
                    MessageEntity(
                        id = errId,
                        sessionId = sessionId,
                        parentId = parentMessageId,
                        role = "assistant",
                        speakerLabel = persona.name,
                        content = "Request failed: $errMsg",
                        mood = "error",
                        providerName = prov.name,
                        modelName = prov.selectedModel,
                        isError = true,
                    )
                )
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sessionId to errId)
                _uiState.value = _uiState.value.copy(
                    isStreaming = false,
                    streamingContent = "",
                    streamingThought = "",
                    streamingParentMessageId = null,
                    retryStatusText = "",
                    currentMood = "error",
                    errorMessage = errMsg,
                )
            } finally {
                activeStreamSessionId = null
                activeStreamParentId = null
            }
        }
    }

    /**
     * Instant, lag-free Stop button:
     * 1. Snapshots any partial streamed text/thought and persists it cleanly to Room so it is NEVER lost.
     * 2. Immediately cancels active OkHttp network requests and coroutine job.
     * 3. Cancels GGUF generation off the main thread so the UI never freezes.
     */
    fun stopStreaming() {
        soundEngine.playClick()
        val snapContent = _uiState.value.streamingContent.trim()
        val snapThought = _uiState.value.streamingThought.trim()
        val sid = activeStreamSessionId
        val pid = activeStreamParentId
        val provName = activeStreamProviderName
        val modelName = activeStreamModelName
        val speaker = activeStreamSpeakerName

        streamJob?.cancel()
        streamJob = null
        _streamingParentId.value = null
        llmClient.cancelActiveRequests()

        _uiState.value = _uiState.value.copy(
            isStreaming = false,
            streamingContent = "",
            streamingThought = "",
            streamingParentMessageId = null,
            retryStatusText = "",
        )

        viewModelScope.launch(Dispatchers.IO) {
            onDeviceEngine.cancelGgufGeneration()
            if (!sid.isNullOrBlank() && (snapContent.isNotEmpty() || snapThought.isNotEmpty())) {
                val partialId = UUID.randomUUID().toString()
                val text = snapContent.ifBlank { "(Stopped during thinking)" }
                dao.upsertMessage(
                    MessageEntity(
                        id = partialId,
                        sessionId = sid,
                        parentId = pid,
                        role = "assistant",
                        speakerLabel = speaker,
                        content = text,
                        thought = snapThought,
                        mood = MoodDetector.detectMood(text),
                        providerName = provName,
                        modelName = modelName,
                        tokenEstimate = ProviderPresets.estimateTokens(text + snapThought),
                    )
                )
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to partialId)
                refreshSessionStats(sid)
            }
        }
    }

    // ── Agent Mode Shizuku Execution ─────────────────────────────────────

    fun approvePendingAgentCommand(editedCommand: String) {
        val pending = _uiState.value.pendingGuard ?: return
        val reassessment = CommandGuard.assess(editedCommand)
        if (reassessment.tier == CommandSafetyTier.BLOCKED) {
            _uiState.value = _uiState.value.copy(
                pendingGuard = pending.copy(assessment = reassessment),
                errorMessage = reassessment.reason,
            )
            return
        }
        _uiState.value = _uiState.value.copy(pendingGuard = null)
        soundEngine.playPop()
        viewModelScope.launch {
            executeAgentCommand(pending.sessionId, pending.sourceMessageId, reassessment.command)
        }
    }

    fun denyPendingAgentCommand() {
        val pending = _uiState.value.pendingGuard ?: return
        _uiState.value = _uiState.value.copy(pendingGuard = null)
        soundEngine.playClick()
        viewModelScope.launch {
            val status = if (pending.assessment.tier == CommandSafetyTier.BLOCKED) "blocked" else "denied"
            val toolMsgId = UUID.randomUUID().toString()
            dao.upsertMessage(
                MessageEntity(
                    id = toolMsgId,
                    sessionId = pending.sessionId,
                    parentId = pending.sourceMessageId,
                    role = "tool",
                    content = if (status == "blocked") "Command blocked by Command Guard." else "Command denied by user.",
                    toolCommand = pending.assessment.command,
                    toolOutput = pending.assessment.reason,
                    toolStatus = status,
                )
            )
            _selectedLeafBySession.value = _selectedLeafBySession.value + (pending.sessionId to toolMsgId)
        }
    }

    private suspend fun executeAgentCommand(sessionId: String, parentId: String, command: String) {
        val shizukuConnected = _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_SHELL ||
            _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_ROOT
        val runnerName = if (shizukuConnected) "Shizuku" else "Local Shell"
        val res = if (shizukuConnected) {
            shizukuBridge.runCommand(command, timeoutSec = 20)
        } else {
            shizukuBridge.runLocalShellCommand(command, resolveLocalWorkspaceDir(), timeoutSec = 20)
        }
        val output = res.getOrElse { "Error: ${it.localizedMessage}" }
        val toolMsgId = UUID.randomUUID().toString()
        val toolEntity = MessageEntity(
            id = toolMsgId,
            sessionId = sessionId,
            parentId = parentId,
            role = "tool",
            content = "$runnerName executed `$command`.",
            toolCommand = command,
            toolOutput = output.take(8000),
            toolStatus = "approved",
            providerName = runnerName,
        )
        dao.upsertMessage(toolEntity)
        _selectedLeafBySession.value = _selectedLeafBySession.value + (sessionId to toolMsgId)
        refreshSessionStats(sessionId)

        val all = dao.getMessagesForSessionOnce(sessionId)
        val path = ChatTreeHelper.buildAncestorPath(all, toolMsgId)
        runAssistantGeneration(
            sessionId = sessionId,
            parentMessageId = toolMsgId,
            historyBeforePrompt = path,
            promptText = "Summarize the $runnerName command output above clearly and concisely for the user.",
            attachmentBitmaps = emptyList(),
            attachedFile = null,
        )
    }

    // ── Live Voice Mode & Floating Assistant Reply ───────────────────────

    fun cancelLiveStream() {
        liveStreamJob?.cancel()
        liveStreamJob = null
        llmClient.cancelActiveRequests()
    }

    private fun detectUserEndCallIntent(transcript: String): Boolean {
        val lower = transcript.lowercase()
            .replace(Regex("[^a-z0-9\\s']"), " ")
            .replace(Regex("\\s+"), " ")
            .trim()
        if (lower.isBlank()) return false
        val exactPhrases = listOf(
            "end the call",
            "end call",
            "end this call",
            "hang up",
            "hang up the call",
            "close live mode",
            "exit live mode",
            "stop live mode",
            "leave live mode",
            "quit live mode",
            "turn off live mode",
            "shut down live mode",
            "end live mode",
            "end live call",
            "close the call",
            "disconnect the call",
            "disconnect call",
            "bye hang up",
            "goodbye hang up",
            "goodbye end the call",
            "bye end the call",
        )
        return exactPhrases.any { lower == it || lower.contains(it) }
    }

    private fun sanitizeLiveVoiceReply(raw: String): String {
        var cleaned = raw
            .replace(Regex("\\[END_CALL]", RegexOption.IGNORE_CASE), "")
            .replace("\r\n", "\n")
        // Replace markdown links [label](url) with readable text
        cleaned = cleaned.replace(Regex("\\[([^\\]]+)]\\((https?://[^)]+)\\)")) { m ->
            val label = m.groupValues[1].trim()
            val url = m.groupValues[2].trim()
            if (label.startsWith("http", ignoreCase = true) || label.isBlank()) {
                url.removePrefix("https://").removePrefix("http://").removePrefix("www.").substringBefore("/")
            } else {
                label
            }
        }
        // Strip fenced code blocks markers & inline backticks
        cleaned = cleaned.replace(Regex("```[a-zA-Z0-9_-]*\\n?"), "")
        cleaned = cleaned.replace("`", "")
        // Strip bold / italic / strikethrough markdown markers
        cleaned = cleaned.replace(Regex("\\*\\*(.+?)\\*\\*"), "$1")
        cleaned = cleaned.replace(Regex("__(.+?)__"), "$1")
        cleaned = cleaned.replace(Regex("~~(.+?)~~"), "$1")
        cleaned = cleaned.replace(Regex("(?<!\\w)\\*([^*\n]+?)\\*(?!\\w)"), "$1")
        cleaned = cleaned.replace(Regex("(?<!\\w)_([^_\n]+?)_(?!\\w)"), "$1")
        // Strip headings, bullets, numbered list markers, and collapse paragraph walls into smooth spoken lines
        val rawLines = cleaned.split('\n').mapNotNull { line ->
            val stripped = line.trim()
                .replace(Regex("^#{1,6}\\s+"), "")
                .replace(Regex("^[-*•+]\\s+"), "")
                .replace(Regex("^\\d+[.)]\\s+"), "")
                .replace(Regex("^>\\s*"), "")
                .replace(Regex("\\s+"), " ")
                .trim()
            stripped.takeIf { it.isNotEmpty() }
        }
        // Cap strictly at 50 lines max so Live Mode never overflows past the screen
        val cappedLines = rawLines.take(50)
        val joined = cappedLines.joinToString(" ")
        return if (joined.length > 2400) {
            joined.take(2397).substringBeforeLast(' ', joined.take(2397)) + "..."
        } else {
            joined
        }
    }

    fun streamLiveReply(
        transcript: String,
        screenBitmap: Bitmap? = null,
        isRetry: Boolean = false,
        onStageChanged: (String) -> Unit = {},
        onDelta: (String) -> Unit,
        onMoodChanged: (String) -> Unit = {},
        onEndCallRequested: () -> Unit = {},
        onComplete: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        val cleanTranscript = transcript.trim()
        if (cleanTranscript.isEmpty()) return
        val prov = _uiState.value.activeProvider ?: ProviderPresets.defaultProfiles().first()
        val prefs = preferences.value
        val persona = _uiState.value.resolvedPersona
        val ctxCfg = prefs.contextModify
        val systemPrompt = llmClient.buildSystemPrompt(
            persona = persona,
            memories = _uiState.value.memories,
            agentModeEnabled = false,
            shizukuConnected = false,
            moodMethod = prefs.moodMethod,
            contextConfig = ContextModifyConfig(
                includePersona = true,
                includeMemories = true,
                includeIllumeInstructions = false,
                includeAgentInstructions = false,
                includeMoodInstructions = prefs.moodMethod == "inline_tag",
            ),
            includeDeviceActions = true,
            extraInstruction = "[Live Voice Mode] Output PURE SPOKEN PLAIN TEXT ONLY. NEVER format text with markdown: zero **bold**, zero *italics*, zero backticks, zero # headings, zero bullet points, zero numbered lists, and zero paragraph breaks. Keep responses as short and conversational as possible (1 to 3 quick spoken sentences by default) unless the user specifically asks for a longer explanation, and NEVER exceed 50 lines. Remember the conversation history and active persona. If the user asks to end the call, hang up, stop, or close Live Mode, say a brief friendly goodbye and append [END_CALL] at the very end.",
        )

        // Cancel any previous in-flight live request so Pollinations Classic API never throws HTTP 429 overlap
        liveStreamJob?.cancel()
        liveStreamJob = viewModelScope.launch {
            val sb = StringBuilder()
            val startMs = System.currentTimeMillis()
            try {
                onStageChanged("Thinking...")
                val sid = ensureActiveSession("Live · ${persona.name}")
                val allBefore = dao.getMessagesForSessionOnce(sid)
                val currentLeafId = _selectedLeafBySession.value[sid]
                    ?: dao.getSession(sid)?.activeLeafId?.takeIf { it.isNotBlank() }
                    ?: allBefore.lastOrNull()?.id

                val existingLeafMsg = allBefore.firstOrNull { it.id == currentLeafId }
                val reuseExistingUserMsg = isRetry &&
                    existingLeafMsg != null &&
                    existingLeafMsg.role == "user" &&
                    existingLeafMsg.content == cleanTranscript

                val ancestorHistory: List<MessageEntity>
                val userMsgId: String
                if (reuseExistingUserMsg && existingLeafMsg != null) {
                    userMsgId = existingLeafMsg.id
                    ancestorHistory = sliceHistoryFromLatestCompact(
                        ChatTreeHelper.buildAncestorPath(allBefore, existingLeafMsg.parentId)
                    )
                } else {
                    ancestorHistory = sliceHistoryFromLatestCompact(
                        ChatTreeHelper.buildAncestorPath(allBefore, currentLeafId)
                    )
                    val savedAttachmentPath = if (screenBitmap != null) {
                        withContext(Dispatchers.IO) { saveAttachmentLocally(screenBitmap) }
                    } else ""
                    userMsgId = UUID.randomUUID().toString()
                    dao.upsertMessage(
                        MessageEntity(
                            id = userMsgId,
                            sessionId = sid,
                            parentId = currentLeafId,
                            role = "user",
                            content = cleanTranscript,
                            attachmentPath = savedAttachmentPath,
                            tokenEstimate = ProviderPresets.estimateTokens(cleanTranscript),
                        )
                    )
                    _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to userMsgId)
                    refreshSessionStats(sid)
                }

                dao.incrementProviderUsage(prov.id)
                val maxRetries = if (prov.protocol == "on_device") 0 else prefs.maxAutoRetries.coerceIn(0, 4)

                suspend fun runLivePass(passPrompt: String, passBmp: Bitmap?): String {
                    var attempt = 0
                    while (true) {
                        sb.clear()
                        try {
                            val flow = if (prov.protocol == "on_device") {
                                onDeviceEngine.streamReply(
                                    systemPrompt = systemPrompt,
                                    history = ancestorHistory,
                                    userPrompt = passPrompt,
                                    historyLimit = ctxCfg.historyLimit,
                                )
                            } else {
                                llmClient.streamChat(
                                    provider = prov,
                                    systemPrompt = systemPrompt,
                                    history = ancestorHistory,
                                    userPrompt = passPrompt,
                                    imageBitmap = passBmp,
                                    historyLimit = ctxCfg.historyLimit,
                                )
                            }
                            flow.collect { chunk ->
                                if (chunk.contentDelta.isNotEmpty()) {
                                    sb.append(chunk.contentDelta)
                                    val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                                    val (tagMood, bodyNoMood) = MoodDetector.extractInlineMoodTag(clean)
                                    if (tagMood != null) onMoodChanged(tagMood)
                                    onDelta(sanitizeLiveVoiceReply(bodyNoMood))
                                }
                            }
                            return sb.toString()
                        } catch (e: CancellationException) {
                            throw e
                        } catch (e: Exception) {
                            val retryable = prov.protocol != "on_device" && UniversalLlmClient.isRetryableError(e)
                            if (!retryable || attempt >= maxRetries) throw e
                            attempt++
                            onStageChanged("Busy — retrying ($attempt/$maxRetries)...")
                            delay((1300L * attempt).coerceAtMost(5000L))
                        }
                    }
                }

                var rawOut = runLivePass(cleanTranscript, screenBitmap)
                var (_, finalClean) = ProviderPresets.parseThoughts(rawOut)
                var (tagMood, finalBody) = MoodDetector.extractInlineMoodTag(finalClean)
                var out = finalBody.ifBlank { finalClean.ifBlank { rawOut.trim() } }

                // Quiet autonomous [DEVICE_ACTION] / [WEB_SEARCH] loop before speaking
                val toolResults = StringBuilder()
                var round = 0
                while (round < 2) {
                    val actionPayloads = AndroidDeviceActions.extractActionPayloads(out)
                    val (webQuery, _) = UniversalLlmClient.extractWebSearchQuery(out)
                    if (actionPayloads.isEmpty() && webQuery.isNullOrBlank()) break
                    round++
                    if (actionPayloads.isNotEmpty()) {
                        onStageChanged("Running action...")
                        for (payload in actionPayloads.take(3)) {
                            val res = AndroidDeviceActions.executePayload(appContext, payload, webTools)
                            toolResults.append("[Device Action (${res.action}): ${if (res.success) "OK" else "FAILED"}] ${res.output}\n")
                        }
                    }
                    if (!webQuery.isNullOrBlank()) {
                        onStageChanged("Searching web...")
                        val searchRes = webTools.searchWeb(webQuery, maxResults = 4)
                        val block = searchRes.fold(
                            onSuccess = { items ->
                                if (items.isEmpty()) "No web results for $webQuery."
                                else items.joinToString("\n") { "${it.title}: ${it.snippet}" }
                            },
                            onFailure = { "Web search error: ${it.localizedMessage}" },
                        )
                        toolResults.append("[Web Search \"$webQuery\"]\n$block\n")
                    }
                    onStageChanged("Thinking...")
                    val followPrompt = buildString {
                        append(cleanTranscript)
                        append("\n\n")
                        append(toolResults.toString())
                        append("Reply in 1 to 3 natural spoken sentences using the live results above. Do NOT emit another [DEVICE_ACTION] or [WEB_SEARCH] tag.")
                    }
                    rawOut = runLivePass(followPrompt, null)
                    val parsed = ProviderPresets.parseThoughts(rawOut)
                    finalClean = parsed.second
                    val moodSplit = MoodDetector.extractInlineMoodTag(finalClean)
                    tagMood = moodSplit.first
                    finalBody = moodSplit.second
                    out = finalBody.ifBlank { finalClean.ifBlank { rawOut.trim() } }
                }

                val endCallTagged = out.contains("[END_CALL]", ignoreCase = true) ||
                    rawOut.contains("[END_CALL]", ignoreCase = true) ||
                    detectUserEndCallIntent(cleanTranscript)

                out = sanitizeLiveVoiceReply(UniversalLlmClient.sanitizeVisibleReply(out))
                    .ifBlank { if (endCallTagged) "Alright, talk to you soon!" else "Done!" }

                val mood = tagMood ?: MoodDetector.detectMood(out)
                val latency = (System.currentTimeMillis() - startMs).coerceAtLeast(1L)
                val estTokens = ProviderPresets.estimateTokens(out)

                val assistantMsgId = UUID.randomUUID().toString()
                val assistantEntity = MessageEntity(
                    id = assistantMsgId,
                    sessionId = sid,
                    parentId = userMsgId,
                    role = "assistant",
                    speakerLabel = persona.name,
                    content = out,
                    mood = mood,
                    providerName = prov.name,
                    modelName = prov.selectedModel,
                    tokenEstimate = estTokens,
                    latencyMs = latency,
                )
                dao.upsertMessage(assistantEntity)
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to assistantMsgId)
                refreshSessionStats(sid)

                onMoodChanged(mood)
                if (endCallTagged) {
                    onEndCallRequested()
                }
                onComplete(out)

                val isKeylessPollinations = prov.id == ProviderPresets.ID_POLLINATIONS_FREE && prov.apiKey.isBlank()
                if (prefs.moodMethod == "background_ai" && prov.protocol != "on_device" && !isKeylessPollinations) {
                    viewModelScope.launch {
                        val refined = llmClient.classifyMoodFast(prov, out)
                        if (!refined.isNullOrBlank()) {
                            onMoodChanged(refined)
                            dao.upsertMessage(assistantEntity.copy(mood = refined))
                        }
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                onError(e.localizedMessage ?: "Live Mode error with ${prov.name}")
            }
        }
    }

    // ── Providers, Personas, Memories, Templates, Local Models & Illume ──

    suspend fun saveProviderProfile(profile: ProviderProfileEntity) {
        dao.upsertProvider(profile.copy(updatedAtMs = System.currentTimeMillis()))
        scheduleBackgroundCloudSync()
    }

    suspend fun fetchLiveModels(profile: ProviderProfileEntity): Result<List<String>> {
        val res = llmClient.fetchModels(profile)
        res.onSuccess { list ->
            if (list.isNotEmpty()) {
                val chosenModel = when {
                    profile.selectedModel.isNotBlank() && profile.selectedModel in list -> profile.selectedModel
                    !profile.requiresKey -> list.first()
                    else -> ""
                }
                dao.upsertProvider(
                    profile.copy(
                        cachedModelsJson = ProviderPresets.encodeModels(list),
                        selectedModel = chosenModel,
                        updatedAtMs = System.currentTimeMillis(),
                    )
                )
                scheduleBackgroundCloudSync()
            }
        }
        return res
    }

    fun addCustomProvider(name: String, baseUrl: String, apiKey: String, model: String, protocol: String) {
        soundEngine.playPop()
        viewModelScope.launch {
            val id = "custom_${System.currentTimeMillis()}"
            dao.upsertProvider(
                ProviderProfileEntity(
                    id = id,
                    name = name.trim().ifBlank { "Custom Provider" },
                    badge = "router",
                    protocol = protocol,
                    baseUrl = baseUrl.trim(),
                    apiKey = apiKey.trim(),
                    selectedModel = model.trim(),
                    cachedModelsJson = if (model.isNotBlank()) ProviderPresets.encodeModels(listOf(model.trim())) else "[]",
                    requiresKey = apiKey.isNotBlank(),
                    isCustom = true,
                )
            )
            prefsStore.updateActiveProviderId(id)
            scheduleBackgroundCloudSync()
            showBanner("Added provider: $name")
        }
    }

    fun deleteCustomProvider(id: String) {
        viewModelScope.launch {
            dao.deleteProvider(id)
            if (preferences.value.activeProviderId == id) {
                prefsStore.updateActiveProviderId(ProviderPresets.ID_POLLINATIONS_FREE)
            }
        }
    }

    fun savePersona(
        existingId: String? = null,
        name: String,
        iconKey: String,
        tagline: String,
        systemPrompt: String,
        accentHex: String = "#A855F7",
    ) {
        soundEngine.playPop()
        viewModelScope.launch {
            val id = existingId?.takeIf { it.isNotBlank() } ?: UUID.randomUUID().toString()
            dao.upsertPersona(
                CustomPersonaEntity(
                    id = id,
                    name = name.trim().ifBlank { "Persona" },
                    iconKey = iconKey.trim().ifBlank { "sparkle" },
                    tagline = tagline.trim(),
                    systemPrompt = systemPrompt.trim(),
                    accentHex = accentHex.ifBlank { "#A855F7" },
                )
            )
            scheduleBackgroundCloudSync()
            showBanner(if (existingId != null) "Updated persona: $name" else "Saved persona: $name")
        }
    }

    fun addCustomPersona(name: String, iconKey: String, tagline: String, systemPrompt: String, accentHex: String = "#A855F7") {
        savePersona(null, name, iconKey, tagline, systemPrompt, accentHex)
    }

    fun deleteCustomPersona(id: String) {
        soundEngine.playClick()
        viewModelScope.launch {
            dao.deletePersona(id)
            val remaining = dao.getAllPersonasOnce()
            if (_uiState.value.activePersonaId == id && remaining.isNotEmpty()) {
                selectPersona(remaining.first().id)
            }
            scheduleBackgroundCloudSync()
        }
    }

    fun restoreDefaultPersonas() {
        soundEngine.playPop()
        viewModelScope.launch(Dispatchers.IO) {
            BuiltInPersonas.ALL.forEachIndexed { idx, p ->
                dao.upsertPersona(
                    CustomPersonaEntity(
                        id = p.id,
                        name = p.name,
                        iconKey = p.iconKey,
                        tagline = p.tagline,
                        systemPrompt = p.systemPrompt,
                        accentHex = p.accentHex,
                        createdAtMs = 1_700_000_000_000L + idx * 1000L,
                    )
                )
            }
            withContext(Dispatchers.Main) {
                showBanner("Restored all 8 default personas.")
            }
        }
    }

    fun addMemory(title: String, content: String) {
        soundEngine.playPop()
        viewModelScope.launch {
            dao.upsertMemory(MemoryEntity(UUID.randomUUID().toString(), title.trim(), content.trim()))
            scheduleBackgroundCloudSync()
            showBanner("Memory saved locally.")
        }
    }

    fun toggleMemory(memory: MemoryEntity) {
        viewModelScope.launch { dao.upsertMemory(memory.copy(enabled = !memory.enabled)) }
    }

    fun deleteMemory(id: String) {
        viewModelScope.launch { dao.deleteMemory(id) }
    }

    fun savePromptTemplate(existingId: String? = null, slashTrigger: String, title: String, body: String) {
        soundEngine.playPop()
        val normalized = if (existingId == ProviderPresets.ID_COMPACT_TEMPLATE) {
            "/compact"
        } else {
            slashTrigger.trim().let { if (it.startsWith("/")) it else "/$it" }
        }
        viewModelScope.launch {
            dao.upsertPromptTemplate(
                PromptTemplateEntity(
                    id = existingId?.takeIf { it.isNotBlank() } ?: UUID.randomUUID().toString(),
                    slashKey = normalized,
                    title = title.trim().ifBlank { normalized },
                    promptBody = body.trim(),
                )
            )
            scheduleBackgroundCloudSync()
            showBanner("Saved command $normalized")
        }
    }

    fun addPromptTemplate(slashTrigger: String, title: String, body: String) {
        savePromptTemplate(null, slashTrigger, title, body)
    }

    fun deletePromptTemplate(id: String) {
        if (id == ProviderPresets.ID_COMPACT_TEMPLATE) {
            showBanner("/compact is a built-in command and cannot be removed (you can edit its prompt).")
            return
        }
        viewModelScope.launch { dao.deletePromptTemplate(id) }
    }

    fun readAttachedTextFile(uri: Uri, onLoaded: (AttachedTextFile) -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val result = runCatching {
                val name = resolveUriDisplayName(uri).ifBlank { "document.txt" }
                val text = appContext.contentResolver.openInputStream(uri)?.bufferedReader()?.use { reader ->
                    val buf = CharArray(16_384)
                    val read = reader.read(buf)
                    if (read > 0) String(buf, 0, read) else ""
                }.orEmpty()
                require(text.isNotBlank()) { "Selected file appears empty or unreadable." }
                AttachedTextFile(name, text)
            }
            withContext(Dispatchers.Main) {
                result.onSuccess {
                    soundEngine.playPop()
                    onLoaded(it)
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun importKaggleJsonUri(uri: Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            val raw = runCatching {
                appContext.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }.orEmpty()
            }.getOrDefault("")
            val parsed = kaggleEngine.saveCredentialsFromJson(raw)
            withContext(Dispatchers.Main) {
                parsed.onSuccess { (username, key) ->
                    viewModelScope.launch {
                        prefsStore.updateKaggleConfig(
                            username = username,
                            key = key,
                            slug = KaggleImageEngine.DEFAULT_KERNEL_SLUG,
                            modelId = preferences.value.kaggleHfModel,
                        )
                        prefsStore.updateImagineConfig(
                            provider = "kaggle",
                            model = preferences.value.kagglePreset,
                            apiKey = preferences.value.imagineApiKey,
                            customUrl = preferences.value.imagineCustomUrl,
                        )
                        val (_, statusMsg) = kaggleEngine.validateCredentials(username, key)
                        _uiState.value = _uiState.value.copy(kaggleTestResult = statusMsg)
                        refreshKaggleCache()
                    }
                    soundEngine.playPop()
                    scheduleBackgroundCloudSync()
                    showBanner("Imported kaggle.json for @$username")
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun saveKaggleCredentials(
        username: String,
        apiKey: String,
        hfToken: String? = null,
        civitaiToken: String? = null,
    ) {
        secureKaggleStore.saveCredentials(username, apiKey)
        if (hfToken != null) secureKaggleStore.saveHfToken(hfToken)
        if (civitaiToken != null) secureKaggleStore.saveCivitaiToken(civitaiToken)
        viewModelScope.launch {
            prefsStore.updateKaggleConfig(
                username = username.trim(),
                key = apiKey.trim(),
                slug = KaggleImageEngine.DEFAULT_KERNEL_SLUG,
                modelId = preferences.value.kaggleHfModel,
            )
            scheduleBackgroundCloudSync()
        }
    }

    fun testKaggleConnection() {
        soundEngine.playClick()
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(kaggleTestResult = "Testing Kaggle API...")
            val (u, k) = kaggleEngine.getCredentials(preferences.value)
            val (ok, msg) = kaggleEngine.validateCredentials(u, k)
            _uiState.value = _uiState.value.copy(kaggleTestResult = msg)
            showSettingsFeedback(msg, isError = !ok)
            if (ok) refreshKaggleCache()
        }
    }

    fun refreshKaggleCache() {
        viewModelScope.launch {
            val res = kaggleEngine.refreshCacheMap(preferences.value)
            res.onSuccess { map ->
                _uiState.value = _uiState.value.copy(kaggleCacheStatusMap = map)
                prefsStore.updateKaggleFullSettings(cacheMapJson = kaggleEngine.encodeCacheMap(map))
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(kaggleCacheStatusText = err.localizedMessage ?: "Cache check failed")
            }
        }
    }

    fun buildKaggleCache(presetLabel: String) {
        if (_uiState.value.kaggleCacheBusyPreset != null) return
        soundEngine.playPop()
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                kaggleCacheBusyPreset = presetLabel,
                kaggleCacheStatusText = "Starting CPU-only cloud cache builder...",
            )
            val res = kaggleEngine.buildCloudCacheForPreset(
                prefs = preferences.value,
                presetLabel = presetLabel,
                onStatus = { st ->
                    _uiState.value = _uiState.value.copy(kaggleCacheStatusText = st)
                },
            )
            res.onSuccess { entry ->
                val updated = _uiState.value.kaggleCacheStatusMap + (presetLabel to entry)
                _uiState.value = _uiState.value.copy(
                    kaggleCacheBusyPreset = null,
                    kaggleCacheStatusText = "Cached $presetLabel (${String.format("%.2f", entry.bytes / 1_073_741_824.0)} GB)",
                    kaggleCacheStatusMap = updated,
                )
                prefsStore.updateKaggleFullSettings(cacheMapJson = kaggleEngine.encodeCacheMap(updated))
                showBanner("Cloud cache ready for $presetLabel")
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(
                    kaggleCacheBusyPreset = null,
                    kaggleCacheStatusText = err.localizedMessage ?: "Cache build failed",
                    errorMessage = err.localizedMessage,
                )
            }
        }
    }

    fun deleteKaggleCache(presetLabel: String) {
        soundEngine.playClick()
        viewModelScope.launch {
            val slug = KaggleImageEngine.presetSlug(presetLabel)
            val res = kaggleEngine.deleteCacheDataset(preferences.value, slug)
            res.onSuccess {
                val updated = _uiState.value.kaggleCacheStatusMap + (
                    presetLabel to KaggleImageEngine.CacheEntry(slug = slug, exists = false, healthy = false)
                )
                _uiState.value = _uiState.value.copy(
                    kaggleCacheStatusMap = updated,
                    kaggleCacheStatusText = "Deleted cloud cache $slug",
                )
                prefsStore.updateKaggleFullSettings(cacheMapJson = kaggleEngine.encodeCacheMap(updated))
                showBanner("Deleted cloud cache $slug")
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    suspend fun enhanceKagglePrompt(rawPrompt: String, useLlm: Boolean): Result<String> {
        if (!useLlm) {
            return Result.success(KaggleImageEngine.enhancePromptLocal(rawPrompt))
        }
        val prefs = preferences.value
        val activeProv = _uiState.value.activeProvider
        return kaggleEngine.enhancePromptWithLlm(
            rawPrompt = rawPrompt,
            provider = activeProv,
            modelOverride = prefs.kaggleEnhancerModel,
        )
    }

    // ── Offline Local Models (Zero-Copy SAF Mount + Free RAM) ────────────

    fun refreshLocalModelsList(rawJsonOverride: String? = null) {
        viewModelScope.launch(Dispatchers.IO) {
            val files = onDeviceEngine.listInstalledModels()
            val registered = prefsStore.decodeRegisteredLocalModels(
                rawJsonOverride ?: preferences.value.registeredLocalModelsJson
            )
            val unified = onDeviceEngine.listAllAvailableModels(registered)
            _uiState.value = _uiState.value.copy(
                installedLocalModels = files,
                registeredLocalModels = unified,
            )
        }
    }

    fun importLocalModel(uri: Uri, onLoadedNavigateToChat: (() -> Unit)? = null) {
        viewModelScope.launch {
            val res = onDeviceEngine.mountOrImportModelFromUri(uri)
            res.onSuccess { item ->
                // Persist in registered models list so it NEVER disappears after app restart!
                val current = prefsStore.decodeRegisteredLocalModels(preferences.value.registeredLocalModelsJson)
                    .filterNot { it.uriOrPath == item.uriOrPath }
                val updated = listOf(item) + current
                prefsStore.updateRegisteredLocalModelsJson(prefsStore.encodeRegisteredLocalModels(updated))
                refreshLocalModelsList(prefsStore.encodeRegisteredLocalModels(updated))
                loadLocalModel(item, onLoadedNavigateToChat)
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    fun downloadCuratedLocalModel(model: CuratedLocalModel, onLoadedNavigateToChat: (() -> Unit)? = null) {
        viewModelScope.launch {
            val res = onDeviceEngine.downloadCuratedModel(model)
            res.onSuccess { file ->
                val item = RegisteredLocalModel(
                    uriOrPath = file.absolutePath,
                    displayName = file.name,
                    sizeBytes = file.length(),
                    isContentUri = false,
                )
                refreshLocalModelsList()
                showBanner("Downloaded ${model.name}. Loading...")
                loadLocalModel(item, onLoadedNavigateToChat)
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    fun loadLocalModelFile(file: File, onLoadedNavigateToChat: (() -> Unit)? = null) {
        loadLocalModel(
            RegisteredLocalModel(
                uriOrPath = file.absolutePath,
                displayName = file.name,
                sizeBytes = file.length(),
                isContentUri = false,
            ),
            onLoadedNavigateToChat,
        )
    }

    fun loadLocalModel(item: RegisteredLocalModel, onLoadedNavigateToChat: (() -> Unit)? = null) {
        val st = _uiState.value.localModelStatus
        if (st.loading) return
        if (st.loaded && (st.modelPath == item.uriOrPath || st.modelName == item.displayName)) {
            viewModelScope.launch {
                val onDeviceProv = dao.getProvider(ProviderPresets.ID_ON_DEVICE)
                if (onDeviceProv != null && onDeviceProv.selectedModel != item.displayName) {
                    dao.upsertProvider(onDeviceProv.copy(selectedModel = item.displayName, updatedAtMs = System.currentTimeMillis()))
                }
                prefsStore.updateActiveProviderId(ProviderPresets.ID_ON_DEVICE)
                soundEngine.playPop()
                showBanner("${item.displayName} is already loaded — opening Chat.")
                onLoadedNavigateToChat?.invoke()
            }
            return
        }
        viewModelScope.launch {
            val prefs = preferences.value
            val res = onDeviceEngine.loadModel(
                uriOrPath = item.uriOrPath,
                displayName = item.displayName,
                maxTokens = prefs.contextModify.ggufMaxTokens,
                useGpu = prefs.localUseGpu,
                shizukuAutoGuard = prefs.shizukuAutoGuard,
                ggufConfig = prefs.contextModify,
            )
            res.onSuccess {
                prefsStore.updateLocalModel(item.uriOrPath, item.displayName, prefs.contextModify.ggufMaxTokens, prefs.localUseGpu)
                val onDeviceProv = dao.getProvider(ProviderPresets.ID_ON_DEVICE)
                if (onDeviceProv != null) {
                    dao.upsertProvider(onDeviceProv.copy(selectedModel = item.displayName, updatedAtMs = System.currentTimeMillis()))
                }
                prefsStore.updateActiveProviderId(ProviderPresets.ID_ON_DEVICE)
                soundEngine.playPop()
                showBanner("Loaded offline model: ${item.displayName}")
                onLoadedNavigateToChat?.invoke()
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    fun unloadLocalModel() {
        onDeviceEngine.unloadModel(stopGuard = true)
        showBanner("Offline model unloaded.")
    }

    fun deleteLocalModel(file: File) {
        deleteLocalModelItem(
            RegisteredLocalModel(
                uriOrPath = file.absolutePath,
                displayName = file.name,
                sizeBytes = file.length(),
                isContentUri = false,
            )
        )
    }

    fun deleteLocalModelItem(item: RegisteredLocalModel) {
        viewModelScope.launch(Dispatchers.IO) {
            onDeviceEngine.deleteLocalModel(item)
            val prefs = preferences.value
            val remaining = prefsStore.decodeRegisteredLocalModels(prefs.registeredLocalModelsJson)
                .filterNot { it.uriOrPath == item.uriOrPath || it.displayName == item.displayName }
            val encoded = prefsStore.encodeRegisteredLocalModels(remaining)
            prefsStore.updateRegisteredLocalModelsJson(encoded)

            val installedFallback = onDeviceEngine.listAllAvailableModels(remaining)
            val nextModel = installedFallback.firstOrNull()
            if (prefs.localModelPath == item.uriOrPath || prefs.localModelName == item.displayName) {
                prefsStore.updateLocalModel(
                    path = nextModel?.uriOrPath.orEmpty(),
                    name = nextModel?.displayName.orEmpty(),
                    maxTokens = prefs.localMaxTokens,
                    useGpu = prefs.localUseGpu,
                )
            }
            val onDeviceProv = dao.getProvider(ProviderPresets.ID_ON_DEVICE)
            if (onDeviceProv != null && (onDeviceProv.selectedModel == item.displayName || installedFallback.isEmpty())) {
                dao.upsertProvider(
                    onDeviceProv.copy(
                        selectedModel = nextModel?.displayName ?: "No local model loaded",
                        updatedAtMs = System.currentTimeMillis(),
                    )
                )
            }
            refreshLocalModelsList(encoded)
        }
    }

    fun freeAllRam() {
        soundEngine.playPop()
        viewModelScope.launch {
            val shizukuConnected = _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_SHELL ||
                _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_ROOT
            val freedMb = onDeviceEngine.reclaimInternalRam(includeShizuku = shizukuConnected)
            val avail = onDeviceEngine.availableDeviceRamMb()
            if (!shizukuConnected) {
                val warn = "Shizuku is NOT connected — only cleared Cellium's own RAM (~${freedMb} MB; ${avail} MB device free). Start & authorize Shizuku in Agent & Shizuku to free your phone's full RAM."
                showSettingsFeedback(warn, isError = true)
            } else {
                val msg = if (freedMb > 0) {
                    "Freed ~${freedMb} MB across device via Shizuku (${avail} MB now free)."
                } else {
                    "Device RAM trimmed & caches cleared via Shizuku (${avail} MB available)."
                }
                showSettingsFeedback(msg, isError = false)
            }
        }
    }

    // ── Illume Artwork Engine ────────────────────────────────────────────

    suspend fun generateArtwork(
        prompt: String,
        negativePrompt: String = "",
        aspectRatio: String = "1:1",
        providerOverride: String? = null,
        modelOverride: String? = null,
    ): Result<ArtworkEntity> {
        val prefs = preferences.value
        val provider = providerOverride ?: prefs.imagineProvider
        if (provider == "kaggle") {
            val sizeLabel = when (aspectRatio) {
                "16:9" -> "1216x832 (16:9)"
                "9:16" -> "832x1216 (9:16)"
                "4:3" -> "1152x896 (4:3)"
                "3:4" -> "896x1152 (3:4)"
                "1:1" -> "1024x1024 (1:1)"
                else -> prefs.kaggleSize
            }
            return generateKaggleBatch(
                prompt = prompt,
                stickyPrompt = prefs.kaggleStickyPrompt,
                negativePrompt = negativePrompt.ifBlank { prefs.kaggleNegativePrompt },
                presetLabel = modelOverride?.takeIf { lbl -> KaggleImageEngine.MODEL_PRESETS.any { it.label == lbl } }
                    ?: prefs.kagglePreset,
                sizeLabel = sizeLabel,
                steps = prefs.kaggleSteps,
                guidance = prefs.kaggleGuidance,
                batch = 1,
                seed = prefs.kaggleSeed,
            ).map { it.first() }
        }
        val model = modelOverride ?: prefs.imagineModel
        _uiState.value = _uiState.value.copy(isGeneratingImage = true, imagineStatusText = "Starting Illume...", errorMessage = null)
        val res = imagineClient.generateImage(
            prompt = prompt,
            negativePrompt = negativePrompt,
            provider = provider,
            model = model,
            aspectRatio = aspectRatio,
            apiKey = prefs.imagineApiKey,
            customUrl = prefs.imagineCustomUrl,
            kaggleUsername = prefs.kaggleUsername,
            kaggleKey = prefs.kaggleKey,
            kaggleKernelSlug = prefs.kaggleKernelSlug,
            onStatusUpdate = { status ->
                _uiState.value = _uiState.value.copy(imagineStatusText = status)
            },
        )
        _uiState.value = _uiState.value.copy(isGeneratingImage = false, imagineStatusText = "")
        return res.map { gen ->
            val entity = ArtworkEntity(
                id = UUID.randomUUID().toString(),
                prompt = prompt,
                negativePrompt = negativePrompt,
                provider = gen.provider,
                model = gen.model,
                aspectRatio = aspectRatio,
                seed = gen.seed,
                localPath = gen.localFile.absolutePath,
            )
            dao.upsertArtwork(entity)
            _uiState.value = _uiState.value.copy(lastGeneratedImagePath = entity.localPath)
            soundEngine.playPop()
            entity
        }
    }

    suspend fun generateKaggleBatch(
        prompt: String,
        stickyPrompt: String = "",
        negativePrompt: String = KaggleImageEngine.DEFAULT_NEGATIVE_PROMPT,
        presetLabel: String = preferences.value.kagglePreset,
        sizeLabel: String = preferences.value.kaggleSize,
        steps: Int = preferences.value.kaggleSteps,
        guidance: Float = preferences.value.kaggleGuidance,
        batch: Int = preferences.value.kaggleBatch,
        seed: Long = preferences.value.kaggleSeed,
        initImagePath: String? = null,
        denoise: Float = 0.75f,
        onStatus: ((String) -> Unit)? = null,
    ): Result<List<ArtworkEntity>> {
        val prefs = preferences.value
        val combinedPrompt = buildString {
            append(prompt.trim())
            val sticky = stickyPrompt.trim()
            if (sticky.isNotBlank() && !prompt.contains(sticky, ignoreCase = true)) {
                if (isNotEmpty()) append(", ")
                append(sticky)
            }
        }
        val (w, h) = KaggleImageEngine.parseSize(sizeLabel)
        val initB64 = if (!initImagePath.isNullOrBlank()) {
            withContext(Dispatchers.IO) { KaggleImageEngine.encodeInitImageBase64(File(initImagePath)) }.orEmpty()
        } else ""
        val req = KaggleImageEngine.GenerationRequest(
            prompt = combinedPrompt,
            negativePrompt = negativePrompt.ifBlank { KaggleImageEngine.DEFAULT_NEGATIVE_PROMPT },
            steps = steps.coerceIn(1, 100),
            width = w,
            height = h,
            seed = seed,
            guidanceScale = guidance.coerceIn(0f, 20f),
            batch = batch.coerceIn(1, 20),
            initB64 = initB64,
            denoise = denoise.coerceIn(0.1f, 0.95f),
        )
        _uiState.value = _uiState.value.copy(
            isGeneratingImage = true,
            imagineStatusText = "Pushing Kaggle GPU render...",
            errorMessage = null,
        )
        val res = kaggleEngine.render(
            prefs = prefs,
            request = req,
            presetOverride = presetLabel,
            onProgress = { prog ->
                val formatted = KaggleImageEngine.formatStage(prog.stage, prog.detail)
                _uiState.value = _uiState.value.copy(imagineStatusText = formatted)
                onStatus?.invoke(formatted)
            },
        )
        _uiState.value = _uiState.value.copy(isGeneratingImage = false, imagineStatusText = "")
        return res.map { gen ->
            val entities = gen.allFiles.mapIndexed { idx, file ->
                val usedSeed = gen.seeds.getOrElse(idx) { if (seed >= 0L) seed + idx else -1L }
                ArtworkEntity(
                    id = UUID.randomUUID().toString(),
                    prompt = combinedPrompt,
                    negativePrompt = req.negativePrompt,
                    provider = "Kaggle GPU",
                    model = gen.presetLabel.ifBlank { presetLabel },
                    aspectRatio = sizeLabel.substringAfter("(").substringBefore(")").ifBlank { "${w}x${h}" },
                    seed = usedSeed,
                    localPath = file.absolutePath,
                )
            }
            entities.forEach { dao.upsertArtwork(it) }
            entities.firstOrNull()?.let { first ->
                _uiState.value = _uiState.value.copy(lastGeneratedImagePath = first.localPath)
            }
            soundEngine.playPop()
            entities
        }
    }

    fun saveArtworkToPhotos(artwork: ArtworkEntity) {
        viewModelScope.launch {
            val res = imagineClient.saveToDevicePhotos(File(artwork.localPath))
            res.onSuccess { showBanner(it) }
                .onFailure { _uiState.value = _uiState.value.copy(errorMessage = it.localizedMessage) }
        }
    }

    fun saveImageToDownloadsCellium(sourcePath: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val res = runCatching {
                val src = File(sourcePath)
                require(src.exists()) { "Image file no longer exists on device." }
                val ext = src.extension.lowercase().ifBlank { "png" }
                val mime = when (ext) {
                    "jpg", "jpeg" -> "image/jpeg"
                    "webp" -> "image/webp"
                    else -> "image/png"
                }
                val fileName = "Cellium_${System.currentTimeMillis()}.$ext"
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    val values = ContentValues().apply {
                        put(MediaStore.Downloads.DISPLAY_NAME, fileName)
                        put(MediaStore.Downloads.MIME_TYPE, mime)
                        put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/Cellium")
                    }
                    val resolver = appContext.contentResolver
                    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                        ?: throw IllegalStateException("Could not create Downloads/Cellium entry.")
                    resolver.openOutputStream(uri)?.use { out ->
                        src.inputStream().use { inp -> inp.copyTo(out) }
                    } ?: throw IllegalStateException("Could not open Downloads stream.")
                } else {
                    @Suppress("DEPRECATION")
                    val dlDir = File(
                        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                        "Cellium",
                    ).apply { mkdirs() }
                    src.copyTo(File(dlDir, fileName), overwrite = true)
                }
                "Saved to Downloads/Cellium/$fileName"
            }
            withContext(Dispatchers.Main) {
                res.onSuccess {
                    soundEngine.playPop()
                    showBanner(it)
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun saveImageToUri(sourcePath: String, targetUri: Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            val res = runCatching {
                val src = File(sourcePath)
                require(src.exists()) { "Image file no longer exists on device." }
                appContext.contentResolver.openOutputStream(targetUri)?.use { out ->
                    src.inputStream().use { inp -> inp.copyTo(out) }
                } ?: throw IllegalStateException("Unable to write to chosen location.")
                "Image saved successfully."
            }
            withContext(Dispatchers.Main) {
                res.onSuccess {
                    soundEngine.playPop()
                    showBanner(it)
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun deleteArtwork(artwork: ArtworkEntity) {
        viewModelScope.launch(Dispatchers.IO) {
            File(artwork.localPath).delete()
            dao.deleteArtwork(artwork.id)
        }
    }

    fun sendArtworkToChat(artwork: ArtworkEntity) {
        viewModelScope.launch {
            val sid = ensureActiveSession("Illume: ${artwork.prompt.take(32)}")
            val parentId = _uiState.value.activeMessages.lastOrNull()?.id
            val msgId = UUID.randomUUID().toString()
            dao.upsertMessage(
                MessageEntity(
                    id = msgId,
                    sessionId = sid,
                    parentId = parentId,
                    role = "assistant",
                    content = "Generated artwork for **\"${artwork.prompt}\"** via ${artwork.provider} (`${artwork.model}`).",
                    mood = "happy",
                    providerName = artwork.provider,
                    modelName = artwork.model,
                    attachmentPath = artwork.localPath,
                )
            )
            _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to msgId)
            refreshSessionStats(sid)
            showBanner("Artwork posted to Chat.")
        }
    }

    // ── Backup JSON, Export, Shizuku & Cloud Sync + Quota Manager ────────

    fun exportFullBackupToUri(uri: Uri, includeApiKeys: Boolean) {
        viewModelScope.launch(Dispatchers.IO) {
            val res = runCatching {
                val payload = backupManager.exportToJson(includeApiKeys)
                appContext.contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(payload.toByteArray(Charsets.UTF_8))
                } ?: throw IllegalStateException("Could not write backup file.")
            }
            withContext(Dispatchers.Main) {
                res.onSuccess {
                    soundEngine.playPop()
                    showBanner("Full backup saved (${if (includeApiKeys) "with" else "without"} API keys).")
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun importFullBackupFromUri(uri: Uri) {
        viewModelScope.launch(Dispatchers.IO) {
            val raw = runCatching {
                appContext.contentResolver.openInputStream(uri)?.bufferedReader()?.use { it.readText() }.orEmpty()
            }.getOrDefault("")
            val res = backupManager.importFromJson(raw)
            withContext(Dispatchers.Main) {
                res.onSuccess { r ->
                    soundEngine.playPop()
                    showBanner("Restored ${r.sessionsRestored} chats, ${r.messagesRestored} msgs, ${r.personasRestored} personas.")
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = "Invalid backup JSON: ${err.localizedMessage}")
                }
            }
        }
    }

    fun exportActiveSessionMarkdown(): String? {
        val sess = _uiState.value.activeSession ?: return null
        return ChatTreeHelper.exportAsMarkdown(sess, _uiState.value.activeMessages)
    }

    fun exportActiveSessionJson(): String? {
        val sess = _uiState.value.activeSession ?: return null
        return ChatTreeHelper.exportAsJson(sess, _uiState.value.activeMessages)
    }

    fun triggerManualShizukuAntiKill() {
        soundEngine.playPop()
        viewModelScope.launch {
            MemoryGuardService.start(appContext, "Manual Shizuku Anti-Kill Active")
            val res = shizukuBridge.applyAntiKillProtection(reason = "Manual boost")
            res.onSuccess { showSettingsFeedback("Anti-Kill applied: ${it.take(120)}", isError = false) }
                .onFailure { showSettingsFeedback(it.localizedMessage ?: "Shizuku Anti-Kill failed", isError = true) }
        }
    }

    fun testShizukuCommand() {
        soundEngine.playClick()
        viewModelScope.launch {
            val res = shizukuBridge.runCommand("id && uname -m")
            res.onSuccess { out ->
                val clean = out.trim().ifBlank { "OK" }
                showSettingsFeedback("Shizuku shell OK: $clean", isError = false)
            }.onFailure { err ->
                showSettingsFeedback(err.localizedMessage ?: "Shizuku shell test failed", isError = true)
            }
        }
    }

    /**
     * Called immediately after signing in with Google from Guest Mode.
     * If BOTH local guest data and cloud account data exist, prompts the user to pick
     * Merge Both, Keep Local (Replace Cloud), or Keep Cloud (Replace Local).
     */
    fun checkAndSyncAfterGoogleSignIn() {
        viewModelScope.launch {
            val hasLocal = dao.getAllSessionsOnce().isNotEmpty() ||
                dao.getAllProviders().any { it.apiKey.isNotBlank() }
            val hasCloud = cloudSync.hasCloudData()
            if (hasLocal && hasCloud) {
                _uiState.value = _uiState.value.copy(pendingSyncConflict = true)
            } else {
                syncWithGoogleCloud(silent = false, mode = CloudSyncMode.MERGE_BOTH)
            }
        }
    }

    fun resolveSyncConflict(mode: CloudSyncMode) {
        _uiState.value = _uiState.value.copy(pendingSyncConflict = false)
        syncWithGoogleCloud(silent = false, mode = mode)
    }

    fun dismissSyncConflict() {
        _uiState.value = _uiState.value.copy(pendingSyncConflict = false)
    }

    fun setShizukuHideMicDot(enabled: Boolean) {
        soundEngine.playClick()
        viewModelScope.launch {
            val shizukuConnected = _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_SHELL ||
                _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_ROOT
            if (!shizukuConnected) {
                prefsStore.updateWakeWordSettings(
                    enabled = preferences.value.wakeWordEnabled,
                    shizukuHideDot = false,
                )
                showSettingsFeedback(
                    "Shizuku is not connected. Authorize Shizuku first to toggle the Android privacy indicator flag.",
                    isError = true,
                )
                return@launch
            }
            val flagVal = if (enabled) "false" else "true"
            val res = shizukuBridge.runCommand(
                "cmd device_config put privacy camera_mic_icons_enabled $flagVal default",
                timeoutSec = 10,
            )
            res.onSuccess {
                prefsStore.updateWakeWordSettings(
                    enabled = preferences.value.wakeWordEnabled,
                    shizukuHideDot = enabled,
                )
                showSettingsFeedback(
                    if (enabled) {
                        "System mic/camera privacy dot hidden OS-wide via Shizuku. Turn this OFF anytime to restore."
                    } else {
                        "Android system mic/camera privacy dot restored."
                    },
                    isError = false,
                )
            }.onFailure { err ->
                showSettingsFeedback(
                    "Failed updating privacy dot via Shizuku: ${err.localizedMessage}",
                    isError = true,
                )
            }
        }
    }

    fun syncWithGoogleCloud(silent: Boolean = false, mode: CloudSyncMode = CloudSyncMode.MERGE_BOTH) {
        viewModelScope.launch {
            if (!silent) {
                _uiState.value = _uiState.value.copy(isSyncingCloud = true, errorMessage = null, cloudStorageError = null)
            }
            val res = cloudSync.syncNow(preferences.value, mode)
            if (!silent) {
                _uiState.value = _uiState.value.copy(isSyncingCloud = false)
                res.onSuccess { report ->
                    if (report.storageSummary != null) {
                        _uiState.value = _uiState.value.copy(
                            cloudStorageSummary = report.storageSummary,
                            cloudStorageError = null,
                        )
                    } else {
                        refreshCloudStorage()
                    }
                    showSettingsFeedback(report.message, isError = false)
                }.onFailure {
                    showSettingsFeedback(it.localizedMessage ?: "Cloud sync failed", isError = true)
                }
            }
        }
    }

    fun refreshCloudStorage() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(cloudStorageLoading = true, cloudStorageError = null)
            val res = cloudSync.inspectCloudStorage()
            res.onSuccess { summary ->
                _uiState.value = _uiState.value.copy(
                    cloudStorageLoading = false,
                    cloudStorageSummary = summary,
                    cloudStorageError = null,
                )
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(
                    cloudStorageLoading = false,
                    cloudStorageError = err.localizedMessage ?: "Failed inspecting cloud storage.",
                )
            }
        }
    }

    fun deleteCloudStorageItem(collection: String, docId: String) {
        soundEngine.playClick()
        viewModelScope.launch {
            val res = cloudSync.deleteCloudItem(collection, docId)
            res.onSuccess {
                showSettingsFeedback("Deleted item from Cloud.", isError = false)
                refreshCloudStorage()
            }.onFailure {
                showSettingsFeedback(it.localizedMessage ?: "Cloud delete failed", isError = true)
            }
        }
    }

    private fun scheduleBackgroundCloudSync() {
        if (Firebase.auth.currentUser == null) return
        autoSyncJob?.cancel()
        autoSyncJob = viewModelScope.launch {
            delay(2500L)
            cloudSync.syncNow(preferences.value)
        }
    }

    fun clearBanner() { _uiState.value = _uiState.value.copy(bannerMessage = null) }
    fun clearError() { _uiState.value = _uiState.value.copy(errorMessage = null) }
    fun showBanner(msg: String) { _uiState.value = _uiState.value.copy(bannerMessage = msg) }
    fun showSettingsFeedback(msg: String, isError: Boolean = false) {
        _uiState.value = _uiState.value.copy(
            settingsFeedbackMessage = msg,
            settingsFeedbackIsError = isError,
        )
    }
    fun clearSettingsFeedback() {
        _uiState.value = _uiState.value.copy(
            settingsFeedbackMessage = null,
            settingsFeedbackIsError = false,
        )
    }

    // ── Internals ────────────────────────────────────────────────────────

    private suspend fun ensureActiveSession(firstPromptHint: String): String {
        val existing = _activeSessionId.value
        if (!existing.isNullOrBlank() && dao.getSession(existing) != null) return existing
        val id = UUID.randomUUID().toString()
        val prov = _uiState.value.activeProvider
        val autoTitle = buildSmartTitle(firstPromptHint)
        dao.upsertSession(
            SessionEntity(
                id = id,
                title = autoTitle,
                personaId = _uiState.value.activePersonaId,
                providerId = prov?.id ?: ProviderPresets.ID_POLLINATIONS_FREE,
                modelName = prov?.selectedModel.orEmpty(),
            )
        )
        _activeSessionId.value = id
        return id
    }

    private suspend fun refreshSessionStats(sessionId: String, firstPromptHint: String? = null) {
        val sess = dao.getSession(sessionId) ?: return
        val allMsgs = dao.getMessagesForSessionOnce(sessionId)
        val leaf = _selectedLeafBySession.value[sessionId] ?: allMsgs.lastOrNull()?.id.orEmpty()
        val path = ChatTreeHelper.buildActivePath(allMsgs, leaf).messages
        val title = if (sess.title == "New Chat" && !firstPromptHint.isNullOrBlank()) {
            buildSmartTitle(firstPromptHint)
        } else sess.title
        dao.upsertSession(
            sess.copy(
                title = title,
                activeLeafId = leaf,
                messageCount = path.size,
                tokenCount = path.sumOf { it.tokenEstimate },
                lastMessagePreview = path.lastOrNull()?.content?.take(140).orEmpty(),
                updatedAtMs = System.currentTimeMillis(),
            )
        )
        scheduleBackgroundCloudSync()
    }

    private fun buildSmartTitle(raw: String): String {
        val cleaned = raw.replace(Regex("[\\r\\n]+"), " ").replace(Regex("\\s+"), " ").trim()
        if (cleaned.isEmpty()) return "New Chat"
        val words = cleaned.split(" ").take(6).joinToString(" ")
        return words.take(44)
    }

    private fun attachmentsDir(): File {
        val dir = appContext.getExternalFilesDir("attachments") ?: File(appContext.filesDir, "attachments")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    private fun webImagesDir(): File {
        val dir = appContext.getExternalFilesDir("web_images") ?: File(appContext.filesDir, "web_images")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    private fun resolveLocalWorkspaceDir(): File {
        val preferred = File(preferences.value.agentWorkspacePath.trim().ifBlank { "/sdcard/Documents/CelliumProjects" })
        if (runCatching { preferred.mkdirs(); preferred.exists() && preferred.canWrite() }.getOrDefault(false)) {
            return preferred
        }
        val fallback = appContext.getExternalFilesDir("agent_workspace") ?: File(appContext.filesDir, "agent_workspace")
        if (!fallback.exists()) fallback.mkdirs()
        return fallback
    }

    private fun copyImageToAgentWorkspace(sourceFile: File): String? = runCatching {
        if (!sourceFile.exists()) return@runCatching null
        val wsImages = File(resolveLocalWorkspaceDir(), "images").apply { mkdirs() }
        val dest = File(wsImages, sourceFile.name)
        sourceFile.copyTo(dest, overwrite = true)
        dest.absolutePath
    }.getOrNull()

    private fun saveAttachmentLocally(bitmap: Bitmap): String = runCatching {
        val dir = attachmentsDir()
        val f = File(dir, "att_${System.currentTimeMillis()}_${UUID.randomUUID().toString().take(6)}.jpg")
        FileOutputStream(f).use { bitmap.compress(Bitmap.CompressFormat.JPEG, 80, it) }
        f.absolutePath
    }.getOrDefault("")

    private fun decodeScaledBitmapFromFile(file: File, maxDim: Int = 1280): Bitmap? = runCatching {
        if (!file.exists() || !file.canRead() || file.length() <= 0L) return@runCatching null
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@runCatching null
        var sample = 1
        while (bounds.outWidth / sample > maxDim * 2 || bounds.outHeight / sample > maxDim * 2) {
            sample *= 2
        }
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        BitmapFactory.decodeFile(file.absolutePath, opts)
    }.getOrNull()

    private fun loadBitmapsFromAttachmentPaths(attachmentPath: String): List<Bitmap> {
        if (attachmentPath.isBlank()) return emptyList()
        return attachmentPath.lines()
            .map { it.trim() }
            .filter { it.isNotBlank() }
            .take(5)
            .mapNotNull { decodeScaledBitmapFromFile(File(it)) }
    }

    private suspend fun loadLocalOrShizukuBitmap(rawPath: String, shizukuConnected: Boolean): Bitmap? {
        val trimmed = rawPath.trim()
        if (trimmed.isEmpty()) return null
        val directFile = File(trimmed)
        if (directFile.exists() && directFile.canRead()) {
            decodeScaledBitmapFromFile(directFile)?.let { return it }
        }
        val wsCandidate = File(resolveLocalWorkspaceDir(), trimmed.removePrefix("/"))
        if (wsCandidate.exists() && wsCandidate.canRead()) {
            decodeScaledBitmapFromFile(wsCandidate)?.let { return it }
        }
        if (shizukuConnected) {
            val escaped = trimmed.replace("'", "'\\''")
            val res = shizukuBridge.runCommand("base64 -w 0 '$escaped' 2>/dev/null || base64 '$escaped'", timeoutSec = 10)
            val b64 = res.getOrNull()?.replace(Regex("\\s+"), "").orEmpty()
            if (b64.isNotBlank() && b64.length < 16_000_000) {
                return runCatching {
                    val bytes = Base64.decode(b64, Base64.DEFAULT)
                    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@runCatching null
                    var sample = 1
                    while (bounds.outWidth / sample > 2560 || bounds.outHeight / sample > 2560) {
                        sample *= 2
                    }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, BitmapFactory.Options().apply { inSampleSize = sample })
                }.getOrNull()
            }
        }
        return null
    }

    private fun resolveUriDisplayName(uri: Uri): String {
        appContext.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { c ->
                if (c.moveToFirst()) {
                    val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) return c.getString(idx).orEmpty()
                }
            }
        return uri.lastPathSegment?.substringAfterLast('/').orEmpty()
    }

    override fun onCleared() {
        super.onCleared()
        arenaController.stop()
        shizukuBridge.unregisterListeners()
        soundEngine.release()
        ttsEngine.release()
    }
}

package com.henny.cellium.ui.chat

import android.app.Application
import android.graphics.Bitmap
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.firebase.Firebase
import com.google.firebase.auth.auth
import com.henny.cellium.ai.CuratedLocalModel
import com.henny.cellium.ai.LocalModelStatus
import com.henny.cellium.ai.MultiImagineClient
import com.henny.cellium.ai.OnDeviceLlmEngine
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderCatalogEntry
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.ai.WebToolsClient
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumNotificationManager
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.core.PreferencesStore
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
import com.henny.cellium.data.sync.CloudSyncManager
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
    val currentMood: String = "idle",
    val pendingGuard: PendingAgentGuard? = null,
    val shizukuStatus: ShizukuStatus = ShizukuStatus.NOT_RUNNING,
    val shizukuAntiKill: Boolean = false,
    val shizukuReport: String = "Shizuku standby",
    val localModelStatus: LocalModelStatus = LocalModelStatus(),
    val installedLocalModels: List<File> = emptyList(),
    val isGeneratingImage: Boolean = false,
    val imagineStatusText: String = "",
    val isSyncingCloud: Boolean = false,
    val bannerMessage: String? = null,
    val errorMessage: String? = null,
) {
    val activeSession: SessionEntity?
        get() = sessions.firstOrNull { it.id == activeSessionId }

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
            }
        )
}

@OptIn(ExperimentalCoroutinesApi::class)
class CelliumViewModel(application: Application) : AndroidViewModel(application) {
    private val appContext = application.applicationContext
    private val db = CelliumDatabase.getInstance(appContext)
    private val dao = db.dao()

    val prefsStore = PreferencesStore(appContext)
    val soundEngine = CelliumSoundEngine(appContext)
    val shizukuBridge = ShizukuBridge(appContext)
    val llmClient = UniversalLlmClient()
    val webTools = WebToolsClient()
    val onDeviceEngine = OnDeviceLlmEngine(appContext, shizukuBridge)
    val imagineClient = MultiImagineClient(appContext)
    val backupManager = AppBackupManager(dao)
    private val cloudSync = CloudSyncManager(dao, prefsStore)

    private val _preferencesLoaded = MutableStateFlow(false)
    val preferencesLoaded: StateFlow<Boolean> = _preferencesLoaded.asStateFlow()

    val preferences: StateFlow<CelliumPreferences> = prefsStore.preferencesFlow
        .onEach { _preferencesLoaded.value = true }
        .stateIn(
            scope = viewModelScope,
            started = SharingStarted.Eagerly,
            initialValue = prefsStore.readCachedInitialPreferences(),
        )

    /**
     * Decoupled RAM telemetry flow — collected ONLY inside Settings RAM Watchdog
     * so polling every 5s NEVER recomposes Chat, Imagine, or Live screens!
     */
    private val _processRamMb = MutableStateFlow(0)
    val processRamMb: StateFlow<Int> = _processRamMb.asStateFlow()

    private val _activeSessionId = MutableStateFlow<String?>(null)
    private val _selectedLeafBySession = MutableStateFlow<Map<String, String>>(emptyMap())
    private val _uiState = MutableStateFlow(CelliumUiState())
    val uiState: StateFlow<CelliumUiState> = _uiState.asStateFlow()

    @Volatile private var appInForeground = true
    @Volatile private var currentVisibleTab = "chat"

    val arenaController = ArenaController(
        scope = viewModelScope,
        dao = dao,
        llmClient = llmClient,
        onDeviceEngine = onDeviceEngine,
        soundEngine = soundEngine,
        providersProvider = { _uiState.value.providers },
        customPersonasProvider = { _uiState.value.customPersonas },
        memoriesProvider = { _uiState.value.memories },
        onNotifyIfBackground = { sid, title, speaker, text ->
            maybePostReplyNotification(sid, title, speaker, text)
        },
    )

    private var streamJob: Job? = null
    private var autoSyncJob: Job? = null
    private var autoGuardTriggeredForPeak = false

    init {
        shizukuBridge.registerListeners()
        seedDefaultsIfNeeded()
        observeCoreFlows()
        observeDirectReplies()
        startRamWatchdog()
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

    private fun maybePostReplyNotification(sessionId: String, title: String, sender: String, text: String) {
        if (!preferences.value.notificationsEnabled) return
        val viewingThisChat = appInForeground && currentVisibleTab == "chat" && _activeSessionId.value == sessionId
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
                    attachmentBitmap = null,
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
            if (dao.getAllPromptTemplatesOnce().isEmpty()) {
                dao.insertPromptTemplatesIfMissing(ProviderPresets.defaultPromptTemplates())
            }
            refreshLocalModelsList()
        }
    }

    private fun observeCoreFlows() {
        viewModelScope.launch {
            preferences.collectLatest { p ->
                soundEngine.enabled = p.soundsEnabled
                soundEngine.animaleseEnabled = p.animaleseEnabled
                soundEngine.hapticsEnabled = p.hapticsEnabled
                soundEngine.masterVolume = p.sfxVolume
                val currentProviders = _uiState.value.providers
                val activeProv = currentProviders.firstOrNull { it.id == p.activeProviderId }
                    ?: currentProviders.firstOrNull()
                _uiState.value = _uiState.value.copy(activeProvider = activeProv)
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
                    regular.firstOrNull { !it.archived }?.id ?: regular.firstOrNull()?.id
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
            ) { allMsgs, sid, leafMap ->
                val sessionLeaf = sid?.let {
                    leafMap[it] ?: _uiState.value.sessions.firstOrNull { s -> s.id == it }?.activeLeafId
                }
                ChatTreeHelper.buildActivePath(allMsgs, sessionLeaf)
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
                _activeSessionId.value = _uiState.value.sessions.firstOrNull { it.id != sessionId && !it.isArena }?.id
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
     * For User messages, optionally regenerates Cel's reply right below.
     */
    fun editMessageInPlace(original: MessageEntity, editedText: String, regenerateIfUser: Boolean = false) {
        val clean = editedText.trim()
        if (clean.isEmpty()) return
        soundEngine.playClick()
        viewModelScope.launch {
            dao.upsertMessage(
                original.copy(
                    content = clean,
                    tokenEstimate = ProviderPresets.estimateTokens(clean),
                    isError = false,
                )
            )
            refreshSessionStats(original.sessionId)
            if (original.role == "user" && regenerateIfUser && !_uiState.value.isStreaming) {
                val all = dao.getMessagesForSessionOnce(original.sessionId)
                val historyBefore = if (original.parentId != null) {
                    ChatTreeHelper.buildActivePath(all, original.parentId).messages
                } else emptyList()
                runAssistantGeneration(
                    sessionId = original.sessionId,
                    parentMessageId = original.id,
                    historyBeforePrompt = historyBefore,
                    promptText = clean,
                    attachmentBitmap = null,
                    attachedFile = null,
                )
            }
        }
    }

    /**
     * Edit ANY message (User OR Cel Assistant) as a brand-new sibling branch!
     * User branch triggers a fresh Cel reply; Assistant branch inserts an edited sibling version.
     */
    fun editMessageAsBranch(original: MessageEntity, editedText: String, regenerateIfUser: Boolean = true) {
        val clean = editedText.trim()
        if (clean.isEmpty()) return
        soundEngine.playPop()
        if (original.role == "user") {
            if (regenerateIfUser && !_uiState.value.isStreaming) {
                sendMessageInternal(
                    prompt = clean,
                    attachmentBitmap = null,
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
            // Cel / Assistant sibling branch!
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
            val all = dao.getMessagesForSessionOnce(assistantMsg.sessionId)
            val parentUser = all.firstOrNull { it.id == assistantMsg.parentId } ?: return@launch
            val branchBeforeUser = if (parentUser.parentId != null) {
                ChatTreeHelper.buildActivePath(all, parentUser.parentId).messages
            } else emptyList()
            val file = if (parentUser.attachmentFileName.isNotBlank()) {
                AttachedTextFile(parentUser.attachmentFileName, parentUser.attachmentFileContent)
            } else null
            runAssistantGeneration(
                sessionId = assistantMsg.sessionId,
                parentMessageId = parentUser.id,
                historyBeforePrompt = branchBeforeUser,
                promptText = parentUser.content,
                attachmentBitmap = null,
                attachedFile = file,
            )
        }
    }

    fun retryLastUserTurn() {
        val lastUser = _uiState.value.activeMessages.lastOrNull { it.role == "user" } ?: return
        if (_uiState.value.isStreaming) return
        soundEngine.playClick()
        viewModelScope.launch {
            val all = dao.getMessagesForSessionOnce(lastUser.sessionId)
            val before = if (lastUser.parentId != null) {
                ChatTreeHelper.buildActivePath(all, lastUser.parentId).messages
            } else emptyList()
            val file = if (lastUser.attachmentFileName.isNotBlank()) {
                AttachedTextFile(lastUser.attachmentFileName, lastUser.attachmentFileContent)
            } else null
            runAssistantGeneration(
                sessionId = lastUser.sessionId,
                parentMessageId = lastUser.id,
                historyBeforePrompt = before,
                promptText = lastUser.content,
                attachmentBitmap = null,
                attachedFile = file,
            )
        }
    }

    // ── Chat Sending, Slash Commands, Web Tools & Streaming ──────────────

    fun sendMessage(
        prompt: String,
        attachmentBitmap: Bitmap? = null,
        attachedFile: AttachedTextFile? = null,
    ) {
        val trimmed = prompt.trim()
        if ((trimmed.isEmpty() && attachmentBitmap == null && attachedFile == null) || _uiState.value.isStreaming) return

        // /clear
        if (trimmed.equals("/clear", ignoreCase = true)) {
            startNewSession()
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

        // /imagine <prompt>
        if (trimmed.startsWith("/imagine ", ignoreCase = true)) {
            val imgPrompt = trimmed.removePrefix("/imagine ").trim()
            if (imgPrompt.isNotEmpty()) {
                viewModelScope.launch {
                    val res = generateArtwork(imgPrompt)
                    res.onSuccess { art -> sendArtworkToChat(art) }
                        .onFailure { err -> _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage) }
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
        sendMessageInternal(trimmed, attachmentBitmap, attachedFile, explicitParentId = lastId, sessionIdOverride = null)
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
                attachmentBitmap = null,
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
                attachmentBitmap = null,
                attachedFile = AttachedTextFile("webpage_extract.txt", body),
                explicitParentId = lastId,
                sessionIdOverride = null,
            )
        }
    }

    private fun sendMessageInternal(
        prompt: String,
        attachmentBitmap: Bitmap?,
        attachedFile: AttachedTextFile?,
        explicitParentId: String?,
        sessionIdOverride: String?,
    ) {
        soundEngine.playSend()
        viewModelScope.launch {
            val fallbackTitle = attachedFile?.fileName ?: "Image Analysis"
            val sid = sessionIdOverride ?: ensureActiveSession(prompt.ifBlank { fallbackTitle })
            val attachPath = attachmentBitmap?.let { saveAttachmentLocally(it) }.orEmpty()
            val userMsgId = UUID.randomUUID().toString()
            val allBefore = dao.getMessagesForSessionOnce(sid)
            val historyBefore = if (explicitParentId != null) {
                ChatTreeHelper.buildActivePath(allBefore, explicitParentId).messages
            } else emptyList()

            val displayContent = prompt.ifBlank {
                if (attachedFile != null) "Analyze attached file: ${attachedFile.fileName}" else "[Attached Image]"
            }
            val userMsg = MessageEntity(
                id = userMsgId,
                sessionId = sid,
                parentId = explicitParentId,
                role = "user",
                content = displayContent,
                attachmentPath = attachPath,
                attachmentFileName = attachedFile?.fileName.orEmpty(),
                attachmentFileContent = attachedFile?.content.orEmpty(),
                tokenEstimate = ProviderPresets.estimateTokens(displayContent),
            )
            dao.upsertMessage(userMsg)
            _selectedLeafBySession.value = _selectedLeafBySession.value + (sid to userMsgId)
            refreshSessionStats(sid, firstPromptHint = displayContent)

            runAssistantGeneration(
                sessionId = sid,
                parentMessageId = userMsgId,
                historyBeforePrompt = historyBefore,
                promptText = displayContent,
                attachmentBitmap = attachmentBitmap,
                attachedFile = attachedFile,
            )
        }
    }

    private fun runAssistantGeneration(
        sessionId: String,
        parentMessageId: String,
        historyBeforePrompt: List<MessageEntity>,
        promptText: String,
        attachmentBitmap: Bitmap?,
        attachedFile: AttachedTextFile?,
    ) {
        val prov = _uiState.value.activeProvider ?: ProviderPresets.defaultProfiles().first()
        val prefs = preferences.value
        val persona = _uiState.value.resolvedPersona
        val shizukuConnected = _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_SHELL ||
            _uiState.value.shizukuStatus == ShizukuStatus.CONNECTED_ROOT
        val systemPrompt = llmClient.buildSystemPrompt(
            persona = persona,
            memories = _uiState.value.memories,
            agentModeEnabled = prefs.agentModeEnabled,
            shizukuConnected = shizukuConnected,
        )

        streamJob?.cancel()
        streamJob = viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                isStreaming = true,
                streamingContent = "",
                streamingThought = "",
                currentMood = "thinking",
                errorMessage = null,
            )
            val startMs = System.currentTimeMillis()
            val rawContent = StringBuilder()
            val rawThought = StringBuilder()
            var chirpCounter = 0
            var lastUiFlushMs = 0L

            try {
                val flow = if (prov.protocol == "on_device") {
                    onDeviceEngine.streamReply(systemPrompt, historyBeforePrompt, promptText)
                } else {
                    llmClient.streamChat(
                        provider = prov,
                        systemPrompt = systemPrompt,
                        history = historyBeforePrompt,
                        userPrompt = promptText,
                        imageBitmap = attachmentBitmap,
                        attachedFileName = attachedFile?.fileName.orEmpty(),
                        attachedFileContent = attachedFile?.content.orEmpty(),
                    )
                }
                flow.collect { chunk ->
                    if (chunk.thoughtDelta.isNotEmpty()) rawThought.append(chunk.thoughtDelta)
                    if (chunk.contentDelta.isNotEmpty()) {
                        rawContent.append(chunk.contentDelta)
                        chirpCounter++
                        if (chirpCounter % 7 == 0) soundEngine.playAnimaleseChirp(chirpCounter)
                    }
                    // 32ms UI flush throttle eliminates stutter & typing input delay during fast streams
                    val now = System.currentTimeMillis()
                    if (now - lastUiFlushMs >= 32L) {
                        lastUiFlushMs = now
                        val (inlineThought, cleanBody) = ProviderPresets.parseThoughts(rawContent.toString())
                        val mergedThought = listOf(rawThought.toString().trim(), inlineThought)
                            .filter { it.isNotEmpty() }.joinToString("\n\n")
                        _uiState.value = _uiState.value.copy(
                            streamingContent = cleanBody,
                            streamingThought = mergedThought,
                            currentMood = if (cleanBody.isNotBlank()) MoodDetector.detectMood(cleanBody) else "thinking",
                        )
                    }
                }

                val (inlineThought, cleanBody) = ProviderPresets.parseThoughts(rawContent.toString())
                val mergedThought = listOf(rawThought.toString().trim(), inlineThought)
                    .filter { it.isNotEmpty() }.joinToString("\n\n")
                val finalBody = cleanBody.ifBlank { rawContent.toString().trim() }
                val latency = (System.currentTimeMillis() - startMs).coerceAtLeast(1L)
                val detectedMood = MoodDetector.detectMood(finalBody)
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
                    speakerLabel = persona.name,
                    content = finalBody.ifBlank { "(Empty response)" },
                    thought = mergedThought,
                    mood = detectedMood,
                    providerName = prov.name,
                    modelName = modelUsed,
                    tokenEstimate = estTokens,
                    latencyMs = latency,
                    tokensPerSec = tps,
                    estimatedCostUsd = estCost,
                )
                dao.upsertMessage(assistantEntity)
                _selectedLeafBySession.value = _selectedLeafBySession.value + (sessionId to assistantId)
                refreshSessionStats(sessionId)
                soundEngine.playRecv()

                val sessTitle = dao.getSession(sessionId)?.title ?: "Cel.Cellium"
                maybePostReplyNotification(sessionId, sessTitle, persona.name, assistantEntity.content)

                _uiState.value = _uiState.value.copy(
                    isStreaming = false,
                    streamingContent = "",
                    streamingThought = "",
                    currentMood = detectedMood,
                )

                if (prefs.agentModeEnabled) {
                    val agentCmd = CommandGuard.extractAgentCommand(finalBody)
                    if (!agentCmd.isNullOrBlank()) {
                        val assessment = CommandGuard.assess(agentCmd)
                        if (assessment.tier == CommandSafetyTier.SAFE && prefs.agentAutoApproveSafe && shizukuConnected) {
                            executeAgentCommand(sessionId, assistantId, assessment.command)
                        } else {
                            _uiState.value = _uiState.value.copy(
                                pendingGuard = PendingAgentGuard(sessionId, assistantId, assessment)
                            )
                        }
                    }
                }
            } catch (e: CancellationException) {
                _uiState.value = _uiState.value.copy(isStreaming = false, streamingContent = "", streamingThought = "")
                throw e
            } catch (e: Exception) {
                val errMsg = e.localizedMessage ?: "Failed to get response from ${prov.name}."
                DevLogBuffer.add("ERROR", "Chat", errMsg)
                // Persist an error bubble with Retry action directly in the timeline
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
                    currentMood = "error",
                    errorMessage = errMsg,
                )
            }
        }
    }

    fun stopStreaming() {
        soundEngine.playClick()
        streamJob?.cancel()
        streamJob = null
        onDeviceEngine.cancelGgufGeneration()
        _uiState.value = _uiState.value.copy(isStreaming = false, streamingContent = "", streamingThought = "")
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
        val res = shizukuBridge.runCommand(command, timeoutSec = 20)
        val output = res.getOrElse { "Error: ${it.localizedMessage}" }
        val toolMsgId = UUID.randomUUID().toString()
        val toolEntity = MessageEntity(
            id = toolMsgId,
            sessionId = sessionId,
            parentId = parentId,
            role = "tool",
            content = "Shizuku shell executed `$command`.",
            toolCommand = command,
            toolOutput = output.take(8000),
            toolStatus = "approved",
            providerName = "Shizuku",
        )
        dao.upsertMessage(toolEntity)
        _selectedLeafBySession.value = _selectedLeafBySession.value + (sessionId to toolMsgId)
        refreshSessionStats(sessionId)

        val all = dao.getMessagesForSessionOnce(sessionId)
        val path = ChatTreeHelper.buildActivePath(all, toolMsgId).messages
        runAssistantGeneration(
            sessionId = sessionId,
            parentMessageId = toolMsgId,
            historyBeforePrompt = path,
            promptText = "Summarize the Shizuku command output above clearly and concisely for the user.",
            attachmentBitmap = null,
            attachedFile = null,
        )
    }

    // ── Live Voice Mode Reply ────────────────────────────────────────────

    fun streamLiveReply(
        transcript: String,
        onDelta: (String) -> Unit,
        onComplete: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        val prov = _uiState.value.activeProvider ?: ProviderPresets.defaultProfiles().first()
        val persona = _uiState.value.resolvedPersona
        val systemPrompt = "${persona.systemPrompt}\n\n[Live Voice Mode] Reply naturally in 1 to 3 spoken sentences without markdown formatting."
        viewModelScope.launch {
            val sb = StringBuilder()
            try {
                val flow = if (prov.protocol == "on_device") {
                    onDeviceEngine.streamReply(systemPrompt, emptyList(), transcript)
                } else {
                    llmClient.streamChat(prov, systemPrompt, emptyList(), transcript, null)
                }
                flow.collect { chunk ->
                    if (chunk.contentDelta.isNotEmpty()) {
                        sb.append(chunk.contentDelta)
                        val (_, clean) = ProviderPresets.parseThoughts(sb.toString())
                        onDelta(clean)
                    }
                }
                val (_, finalClean) = ProviderPresets.parseThoughts(sb.toString())
                onComplete(finalClean.ifBlank { sb.toString().trim() })
            } catch (e: Exception) {
                onError(e.localizedMessage ?: "Live Mode error with ${prov.name}")
            }
        }
    }

    // ── Providers, Personas, Memories, Templates, Local Models & Imagine ─

    suspend fun saveProviderProfile(profile: ProviderProfileEntity) {
        dao.upsertProvider(profile.copy(updatedAtMs = System.currentTimeMillis()))
        scheduleBackgroundCloudSync()
    }

    suspend fun fetchLiveModels(profile: ProviderProfileEntity): Result<List<String>> {
        val res = llmClient.fetchModels(profile)
        res.onSuccess { list ->
            if (list.isNotEmpty()) {
                val chosenModel = if (profile.selectedModel.isNotBlank() && profile.selectedModel in list) {
                    profile.selectedModel
                } else {
                    list.first()
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

    fun addCustomPersona(name: String, iconKey: String, tagline: String, systemPrompt: String, accentHex: String = "#A855F7") {
        soundEngine.playPop()
        viewModelScope.launch {
            dao.upsertPersona(
                CustomPersonaEntity(
                    id = UUID.randomUUID().toString(),
                    name = name.trim(),
                    iconKey = iconKey.trim().ifBlank { "sparkle" },
                    tagline = tagline.trim(),
                    systemPrompt = systemPrompt.trim(),
                    accentHex = accentHex,
                )
            )
            showBanner("Saved persona: $name")
        }
    }

    fun deleteCustomPersona(id: String) {
        viewModelScope.launch { dao.deletePersona(id) }
    }

    fun addMemory(title: String, content: String) {
        soundEngine.playPop()
        viewModelScope.launch {
            dao.upsertMemory(MemoryEntity(UUID.randomUUID().toString(), title.trim(), content.trim()))
            showBanner("Memory saved locally.")
        }
    }

    fun toggleMemory(memory: MemoryEntity) {
        viewModelScope.launch { dao.upsertMemory(memory.copy(enabled = !memory.enabled)) }
    }

    fun deleteMemory(id: String) {
        viewModelScope.launch { dao.deleteMemory(id) }
    }

    fun addPromptTemplate(slashTrigger: String, title: String, body: String) {
        soundEngine.playPop()
        val normalized = slashTrigger.trim().let { if (it.startsWith("/")) it else "/$it" }
        viewModelScope.launch {
            dao.upsertPromptTemplate(
                PromptTemplateEntity(
                    id = UUID.randomUUID().toString(),
                    slashKey = normalized,
                    title = title.trim().ifBlank { normalized },
                    promptBody = body.trim(),
                )
            )
            showBanner("Saved template $normalized")
        }
    }

    fun deletePromptTemplate(id: String) {
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
            val parsed = imagineClient.parseKaggleJson(raw)
            withContext(Dispatchers.Main) {
                parsed.onSuccess { creds ->
                    viewModelScope.launch {
                        prefsStore.updateKaggleConfig(
                            username = creds.username,
                            key = creds.key,
                            slug = preferences.value.kaggleKernelSlug,
                            modelId = preferences.value.kaggleModelId,
                        )
                        prefsStore.updateImagineConfig(
                            provider = "kaggle",
                            model = preferences.value.kaggleModelId,
                            apiKey = preferences.value.imagineApiKey,
                            customUrl = preferences.value.imagineCustomUrl,
                        )
                    }
                    soundEngine.playPop()
                    scheduleBackgroundCloudSync()
                    showBanner("Imported kaggle.json for @${creds.username}")
                }.onFailure { err ->
                    _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
                }
            }
        }
    }

    fun refreshLocalModelsList() {
        viewModelScope.launch(Dispatchers.IO) {
            val files = onDeviceEngine.listInstalledModels()
            _uiState.value = _uiState.value.copy(installedLocalModels = files)
        }
    }

    fun importLocalModel(uri: Uri) {
        viewModelScope.launch {
            val res = onDeviceEngine.importModelFromUri(uri)
            res.onSuccess { file ->
                refreshLocalModelsList()
                loadLocalModelFile(file)
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    fun downloadCuratedLocalModel(model: CuratedLocalModel) {
        viewModelScope.launch {
            val res = onDeviceEngine.downloadCuratedModel(model)
            res.onSuccess { file ->
                refreshLocalModelsList()
                showBanner("Downloaded ${model.name}. Loading...")
                loadLocalModelFile(file)
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage)
            }
        }
    }

    fun loadLocalModelFile(file: File) {
        viewModelScope.launch {
            val prefs = preferences.value
            val res = onDeviceEngine.loadModel(
                modelPath = file.absolutePath,
                maxTokens = prefs.localMaxTokens,
                useGpu = prefs.localUseGpu,
                shizukuAutoGuard = prefs.shizukuAutoGuard,
            )
            res.onSuccess {
                prefsStore.updateLocalModel(file.absolutePath, file.name, prefs.localMaxTokens, prefs.localUseGpu)
                val onDeviceProv = dao.getProvider(ProviderPresets.ID_ON_DEVICE)
                if (onDeviceProv != null) {
                    dao.upsertProvider(onDeviceProv.copy(selectedModel = file.name, updatedAtMs = System.currentTimeMillis()))
                }
                prefsStore.updateActiveProviderId(ProviderPresets.ID_ON_DEVICE)
                soundEngine.playPop()
                showBanner("Loaded offline model: ${file.name}")
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
        viewModelScope.launch(Dispatchers.IO) {
            onDeviceEngine.deleteModelFile(file)
            refreshLocalModelsList()
        }
    }

    suspend fun generateArtwork(
        prompt: String,
        negativePrompt: String = "",
        aspectRatio: String = "1:1",
        providerOverride: String? = null,
        modelOverride: String? = null,
    ): Result<ArtworkEntity> {
        val prefs = preferences.value
        val provider = providerOverride ?: prefs.imagineProvider
        val model = modelOverride ?: if (provider == "kaggle") prefs.kaggleModelId else prefs.imagineModel
        _uiState.value = _uiState.value.copy(isGeneratingImage = true, imagineStatusText = "Starting...", errorMessage = null)
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
            soundEngine.playPop()
            entity
        }
    }

    fun saveArtworkToPhotos(artwork: ArtworkEntity) {
        viewModelScope.launch {
            val res = imagineClient.saveToDevicePhotos(File(artwork.localPath))
            res.onSuccess { showBanner(it) }
                .onFailure { _uiState.value = _uiState.value.copy(errorMessage = it.localizedMessage) }
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
            val sid = ensureActiveSession("Imagine: ${artwork.prompt.take(32)}")
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

    // ── Backup JSON, Export, Shizuku & Cloud Sync ────────────────────────

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
            res.onSuccess { showBanner(it) }
                .onFailure { _uiState.value = _uiState.value.copy(errorMessage = it.localizedMessage) }
        }
    }

    fun testShizukuCommand() {
        soundEngine.playClick()
        viewModelScope.launch {
            val res = shizukuBridge.runCommand("id && uname -m")
            res.onSuccess { out ->
                val clean = out.trim().ifBlank { "OK" }
                showBanner("Shizuku shell OK: $clean")
            }.onFailure { err ->
                _uiState.value = _uiState.value.copy(errorMessage = err.localizedMessage ?: "Shizuku shell test failed")
            }
        }
    }

    fun syncWithGoogleCloud(silent: Boolean = false) {
        viewModelScope.launch {
            if (!silent) {
                _uiState.value = _uiState.value.copy(isSyncingCloud = true, errorMessage = null)
            }
            val res = cloudSync.syncNow(preferences.value)
            if (!silent) {
                _uiState.value = _uiState.value.copy(isSyncingCloud = false)
                res.onSuccess { showBanner(it.message) }
                    .onFailure { _uiState.value = _uiState.value.copy(errorMessage = it.localizedMessage) }
            }
        }
    }

    private fun scheduleBackgroundCloudSync() {
        if (com.google.firebase.Firebase.auth.currentUser == null) return
        autoSyncJob?.cancel()
        autoSyncJob = viewModelScope.launch {
            delay(2500L)
            cloudSync.syncNow(preferences.value)
        }
    }

    fun clearBanner() { _uiState.value = _uiState.value.copy(bannerMessage = null) }
    fun clearError() { _uiState.value = _uiState.value.copy(errorMessage = null) }
    fun showBanner(msg: String) { _uiState.value = _uiState.value.copy(bannerMessage = msg) }

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

    private fun saveAttachmentLocally(bitmap: Bitmap): String = runCatching {
        val dir = File(appContext.filesDir, "attachments").apply { if (!exists()) mkdirs() }
        val f = File(dir, "att_${System.currentTimeMillis()}.jpg")
        FileOutputStream(f).use { bitmap.compress(Bitmap.CompressFormat.JPEG, 82, it) }
        f.absolutePath
    }.getOrDefault("")

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
    }
}

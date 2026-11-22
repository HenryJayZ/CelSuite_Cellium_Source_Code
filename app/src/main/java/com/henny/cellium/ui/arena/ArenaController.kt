package com.henny.cellium.ui.arena

import com.henny.cellium.ai.OnDeviceLlmEngine
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.ai.UniversalLlmClient
import com.henny.cellium.avatar.MoodDetector
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.core.ContextModifyConfig
import com.henny.cellium.core.DevLogBuffer
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.data.CustomPersona
import com.henny.cellium.data.PersonaSpec
import com.henny.cellium.data.local.CelliumDao
import com.henny.cellium.data.local.CustomPersonaEntity
import com.henny.cellium.data.local.MemoryEntity
import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.data.local.SessionEntity
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.util.UUID

data class ArenaUiState(
    val sessionId: String? = null,
    val providerAId: String = ProviderPresets.ID_POLLINATIONS_FREE,
    val modelA: String = "openai-fast",
    val personaAId: String = "default",
    val providerBId: String = ProviderPresets.ID_POLLINATIONS_FREE,
    val modelB: String = "openai-fast",
    val personaBId: String = "celeste",
    val messages: List<MessageEntity> = emptyList(),
    val isRunning: Boolean = false,
    val isPaused: Boolean = false,
    val activeSpeaker: String = "", // "A" or "B"
    val streamingContent: String = "",
    val retryStatusText: String = "",
    val nextTurnSlot: String = "A",
    val maxAutoTurns: Int = 12,
    val turnsCompleted: Int = 0,
    val errorMessage: String? = null,
)

/**
 * 2-AI Group Chat (Arena Mode) orchestrator.
 * Two distinct AI slots (any provider, model, and persona) converse turn-by-turn
 * with auto-retry on transient rate limits and zero duplicate bubble flashing.
 */
class ArenaController(
    private val scope: CoroutineScope,
    private val dao: CelliumDao,
    private val llmClient: UniversalLlmClient,
    private val onDeviceEngine: OnDeviceLlmEngine,
    private val soundEngine: CelliumSoundEngine,
    private val providersProvider: () -> List<ProviderProfileEntity>,
    private val customPersonasProvider: () -> List<CustomPersonaEntity>,
    private val memoriesProvider: () -> List<MemoryEntity>,
    private val maxAutoRetriesProvider: () -> Int = { 10 },
    private val onNotifyIfBackground: (sessionId: String, title: String, speaker: String, text: String) -> Unit,
) {
    private val _state = MutableStateFlow(ArenaUiState())
    val state: StateFlow<ArenaUiState> = _state.asStateFlow()

    private var loopJob: Job? = null
    private var sessionObserverJob: Job? = null

    fun ensureArenaSession(existingSessionId: String? = null) {
        scope.launch {
            val targetId = existingSessionId ?: _state.value.sessionId
            val existing = targetId?.let { dao.getSession(it) }
            val session = if (existing != null && existing.isArena) {
                existing
            } else {
                val id = UUID.randomUUID().toString()
                val st = _state.value
                SessionEntity(
                    id = id,
                    title = "Arena: 2-AI Group Chat",
                    personaId = st.personaAId,
                    providerId = st.providerAId,
                    modelName = st.modelA,
                    isArena = true,
                    arenaProviderA = st.providerAId,
                    arenaModelA = st.modelA,
                    arenaPersonaA = st.personaAId,
                    arenaProviderB = st.providerBId,
                    arenaModelB = st.modelB,
                    arenaPersonaB = st.personaBId,
                ).also { dao.upsertSession(it) }
            }
            _state.value = _state.value.copy(
                sessionId = session.id,
                providerAId = session.arenaProviderA.ifBlank { ProviderPresets.ID_POLLINATIONS_FREE },
                modelA = normalizePollinationsModel(session.arenaProviderA, session.arenaModelA),
                personaAId = session.arenaPersonaA.ifBlank { "default" },
                providerBId = session.arenaProviderB.ifBlank { ProviderPresets.ID_POLLINATIONS_FREE },
                modelB = normalizePollinationsModel(session.arenaProviderB, session.arenaModelB),
                personaBId = session.arenaPersonaB.ifBlank { "celeste" },
            )
            observeMessages(session.id)
        }
    }

    private fun normalizePollinationsModel(providerId: String, rawModel: String): String {
        val clean = rawModel.trim()
        if (providerId == ProviderPresets.ID_POLLINATIONS_FREE || providerId.isBlank()) {
            if (clean.isBlank() || clean.equals("openai", ignoreCase = true) || clean.equals("mistral", ignoreCase = true)) {
                return "openai-fast"
            }
        }
        return clean
    }

    fun startFreshArena() {
        stop()
        scope.launch {
            val st = _state.value
            val id = UUID.randomUUID().toString()
            val session = SessionEntity(
                id = id,
                title = "Arena: 2-AI Group Chat",
                personaId = st.personaAId,
                providerId = st.providerAId,
                modelName = st.modelA,
                isArena = true,
                arenaProviderA = st.providerAId,
                arenaModelA = st.modelA,
                arenaPersonaA = st.personaAId,
                arenaProviderB = st.providerBId,
                arenaModelB = st.modelB,
                arenaPersonaB = st.personaBId,
            )
            dao.upsertSession(session)
            _state.value = st.copy(
                sessionId = id,
                messages = emptyList(),
                isRunning = false,
                isPaused = false,
                activeSpeaker = "",
                streamingContent = "",
                retryStatusText = "",
                nextTurnSlot = "A",
                turnsCompleted = 0,
                errorMessage = null,
            )
            observeMessages(id)
        }
    }

    private fun observeMessages(sessionId: String) {
        sessionObserverJob?.cancel()
        sessionObserverJob = scope.launch {
            dao.observeMessagesForSession(sessionId).collect { list ->
                _state.value = _state.value.copy(messages = list)
            }
        }
    }

    fun updateSlotA(providerId: String, model: String, personaId: String) {
        _state.value = _state.value.copy(providerAId = providerId, modelA = model, personaAId = personaId)
        persistArenaConfig()
    }

    fun updateSlotB(providerId: String, model: String, personaId: String) {
        _state.value = _state.value.copy(providerBId = providerId, modelB = model, personaBId = personaId)
        persistArenaConfig()
    }

    private fun persistArenaConfig() {
        val st = _state.value
        val sid = st.sessionId ?: return
        scope.launch {
            val existing = dao.getSession(sid) ?: return@launch
            dao.upsertSession(
                existing.copy(
                    arenaProviderA = st.providerAId,
                    arenaModelA = st.modelA,
                    arenaPersonaA = st.personaAId,
                    arenaProviderB = st.providerBId,
                    arenaModelB = st.modelB,
                    arenaPersonaB = st.personaBId,
                    updatedAtMs = System.currentTimeMillis(),
                )
            )
        }
    }

    fun sendUserPromptAndRun(text: String, autoContinue: Boolean = true) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        soundEngine.playSend()
        scope.launch {
            if (_state.value.sessionId == null) ensureArenaSession()
            var tries = 0
            while (_state.value.sessionId == null && tries < 10) {
                delay(40)
                tries++
            }
            val sid = _state.value.sessionId ?: return@launch
            val existingMsgs = dao.getMessagesForSessionOnce(sid)
            val parentId = existingMsgs.lastOrNull()?.id
            val userMsg = MessageEntity(
                id = UUID.randomUUID().toString(),
                sessionId = sid,
                parentId = parentId,
                role = "user",
                speakerLabel = "You",
                content = clean,
                tokenEstimate = ProviderPresets.estimateTokens(clean),
            )
            dao.upsertMessage(userMsg)
            updateArenaSessionStats(sid, clean)

            if (autoContinue && (!_state.value.isRunning || _state.value.isPaused)) {
                _state.value = _state.value.copy(isPaused = false, errorMessage = null)
                launchLoop(singleStep = false)
            }
        }
    }

    fun pause() {
        soundEngine.playClick()
        _state.value = _state.value.copy(isPaused = true)
    }

    fun resume() {
        soundEngine.playClick()
        _state.value = _state.value.copy(isPaused = false, errorMessage = null)
        if (!_state.value.isRunning) {
            launchLoop(singleStep = false)
        }
    }

    fun stepOnce() {
        if (_state.value.isRunning && !_state.value.isPaused) return
        soundEngine.playClick()
        _state.value = _state.value.copy(isPaused = false, errorMessage = null)
        launchLoop(singleStep = true)
    }

    fun stop() {
        loopJob?.cancel()
        loopJob = null
        llmClient.cancelActiveRequests()
        _state.value = _state.value.copy(
            isRunning = false,
            isPaused = false,
            activeSpeaker = "",
            streamingContent = "",
            retryStatusText = "",
        )
    }

    private fun launchLoop(singleStep: Boolean) {
        loopJob?.cancel()
        loopJob = scope.launch {
            _state.value = _state.value.copy(isRunning = true, errorMessage = null, retryStatusText = "")
            try {
                var stepsDone = 0
                val maxSteps = if (singleStep) 1 else _state.value.maxAutoTurns
                while (stepsDone < maxSteps) {
                    while (_state.value.isPaused) {
                        delay(200)
                    }
                    val sid = _state.value.sessionId ?: break
                    val slot = _state.value.nextTurnSlot
                    runSingleArenaTurn(sid, slot)
                    val nextSlot = if (slot == "A") "B" else "A"
                    _state.value = _state.value.copy(
                        nextTurnSlot = nextSlot,
                        turnsCompleted = _state.value.turnsCompleted + 1,
                    )
                    stepsDone++
                    if (!singleStep && stepsDone < maxSteps) {
                        delay(650)
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                DevLogBuffer.add("ERROR", "Arena", e.localizedMessage ?: "Arena turn error")
                _state.value = _state.value.copy(errorMessage = e.localizedMessage ?: "Arena turn failed.")
            } finally {
                _state.value = _state.value.copy(
                    isRunning = false,
                    activeSpeaker = "",
                    streamingContent = "",
                    retryStatusText = "",
                )
            }
        }
    }

    private suspend fun runSingleArenaTurn(sessionId: String, slot: String) {
        val st = _state.value
        val provId = if (slot == "A") st.providerAId else st.providerBId
        val modelName = if (slot == "A") st.modelA else st.modelB
        val personaId = if (slot == "A") st.personaAId else st.personaBId
        val otherPersonaId = if (slot == "A") st.personaBId else st.personaAId

        val baseProv = providersProvider().firstOrNull { it.id == provId }
            ?: ProviderCatalog.byId(provId)?.toEntity()
            ?: ProviderPresets.defaultProfiles().first()
        val effectiveProv = baseProv.copy(selectedModel = modelName.ifBlank { baseProv.selectedModel })

        val myPersona = resolvePersona(personaId)
        val otherPersona = resolvePersona(otherPersonaId)
        val speakerTag = "AI $slot · ${myPersona.name}"

        val allMsgs = dao.getMessagesForSessionOnce(sessionId)
        val transcriptPrompt = buildString {
            append("You are participating in a lively 3-way group chat called Cel.Cellium Arena with the Human ('You') and another AI (${otherPersona.name}).\n")
            append("Respond directly to the latest messages in 2-4 concise, engaging sentences without prefixing your own name.\n\n")
            append("[Conversation Transcript]\n")
            allMsgs.takeLast(14).forEach { m ->
                val who = m.speakerLabel.ifBlank { if (m.role == "user") "You" else "Assistant" }
                append("$who: ${m.content}\n")
            }
            append("\nNow reply as ${myPersona.name}:")
        }

        val systemPrompt = llmClient.buildSystemPrompt(
            persona = myPersona,
            memories = memoriesProvider(),
            agentModeEnabled = false,
            shizukuConnected = false,
            contextConfig = ContextModifyConfig(
                includePersona = true,
                includeMemories = true,
                includeIllumeInstructions = false,
                includeAgentInstructions = false,
                includeMoodInstructions = false,
            ),
        )

        val maxRetries = maxAutoRetriesProvider().coerceIn(0, 15)
        var attempt = 0
        var lastError: Exception? = null
        val startMs = System.currentTimeMillis()
        val raw = StringBuilder()

        while (attempt <= maxRetries) {
            raw.clear()
            var lastEmit = 0L
            _state.value = _state.value.copy(
                activeSpeaker = slot,
                streamingContent = "",
                retryStatusText = if (attempt == 0) "" else "Retrying AI $slot ($attempt/$maxRetries)...",
            )
            try {
                val flow = if (effectiveProv.protocol == "on_device") {
                    onDeviceEngine.streamReply(systemPrompt, emptyList(), transcriptPrompt)
                } else {
                    llmClient.streamChat(effectiveProv, systemPrompt, emptyList(), transcriptPrompt, null)
                }

                flow.collect { chunk ->
                    if (chunk.contentDelta.isNotEmpty()) {
                        raw.append(chunk.contentDelta)
                        val now = System.currentTimeMillis()
                        if (now - lastEmit >= 36L) {
                            lastEmit = now
                            val (_, clean) = ProviderPresets.parseThoughts(raw.toString())
                            _state.value = _state.value.copy(streamingContent = clean, retryStatusText = "")
                        }
                    }
                }
                lastError = null
                break
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                lastError = e
                val retryable = effectiveProv.protocol != "on_device" && UniversalLlmClient.isRetryableError(e)
                if (!retryable || attempt >= maxRetries) {
                    throw e
                }
                attempt++
                val backoffMs = (1200L * attempt).coerceAtMost(6000L)
                _state.value = _state.value.copy(
                    streamingContent = "",
                    retryStatusText = "Rate limited / busy — retrying AI $slot ($attempt/$maxRetries)...",
                )
                delay(backoffMs)
            }
        }
        if (lastError != null) throw lastError

        val (thought, cleanBody) = ProviderPresets.parseThoughts(raw.toString())
        val (tagMood, strippedBody) = MoodDetector.extractInlineMoodTag(cleanBody)
        val finalText = strippedBody.ifBlank { cleanBody.ifBlank { raw.toString().trim() } }.ifBlank { "(No response)" }
        val latency = (System.currentTimeMillis() - startMs).coerceAtLeast(1L)
        val tokens = ProviderPresets.estimateTokens(finalText + thought)
        val tps = (tokens.toFloat() / (latency.toFloat() / 1000f)).coerceAtMost(999f)
        val cost = ProviderPresets.estimateCostUsd(effectiveProv.selectedModel, tokens, effectiveProv.requiresKey, effectiveProv.protocol)

        val msg = MessageEntity(
            id = UUID.randomUUID().toString(),
            sessionId = sessionId,
            parentId = allMsgs.lastOrNull()?.id,
            role = "assistant",
            speakerLabel = speakerTag,
            content = finalText,
            thought = thought,
            mood = tagMood ?: MoodDetector.detectMood(finalText),
            providerName = effectiveProv.name,
            modelName = effectiveProv.selectedModel,
            tokenEstimate = tokens,
            latencyMs = latency,
            tokensPerSec = tps,
            estimatedCostUsd = cost,
        )

        // Clear live streaming slot BEFORE upserting to Room so the message NEVER renders twice!
        _state.value = _state.value.copy(
            activeSpeaker = "",
            streamingContent = "",
            retryStatusText = "",
        )
        dao.upsertMessage(msg)
        dao.incrementProviderUsage(effectiveProv.id)
        updateArenaSessionStats(sessionId, finalText)
        soundEngine.playRecv()
        onNotifyIfBackground(sessionId, "Cel.Cellium Arena", speakerTag, finalText)
    }

    private suspend fun updateArenaSessionStats(sessionId: String, preview: String) {
        val sess = dao.getSession(sessionId) ?: return
        val msgs = dao.getMessagesForSessionOnce(sessionId)
        val title = if (sess.title == "Arena: 2-AI Group Chat" && msgs.size <= 2) {
            "Arena: ${preview.replace("\n", " ").take(36)}"
        } else sess.title
        dao.upsertSession(
            sess.copy(
                title = title,
                messageCount = msgs.size,
                tokenCount = msgs.sumOf { it.tokenEstimate },
                lastMessagePreview = preview.take(140),
                updatedAtMs = System.currentTimeMillis(),
            )
        )
    }

    private fun resolvePersona(id: String): PersonaSpec {
        val custom = customPersonasProvider().map {
            CustomPersona(
                id = it.id,
                name = it.name,
                emoji = it.iconKey,
                tagline = it.tagline,
                systemPrompt = it.systemPrompt,
                accentHex = it.accentHex,
            )
        }
        return BuiltInPersonas.resolve(id, custom)
    }
}

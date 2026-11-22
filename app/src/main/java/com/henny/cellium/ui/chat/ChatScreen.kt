package com.henny.cellium.ui.chat

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.os.Build
import android.provider.MediaStore
import android.speech.RecognizerIntent
import android.speech.tts.TextToSpeech
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ArrowDropDown
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Folder
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.History
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalScrollCaptureInProgress
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.ui.components.CelliumIcons
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.GlassPill
import com.henny.cellium.ui.components.MarkdownMessageContent
import com.henny.cellium.ui.components.ThoughtAccordion
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.components.copyTextToClipboard
import com.henny.cellium.ui.settings.ProviderEditDialog
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelRedError
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

@Composable
fun ChatScreen(
    viewModel: CelliumViewModel,
    onOpenArena: () -> Unit,
    onOpenArenaSession: (String) -> Unit,
    onOpenSettingsProviders: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val visuals = LocalCelliumVisuals.current
    val ui by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()

    var pendingImages by remember { mutableStateOf<List<Bitmap>>(emptyList()) }
    var pendingFile by remember { mutableStateOf<AttachedTextFile?>(null) }
    var injectedComposerText by remember { mutableStateOf<String?>(null) }
    var showSessionsSheet by remember { mutableStateOf(false) }
    var showProviderSheet by remember { mutableStateOf(false) }
    var showPersonaSheet by remember { mutableStateOf(false) }
    var showModifySheet by remember { mutableStateOf(false) }
    var showWorkspacePrompt by remember { mutableStateOf(false) }
    var configuringProvider by remember { mutableStateOf<ProviderProfileEntity?>(null) }

    val listState = rememberLazyListState()
    val starredModels = remember(prefs.starredModelsJson) {
        viewModel.prefsStore.decodeStarredModels(prefs.starredModelsJson)
    }

    var tts by remember { mutableStateOf<TextToSpeech?>(null) }
    DisposableEffect(context) {
        var engine: TextToSpeech? = null
        engine = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                engine?.language = Locale.US
            }
        }
        tts = engine
        onDispose {
            engine?.stop()
            engine?.shutdown()
        }
    }

    val multiPhotoPicker = rememberLauncherForActivityResult(
        ActivityResultContracts.PickMultipleVisualMedia(maxItems = 5)
    ) { uris ->
        if (uris.isNotEmpty()) {
            val decoded = uris.mapNotNull { uri ->
                runCatching {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                        ImageDecoder.decodeBitmap(ImageDecoder.createSource(context.contentResolver, uri)) { decoder, _, _ ->
                            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                        }
                    } else {
                        @Suppress("DEPRECATION")
                        MediaStore.Images.Media.getBitmap(context.contentResolver, uri)
                    }
                }.getOrNull()
            }
            if (decoded.isNotEmpty()) {
                pendingImages = (pendingImages + decoded).take(5)
            }
        }
    }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            viewModel.readAttachedTextFile(uri) { loaded ->
                pendingFile = loaded
            }
        }
    }

    val speechLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val spoken = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!spoken.isNullOrBlank()) {
                injectedComposerText = spoken
            }
        }
    }

    LaunchedEffect(ui.activeMessages.size, ui.isStreaming, ui.isGeneratingImage) {
        val count = ui.activeMessages.size + (if (ui.isStreaming) 1 else 0) + (if (ui.isGeneratingImage) 1 else 0)
        if (count > 0) listState.animateScrollToItem(count - 1)
    }

    val persona = ui.resolvedPersona
    val activeProv = ui.activeProvider
    val isOfflineProvider = activeProv?.protocol == "on_device"
    val scrollCaptureActive = LocalScrollCaptureInProgress.current

    // No redundant .statusBarsPadding() here — CelliumApp Scaffold handles safeDrawing + consumeWindowInsets
    Column(
        modifier = Modifier
            .fillMaxSize()
            .imePadding(),
    ) {
        // Liquid Glass Top Bar (hidden during Android/Samsung Scroll Capture so tiles stitch cleanly)
        if (!scrollCaptureActive) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            GlassPill(
                onClick = {
                    viewModel.soundEngine.playClick()
                    showSessionsSheet = true
                },
                modifier = Modifier.testTag("sessions_drawer_button"),
            ) {
                Icon(Icons.Rounded.History, contentDescription = "Sessions", tint = CelLavender, modifier = Modifier.size(16.dp))
                Text(
                    text = "${ui.sessions.count { !it.archived }}",
                    style = MaterialTheme.typography.labelMedium,
                    color = CelTextPrimary,
                    maxLines = 1,
                    softWrap = false,
                )
            }

            if (isOfflineProvider) {
                GlassPill(
                    onClick = {
                        viewModel.soundEngine.playClick()
                        showModifySheet = true
                    },
                    modifier = Modifier.testTag("offline_modify_pill"),
                ) {
                    Icon(Icons.Rounded.Tune, contentDescription = "Modify GGUF & Context", tint = visuals.primary, modifier = Modifier.size(15.dp))
                    Text("Modify", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, softWrap = false)
                }
            }

            GlassPill(
                onClick = {
                    viewModel.soundEngine.playClick()
                    showProviderSheet = true
                },
                selected = true,
                modifier = Modifier.testTag("provider_dropdown_pill"),
            ) {
                Icon(
                    imageVector = CelliumIcons.resolve(activeProv?.badge ?: "sparkle"),
                    contentDescription = null,
                    tint = visuals.primary,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = activeProv?.let {
                        val modelLabel = if (it.protocol == "on_device") {
                            ui.localModelStatus.modelName.ifBlank { it.selectedModel.ifBlank { "No model" } }
                        } else {
                            it.selectedModel.removePrefix("models/").ifBlank { "select model" }
                        }
                        "${it.name}: ${modelLabel.take(16)}"
                    } ?: "Select Provider",
                    style = MaterialTheme.typography.labelMedium,
                    color = CelTextPrimary,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 185.dp),
                )
                Icon(Icons.Rounded.ArrowDropDown, contentDescription = null, tint = CelLavender, modifier = Modifier.size(16.dp))
            }

            GlassPill(
                onClick = {
                    viewModel.soundEngine.playClick()
                    showPersonaSheet = true
                },
                modifier = Modifier.testTag("persona_picker_pill"),
            ) {
                Icon(
                    imageVector = CelliumIcons.resolve(persona.iconKey),
                    contentDescription = null,
                    tint = CelLavender,
                    modifier = Modifier.size(15.dp),
                )
                Text(persona.name, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, softWrap = false)
            }

            GlassPill(
                onClick = {
                    viewModel.soundEngine.playPop()
                    onOpenArena()
                },
                modifier = Modifier.testTag("chat_top_arena_button"),
            ) {
                Icon(Icons.Rounded.Forum, contentDescription = "Arena 2-AI Group Chat", tint = Color(0xFF38BDF8), modifier = Modifier.size(16.dp))
                Text("Arena", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, softWrap = false)
            }

            GlassPill(
                onClick = {
                    viewModel.soundEngine.playClick()
                    val enabling = !prefs.agentModeEnabled
                    scope.launch {
                        viewModel.prefsStore.updateAgentMode(enabling)
                    }
                    if (enabling && !prefs.agentWorkspacePrompted) {
                        showWorkspacePrompt = true
                    }
                },
                selected = prefs.agentModeEnabled,
                modifier = Modifier.testTag("agent_mode_toggle"),
            ) {
                Icon(
                    Icons.Rounded.Terminal,
                    contentDescription = "Agent Mode",
                    tint = if (prefs.agentModeEnabled) CelEmeraldThought else CelTextSecondary,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = if (prefs.agentModeEnabled) "Agent ON" else "Agent",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (prefs.agentModeEnabled) CelEmeraldThought else CelTextSecondary,
                    maxLines = 1,
                    softWrap = false,
                )
            }

            GlassPill(
                onClick = { viewModel.startNewSession() },
                modifier = Modifier.testTag("new_chat_button"),
            ) {
                Icon(Icons.Rounded.Add, contentDescription = "New Chat", tint = CelLavender, modifier = Modifier.size(16.dp))
            }
        }
        }

        // Error or status banner
        ui.errorMessage?.let { err ->
            Surface(
                color = CelRedError.copy(alpha = 0.16f),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 3.dp),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(err, style = MaterialTheme.typography.labelSmall, color = CelRedError, modifier = Modifier.weight(1f))
                    TextButton(onClick = {
                        viewModel.clearError()
                        viewModel.retryLastUserTurn()
                    }) { Text("Retry", color = CelTextPrimary, maxLines = 1, softWrap = false) }
                    IconButton(onClick = { viewModel.clearError() }, modifier = Modifier.size(28.dp)) {
                        Icon(Icons.Rounded.Close, contentDescription = "Dismiss", tint = CelRedError, modifier = Modifier.size(16.dp))
                    }
                }
            }
        }

        ui.bannerMessage?.let { msg ->
            Surface(
                color = CelEmeraldThought.copy(alpha = 0.15f),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 3.dp),
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(msg, style = MaterialTheme.typography.labelSmall, color = CelEmeraldThought, modifier = Modifier.weight(1f))
                    IconButton(onClick = { viewModel.clearBanner() }, modifier = Modifier.size(24.dp)) {
                        Icon(Icons.Rounded.Close, contentDescription = "Dismiss", tint = CelEmeraldThought, modifier = Modifier.size(14.dp))
                    }
                }
            }
        }

        // Chat Timeline or Welcome Hero
        Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
            if (ui.activeMessages.isEmpty() && !ui.isStreaming && !ui.isGeneratingImage) {
                EmptyChatHero(
                    personaName = persona.name,
                    personaIconKey = persona.iconKey,
                    personaTagline = persona.tagline,
                    providerName = activeProv?.name ?: "Pollinations AI (Free · No Key)",
                    mood = ui.currentMood,
                    avatarGender = prefs.avatarGender,
                    highFps = prefs.highFpsMode,
                    onQuickPrompt = { viewModel.sendMessage(it) },
                    onOpenArena = onOpenArena,
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(ui.activeMessages, key = { it.id }) { msg ->
                        ChatMessageBubble(
                            message = msg,
                            personaName = persona.name,
                            branchInfo = ui.branchInfoById[msg.id],
                            codeWordWrap = prefs.codeWordWrap,
                            onSwitchBranch = { viewModel.switchBranch(it) },
                            onEditInPlace = { m, edited, regen -> viewModel.editMessageInPlace(m, edited, regen) },
                            onEditAsBranch = { m, edited, regen -> viewModel.editMessageAsBranch(m, edited, regen) },
                            onRegenerate = { viewModel.regenerateAssistantMessage(it) },
                            onForkSession = { viewModel.forkSessionFromMessage(it) },
                            onSpeak = { text ->
                                tts?.let { engine ->
                                    if (prefs.ttsVoiceName.isNotBlank()) {
                                        engine.voices?.firstOrNull { it.name == prefs.ttsVoiceName }?.let { engine.voice = it }
                                    }
                                    engine.setSpeechRate(prefs.ttsSpeechRate)
                                    engine.setPitch(prefs.ttsPitch)
                                    engine.speak(text.take(3500), TextToSpeech.QUEUE_FLUSH, null, "cel_msg")
                                }
                            },
                            onDelete = { viewModel.deleteMessage(it) },
                        )
                    }
                    if (ui.isStreaming) {
                        item(key = "streaming_live_bubble") {
                            StreamingAssistantBubble(
                                personaName = persona.name,
                                providerName = activeProv?.name.orEmpty(),
                                thought = ui.streamingThought,
                                content = ui.streamingContent,
                                retryStatusText = ui.retryStatusText,
                                codeWordWrap = prefs.codeWordWrap,
                            )
                        }
                    }
                    if (ui.isGeneratingImage) {
                        item(key = "illume_generating_card") {
                            GlassCard(highlighted = true, contentPadding = 12.dp, modifier = Modifier.fillMaxWidth()) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                                ) {
                                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = visuals.primary)
                                    Icon(Icons.Rounded.Palette, contentDescription = null, tint = CelLavender, modifier = Modifier.size(18.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text("Illume Generating Artwork...", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                                        Text(
                                            text = ui.imagineStatusText.ifBlank { "Rendering image via ${prefs.imagineProvider} (${prefs.imagineModel})..." },
                                            style = MaterialTheme.typography.labelSmall,
                                            color = CelTextSecondary,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Isolated Zero-Lag Composer Bar (hidden during Android/Samsung Scroll Capture)
        if (!scrollCaptureActive) {
            ChatComposerBar(
                personaName = persona.name,
                isStreaming = ui.isStreaming,
                promptTemplates = ui.promptTemplates,
                pendingImages = pendingImages,
                pendingFile = pendingFile,
                injectedText = injectedComposerText,
                onClearInjectedText = { injectedComposerText = null },
                onPastedBitmap = { bmp ->
                    viewModel.soundEngine.playPop()
                    pendingImages = (pendingImages + bmp).take(5)
                },
                onRemoveImageAt = { idx ->
                    pendingImages = pendingImages.filterIndexed { i, _ -> i != idx }
                },
                onClearFile = { pendingFile = null },
                onPickImage = {
                    multiPhotoPicker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                },
                onPickFile = {
                    filePicker.launch(arrayOf("*/*"))
                },
                onStartVoiceInput = {
                    val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                        putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak to ${persona.name}")
                    }
                    runCatching { speechLauncher.launch(intent) }
                },
                onOpenArena = onOpenArena,
                onStopStreaming = { viewModel.stopStreaming() },
                onSend = { text ->
                    val imgs = pendingImages
                    val file = pendingFile
                    pendingImages = emptyList()
                    pendingFile = null
                    viewModel.sendMessage(text, imgs, file)
                },
            )
        }
    }

    ui.pendingGuard?.let { pending ->
        AgentCommandGuardDialog(
            pending = pending,
            onApprove = { viewModel.approvePendingAgentCommand(it) },
            onDeny = { viewModel.denyPendingAgentCommand() },
        )
    }

    if (showProviderSheet) {
        ProviderSearchDropdownSheet(
            savedProviders = ui.providers,
            activeProviderId = activeProv?.id,
            onSelectCatalogProvider = { viewModel.activateCatalogProvider(it) },
            onSelectSavedProviderModel = { pid, model -> viewModel.selectProvider(pid, model) },
            onFetchActiveModels = { viewModel.fetchLiveModels(it) },
            onOpenSettingsProviders = onOpenSettingsProviders,
            onDismiss = { showProviderSheet = false },
            hiddenProviderIds = prefs.hiddenProviderIds,
            starredModels = starredModels,
            onToggleHideProvider = { viewModel.toggleHideProvider(it) },
            onToggleStarModel = { pid, pname, model -> viewModel.toggleStarModel(pid, pname, model) },
            onRequestConfigureKey = { prov -> configuringProvider = prov },
        )
    }

    configuringProvider?.let { prov ->
        ProviderEditDialog(
            provider = prov,
            onDismiss = { configuringProvider = null },
            onSave = { updated ->
                scope.launch {
                    viewModel.saveProviderProfile(updated)
                    viewModel.selectProvider(updated.id, updated.selectedModel)
                }
                configuringProvider = null
            },
            onDelete = if (prov.isCustom) {
                {
                    viewModel.deleteCustomProvider(prov.id)
                    configuringProvider = null
                }
            } else null,
            onFetchModels = { draft -> viewModel.fetchLiveModels(draft) },
            starredModels = starredModels,
            onToggleStarModel = { pid, pname, model -> viewModel.toggleStarModel(pid, pname, model) },
        )
    }

    if (showModifySheet) {
        ContextModifySheet(
            config = prefs.contextModify,
            isOfflineProvider = isOfflineProvider,
            onSave = { cfg ->
                scope.launch {
                    viewModel.prefsStore.updateContextModify(cfg)
                    viewModel.showBanner("Context & Engine parameters updated.")
                }
            },
            onDismiss = { showModifySheet = false },
        )
    }

    if (showWorkspacePrompt) {
        var draftDir by remember(prefs.agentWorkspacePath) { mutableStateOf(prefs.agentWorkspacePath) }
        AlertDialog(
            onDismissRequest = {
                showWorkspacePrompt = false
                scope.launch { viewModel.prefsStore.updateAgentWorkspace(draftDir, prompted = true) }
            },
            containerColor = Color(0xFF140D26),
            icon = { Icon(Icons.Rounded.Folder, contentDescription = null, tint = CelEmeraldThought) },
            title = { Text("Agent Project Workspace", color = CelTextPrimary) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        text = "Choose where Cel's Shizuku Agent should create files and run project tasks. You can change this anytime in Settings -> Agent & Shizuku.",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                    OutlinedTextField(
                        value = draftDir,
                        onValueChange = { draftDir = it },
                        label = { Text("Workspace Directory") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        showWorkspacePrompt = false
                        scope.launch {
                            viewModel.prefsStore.updateAgentWorkspace(draftDir, prompted = true)
                            viewModel.showBanner("Agent workspace set to ${draftDir.trim()}")
                        }
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                ) {
                    Text("Save Workspace", maxLines = 1, softWrap = false)
                }
            },
            dismissButton = {
                TextButton(onClick = {
                    showWorkspacePrompt = false
                    scope.launch { viewModel.prefsStore.updateAgentWorkspace(prefs.agentWorkspacePath, prompted = true) }
                }) {
                    Text("Keep Default", maxLines = 1, softWrap = false)
                }
            },
        )
    }

    if (showSessionsSheet) {
        SessionsDrawerSheet(
            sessions = ui.sessions,
            activeSessionId = ui.activeSessionId,
            onSearchContent = { viewModel.searchSessionIdsByContent(it) },
            onSelect = { viewModel.selectSession(it) },
            onNewChat = { viewModel.startNewSession() },
            onOpenArena = onOpenArena,
            onOpenArenaSession = onOpenArenaSession,
            onTogglePin = { viewModel.togglePinSession(it) },
            onToggleArchive = { viewModel.toggleArchiveSession(it) },
            onDelete = { viewModel.deleteSession(it) },
            onExportMd = {
                viewModel.exportActiveSessionMarkdown()?.let {
                    copyTextToClipboard(context, it)
                    viewModel.showBanner("Markdown transcript copied to clipboard.")
                }
            },
            onExportJson = {
                viewModel.exportActiveSessionJson()?.let {
                    copyTextToClipboard(context, it)
                    viewModel.showBanner("JSON transcript copied to clipboard.")
                }
            },
            onDismiss = { showSessionsSheet = false },
        )
    }

    if (showPersonaSheet) {
        PersonaPickerSheet(
            activePersonaId = ui.activePersonaId,
            customPersonas = ui.customPersonas,
            onSelect = { viewModel.selectPersona(it) },
            onDismiss = { showPersonaSheet = false },
        )
    }
}

@Composable
private fun StreamingAssistantBubble(
    personaName: String,
    providerName: String,
    thought: String,
    content: String,
    retryStatusText: String = "",
    codeWordWrap: Boolean = true,
) {
    val visuals = LocalCelliumVisuals.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(visuals.glassSurface)
            .border(1.dp, visuals.activeBorder, RoundedCornerShape(18.dp))
            .padding(13.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text = "$personaName · $providerName · streaming",
            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
            color = visuals.primary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (retryStatusText.isNotBlank()) {
            Surface(
                color = CelAmber.copy(alpha = 0.16f),
                shape = RoundedCornerShape(8.dp),
            ) {
                Text(
                    text = retryStatusText,
                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                    color = CelAmber,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
        }
        if (thought.isNotBlank()) ThoughtAccordion(thought = thought)
        if (content.isNotBlank()) {
            MarkdownMessageContent(text = content, defaultWordWrap = codeWordWrap)
        } else if (retryStatusText.isBlank()) {
            Text("Thinking...", style = MaterialTheme.typography.bodySmall, color = CelTextSecondary)
        }
    }
}

@Composable
private fun EmptyChatHero(
    personaName: String,
    personaIconKey: String,
    personaTagline: String,
    providerName: String,
    mood: String,
    avatarGender: String,
    highFps: Boolean,
    onQuickPrompt: (String) -> Unit,
    onOpenArena: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    var avatarLibrary by remember { mutableStateOf<AvatarLibrary?>(null) }
    LaunchedEffect(context) {
        avatarLibrary = withContext(Dispatchers.IO) { AvatarLibrary.load(context) }
    }
    val expr = remember(avatarLibrary, avatarGender, mood) {
        val baseName = when (mood.lowercase()) {
            "happy" -> "Happy"
            "thinking" -> "Thinking"
            "sad" -> "Sad"
            "surprised" -> "Surprised"
            else -> "Neutral"
        }
        avatarLibrary?.get(avatarGender, baseName, "Base")
            ?: avatarLibrary?.get(avatarGender, "Happy", "Base")
    }
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        DotMatrixAvatarCanvas(
            expression = expr,
            scale = 1.0f,
            showGrid = false,
            highFps = highFps,
            modifier = Modifier.size(132.dp),
        )
        Spacer(Modifier.height(10.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            VectorBadgeIcon(iconKey = personaIconKey, contentDescription = null, tint = visuals.primary, containerSize = 30.dp, iconSize = 17.dp)
            Text(
                text = personaName,
                style = MaterialTheme.typography.headlineSmall.copy(fontWeight = FontWeight.Bold),
                color = CelTextPrimary,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            text = personaTagline,
            style = MaterialTheme.typography.bodySmall,
            color = CelTextSecondary,
        )
        Spacer(Modifier.height(6.dp))
        Text(
            text = "Active Engine: $providerName",
            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
            color = CelLavender,
        )
        Spacer(Modifier.height(18.dp))
        GlassCard(contentPadding = 12.dp, modifier = Modifier.fillMaxWidth()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Quick Launch", style = MaterialTheme.typography.labelLarge, color = CelLavender)
                Row(
                    modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    GlassPill(onClick = { onQuickPrompt("Hey Cel! Give me a quick rundown of what we can build today.") }) {
                        Text("Say hi to Cel", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, softWrap = false)
                    }
                    GlassPill(onClick = { onQuickPrompt("/web latest Android AI news") }) {
                        Text("/web search", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, softWrap = false)
                    }
                    GlassPill(onClick = onOpenArena) {
                        Icon(Icons.Rounded.Forum, contentDescription = null, tint = Color(0xFF38BDF8), modifier = Modifier.size(14.dp))
                        Text("2-AI Arena", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, softWrap = false)
                    }
                    GlassPill(onClick = { onQuickPrompt("/illume neon obsidian cyberpunk library, liquid glass aesthetic") }) {
                        Text("/illume art", style = MaterialTheme.typography.labelSmall, color = CelTextPrimary, maxLines = 1, softWrap = false)
                    }
                }
            }
        }
    }
}

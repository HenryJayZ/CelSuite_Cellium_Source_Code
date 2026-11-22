package com.henny.cellium.ui.arena

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.SkipNext
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.chat.PersonaPickerSheet
import com.henny.cellium.ui.chat.ProviderSearchDropdownSheet
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.MarkdownMessageContent
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelRedError
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals

@Composable
fun ArenaScreen(
    viewModel: CelliumViewModel,
    initialSessionId: String? = null,
    onBack: () -> Unit,
    onOpenSettingsProviders: () -> Unit,
) {
    BackHandler {
        viewModel.arenaController.pause()
        onBack()
    }

    val visuals = LocalCelliumVisuals.current
    val ui by viewModel.uiState.collectAsStateWithLifecycle()
    val arena by viewModel.arenaController.state.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()

    var input by remember { mutableStateOf("") }
    var pickingProviderForSlot by remember { mutableStateOf<String?>(null) }
    var pickingPersonaForSlot by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(initialSessionId) {
        viewModel.arenaController.ensureArenaSession(initialSessionId)
    }

    LaunchedEffect(arena.messages.size, arena.streamingContent.isNotEmpty()) {
        val count = arena.messages.size + if (arena.activeSpeaker.isNotEmpty()) 1 else 0
        if (count > 0) listState.animateScrollToItem(count - 1)
    }

    val provAName = ui.providers.firstOrNull { it.id == arena.providerAId }?.name
        ?: ProviderCatalog.byId(arena.providerAId)?.name ?: "Provider A"
    val provBName = ui.providers.firstOrNull { it.id == arena.providerBId }?.name
        ?: ProviderCatalog.byId(arena.providerBId)?.name ?: "Provider B"
    val personaA = BuiltInPersonas.ALL.firstOrNull { it.id == arena.personaAId } ?: BuiltInPersonas.ALL.first()
    val personaB = BuiltInPersonas.ALL.firstOrNull { it.id == arena.personaBId } ?: BuiltInPersonas.ALL[1]

    Column(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .imePadding(),
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                IconButton(onClick = { viewModel.arenaController.pause(); onBack() }) {
                    Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = "Back", tint = CelTextPrimary)
                }
                VectorBadgeIcon(iconKey = "forum", contentDescription = null, tint = Color(0xFF38BDF8), containerSize = 32.dp, iconSize = 18.dp)
                Column {
                    Text("Arena Mode · 2-AI Group Chat", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                    Text(
                        text = when {
                            arena.isRunning && arena.isPaused -> "Paused · Tap Resume or send a message"
                            arena.isRunning -> "Live · AI ${arena.activeSpeaker.ifBlank { arena.nextTurnSlot }} speaking"
                            else -> "Pick 2 AIs, send a topic, chime in anytime"
                        },
                        style = MaterialTheme.typography.labelSmall,
                        color = CelLavender,
                    )
                }
            }
            IconButton(
                onClick = { viewModel.arenaController.startFreshArena() },
                modifier = Modifier.testTag("arena_new_button"),
            ) {
                Icon(Icons.Rounded.Add, contentDescription = "New Arena", tint = CelLavender)
            }
        }

        // Slot A & Slot B Picker Row
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ArenaSlotCard(
                slotLabel = "AI A",
                accent = visuals.primary,
                providerName = provAName,
                modelName = arena.modelA,
                personaName = personaA.name,
                personaIconKey = personaA.iconKey,
                isSpeaking = arena.activeSpeaker == "A",
                onPickProvider = { pickingProviderForSlot = "A" },
                onPickPersona = { pickingPersonaForSlot = "A" },
                modifier = Modifier.weight(1f),
            )
            ArenaSlotCard(
                slotLabel = "AI B",
                accent = Color(0xFF38BDF8),
                providerName = provBName,
                modelName = arena.modelB,
                personaName = personaB.name,
                personaIconKey = personaB.iconKey,
                isSpeaking = arena.activeSpeaker == "B",
                onPickProvider = { pickingProviderForSlot = "B" },
                onPickPersona = { pickingPersonaForSlot = "B" },
                modifier = Modifier.weight(1f),
            )
        }

        // Playback Controls Bar (Pause / Resume / Step / Stop)
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (arena.isRunning && !arena.isPaused) {
                Button(
                    onClick = { viewModel.arenaController.pause() },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF59E0B)),
                    modifier = Modifier.weight(1f).testTag("arena_pause_button"),
                ) {
                    Icon(Icons.Rounded.Pause, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.size(4.dp))
                    Text("Pause")
                }
            } else {
                Button(
                    onClick = { viewModel.arenaController.resume() },
                    enabled = arena.messages.isNotEmpty(),
                    colors = ButtonDefaults.buttonColors(containerColor = CelEmeraldThought),
                    modifier = Modifier.weight(1f).testTag("arena_resume_button"),
                ) {
                    Icon(Icons.Rounded.PlayArrow, contentDescription = null, tint = Color.Black, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.size(4.dp))
                    Text(if (arena.isPaused) "Resume" else "Auto Talk", color = Color.Black)
                }
            }
            OutlinedButton(
                onClick = { viewModel.arenaController.stepOnce() },
                enabled = arena.messages.isNotEmpty() && (!arena.isRunning || arena.isPaused),
                modifier = Modifier.testTag("arena_step_button"),
            ) {
                Icon(Icons.Rounded.SkipNext, contentDescription = null, modifier = Modifier.size(16.dp))
                Text("Step")
            }
            if (arena.isRunning) {
                OutlinedButton(
                    onClick = { viewModel.arenaController.stop() },
                    modifier = Modifier.testTag("arena_stop_button"),
                ) {
                    Icon(Icons.Rounded.Stop, contentDescription = null, tint = CelRedError, modifier = Modifier.size(16.dp))
                    Text("Stop", color = CelRedError)
                }
            }
        }

        arena.errorMessage?.let { err ->
            Text(
                text = err,
                style = MaterialTheme.typography.labelSmall,
                color = CelRedError,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 2.dp),
            )
        }

        // Conversation Feed
        Box(modifier = Modifier.weight(1f).fillMaxWidth()) {
            if (arena.messages.isEmpty()) {
                Column(
                    modifier = Modifier.fillMaxSize().padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center,
                ) {
                    Icon(Icons.Rounded.Forum, contentDescription = null, tint = Color(0xFF38BDF8), modifier = Modifier.size(48.dp))
                    Spacer(Modifier.height(10.dp))
                    Text("Start a 2-AI Group Chat", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        text = "Send a topic below. AI A and AI B will debate, collaborate, or brainstorm turn-by-turn. Pause, resume, or jump into the chat anytime.",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(arena.messages, key = { it.id }) { msg ->
                        val isUser = msg.role == "user"
                        val isSlotB = msg.speakerLabel.startsWith("AI B")
                        val accent = when {
                            isUser -> CelEmeraldThought
                            isSlotB -> Color(0xFF38BDF8)
                            else -> visuals.primary
                        }
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(16.dp))
                                .background(if (isUser) accent.copy(alpha = 0.16f) else visuals.glassSurface)
                                .border(1.dp, accent.copy(alpha = 0.55f), RoundedCornerShape(16.dp))
                                .padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(6.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = msg.speakerLabel.ifBlank { if (isUser) "You" else "AI" },
                                    style = MaterialTheme.typography.labelSmall.copy(
                                        fontFamily = JetBrainsMono,
                                        fontWeight = FontWeight.Bold,
                                    ),
                                    color = accent,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                if (!isUser && msg.modelName.isNotBlank()) {
                                    Text(
                                        text = msg.modelName.take(20),
                                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                        color = CelTextMuted,
                                        maxLines = 1,
                                        softWrap = false,
                                    )
                                }
                            }
                            MarkdownMessageContent(text = msg.content)
                        }
                    }

                    if (arena.activeSpeaker.isNotEmpty()) {
                        item(key = "arena_streaming") {
                            val accent = if (arena.activeSpeaker == "B") Color(0xFF38BDF8) else visuals.primary
                            GlassCard(highlighted = true, contentPadding = 12.dp, modifier = Modifier.fillMaxWidth()) {
                                Text(
                                    text = "AI ${arena.activeSpeaker} is replying...",
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = accent,
                                )
                                Spacer(Modifier.height(4.dp))
                                MarkdownMessageContent(text = arena.streamingContent.ifBlank { "..." })
                            }
                        }
                    }
                }
            }
        }

        // User Injection Bar (always enabled — chime in anytime!)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                placeholder = { Text("Send a topic or chime in anytime...") },
                modifier = Modifier.weight(1f).testTag("arena_input_field"),
                maxLines = 3,
            )
            IconButton(
                onClick = {
                    val toSend = input.trim()
                    if (toSend.isNotEmpty()) {
                        input = ""
                        viewModel.arenaController.sendUserPromptAndRun(toSend, autoContinue = true)
                    }
                },
                enabled = input.isNotBlank(),
                modifier = Modifier
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(if (input.isNotBlank()) visuals.primary else Color(0xFF2D2246))
                    .testTag("arena_send_button"),
            ) {
                Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = "Send to Arena", tint = Color.White)
            }
        }
    }

    pickingProviderForSlot?.let { slot ->
        ProviderSearchDropdownSheet(
            savedProviders = ui.providers,
            activeProviderId = if (slot == "A") arena.providerAId else arena.providerBId,
            onSelectCatalogProvider = { entry ->
                viewModel.activateCatalogProvider(entry)
                if (slot == "A") {
                    viewModel.arenaController.updateSlotA(entry.id, entry.defaultModel, arena.personaAId)
                } else {
                    viewModel.arenaController.updateSlotB(entry.id, entry.defaultModel, arena.personaBId)
                }
            },
            onSelectSavedProviderModel = { pid, model ->
                if (slot == "A") {
                    viewModel.arenaController.updateSlotA(pid, model, arena.personaAId)
                } else {
                    viewModel.arenaController.updateSlotB(pid, model, arena.personaBId)
                }
            },
            onFetchActiveModels = { viewModel.fetchLiveModels(it) },
            onOpenSettingsProviders = onOpenSettingsProviders,
            onDismiss = { pickingProviderForSlot = null },
        )
    }

    pickingPersonaForSlot?.let { slot ->
        PersonaPickerSheet(
            activePersonaId = if (slot == "A") arena.personaAId else arena.personaBId,
            customPersonas = ui.customPersonas,
            onSelect = { pid ->
                if (slot == "A") {
                    viewModel.arenaController.updateSlotA(arena.providerAId, arena.modelA, pid)
                } else {
                    viewModel.arenaController.updateSlotB(arena.providerBId, arena.modelB, pid)
                }
            },
            onDismiss = { pickingPersonaForSlot = null },
        )
    }
}

@Composable
private fun ArenaSlotCard(
    slotLabel: String,
    accent: Color,
    providerName: String,
    modelName: String,
    personaName: String,
    personaIconKey: String,
    isSpeaking: Boolean,
    onPickProvider: () -> Unit,
    onPickPersona: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalCelliumVisuals.current
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(if (isSpeaking) accent.copy(alpha = 0.22f) else visuals.glassSurface)
            .border(if (isSpeaking) 1.5.dp else 1.dp, accent.copy(alpha = if (isSpeaking) 0.9f else 0.45f), RoundedCornerShape(14.dp))
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth().clickable(onClick = onPickPersona),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            VectorBadgeIcon(iconKey = personaIconKey, contentDescription = null, tint = accent, containerSize = 22.dp, iconSize = 13.dp)
            Text(
                text = "$slotLabel · $personaName",
                style = MaterialTheme.typography.labelMedium,
                color = CelTextPrimary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Surface(
            onClick = onPickProvider,
            shape = RoundedCornerShape(8.dp),
            color = accent.copy(alpha = 0.14f),
        ) {
            Text(
                text = "${providerName.take(14)} · ${modelName.take(14)}",
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                color = CelLavender,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 4.dp),
            )
        }
    }
}

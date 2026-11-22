package com.henny.cellium.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Archive
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.PushPin
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Unarchive
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderCatalogEntry
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.data.BuiltInPersonas
import com.henny.cellium.data.local.CustomPersonaEntity
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.data.local.SessionEntity
import com.henny.cellium.ui.components.CelliumIcons
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

/**
 * Searchable 200+ AI Provider Dropdown Sheet.
 * Common & Free/Keyless providers appear first; category pills + instant search filter all 200+ entries.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProviderSearchDropdownSheet(
    savedProviders: List<ProviderProfileEntity>,
    activeProviderId: String?,
    onSelectCatalogProvider: (ProviderCatalogEntry) -> Unit,
    onSelectSavedProviderModel: (String, String) -> Unit,
    onOpenSettingsProviders: () -> Unit,
    onDismiss: () -> Unit,
    onFetchActiveModels: (suspend (ProviderProfileEntity) -> Result<List<String>>)? = null,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var modelQuery by remember { mutableStateOf("") }
    var selectedCategory by remember { mutableStateOf("All") }
    var fetchingModels by remember { mutableStateOf(false) }
    var fetchError by remember { mutableStateOf<String?>(null) }
    var liveFetchedModels by remember(activeProviderId) { mutableStateOf<List<String>?>(null) }
    val categories = remember {
        listOf("All", "Popular", "Free", "Frontier", "Fast", "Aggregator", "Regional", "Enterprise", "Local", "Offline")
    }
    val savedById = remember(savedProviders) { savedProviders.associateBy { it.id } }
    val activeSaved = savedById[activeProviderId]

    val filtered = remember(query, selectedCategory) {
        val base = ProviderCatalog.search(query)
        when (selectedCategory) {
            "All" -> base
            "Popular" -> base.filter { it.popular }
            else -> base.filter { it.category.equals(selectedCategory, ignoreCase = true) }
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = Color(0xFF130B24),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text(
                        text = "AI Providers (${ProviderCatalog.ALL.size}+)",
                        style = MaterialTheme.typography.titleMedium,
                        color = CelTextPrimary,
                    )
                    Text(
                        text = "Common & Free keyless providers pinned first",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextMuted,
                    )
                }
                OutlinedButton(onClick = { onDismiss(); onOpenSettingsProviders() }) {
                    Icon(Icons.Rounded.Key, contentDescription = null, modifier = Modifier.size(15.dp))
                    Spacer(Modifier.size(6.dp))
                    Text("Keys")
                }
            }

            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                placeholder = { Text("Search 200+ providers, regions, or models...") },
                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, tint = CelLavender) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("provider_search_input"),
            )

            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                categories.forEach { cat ->
                    FilterChip(
                        selected = selectedCategory == cat,
                        onClick = { selectedCategory = cat },
                        label = { Text(cat, style = MaterialTheme.typography.labelSmall) },
                    )
                }
            }

            // Live models for currently active provider (ALL models returned by the key, searchable)
            if (activeSaved != null && query.isBlank() && activeSaved.protocol != "on_device") {
                val allModels = remember(activeSaved.cachedModelsJson, activeSaved.selectedModel, liveFetchedModels) {
                    val base = liveFetchedModels ?: ProviderPresets.decodeModels(activeSaved.cachedModelsJson)
                    (base + activeSaved.selectedModel).filter { it.isNotBlank() }.distinct()
                }
                val filteredModels = remember(allModels, modelQuery) {
                    val mq = modelQuery.trim().lowercase()
                    if (mq.isEmpty()) allModels else allModels.filter { it.lowercase().contains(mq) }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "Models · ${activeSaved.name} (${filteredModels.size}/${allModels.size})",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelLavender,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    if (onFetchActiveModels != null) {
                        OutlinedButton(
                            onClick = {
                                fetchingModels = true
                                fetchError = null
                                scope.launch {
                                    val res = onFetchActiveModels(activeSaved)
                                    fetchingModels = false
                                    res.onSuccess { list ->
                                        liveFetchedModels = list
                                    }.onFailure { err ->
                                        fetchError = err.localizedMessage ?: "Failed to ping key"
                                    }
                                }
                            },
                            enabled = !fetchingModels,
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            if (fetchingModels) {
                                CircularProgressIndicator(modifier = Modifier.size(13.dp), strokeWidth = 2.dp)
                            } else {
                                Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(14.dp))
                            }
                            Spacer(Modifier.size(4.dp))
                            Text("Fetch Live", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                }
                if (fetchError != null) {
                    Text(
                        text = fetchError!!,
                        style = MaterialTheme.typography.labelSmall,
                        color = CelDangerRed,
                    )
                }
                if (allModels.size > 6) {
                    OutlinedTextField(
                        value = modelQuery,
                        onValueChange = { modelQuery = it },
                        placeholder = { Text("Search all ${allModels.size} models for ${activeSaved.name}...") },
                        leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp), tint = CelLavender) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().testTag("active_model_search_input"),
                    )
                }
                if (filteredModels.isNotEmpty()) {
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth().heightIn(max = 175.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        items(filteredModels, key = { "active_model_$it" }) { m ->
                            val isSel = m == activeSaved.selectedModel
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (isSel) visuals.primary.copy(alpha = 0.24f) else visuals.glassSurface)
                                    .border(1.dp, if (isSel) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(10.dp))
                                    .clickable {
                                        onSelectSavedProviderModel(activeSaved.id, m)
                                        onDismiss()
                                    }
                                    .padding(horizontal = 10.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    text = m.removePrefix("models/"),
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = if (isSel) CelTextPrimary else CelTextSecondary,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f),
                                )
                                if (isSel) {
                                    Icon(Icons.Rounded.Check, contentDescription = "Selected model", tint = visuals.primary, modifier = Modifier.size(15.dp))
                                }
                            }
                        }
                    }
                } else if (activeSaved.requiresKey) {
                    Text(
                        text = if (activeSaved.apiKey.isBlank()) "Add your API key in Keys, then tap Fetch Live to load every model on your key." else "Tap Fetch Live above to query all models available on your key.",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextMuted,
                    )
                }
            }

            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 380.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(filtered, key = { it.id }) { entry ->
                    val saved = savedById[entry.id]
                    val isActive = entry.id == activeProviderId
                    val hasKey = !saved?.apiKey.isNullOrBlank()
                    val catColor = CelliumIcons.accentForCategory(entry.category)

                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (isActive) visuals.primary.copy(alpha = 0.20f) else visuals.glassSurface)
                            .border(
                                width = 1.dp,
                                color = if (isActive) visuals.activeBorder else visuals.subtleBorder,
                                shape = RoundedCornerShape(14.dp),
                            )
                            .clickable {
                                onSelectCatalogProvider(entry)
                                onDismiss()
                            }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        VectorBadgeIcon(
                            iconKey = entry.iconKey,
                            contentDescription = entry.name,
                            tint = catColor,
                            containerSize = 32.dp,
                            iconSize = 17.dp,
                        )
                        Column(modifier = Modifier.weight(1f)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Text(
                                    text = entry.name,
                                    style = MaterialTheme.typography.titleSmall,
                                    color = CelTextPrimary,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                    modifier = Modifier.weight(1f, fill = false),
                                )
                                Surface(
                                    shape = RoundedCornerShape(6.dp),
                                    color = catColor.copy(alpha = 0.18f),
                                ) {
                                    Text(
                                        text = if (!entry.requiresKey) "NO KEY" else entry.category.uppercase(),
                                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                        color = catColor,
                                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                                    )
                                }
                            }
                            Text(
                                text = saved?.selectedModel?.ifBlank {
                                    if (entry.requiresKey) "Ping key to load live models" else entry.defaultModel
                                } ?: if (entry.requiresKey) "Requires API key · Fetch live models" else entry.defaultModel,
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = CelTextMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        if (hasKey) {
                            Icon(Icons.Rounded.Key, contentDescription = "Key saved", tint = CelEmeraldThought, modifier = Modifier.size(16.dp))
                        }
                        if (isActive) {
                            Icon(Icons.Rounded.Check, contentDescription = "Active", tint = visuals.primary, modifier = Modifier.size(18.dp))
                        }
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SessionsDrawerSheet(
    sessions: List<SessionEntity>,
    activeSessionId: String?,
    onSearchContent: suspend (String) -> Set<String>,
    onSelect: (String) -> Unit,
    onNewChat: () -> Unit,
    onOpenArena: () -> Unit,
    onOpenArenaSession: (String) -> Unit,
    onTogglePin: (SessionEntity) -> Unit,
    onToggleArchive: (SessionEntity) -> Unit,
    onDelete: (String) -> Unit,
    onExportMd: () -> Unit,
    onExportJson: () -> Unit,
    onDismiss: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    var search by remember { mutableStateOf("") }
    var showArchived by remember { mutableStateOf(false) }
    var contentMatchIds by remember { mutableStateOf<Set<String>>(emptySet()) }

    LaunchedEffect(search) {
        contentMatchIds = if (search.trim().length >= 2) onSearchContent(search) else emptySet()
    }

    val filtered = remember(sessions, search, showArchived, contentMatchIds) {
        val q = search.trim().lowercase()
        sessions.filter { s ->
            val archiveOk = if (showArchived) s.archived else !s.archived
            val queryOk = q.isEmpty() ||
                s.title.lowercase().contains(q) ||
                s.lastMessagePreview.lowercase().contains(q) ||
                s.id in contentMatchIds
            archiveOk && queryOk
        }
    }

    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Color(0xFF130B24)) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("Sessions & Arena", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedButton(
                        onClick = { onDismiss(); onOpenArena() },
                        modifier = Modifier.testTag("drawer_arena_button"),
                    ) {
                        Icon(Icons.Rounded.Forum, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.size(4.dp))
                        Text("Arena")
                    }
                    Button(
                        onClick = { onNewChat(); onDismiss() },
                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                    ) {
                        Icon(Icons.Rounded.Add, contentDescription = null, modifier = Modifier.size(16.dp))
                        Text("New")
                    }
                }
            }

            OutlinedTextField(
                value = search,
                onValueChange = { search = it },
                placeholder = { Text("Search titles & message contents...") },
                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, tint = CelLavender) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().testTag("sessions_search_input"),
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(
                        selected = !showArchived,
                        onClick = { showArchived = false },
                        label = { Text("Active (${sessions.count { !it.archived }})") },
                    )
                    FilterChip(
                        selected = showArchived,
                        onClick = { showArchived = true },
                        label = { Text("Archived (${sessions.count { it.archived }})") },
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    IconButton(onClick = onExportMd, modifier = Modifier.size(34.dp)) {
                        Icon(Icons.Rounded.Download, contentDescription = "Export Markdown", tint = CelLavender, modifier = Modifier.size(18.dp))
                    }
                    OutlinedButton(onClick = onExportJson) {
                        Text("JSON", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }

            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 360.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(filtered, key = { it.id }) { s ->
                    val active = s.id == activeSessionId
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (active) visuals.primary.copy(alpha = 0.22f) else visuals.glassSurface)
                            .border(1.dp, if (active) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(14.dp))
                            .clickable {
                                onDismiss()
                                if (s.isArena) onOpenArenaSession(s.id) else onSelect(s.id)
                            }
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        if (s.isArena) {
                            VectorBadgeIcon(
                                iconKey = "forum",
                                contentDescription = "Arena session",
                                tint = Color(0xFF38BDF8),
                                containerSize = 28.dp,
                                iconSize = 15.dp,
                                modifier = Modifier.padding(end = 8.dp),
                            )
                        }
                        Column(modifier = Modifier.weight(1f)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(4.dp),
                            ) {
                                if (s.pinned) {
                                    Icon(Icons.Rounded.PushPin, contentDescription = "Pinned", tint = CelLavender, modifier = Modifier.size(13.dp))
                                }
                                Text(
                                    text = s.title,
                                    style = MaterialTheme.typography.titleSmall,
                                    color = CelTextPrimary,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Text(
                                text = "${s.messageCount} msgs · ${s.modelName.removePrefix("models/").ifBlank { "default" }}",
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = CelTextMuted,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        IconButton(onClick = { onTogglePin(s) }, modifier = Modifier.size(32.dp)) {
                            Icon(
                                Icons.Rounded.PushPin,
                                contentDescription = "Pin",
                                tint = if (s.pinned) visuals.primary else CelTextMuted,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                        IconButton(onClick = { onToggleArchive(s) }, modifier = Modifier.size(32.dp)) {
                            Icon(
                                if (s.archived) Icons.Rounded.Unarchive else Icons.Rounded.Archive,
                                contentDescription = if (s.archived) "Unarchive" else "Archive",
                                tint = CelTextMuted,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                        IconButton(onClick = { onDelete(s.id) }, modifier = Modifier.size(32.dp)) {
                            Icon(Icons.Rounded.DeleteOutline, contentDescription = "Delete", tint = CelTextMuted, modifier = Modifier.size(16.dp))
                        }
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonaPickerSheet(
    activePersonaId: String,
    customPersonas: List<CustomPersonaEntity>,
    onSelect: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = Color(0xFF130B24)) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("Switch Persona", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
            LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 420.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(BuiltInPersonas.ALL, key = { it.id }) { p ->
                    val sel = p.id == activePersonaId
                    val accent = runCatching { Color(android.graphics.Color.parseColor(p.accentHex)) }.getOrDefault(visuals.primary)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (sel) visuals.primary.copy(alpha = 0.22f) else visuals.glassSurface)
                            .border(1.dp, if (sel) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(14.dp))
                            .clickable { onSelect(p.id); onDismiss() }
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        VectorBadgeIcon(iconKey = p.iconKey, contentDescription = p.name, tint = accent, containerSize = 34.dp, iconSize = 18.dp)
                        Column(modifier = Modifier.weight(1f)) {
                            Text(p.name, style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                            Text(p.tagline, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        if (sel) Icon(Icons.Rounded.Check, contentDescription = "Selected", tint = visuals.primary)
                    }
                }
                items(customPersonas, key = { it.id }) { c ->
                    val sel = c.id == activePersonaId
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (sel) visuals.primary.copy(alpha = 0.22f) else visuals.glassSurface)
                            .border(1.dp, if (sel) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(14.dp))
                            .clickable { onSelect(c.id); onDismiss() }
                            .padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        VectorBadgeIcon(iconKey = c.iconKey, contentDescription = c.name, tint = visuals.secondary, containerSize = 34.dp, iconSize = 18.dp)
                        Column(modifier = Modifier.weight(1f)) {
                            Text("${c.name} · Custom", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                            Text(c.tagline.ifBlank { c.systemPrompt.take(60) }, style = MaterialTheme.typography.labelSmall, color = CelTextSecondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        if (sel) Icon(Icons.Rounded.Check, contentDescription = "Selected", tint = visuals.primary)
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
        }
    }
}

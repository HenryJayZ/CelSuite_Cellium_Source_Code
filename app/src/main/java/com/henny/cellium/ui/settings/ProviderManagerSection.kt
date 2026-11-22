package com.henny.cellium.ui.settings

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CleaningServices
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Star
import androidx.compose.material.icons.rounded.StarOutline
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.henny.cellium.ai.ProviderCatalog
import com.henny.cellium.ai.ProviderPresets
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.core.StarredModelEntry
import com.henny.cellium.data.local.ProviderProfileEntity
import com.henny.cellium.ui.chat.CelliumUiState
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.chat.ProviderSearchDropdownSheet
import com.henny.cellium.ui.components.GlassCard
import com.henny.cellium.ui.components.VectorBadgeIcon
import com.henny.cellium.ui.theme.CelAmber
import com.henny.cellium.ui.theme.CelDangerRed
import com.henny.cellium.ui.theme.CelEmeraldThought
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelTerminalBg
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProvidersHubCard(
    uiState: CelliumUiState,
    prefs: CelliumPreferences,
    viewModel: CelliumViewModel,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    var editingProvider by remember { mutableStateOf<ProviderProfileEntity?>(null) }
    var showAddCustom by remember { mutableStateOf(false) }
    var showCatalogSheet by remember { mutableStateOf(false) }
    var filterQuery by remember { mutableStateOf("") }

    val starredModels = remember(prefs.starredModelsJson) {
        viewModel.prefsStore.decodeStarredModels(prefs.starredModelsJson)
    }

    val displayedProviders = remember(uiState.providers, filterQuery, prefs.hiddenProviderIds) {
        val q = filterQuery.trim().lowercase()
        val sorted = uiState.providers.sortedByDescending { it.usageCount }
        if (q.isEmpty()) {
            sorted.filter { it.id !in prefs.hiddenProviderIds || it.id == uiState.activeProvider?.id }.take(14)
        } else {
            sorted.filter {
                it.name.lowercase().contains(q) || it.selectedModel.lowercase().contains(q)
            }
        }
    }

    GlassCard(highlighted = true, shape = RoundedCornerShape(22.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Rounded.Key, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("AI Providers & Keys (${ProviderCatalog.ALL.size}+)", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        text = "Sorted by usage · ${starredModels.size} starred · ${prefs.hiddenProviderIds.size} hidden",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            IconButton(
                onClick = { showAddCustom = true },
                modifier = Modifier.testTag("settings_add_provider_button"),
            ) {
                Icon(Icons.Rounded.Add, contentDescription = "Add custom provider", tint = visuals.primary)
            }
        }

        Spacer(Modifier.height(10.dp))

        Button(
            onClick = { showCatalogSheet = true },
            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().testTag("settings_browse_200_providers"),
        ) {
            Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("Browse All ${ProviderCatalog.ALL.size}+ Providers", maxLines = 1, softWrap = false)
        }

        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = filterQuery,
            onValueChange = { filterQuery = it },
            placeholder = { Text("Filter configured or hidden providers...") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
        )

        Spacer(Modifier.height(10.dp))

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            displayedProviders.forEach { p ->
                val isActive = uiState.activeProvider?.id == p.id
                val isHidden = p.id in prefs.hiddenProviderIds
                val isConfigured = !p.requiresKey || p.protocol == "on_device" || p.apiKey.isNotBlank() || p.baseUrl.contains("127.0.0.1")
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .background(if (isActive) visuals.primary.copy(alpha = 0.20f) else CelTerminalBg.copy(alpha = 0.7f))
                        .border(1.dp, if (isActive) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(14.dp))
                        .clickable { editingProvider = p }
                        .padding(horizontal = 10.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    VectorBadgeIcon(
                        iconKey = p.badge,
                        contentDescription = p.name,
                        tint = if (isConfigured) CelEmeraldThought else visuals.primary,
                        containerSize = 32.dp,
                        iconSize = 17.dp,
                    )
                    Spacer(Modifier.width(9.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(
                                text = p.name,
                                style = MaterialTheme.typography.titleSmall,
                                color = if (isHidden) CelTextMuted else CelTextPrimary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            Box(
                                modifier = Modifier
                                    .size(7.dp)
                                    .clip(CircleShape)
                                    .background(if (isConfigured) CelEmeraldThought else CelAmber)
                            )
                        }
                        val detail = buildString {
                            append(p.selectedModel.ifBlank { "Tap to configure" })
                            if (p.usageCount > 0) append(" · ${p.usageCount} uses")
                        }
                        Text(
                            text = detail,
                            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                            color = CelTextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    if (!isActive) {
                        IconButton(
                            onClick = { viewModel.toggleHideProvider(p.id) },
                            modifier = Modifier.size(30.dp),
                        ) {
                            Icon(
                                imageVector = if (isHidden) Icons.Rounded.Visibility else Icons.Rounded.VisibilityOff,
                                contentDescription = if (isHidden) "Unhide" else "Hide",
                                tint = CelTextMuted,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                    }
                    TextButton(onClick = { viewModel.selectProvider(p.id) }) {
                        Text(
                            text = if (isActive) "Active" else "Use",
                            color = if (isActive) CelEmeraldThought else visuals.primary,
                            maxLines = 1,
                            softWrap = false,
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        HorizontalDivider(color = visuals.subtleBorder)
        Spacer(Modifier.height(10.dp))

        Text(
            text = "Auto-Retry on Rate Limit / Busy: ${prefs.maxAutoRetries}x",
            style = MaterialTheme.typography.labelMedium,
            color = CelTextPrimary,
        )
        Text(
            text = if (prefs.maxAutoRetries == 0) "Disabled — fail immediately on 429/503" else "Automatically retries HTTP 429 / 503 with smart backoff (default 10x)",
            style = MaterialTheme.typography.labelSmall,
            color = CelTextSecondary,
        )
        Slider(
            value = prefs.maxAutoRetries.toFloat(),
            onValueChange = { v ->
                scope.launch { viewModel.prefsStore.updateMaxAutoRetries(v.toInt()) }
            },
            valueRange = 0f..15f,
            steps = 14,
        )
    }

    if (showCatalogSheet) {
        ProviderSearchDropdownSheet(
            savedProviders = uiState.providers,
            activeProviderId = uiState.activeProvider?.id,
            onSelectCatalogProvider = { entry ->
                viewModel.activateCatalogProvider(entry)
                val saved = uiState.providers.firstOrNull { it.id == entry.id } ?: entry.toEntity()
                if (entry.requiresKey && saved.apiKey.isBlank()) {
                    editingProvider = saved
                }
            },
            onSelectSavedProviderModel = { pid, model -> viewModel.selectProvider(pid, model) },
            onFetchActiveModels = { viewModel.fetchLiveModels(it) },
            onOpenSettingsProviders = {},
            onDismiss = { showCatalogSheet = false },
            hiddenProviderIds = prefs.hiddenProviderIds,
            starredModels = starredModels,
            onToggleHideProvider = { viewModel.toggleHideProvider(it) },
            onToggleStarModel = { pid, pname, model -> viewModel.toggleStarModel(pid, pname, model) },
            onRequestConfigureKey = { prov -> editingProvider = prov },
        )
    }

    editingProvider?.let { prov ->
        ProviderEditDialog(
            provider = prov,
            onDismiss = { editingProvider = null },
            onSave = { updated ->
                scope.launch {
                    viewModel.saveProviderProfile(updated)
                    viewModel.selectProvider(updated.id, updated.selectedModel)
                }
                editingProvider = null
            },
            onDelete = if (prov.isCustom) {
                {
                    viewModel.deleteCustomProvider(prov.id)
                    editingProvider = null
                }
            } else null,
            onFetchModels = { draft -> viewModel.fetchLiveModels(draft) },
            starredModels = starredModels,
            onToggleStarModel = { pid, pname, model -> viewModel.toggleStarModel(pid, pname, model) },
        )
    }

    if (showAddCustom) {
        AddCustomProviderDialog(
            onDismiss = { showAddCustom = false },
            onCreate = { name, url, key, model, protocol ->
                viewModel.addCustomProvider(name, url, key, model, protocol)
                showAddCustom = false
            },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProviderEditDialog(
    provider: ProviderProfileEntity,
    onDismiss: () -> Unit,
    onSave: (ProviderProfileEntity) -> Unit,
    onDelete: (() -> Unit)?,
    onFetchModels: suspend (ProviderProfileEntity) -> Result<List<String>>,
    starredModels: List<StarredModelEntry> = emptyList(),
    onToggleStarModel: ((String, String, String) -> Unit)? = null,
) {
    val scope = rememberCoroutineScope()
    val visuals = LocalCelliumVisuals.current
    var baseUrl by remember(provider.id) { mutableStateOf(provider.baseUrl) }
    var apiKey by remember(provider.id) { mutableStateOf(provider.apiKey) }
    var selectedModel by remember(provider.id) { mutableStateOf(provider.selectedModel) }
    var models by remember(provider.id) { mutableStateOf(ProviderPresets.decodeModels(provider.cachedModelsJson)) }
    var modelSearch by remember(provider.id) { mutableStateOf("") }
    var fetching by remember { mutableStateOf(false) }
    var statusText by remember { mutableStateOf<String?>(null) }
    var statusIsError by remember { mutableStateOf(false) }

    val starredKeys = remember(starredModels) {
        starredModels.map { "${it.providerId}::${it.modelName}" }.toSet()
    }
    val filteredModels = remember(models, modelSearch) {
        val q = modelSearch.trim().lowercase()
        if (q.isEmpty()) models else models.filter { it.lowercase().contains(q) }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                VectorBadgeIcon(iconKey = provider.badge, contentDescription = null, containerSize = 28.dp, iconSize = 15.dp)
                Text(provider.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (provider.protocol != "on_device") {
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = { apiKey = it },
                        label = { Text(if (provider.requiresKey) "API Key" else "API Key (Optional)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().testTag("edit_provider_key"),
                    )
                    OutlinedTextField(
                        value = baseUrl,
                        onValueChange = { baseUrl = it },
                        label = { Text("Base URL") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = selectedModel,
                        onValueChange = { selectedModel = it },
                        label = { Text("Model ID") },
                        placeholder = { Text("Ping your key below to pick a live model") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedButton(
                        onClick = {
                            fetching = true
                            statusText = null
                            statusIsError = false
                            scope.launch {
                                val draft = provider.copy(apiKey = apiKey.trim(), baseUrl = baseUrl.trim(), selectedModel = selectedModel.trim())
                                val res = onFetchModels(draft)
                                fetching = false
                                res.onSuccess { list ->
                                    models = list
                                    if (list.isNotEmpty() && (selectedModel.isBlank() || selectedModel !in list)) {
                                        selectedModel = list.first()
                                    }
                                    statusIsError = false
                                    statusText = "Key verified · Loaded all ${list.size} live models"
                                }.onFailure { err ->
                                    statusIsError = true
                                    statusText = err.localizedMessage ?: "Failed to fetch models from key"
                                }
                            }
                        },
                        enabled = !fetching,
                        modifier = Modifier.fillMaxWidth().testTag("edit_provider_fetch_models"),
                    ) {
                        if (fetching) CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        else Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Ping Key & Fetch Models", maxLines = 1, softWrap = false)
                    }
                    if (statusText != null) {
                        Text(
                            text = statusText!!,
                            style = MaterialTheme.typography.labelSmall,
                            color = if (statusIsError) CelDangerRed else CelEmeraldThought,
                        )
                    }
                    if (models.isNotEmpty()) {
                        Text(
                            text = "Live models from key: ${filteredModels.size} / ${models.size}",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelLavender,
                        )
                        if (models.size > 5) {
                            OutlinedTextField(
                                value = modelSearch,
                                onValueChange = { modelSearch = it },
                                placeholder = { Text("Search all ${models.size} models...") },
                                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp)) },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth().testTag("edit_provider_model_search"),
                            )
                        }
                        LazyColumn(
                            modifier = Modifier.fillMaxWidth().heightIn(max = 210.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            items(filteredModels, key = { it }) { m ->
                                val isSel = m == selectedModel
                                val isStarred = "${provider.id}::$m" in starredKeys
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(if (isSel) visuals.primary.copy(alpha = 0.24f) else CelTerminalBg.copy(alpha = 0.72f))
                                        .border(1.dp, if (isSel) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(10.dp))
                                        .clickable { selectedModel = m }
                                        .padding(start = 10.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    Text(
                                        text = m,
                                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                        color = if (isSel) CelTextPrimary else CelTextSecondary,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f),
                                    )
                                    if (onToggleStarModel != null) {
                                        IconButton(
                                            onClick = { onToggleStarModel(provider.id, provider.name, m) },
                                            modifier = Modifier.size(28.dp),
                                        ) {
                                            Icon(
                                                imageVector = if (isStarred) Icons.Rounded.Star else Icons.Rounded.StarOutline,
                                                contentDescription = if (isStarred) "Unstar" else "Star",
                                                tint = if (isStarred) CelAmber else CelTextMuted,
                                                modifier = Modifier.size(15.dp),
                                            )
                                        }
                                    }
                                    if (isSel) {
                                        Icon(Icons.Rounded.Check, contentDescription = "Selected", tint = visuals.primary, modifier = Modifier.size(16.dp))
                                    }
                                }
                            }
                        }
                    } else if (provider.requiresKey) {
                        Text(
                            text = "Enter your API key and tap 'Ping Key & Fetch Models' to query every model your key supports.",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                } else {
                    Text(
                        "On-Device Offline AI supports both .gguf (llama.cpp zero-copy mount) and .task/.bin (MediaPipe) models completely offline with zero API keys.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSave(
                    provider.copy(
                        apiKey = apiKey.trim(),
                        baseUrl = baseUrl.trim(),
                        selectedModel = selectedModel.trim(),
                        cachedModelsJson = ProviderPresets.encodeModels(models),
                    )
                )
            }) { Text("Save & Use", maxLines = 1, softWrap = false) }
        },
        dismissButton = {
            Row {
                if (onDelete != null) {
                    TextButton(onClick = onDelete) { Text("Delete", color = CelDangerRed, maxLines = 1, softWrap = false) }
                }
                TextButton(onClick = onDismiss) { Text("Close", maxLines = 1, softWrap = false) }
            }
        },
    )
}

@Composable
private fun AddCustomProviderDialog(
    onDismiss: () -> Unit,
    onCreate: (name: String, baseUrl: String, apiKey: String, model: String, protocol: String) -> Unit,
) {
    var name by remember { mutableStateOf("") }
    var baseUrl by remember { mutableStateOf("https://") }
    var apiKey by remember { mutableStateOf("") }
    var model by remember { mutableStateOf("") }
    var protocol by remember { mutableStateOf("openai") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Custom Provider") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(value = name, onValueChange = { name = it }, label = { Text("Provider Name") }, singleLine = true)
                OutlinedTextField(value = baseUrl, onValueChange = { baseUrl = it }, label = { Text("Base URL (/v1)") }, singleLine = true)
                OutlinedTextField(value = apiKey, onValueChange = { apiKey = it }, label = { Text("API Key (Optional for local)") }, singleLine = true)
                OutlinedTextField(value = model, onValueChange = { model = it }, label = { Text("Default Model ID") }, singleLine = true)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = protocol == "openai", onClick = { protocol = "openai" }, label = { Text("OpenAI", maxLines = 1, softWrap = false) })
                    FilterChip(selected = protocol == "anthropic", onClick = { protocol = "anthropic" }, label = { Text("Anthropic", maxLines = 1, softWrap = false) })
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onCreate(name, baseUrl, apiKey, model, protocol) },
                enabled = name.isNotBlank() && baseUrl.isNotBlank(),
            ) { Text("Add", maxLines = 1, softWrap = false) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel", maxLines = 1, softWrap = false) } },
    )
}

@Composable
fun OnDeviceModelManagerCard(
    uiState: CelliumUiState,
    prefs: CelliumPreferences,
    processRamMb: Int,
    viewModel: CelliumViewModel,
    onJumpToChat: () -> Unit = {},
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) viewModel.importLocalModel(uri, onLoadedNavigateToChat = onJumpToChat)
    }

    GlassCard(shape = RoundedCornerShape(22.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Rounded.Memory, contentDescription = null, tint = visuals.tertiary)
                Column {
                    Text("On-Device Offline AI (.gguf & .task)", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(
                        "Zero-Copy SAF Mount · Live RAM: $processRamMb MB",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextSecondary,
                    )
                }
            }
            OutlinedButton(
                onClick = { viewModel.freeAllRam() },
                shape = RoundedCornerShape(10.dp),
            ) {
                Icon(Icons.Rounded.CleaningServices, contentDescription = null, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(4.dp))
                Text("Free RAM", style = MaterialTheme.typography.labelSmall, maxLines = 1, softWrap = false)
            }
        }

        Spacer(Modifier.height(10.dp))

        val st = uiState.localModelStatus
        if (st.loaded) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(CelEmeraldThought.copy(alpha = 0.16f))
                    .padding(10.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Loaded: ${st.modelName}", style = MaterialTheme.typography.labelLarge, color = CelEmeraldThought, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("${st.runtimeEngine.ifBlank { "Offline" }} · Ready for Chat, Live & Arena", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                }
                OutlinedButton(onClick = { viewModel.unloadLocalModel() }, shape = RoundedCornerShape(10.dp)) {
                    Icon(Icons.Rounded.Stop, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("Unload", maxLines = 1, softWrap = false)
                }
            }
            Spacer(Modifier.height(8.dp))
        }

        if (st.loading) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                Text("Loading ${st.modelName} + elevating RAM guard...", style = MaterialTheme.typography.bodySmall, color = CelLavender)
            }
            Spacer(Modifier.height(8.dp))
        }

        if (st.downloadProgress != null) {
            val opLabel = st.operationLabel.ifBlank { "Downloading" }
            Text("$opLabel ${st.downloadingName} (${(st.downloadProgress * 100).toInt()}%)", style = MaterialTheme.typography.labelSmall, color = CelLavender)
            Spacer(Modifier.height(4.dp))
            LinearProgressIndicator(
                progress = { st.downloadProgress },
                modifier = Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(99.dp)),
            )
            Spacer(Modifier.height(8.dp))
        }

        if (st.error != null) {
            Text(st.error, style = MaterialTheme.typography.bodySmall, color = CelDangerRed)
            Spacer(Modifier.height(8.dp))
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Prefer GPU Delegate (.task fallback CPU)", style = MaterialTheme.typography.bodySmall, color = CelTextPrimary, modifier = Modifier.weight(1f))
            Switch(
                checked = prefs.localUseGpu,
                onCheckedChange = { gpu ->
                    scope.launch {
                        viewModel.prefsStore.updateLocalModel(prefs.localModelPath, prefs.localModelName, prefs.localMaxTokens, gpu)
                    }
                },
            )
        }

        Spacer(Modifier.height(8.dp))

        Button(
            onClick = { modelPicker.launch(arrayOf("*/*")) },
            enabled = !st.loading && st.downloadProgress == null,
            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().testTag("import_local_model_button"),
        ) {
            Icon(Icons.Rounded.FolderOpen, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Mount / Import .gguf / .task Model", maxLines = 1, softWrap = false)
        }

        if (uiState.registeredLocalModels.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            Text("Registered Models on Phone (${uiState.registeredLocalModels.size})", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Spacer(Modifier.height(6.dp))
            uiState.registeredLocalModels.forEach { item ->
                val formatBadge = if (item.displayName.endsWith(".gguf", true)) "GGUF" else "TASK"
                val sizeMb = item.sizeBytes / (1024 * 1024)
                val isCurrentlyLoaded = st.loaded && (st.modelPath == item.uriOrPath || st.modelName == item.displayName)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(if (isCurrentlyLoaded) CelEmeraldThought.copy(alpha = 0.14f) else CelTerminalBg)
                        .padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                            Surface(shape = RoundedCornerShape(6.dp), color = visuals.primary.copy(alpha = 0.2f)) {
                                Text(formatBadge, style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono), color = visuals.primary, modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp))
                            }
                            Surface(
                                shape = RoundedCornerShape(6.dp),
                                color = if (item.isContentUri) CelEmeraldThought.copy(alpha = 0.18f) else visuals.secondary.copy(alpha = 0.18f),
                            ) {
                                Text(
                                    text = if (item.isContentUri) "DIRECT" else "LOCAL",
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = if (item.isContentUri) CelEmeraldThought else visuals.secondary,
                                    modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                                )
                            }
                            Text(item.displayName, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text(
                            text = if (sizeMb > 0) "$sizeMb MB · ${if (item.isContentUri) "Zero-copy mounted" else "Stored in app"}" else if (item.isContentUri) "Zero-copy mounted" else "Stored in app",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                    IconButton(
                        onClick = { viewModel.loadLocalModel(item, onLoadedNavigateToChat = onJumpToChat) },
                        enabled = !st.loading,
                    ) {
                        Icon(
                            Icons.Rounded.PlayArrow,
                            contentDescription = "Load local model",
                            tint = if (st.loading) CelTextMuted else CelEmeraldThought,
                        )
                    }
                    IconButton(
                        onClick = { viewModel.deleteLocalModelItem(item) },
                        enabled = !st.loading,
                    ) {
                        Icon(Icons.Rounded.Delete, contentDescription = "Remove local model", tint = CelDangerRed)
                    }
                }
            }
        }

        Spacer(Modifier.height(10.dp))
        Text("Curated On-Device Models (.gguf & .task)", style = MaterialTheme.typography.labelLarge, color = CelLavender)
        Spacer(Modifier.height(6.dp))
        ProviderPresets.CURATED_LOCAL_MODELS.forEach { cm ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 4.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(CelTerminalBg.copy(alpha = 0.7f))
                    .padding(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = if (cm.format == "GGUF") CelEmeraldThought.copy(alpha = 0.2f) else visuals.primary.copy(alpha = 0.2f),
                        ) {
                            Text(
                                cm.format,
                                style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                color = if (cm.format == "GGUF") CelEmeraldThought else visuals.primary,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp),
                            )
                        }
                        Text(cm.name, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text("${cm.sizeLabel} · ~${cm.ramNeededMb} MB RAM · ${cm.description}", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                }
                IconButton(
                    onClick = { viewModel.downloadCuratedLocalModel(cm, onLoadedNavigateToChat = onJumpToChat) },
                    enabled = st.downloadProgress == null && !st.loading,
                ) {
                    Icon(Icons.Rounded.Download, contentDescription = "Download ${cm.name}", tint = visuals.primary)
                }
            }
        }
    }
}

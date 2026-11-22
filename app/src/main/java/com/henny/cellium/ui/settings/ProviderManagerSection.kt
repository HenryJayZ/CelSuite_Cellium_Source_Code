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
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material.icons.rounded.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.JetBrainsMono
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProvidersHubCard(
    uiState: CelliumUiState,
    viewModel: CelliumViewModel,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    var editingProvider by remember { mutableStateOf<ProviderProfileEntity?>(null) }
    var showAddCustom by remember { mutableStateOf(false) }
    var showCatalogSheet by remember { mutableStateOf(false) }
    var filterQuery by remember { mutableStateOf("") }

    val displayedProviders = remember(uiState.providers, filterQuery) {
        val q = filterQuery.trim().lowercase()
        val list = if (q.isEmpty()) uiState.providers.take(10) else uiState.providers.filter {
            it.name.lowercase().contains(q) || it.selectedModel.lowercase().contains(q)
        }
        list
    }

    GlassCard(highlighted = true, shape = RoundedCornerShape(22.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Key, contentDescription = null, tint = visuals.primary)
                Column {
                    Text("AI Providers & API Keys (${ProviderCatalog.ALL.size}+)", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text("Local Room SQLite · Synced privately to your Google account when signed in", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
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

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = { showCatalogSheet = true },
                colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.weight(1f).testTag("settings_browse_200_providers"),
            ) {
                Icon(Icons.Rounded.Search, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Browse All ${ProviderCatalog.ALL.size}+ Providers")
            }
        }

        Spacer(Modifier.height(8.dp))

        OutlinedTextField(
            value = filterQuery,
            onValueChange = { filterQuery = it },
            placeholder = { Text("Filter configured providers...") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
        )

        Spacer(Modifier.height(10.dp))

        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            displayedProviders.forEach { p ->
                val isActive = uiState.activeProvider?.id == p.id
                val isConfigured = !p.requiresKey || p.protocol == "on_device" || p.apiKey.isNotBlank() || p.baseUrl.contains("127.0.0.1")
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(14.dp))
                        .background(if (isActive) visuals.primary.copy(alpha = 0.20f) else CelTerminalBg.copy(alpha = 0.7f))
                        .border(1.dp, if (isActive) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(14.dp))
                        .clickable { editingProvider = p }
                        .padding(horizontal = 12.dp, vertical = 10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    VectorBadgeIcon(
                        iconKey = p.badge,
                        contentDescription = p.name,
                        tint = if (isConfigured) CelEmeraldThought else visuals.primary,
                        containerSize = 32.dp,
                        iconSize = 17.dp,
                    )
                    Spacer(Modifier.width(10.dp))
                    Column(modifier = Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(
                                text = p.name,
                                style = MaterialTheme.typography.titleSmall,
                                color = CelTextPrimary,
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
                        Text(
                            text = p.selectedModel.ifBlank { "Tap to configure" },
                            style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                            color = CelTextSecondary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    TextButton(onClick = { viewModel.selectProvider(p.id) }) {
                        Text(if (isActive) "Active" else "Use", color = if (isActive) CelEmeraldThought else visuals.primary)
                    }
                }
            }
        }
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
private fun ProviderEditDialog(
    provider: ProviderProfileEntity,
    onDismiss: () -> Unit,
    onSave: (ProviderProfileEntity) -> Unit,
    onDelete: (() -> Unit)?,
    onFetchModels: suspend (ProviderProfileEntity) -> Result<List<String>>,
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
                        Text("Ping Key & Fetch All Models")
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
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(if (isSel) visuals.primary.copy(alpha = 0.24f) else CelTerminalBg.copy(alpha = 0.72f))
                                        .border(1.dp, if (isSel) visuals.activeBorder else visuals.subtleBorder, RoundedCornerShape(10.dp))
                                        .clickable { selectedModel = m }
                                        .padding(horizontal = 10.dp, vertical = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                ) {
                                    Text(
                                        text = m,
                                        style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                        color = if (isSel) CelTextPrimary else CelTextSecondary,
                                        maxLines = 2,
                                        overflow = TextOverflow.Ellipsis,
                                        modifier = Modifier.weight(1f),
                                    )
                                    if (isSel) {
                                        Icon(Icons.Rounded.Check, contentDescription = "Selected", tint = visuals.primary, modifier = Modifier.size(16.dp))
                                    }
                                }
                            }
                        }
                    } else if (provider.requiresKey) {
                        Text(
                            text = "Enter your API key and tap 'Ping Key & Fetch All Models' to query every model your key supports.",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                } else {
                    Text(
                        "On-Device Offline AI supports both .gguf (llama.cpp) and .task/.bin (MediaPipe) models completely offline with zero API keys.",
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
            }) { Text("Save & Use") }
        },
        dismissButton = {
            Row {
                if (onDelete != null) {
                    TextButton(onClick = onDelete) { Text("Delete", color = CelDangerRed) }
                }
                TextButton(onClick = onDismiss) { Text("Close") }
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
                    FilterChip(selected = protocol == "openai", onClick = { protocol = "openai" }, label = { Text("OpenAI Compat") })
                    FilterChip(selected = protocol == "anthropic", onClick = { protocol = "anthropic" }, label = { Text("Anthropic") })
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onCreate(name, baseUrl, apiKey, model, protocol) },
                enabled = name.isNotBlank() && baseUrl.isNotBlank(),
            ) { Text("Add") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
fun OnDeviceModelManagerCard(
    uiState: CelliumUiState,
    prefs: CelliumPreferences,
    processRamMb: Int,
    viewModel: CelliumViewModel,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val modelPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) viewModel.importLocalModel(uri)
    }

    GlassCard(shape = RoundedCornerShape(22.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Icon(Icons.Rounded.Memory, contentDescription = null, tint = visuals.tertiary)
                Column {
                    Text("On-Device Offline AI (.gguf & .task)", style = MaterialTheme.typography.titleMedium, color = CelTextPrimary)
                    Text(
                        "llama.cpp GGUF + MediaPipe · Live RAM: $processRamMb MB",
                        style = MaterialTheme.typography.labelSmall,
                        color = CelTextSecondary,
                    )
                }
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
                    Text("Unload")
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
            Text("Downloading ${st.downloadingName} (${(st.downloadProgress * 100).toInt()}%)", style = MaterialTheme.typography.labelSmall, color = CelLavender)
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
            Text("Prefer GPU Delegate (.task fallback CPU)", style = MaterialTheme.typography.bodySmall, color = CelTextPrimary)
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
            colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().testTag("import_local_model_button"),
        ) {
            Icon(Icons.Rounded.FolderOpen, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text("Import Local .gguf / .task / .bin Model")
        }

        if (uiState.installedLocalModels.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            Text("Installed Models on Phone", style = MaterialTheme.typography.labelLarge, color = CelLavender)
            Spacer(Modifier.height(6.dp))
            uiState.installedLocalModels.forEach { f ->
                val badge = if (f.name.endsWith(".gguf", true)) "GGUF" else "TASK"
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 4.dp)
                        .clip(RoundedCornerShape(12.dp))
                        .background(CelTerminalBg)
                        .padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Surface(shape = RoundedCornerShape(6.dp), color = visuals.primary.copy(alpha = 0.2f)) {
                                Text(badge, style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono), color = visuals.primary, modifier = Modifier.padding(horizontal = 5.dp, vertical = 1.dp))
                            }
                            Text(f.name, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text("${f.length() / (1024 * 1024)} MB", style = MaterialTheme.typography.labelSmall, color = CelTextSecondary)
                    }
                    IconButton(onClick = { viewModel.loadLocalModelFile(f) }) {
                        Icon(Icons.Rounded.PlayArrow, contentDescription = "Load local model", tint = CelEmeraldThought)
                    }
                    IconButton(onClick = { viewModel.deleteLocalModel(f) }) {
                        Icon(Icons.Rounded.Delete, contentDescription = "Delete local model", tint = CelDangerRed)
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
                    onClick = { viewModel.downloadCuratedLocalModel(cm) },
                    enabled = st.downloadProgress == null,
                ) {
                    Icon(Icons.Rounded.Download, contentDescription = "Download ${cm.name}", tint = visuals.primary)
                }
            }
        }
    }
}

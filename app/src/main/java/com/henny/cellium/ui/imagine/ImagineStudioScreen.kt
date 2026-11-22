package com.henny.cellium.ui.imagine

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Send
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Science
import androidx.compose.material.icons.rounded.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.henny.cellium.ai.MultiImagineClient
import com.henny.cellium.data.local.ArtworkEntity
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassCard
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
import java.io.File

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ImagineStudioScreen(
    viewModel: CelliumViewModel,
    onJumpToChat: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()

    var prompt by remember { mutableStateOf("") }
    var negativePrompt by remember { mutableStateOf("") }
    var selectedProvider by remember(prefs.imagineProvider) { mutableStateOf(prefs.imagineProvider) }
    var selectedModel by remember(prefs.imagineModel) { mutableStateOf(prefs.imagineModel.ifBlank { "sana" }) }
    var aspectRatio by remember { mutableStateOf("1:1") }
    var apiKey by remember(prefs.imagineApiKey) { mutableStateOf(prefs.imagineApiKey) }
    var customUrl by remember(prefs.imagineCustomUrl) { mutableStateOf(prefs.imagineCustomUrl) }
    var kaggleSlug by remember(prefs.kaggleKernelSlug) { mutableStateOf(prefs.kaggleKernelSlug) }
    var showKeyPanel by remember { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    var livePollinationsModels by remember { mutableStateOf<List<String>>(emptyList()) }
    var refreshingModels by remember { mutableStateOf(false) }

    val kaggleJsonPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) {
            selectedProvider = "kaggle"
            viewModel.importKaggleJsonUri(uri)
        }
    }

    val activeOption = MultiImagineClient.PROVIDERS.firstOrNull { it.id == selectedProvider }
        ?: MultiImagineClient.PROVIDERS.first()
    val modelChoices = remember(selectedProvider, livePollinationsModels) {
        if (selectedProvider == "pollinations" && livePollinationsModels.isNotEmpty()) {
            livePollinationsModels
        } else {
            activeOption.defaultModels
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            GlassCard(highlighted = true, shape = RoundedCornerShape(22.dp)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Illume Studio", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
                        Text(
                            "Pollinations (Free Sana / Live) · Kaggle GPU · HuggingFace · OpenAI",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                    IconButton(onClick = { showKeyPanel = !showKeyPanel }) {
                        Icon(Icons.Rounded.Key, contentDescription = "Illume API key settings", tint = visuals.primary)
                    }
                }

                Spacer(Modifier.height(10.dp))

                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    MultiImagineClient.PROVIDERS.forEach { opt ->
                        FilterChip(
                            selected = opt.id == selectedProvider,
                            onClick = {
                                viewModel.soundEngine.playClick()
                                selectedProvider = opt.id
                                selectedModel = if (opt.id == "kaggle") prefs.kaggleModelId else opt.defaultModels.first()
                                scope.launch {
                                    viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                }
                            },
                            label = { Text(opt.label, maxLines = 1, softWrap = false) },
                            modifier = Modifier.testTag("imagine_provider_${opt.id}"),
                        )
                    }
                }

                Spacer(Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Models", style = MaterialTheme.typography.labelSmall, color = CelLavender)
                    if (selectedProvider == "pollinations") {
                        OutlinedButton(
                            onClick = {
                                refreshingModels = true
                                scope.launch {
                                    val res = viewModel.imagineClient.fetchPollinationsImageModels()
                                    refreshingModels = false
                                    res.onSuccess { list ->
                                        livePollinationsModels = list
                                        if (list.isNotEmpty() && selectedModel !in list) {
                                            selectedModel = list.first()
                                            viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                        }
                                        viewModel.showBanner("Fetched ${list.size} live Pollinations image models.")
                                    }.onFailure { err ->
                                        localError = err.localizedMessage
                                    }
                                }
                            },
                            enabled = !refreshingModels,
                            shape = RoundedCornerShape(10.dp),
                        ) {
                            if (refreshingModels) {
                                CircularProgressIndicator(modifier = Modifier.size(13.dp), strokeWidth = 2.dp)
                            } else {
                                Icon(Icons.Rounded.Refresh, contentDescription = null, modifier = Modifier.size(14.dp))
                            }
                            Spacer(Modifier.width(4.dp))
                            Text("Fetch Live", style = MaterialTheme.typography.labelSmall, maxLines = 1, softWrap = false)
                        }
                    }
                }

                Spacer(Modifier.height(6.dp))

                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    modelChoices.forEach { m ->
                        FilterChip(
                            selected = m == selectedModel,
                            onClick = {
                                selectedModel = m
                                scope.launch {
                                    if (selectedProvider == "kaggle") {
                                        viewModel.prefsStore.updateKaggleConfig(prefs.kaggleUsername, prefs.kaggleKey, kaggleSlug, m)
                                    }
                                    viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                }
                            },
                            label = { Text(m.substringAfterLast('/'), maxLines = 1, softWrap = false) },
                        )
                    }
                }

                if (selectedProvider == "kaggle") {
                    Spacer(Modifier.height(10.dp))
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(14.dp))
                            .background(CelTerminalBg.copy(alpha = 0.85f))
                            .border(1.dp, visuals.activeBorder, RoundedCornerShape(14.dp))
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Icon(Icons.Rounded.Science, contentDescription = null, tint = CelLavender, modifier = Modifier.size(18.dp))
                            Text("Kaggle GPU Notebook Runner", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                        }
                        if (prefs.kaggleUsername.isNotBlank() && prefs.kaggleKey.isNotBlank()) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(16.dp))
                                Text(
                                    text = "kaggle.json loaded · @${prefs.kaggleUsername}",
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = CelEmeraldThought,
                                )
                            }
                        } else {
                            Text(
                                text = "Import your kaggle.json token from Kaggle Account Settings to run free cloud GPU Diffusers notebooks.",
                                style = MaterialTheme.typography.bodySmall,
                                color = CelTextSecondary,
                            )
                        }
                        OutlinedButton(
                            onClick = { kaggleJsonPicker.launch(arrayOf("application/json", "*/*")) },
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth().testTag("import_kaggle_json_button"),
                        ) {
                            Icon(Icons.Rounded.UploadFile, contentDescription = null, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(
                                text = if (prefs.kaggleUsername.isNotBlank()) "Replace kaggle.json" else "Import kaggle.json",
                                maxLines = 1,
                                softWrap = false,
                            )
                        }
                        OutlinedTextField(
                            value = kaggleSlug,
                            onValueChange = {
                                kaggleSlug = it
                                scope.launch {
                                    viewModel.prefsStore.updateKaggleConfig(prefs.kaggleUsername, prefs.kaggleKey, it, selectedModel)
                                }
                            },
                            label = { Text("Kaggle Kernel Slug") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )
                    }
                } else if (showKeyPanel || activeOption.requiresKey || selectedProvider == "custom") {
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = apiKey,
                        onValueChange = {
                            apiKey = it
                            scope.launch { viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, it, customUrl) }
                        },
                        label = {
                            Text(
                                if (selectedProvider == "pollinations") "Pollinations API Key (Optional for Flux/Pro)"
                                else "${activeOption.label} API Key"
                            )
                        },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                    )
                    if (selectedProvider == "custom") {
                        Spacer(Modifier.height(6.dp))
                        OutlinedTextField(
                            value = customUrl,
                            onValueChange = {
                                customUrl = it
                                scope.launch { viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, it) }
                            },
                            label = { Text("Custom /images/generations Base URL") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )
                    }
                }

                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    label = { Text("Image Prompt") },
                    placeholder = { Text("Neon violet crystal cathedral floating in deep space...", color = CelTextMuted) },
                    minLines = 2,
                    maxLines = 4,
                    modifier = Modifier.fillMaxWidth().testTag("imagine_studio_prompt"),
                    shape = RoundedCornerShape(14.dp),
                )
                Spacer(Modifier.height(6.dp))
                OutlinedTextField(
                    value = negativePrompt,
                    onValueChange = { negativePrompt = it },
                    label = { Text("Negative Prompt (Optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                )

                Spacer(Modifier.height(8.dp))
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    listOf("1:1", "16:9", "9:16", "4:3", "3:4").forEach { ar ->
                        FilterChip(
                            selected = aspectRatio == ar,
                            onClick = { aspectRatio = ar },
                            label = { Text(ar, maxLines = 1, softWrap = false) },
                        )
                    }
                }

                if (localError != null) {
                    Spacer(Modifier.height(6.dp))
                    Text(localError!!, style = MaterialTheme.typography.bodySmall, color = CelDangerRed)
                }
                if (uiState.bannerMessage != null) {
                    Spacer(Modifier.height(6.dp))
                    Text(uiState.bannerMessage!!, style = MaterialTheme.typography.bodySmall, color = CelEmeraldThought)
                }

                Spacer(Modifier.height(10.dp))
                Button(
                    onClick = {
                        localError = null
                        viewModel.soundEngine.playSend()
                        scope.launch {
                            viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                            val res = viewModel.generateArtwork(
                                prompt = prompt,
                                negativePrompt = negativePrompt,
                                aspectRatio = aspectRatio,
                                providerOverride = selectedProvider,
                                modelOverride = selectedModel,
                            )
                            res.onFailure { localError = it.localizedMessage }
                        }
                    },
                    enabled = !uiState.isGeneratingImage && prompt.isNotBlank(),
                    colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth().height(50.dp).testTag("imagine_studio_generate"),
                ) {
                    if (uiState.isGeneratingImage) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = visuals.voidBg)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = uiState.imagineStatusText.ifBlank { "Generating via ${activeOption.label}..." },
                            maxLines = 1,
                            softWrap = false,
                        )
                    } else {
                        Icon(Icons.Rounded.AutoAwesome, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Generate with Illume", maxLines = 1, softWrap = false)
                    }
                }
            }
        }

        item {
            Text(
                text = "Local Gallery (${uiState.artworks.size})",
                style = MaterialTheme.typography.titleMedium,
                color = CelTextPrimary,
            )
        }

        if (uiState.artworks.isEmpty()) {
            item {
                GlassCard(shape = RoundedCornerShape(18.dp)) {
                    Text(
                        text = "Your generated art is saved locally on your device. Try Pollinations (Free Sana) immediately or tap Fetch Live for all models!",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                }
            }
        } else {
            items(uiState.artworks, key = { it.id }) { art ->
                ArtworkGalleryCard(
                    art = art,
                    onSavePhotos = { viewModel.saveArtworkToPhotos(art) },
                    onSendToChat = {
                        viewModel.sendArtworkToChat(art)
                        onJumpToChat()
                    },
                    onDelete = { viewModel.deleteArtwork(art) },
                )
            }
        }
    }
}

@Composable
private fun ArtworkGalleryCard(
    art: ArtworkEntity,
    onSavePhotos: () -> Unit,
    onSendToChat: () -> Unit,
    onDelete: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val file = remember(art.localPath) { File(art.localPath) }
    GlassCard(shape = RoundedCornerShape(20.dp), contentPadding = 12.dp) {
        if (file.exists()) {
            AsyncImage(
                model = file,
                contentDescription = art.prompt,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(1.25f)
                    .clip(RoundedCornerShape(14.dp))
                    .border(1.dp, visuals.subtleBorder, RoundedCornerShape(14.dp)),
            )
            Spacer(Modifier.height(10.dp))
        }
        Text(art.prompt, style = MaterialTheme.typography.bodyMedium, color = CelTextPrimary, maxLines = 3)
        Text(
            "${art.provider} · ${art.model} · ${art.aspectRatio} · seed ${art.seed}",
            style = MaterialTheme.typography.labelSmall,
            color = CelTextSecondary,
        )
        Spacer(Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(onClick = onSavePhotos, shape = RoundedCornerShape(12.dp), modifier = Modifier.weight(1f)) {
                Icon(Icons.Rounded.Download, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("Photos", maxLines = 1, softWrap = false)
            }
            OutlinedButton(onClick = onSendToChat, shape = RoundedCornerShape(12.dp), modifier = Modifier.weight(1f)) {
                Icon(Icons.AutoMirrored.Rounded.Send, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("To Chat", maxLines = 1, softWrap = false)
            }
            IconButton(onClick = onDelete) {
                Icon(Icons.Rounded.Delete, contentDescription = "Delete artwork", tint = CelDangerRed)
            }
        }
    }
}

package com.henny.cellium.ui.imagine

import android.content.Intent
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
import androidx.compose.material.icons.rounded.AutoFixHigh
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CloudDone
import androidx.compose.material.icons.rounded.CloudUpload
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Science
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.henny.cellium.ai.KaggleImageEngine
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
import java.util.Locale

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ImagineStudioScreen(
    viewModel: CelliumViewModel,
    onJumpToChat: () -> Unit,
) {
    val visuals = LocalCelliumVisuals.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()

    var selectedProvider by remember(prefs.imagineProvider) { mutableStateOf(prefs.imagineProvider) }
    var selectedModel by remember(prefs.imagineModel) { mutableStateOf(prefs.imagineModel.ifBlank { "Auto (Fastest)" }) }
    var prompt by remember { mutableStateOf(prefs.kagglePrompt) }
    var negativePrompt by remember(prefs.kaggleNegativePrompt) { mutableStateOf(prefs.kaggleNegativePrompt) }
    var aspectRatio by remember { mutableStateOf("1:1") }
    var apiKey by remember(prefs.imagineApiKey) { mutableStateOf(prefs.imagineApiKey) }
    var customUrl by remember(prefs.imagineCustomUrl) { mutableStateOf(prefs.imagineCustomUrl) }
    var showKeyPanel by remember { mutableStateOf(false) }
    var localError by remember { mutableStateOf<String?>(null) }
    var liveProviderModels by remember(selectedProvider) { mutableStateOf<List<String>>(emptyList()) }
    var refreshingModels by remember { mutableStateOf(false) }

    // Full PC-parity Kaggle Cloud GPU studio state
    var kagglePreset by remember(prefs.kagglePreset) { mutableStateOf(prefs.kagglePreset) }
    var kaggleSize by remember(prefs.kaggleSize) { mutableStateOf(prefs.kaggleSize) }
    var kaggleSticky by remember(prefs.kaggleStickyPrompt) { mutableStateOf(prefs.kaggleStickyPrompt) }
    var kaggleSteps by remember(prefs.kaggleSteps) { mutableIntStateOf(prefs.kaggleSteps) }
    var kaggleGuidance by remember(prefs.kaggleGuidance) { mutableFloatStateOf(prefs.kaggleGuidance) }
    var kaggleBatch by remember(prefs.kaggleBatch) { mutableIntStateOf(prefs.kaggleBatch.coerceIn(1, 20)) }
    var kaggleSeed by remember(prefs.kaggleSeed) { mutableLongStateOf(prefs.kaggleSeed) }
    var kaggleRandomSeed by remember(prefs.kaggleSeed) { mutableStateOf(prefs.kaggleSeed < 0L) }
    var kaggleAdvanced by remember(prefs.kaggleDialogMode) { mutableStateOf(prefs.kaggleDialogMode == "advanced") }
    var kaggleAutoClean by remember(prefs.kaggleAutoClean) { mutableStateOf(prefs.kaggleAutoClean) }
    var kaggleCustomMode by remember(prefs.kaggleModelMode) { mutableStateOf(prefs.kaggleModelMode.ifBlank { "hf" }) }
    var kaggleHfModel by remember(prefs.kaggleHfModel) { mutableStateOf(prefs.kaggleHfModel) }
    var kaggleCivitaiUrl by remember(prefs.kaggleCivitaiUrl) { mutableStateOf(prefs.kaggleCivitaiUrl) }
    var kaggleLoraUrl by remember(prefs.kaggleLoraUrl) { mutableStateOf(prefs.kaggleLoraUrl) }
    var kaggleLoraStrength by remember(prefs.kaggleLoraStrength) { mutableFloatStateOf(prefs.kaggleLoraStrength) }
    var editLastImg2Img by remember { mutableStateOf(false) }
    var img2ImgDenoise by remember { mutableFloatStateOf(0.75f) }
    var enhancingPrompt by remember { mutableStateOf(false) }

    val storedCreds = remember(prefs.kaggleUsername, prefs.kaggleKey) {
        viewModel.kaggleEngine.getCredentials(prefs)
    }
    var kaggleUserInput by remember(storedCreds.first) { mutableStateOf(storedCreds.first) }
    var kaggleKeyInput by remember(storedCreds.second) { mutableStateOf(storedCreds.second) }
    var hfTokenInput by remember { mutableStateOf(viewModel.secureKaggleStore.getHfToken()) }
    var civitaiTokenInput by remember { mutableStateOf(viewModel.secureKaggleStore.getCivitaiToken()) }

    val kaggleJsonPicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) {
            selectedProvider = "kaggle"
            viewModel.importKaggleJsonUri(uri)
        }
    }

    LaunchedEffect(selectedProvider, storedCreds.first) {
        if (selectedProvider == "kaggle" && storedCreds.first.isNotBlank() && uiState.kaggleCacheStatusMap.isEmpty()) {
            viewModel.refreshKaggleCache()
        }
    }

    val activeOption = MultiImagineClient.PROVIDERS.firstOrNull { it.id == selectedProvider }
        ?: MultiImagineClient.PROVIDERS.first()
    val modelChoices = remember(selectedProvider, liveProviderModels) {
        if (liveProviderModels.isNotEmpty()) liveProviderModels else activeOption.defaultModels
    }
    val latestImgPath = uiState.lastGeneratedImagePath ?: uiState.artworks.firstOrNull()?.localPath

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
                            "Kaggle 30h/wk Cloud GPU · AI Horde · Pollinations · HuggingFace · OpenAI",
                            style = MaterialTheme.typography.labelSmall,
                            color = CelTextSecondary,
                        )
                    }
                    if (selectedProvider == "kaggle") {
                        FilterChip(
                            selected = kaggleAdvanced,
                            onClick = {
                                kaggleAdvanced = !kaggleAdvanced
                                scope.launch {
                                    viewModel.prefsStore.updateKaggleFullSettings(
                                        dialogMode = if (kaggleAdvanced) "advanced" else "simple",
                                    )
                                }
                            },
                            label = {
                                Text(
                                    if (kaggleAdvanced) "Advanced" else "Simple",
                                    maxLines = 1,
                                    softWrap = false,
                                )
                            },
                            leadingIcon = {
                                Icon(Icons.Rounded.Tune, contentDescription = null, modifier = Modifier.size(15.dp))
                            },
                        )
                    } else {
                        IconButton(onClick = { showKeyPanel = !showKeyPanel }) {
                            Icon(Icons.Rounded.Key, contentDescription = "Illume API key settings", tint = visuals.primary)
                        }
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
                                selectedModel = if (opt.id == "kaggle") kagglePreset else opt.defaultModels.first()
                                scope.launch {
                                    viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                }
                            },
                            label = { Text(opt.label, maxLines = 1, softWrap = false) },
                            modifier = Modifier.testTag("imagine_provider_${opt.id}"),
                        )
                    }
                }

                if (selectedProvider == "kaggle") {
                    Spacer(Modifier.height(12.dp))
                    // ── Kaggle Credentials & Connection Block ──
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
                            Text("Kaggle Cloud GPU Engine (PC-Parity)", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                        }
                        if (storedCreds.first.isNotBlank() && storedCreds.second.isNotBlank()) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = CelEmeraldThought, modifier = Modifier.size(16.dp))
                                Text(
                                    text = "Connected account · @${storedCreds.first} (encrypted)",
                                    style = MaterialTheme.typography.labelSmall.copy(fontFamily = JetBrainsMono),
                                    color = CelEmeraldThought,
                                )
                            }
                        } else {
                            Text(
                                text = "Free 30 hrs/week NVIDIA T4/P100 SDXL cloud GPU. Import kaggle.json from Kaggle Settings -> API -> Create Legacy API Key.",
                                style = MaterialTheme.typography.bodySmall,
                                color = CelLavender,
                            )
                        }

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedButton(
                                onClick = {
                                    runCatching {
                                        val i = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.kaggle.com/settings/account"))
                                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                                        context.startActivity(i)
                                    }
                                },
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.weight(1f),
                            ) {
                                Icon(Icons.Rounded.OpenInNew, contentDescription = null, modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Kaggle", maxLines = 1, softWrap = false)
                            }
                            OutlinedButton(
                                onClick = { kaggleJsonPicker.launch(arrayOf("application/json", "*/*")) },
                                shape = RoundedCornerShape(12.dp),
                                modifier = Modifier.weight(1f).testTag("import_kaggle_json_button"),
                            ) {
                                Icon(Icons.Rounded.UploadFile, contentDescription = null, modifier = Modifier.size(14.dp))
                                Spacer(Modifier.width(4.dp))
                                Text(
                                    if (storedCreds.first.isNotBlank()) "Replace JSON" else "Import JSON",
                                    maxLines = 1,
                                    softWrap = false,
                                )
                            }
                            OutlinedButton(
                                onClick = { viewModel.testKaggleConnection() },
                                shape = RoundedCornerShape(12.dp),
                            ) {
                                Text("Test", maxLines = 1, softWrap = false)
                            }
                        }

                        if (!uiState.kaggleTestResult.isNullOrBlank()) {
                            Text(
                                text = uiState.kaggleTestResult!!,
                                style = MaterialTheme.typography.labelSmall,
                                color = if (uiState.kaggleTestResult!!.startsWith("✅")) CelEmeraldThought else CelLavender,
                            )
                        }

                        if (kaggleAdvanced || storedCreds.first.isBlank()) {
                            OutlinedTextField(
                                value = kaggleUserInput,
                                onValueChange = {
                                    kaggleUserInput = it
                                    viewModel.saveKaggleCredentials(it, kaggleKeyInput)
                                },
                                label = { Text("Kaggle Username") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                            )
                            OutlinedTextField(
                                value = kaggleKeyInput,
                                onValueChange = {
                                    kaggleKeyInput = it
                                    viewModel.saveKaggleCredentials(kaggleUserInput, it)
                                },
                                label = { Text("Kaggle Legacy API Key") },
                                visualTransformation = PasswordVisualTransformation(),
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                            )
                        }
                    }

                    Spacer(Modifier.height(12.dp))
                    // ── 4 Exact Model Presets ──
                    Text("Model Preset", style = MaterialTheme.typography.labelMedium, color = CelLavender)
                    Spacer(Modifier.height(6.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        KaggleImageEngine.MODEL_PRESETS.forEach { preset ->
                            val cacheEntry = uiState.kaggleCacheStatusMap[preset.label]
                            val cachedBadge = if (cacheEntry?.healthy == true) " ⚡" else ""
                            FilterChip(
                                selected = kagglePreset == preset.label,
                                onClick = {
                                    viewModel.soundEngine.playClick()
                                    kagglePreset = preset.label
                                    kaggleSteps = preset.steps
                                    kaggleGuidance = preset.guidance
                                    scope.launch {
                                        viewModel.prefsStore.updateKaggleFullSettings(
                                            preset = preset.label,
                                            steps = preset.steps,
                                            guidance = preset.guidance,
                                        )
                                    }
                                },
                                label = { Text("${preset.label}$cachedBadge", maxLines = 1, softWrap = false) },
                            )
                        }
                    }
                    val activePresetObj = remember(kagglePreset) { KaggleImageEngine.findPreset(kagglePreset) }
                    Text(
                        text = activePresetObj.notes,
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )

                    Spacer(Modifier.height(12.dp))
                    // ── Prompt + Local/AI Enhancer ──
                    OutlinedTextField(
                        value = prompt,
                        onValueChange = {
                            prompt = it
                            scope.launch { viewModel.prefsStore.updateKaggleFullSettings(prompt = it) }
                        },
                        label = { Text("Image Prompt") },
                        placeholder = { Text("1girl, neon violet hair, glowing holographic studio, cinematic lighting...", color = CelTextMuted) },
                        minLines = 2,
                        maxLines = 5,
                        modifier = Modifier.fillMaxWidth().testTag("imagine_studio_prompt"),
                        shape = RoundedCornerShape(14.dp),
                    )
                    Spacer(Modifier.height(6.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = {
                                if (prompt.isBlank()) return@OutlinedButton
                                viewModel.soundEngine.playClick()
                                prompt = KaggleImageEngine.enhancePromptLocal(prompt)
                                scope.launch { viewModel.prefsStore.updateKaggleFullSettings(prompt = prompt) }
                            },
                            enabled = prompt.isNotBlank() && !enhancingPrompt,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f),
                        ) {
                            Icon(Icons.Rounded.AutoFixHigh, contentDescription = null, modifier = Modifier.size(15.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("Enhance (Local)", maxLines = 1, softWrap = false)
                        }
                        OutlinedButton(
                            onClick = {
                                if (prompt.isBlank() || enhancingPrompt) return@OutlinedButton
                                enhancingPrompt = true
                                localError = null
                                scope.launch {
                                    val res = viewModel.enhanceKagglePrompt(prompt, useLlm = true)
                                    enhancingPrompt = false
                                    res.onSuccess { enhanced ->
                                        prompt = enhanced
                                        viewModel.prefsStore.updateKaggleFullSettings(prompt = enhanced)
                                        viewModel.soundEngine.playPop()
                                    }.onFailure { err ->
                                        localError = err.localizedMessage
                                    }
                                }
                            },
                            enabled = prompt.isNotBlank() && !enhancingPrompt,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f),
                        ) {
                            if (enhancingPrompt) {
                                CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
                            } else {
                                Icon(Icons.Rounded.AutoAwesome, contentDescription = null, modifier = Modifier.size(15.dp))
                            }
                            Spacer(Modifier.width(4.dp))
                            Text("Enhance (AI)", maxLines = 1, softWrap = false)
                        }
                    }

                    Spacer(Modifier.height(10.dp))
                    // ── Sticky Style / Character Suffix + 6 Quick Styles ──
                    OutlinedTextField(
                        value = kaggleSticky,
                        onValueChange = {
                            kaggleSticky = it
                            scope.launch { viewModel.prefsStore.updateKaggleFullSettings(stickyPrompt = it) }
                        },
                        label = { Text("Sticky Style / Character Suffix (Auto-appended)") },
                        placeholder = { Text("Tap a Quick Style below or type persistent tags...", color = CelTextMuted) },
                        singleLine = false,
                        maxLines = 2,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(14.dp),
                    )
                    Spacer(Modifier.height(6.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        KaggleImageEngine.QUICK_STYLES.forEach { qs ->
                            FilterChip(
                                selected = kaggleSticky.contains(qs.tags.take(18), ignoreCase = true),
                                onClick = {
                                    viewModel.soundEngine.playClick()
                                    kaggleSticky = if (kaggleSticky.contains(qs.tags.take(18), ignoreCase = true)) {
                                        ""
                                    } else {
                                        qs.tags
                                    }
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(stickyPrompt = kaggleSticky) }
                                },
                                label = { Text(qs.label, maxLines = 1, softWrap = false) },
                            )
                        }
                    }

                    Spacer(Modifier.height(10.dp))
                    // ── 10 SDXL Sizes ──
                    Text("Resolution", style = MaterialTheme.typography.labelMedium, color = CelLavender)
                    Spacer(Modifier.height(4.dp))
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        KaggleImageEngine.SIZE_PRESETS.forEach { sz ->
                            FilterChip(
                                selected = kaggleSize == sz,
                                onClick = {
                                    kaggleSize = sz
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(size = sz) }
                                },
                                label = { Text(sz, maxLines = 1, softWrap = false) },
                            )
                        }
                    }

                    Spacer(Modifier.height(10.dp))
                    // ── Batch Size (1–20) + img2img Edit Last ──
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Batch: $kaggleBatch image(s)", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            listOf(1, 2, 4, 8).forEach { b ->
                                FilterChip(
                                    selected = kaggleBatch == b,
                                    onClick = {
                                        kaggleBatch = b
                                        scope.launch { viewModel.prefsStore.updateKaggleFullSettings(batch = b) }
                                    },
                                    label = { Text("${b}x", maxLines = 1, softWrap = false) },
                                )
                            }
                        }
                    }
                    Slider(
                        value = kaggleBatch.toFloat(),
                        onValueChange = { v -> kaggleBatch = v.toInt().coerceIn(1, 20) },
                        onValueChangeFinished = {
                            scope.launch { viewModel.prefsStore.updateKaggleFullSettings(batch = kaggleBatch) }
                        },
                        valueRange = 1f..20f,
                        steps = 18,
                    )

                    if (!latestImgPath.isNullOrBlank()) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("Edit Last Image (img2img)", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                                Text(
                                    "Re-renders using your latest gallery artwork as reference",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = CelTextSecondary,
                                )
                            }
                            Switch(checked = editLastImg2Img, onCheckedChange = { editLastImg2Img = it })
                        }
                        if (editLastImg2Img) {
                            Text(
                                "Denoise Strength: ${String.format(Locale.US, "%.2f", img2ImgDenoise)}",
                                style = MaterialTheme.typography.labelSmall,
                                color = CelLavender,
                            )
                            Slider(
                                value = img2ImgDenoise,
                                onValueChange = { img2ImgDenoise = it },
                                valueRange = 0.25f..0.92f,
                            )
                        }
                    }

                    // ── Advanced Controls & Phase-5 Cloud Model Cache ──
                    if (kaggleAdvanced) {
                        Spacer(Modifier.height(8.dp))
                        HorizontalDivider(color = visuals.subtleBorder)
                        Spacer(Modifier.height(10.dp))

                        Text(
                            "Steps: $kaggleSteps · Guidance (CFG): ${String.format(Locale.US, "%.1f", kaggleGuidance)}",
                            style = MaterialTheme.typography.labelMedium,
                            color = CelLavender,
                        )
                        Slider(
                            value = kaggleSteps.toFloat(),
                            onValueChange = { kaggleSteps = it.toInt().coerceIn(1, 60) },
                            onValueChangeFinished = {
                                scope.launch { viewModel.prefsStore.updateKaggleFullSettings(steps = kaggleSteps) }
                            },
                            valueRange = 4f..50f,
                        )
                        Slider(
                            value = kaggleGuidance,
                            onValueChange = { kaggleGuidance = it },
                            onValueChangeFinished = {
                                scope.launch { viewModel.prefsStore.updateKaggleFullSettings(guidance = kaggleGuidance) }
                            },
                            valueRange = 1f..14f,
                        )

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Text("Random Seed", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                            Switch(
                                checked = kaggleRandomSeed,
                                onCheckedChange = { isRand ->
                                    kaggleRandomSeed = isRand
                                    kaggleSeed = if (isRand) -1L else 42L
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(seed = kaggleSeed) }
                                },
                            )
                        }
                        if (!kaggleRandomSeed) {
                            OutlinedTextField(
                                value = if (kaggleSeed < 0L) "" else kaggleSeed.toString(),
                                onValueChange = { txt ->
                                    val parsed = txt.filter { it.isDigit() }.toLongOrNull() ?: 0L
                                    kaggleSeed = parsed
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(seed = parsed) }
                                },
                                label = { Text("Fixed Seed") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                            )
                        }

                        Spacer(Modifier.height(6.dp))
                        OutlinedTextField(
                            value = negativePrompt,
                            onValueChange = {
                                negativePrompt = it
                                scope.launch { viewModel.prefsStore.updateKaggleFullSettings(negativePrompt = it) }
                            },
                            label = { Text("Negative Prompt") },
                            minLines = 2,
                            maxLines = 3,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )

                        Spacer(Modifier.height(6.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("Stealth Auto-Wipe", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                                Text(
                                    "Overwrites remote Kaggle kernel with clean CPU stub after download (0 GPU cost)",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = CelTextSecondary,
                                )
                            }
                            Switch(
                                checked = kaggleAutoClean,
                                onCheckedChange = {
                                    kaggleAutoClean = it
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(autoClean = it) }
                                },
                            )
                        }

                        if (kagglePreset == KaggleImageEngine.PRESET_CUSTOM) {
                            Spacer(Modifier.height(8.dp))
                            Text("Custom Checkpoint & LoRA", style = MaterialTheme.typography.labelMedium, color = CelLavender)
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FilterChip(
                                    selected = kaggleCustomMode == "hf" || kaggleCustomMode == "huggingface",
                                    onClick = {
                                        kaggleCustomMode = "hf"
                                        scope.launch { viewModel.prefsStore.updateKaggleFullSettings(modelMode = "hf") }
                                    },
                                    label = { Text("HuggingFace") },
                                )
                                FilterChip(
                                    selected = kaggleCustomMode == "civitai",
                                    onClick = {
                                        kaggleCustomMode = "civitai"
                                        scope.launch { viewModel.prefsStore.updateKaggleFullSettings(modelMode = "civitai") }
                                    },
                                    label = { Text("Civitai URL") },
                                )
                            }
                            if (kaggleCustomMode == "civitai") {
                                OutlinedTextField(
                                    value = kaggleCivitaiUrl,
                                    onValueChange = {
                                        kaggleCivitaiUrl = it
                                        scope.launch { viewModel.prefsStore.updateKaggleFullSettings(civitaiUrl = it) }
                                    },
                                    label = { Text("Civitai Checkpoint Download URL") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(12.dp),
                                )
                            } else {
                                OutlinedTextField(
                                    value = kaggleHfModel,
                                    onValueChange = {
                                        kaggleHfModel = it
                                        scope.launch { viewModel.prefsStore.updateKaggleFullSettings(hfModel = it) }
                                    },
                                    label = { Text("HuggingFace Diffusers Repo ID") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                    shape = RoundedCornerShape(12.dp),
                                )
                            }
                            Spacer(Modifier.height(6.dp))
                            OutlinedTextField(
                                value = kaggleLoraUrl,
                                onValueChange = {
                                    kaggleLoraUrl = it
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(loraUrl = it) }
                                },
                                label = { Text("Optional LoRA Download URL (.safetensors)") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(12.dp),
                            )
                            Text(
                                "LoRA Strength: ${String.format(Locale.US, "%.2f", kaggleLoraStrength)}",
                                style = MaterialTheme.typography.labelSmall,
                                color = CelTextSecondary,
                            )
                            Slider(
                                value = kaggleLoraStrength,
                                onValueChange = { kaggleLoraStrength = it },
                                onValueChangeFinished = {
                                    scope.launch { viewModel.prefsStore.updateKaggleFullSettings(loraStrength = kaggleLoraStrength) }
                                },
                                valueRange = 0.1f..2.0f,
                            )
                        }

                        Spacer(Modifier.height(8.dp))
                        Text("Optional Gated Tokens (Encrypted)", style = MaterialTheme.typography.labelMedium, color = CelLavender)
                        Spacer(Modifier.height(4.dp))
                        OutlinedTextField(
                            value = hfTokenInput,
                            onValueChange = {
                                hfTokenInput = it
                                viewModel.saveKaggleCredentials(kaggleUserInput, kaggleKeyInput, hfToken = it)
                            },
                            label = { Text("HuggingFace Token (optional)") },
                            visualTransformation = PasswordVisualTransformation(),
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )
                        Spacer(Modifier.height(6.dp))
                        OutlinedTextField(
                            value = civitaiTokenInput,
                            onValueChange = {
                                civitaiTokenInput = it
                                viewModel.saveKaggleCredentials(kaggleUserInput, kaggleKeyInput, civitaiToken = it)
                            },
                            label = { Text("Civitai API Token (optional for gated checkpoints)") },
                            visualTransformation = PasswordVisualTransformation(),
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                        )

                        Spacer(Modifier.height(12.dp))
                        // ── Phase-5 Cloud Model Cache Rows ──
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(14.dp))
                                .background(CelTerminalBg.copy(alpha = 0.78f))
                                .border(1.dp, visuals.subtleBorder, RoundedCornerShape(14.dp))
                                .padding(12.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text("Cloud Model Cache (Fast Cold Boot)", style = MaterialTheme.typography.titleSmall, color = CelTextPrimary)
                                IconButton(onClick = { viewModel.refreshKaggleCache() }) {
                                    Icon(Icons.Rounded.Refresh, contentDescription = "Refresh cache status", tint = visuals.primary)
                                }
                            }
                            Text(
                                "Caches 7 GB Civitai checkpoints once into a private Kaggle Dataset using CPU-only (0 GPU quota). Future renders mount locally in seconds.",
                                style = MaterialTheme.typography.bodySmall,
                                color = CelTextSecondary,
                            )
                            KaggleImageEngine.MODEL_PRESETS.filter { it.mode == "civitai" }.forEach { p ->
                                val entry = uiState.kaggleCacheStatusMap[p.label]
                                val isBusy = uiState.kaggleCacheBusyPreset == p.label
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(p.label, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary, maxLines = 1)
                                        Text(
                                            text = when {
                                                isBusy -> "Building cache..."
                                                entry?.healthy == true -> "Cached · ${String.format(Locale.US, "%.2f", entry.bytes / 1_073_741_824.0)} GB"
                                                else -> "Not cached"
                                            },
                                            style = MaterialTheme.typography.labelSmall,
                                            color = if (entry?.healthy == true) CelEmeraldThought else CelTextMuted,
                                        )
                                    }
                                    if (entry?.healthy == true) {
                                        OutlinedButton(
                                            onClick = { viewModel.deleteKaggleCache(p.label) },
                                            enabled = uiState.kaggleCacheBusyPreset == null,
                                            shape = RoundedCornerShape(10.dp),
                                        ) {
                                            Icon(Icons.Rounded.Delete, contentDescription = null, modifier = Modifier.size(14.dp), tint = CelDangerRed)
                                            Spacer(Modifier.width(4.dp))
                                            Text("Delete", maxLines = 1, softWrap = false)
                                        }
                                    } else {
                                        OutlinedButton(
                                            onClick = { viewModel.buildKaggleCache(p.label) },
                                            enabled = uiState.kaggleCacheBusyPreset == null,
                                            shape = RoundedCornerShape(10.dp),
                                        ) {
                                            if (isBusy) {
                                                CircularProgressIndicator(modifier = Modifier.size(13.dp), strokeWidth = 2.dp)
                                            } else {
                                                Icon(Icons.Rounded.CloudUpload, contentDescription = null, modifier = Modifier.size(14.dp))
                                            }
                                            Spacer(Modifier.width(4.dp))
                                            Text("Cache now", maxLines = 1, softWrap = false)
                                        }
                                    }
                                }
                            }
                            if (uiState.kaggleCacheStatusText.isNotBlank()) {
                                Row(
                                    verticalAlignment = Alignment.CenterVertically,
                                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                                ) {
                                    Icon(Icons.Rounded.CloudDone, contentDescription = null, tint = CelLavender, modifier = Modifier.size(14.dp))
                                    Text(
                                        text = uiState.kaggleCacheStatusText,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = CelLavender,
                                    )
                                }
                            }
                        }
                    }
                } else {
                    // ── Standard Providers (AI Horde, Pollinations, HF, OpenAI, Custom) ──
                    Spacer(Modifier.height(8.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("Models", style = MaterialTheme.typography.labelSmall, color = CelLavender)
                        if (selectedProvider == "aihorde" || selectedProvider == "pollinations") {
                            OutlinedButton(
                                onClick = {
                                    refreshingModels = true
                                    scope.launch {
                                        val res = if (selectedProvider == "aihorde") {
                                            viewModel.imagineClient.fetchAiHordeImageModels()
                                        } else {
                                            viewModel.imagineClient.fetchPollinationsImageModels()
                                        }
                                        refreshingModels = false
                                        res.onSuccess { list ->
                                            liveProviderModels = list
                                            if (list.isNotEmpty() && selectedModel !in list) {
                                                selectedModel = list.first()
                                                viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                            }
                                            viewModel.showBanner("Fetched ${list.size} live ${activeOption.label} models.")
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
                                        viewModel.prefsStore.updateImagineConfig(selectedProvider, selectedModel, apiKey, customUrl)
                                    }
                                },
                                label = { Text(m.substringAfterLast('/'), maxLines = 1, softWrap = false) },
                            )
                        }
                    }

                    if (showKeyPanel || activeOption.requiresKey || selectedProvider == "custom") {
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
                            if (selectedProvider == "kaggle") {
                                viewModel.prefsStore.updateImagineConfig("kaggle", kagglePreset, apiKey, customUrl)
                                viewModel.prefsStore.updateKaggleFullSettings(
                                    preset = kagglePreset,
                                    size = kaggleSize,
                                    steps = kaggleSteps,
                                    guidance = kaggleGuidance,
                                    batch = kaggleBatch,
                                    seed = if (kaggleRandomSeed) -1L else kaggleSeed,
                                    prompt = prompt,
                                    stickyPrompt = kaggleSticky,
                                    negativePrompt = negativePrompt,
                                    autoClean = kaggleAutoClean,
                                )
                                val res = viewModel.generateKaggleBatch(
                                    prompt = prompt,
                                    stickyPrompt = kaggleSticky,
                                    negativePrompt = negativePrompt,
                                    presetLabel = kagglePreset,
                                    sizeLabel = kaggleSize,
                                    steps = kaggleSteps,
                                    guidance = kaggleGuidance,
                                    batch = kaggleBatch,
                                    seed = if (kaggleRandomSeed) -1L else kaggleSeed,
                                    initImagePath = if (editLastImg2Img) latestImgPath else null,
                                    denoise = img2ImgDenoise,
                                )
                                res.onSuccess { list ->
                                    viewModel.showBanner("Rendered ${list.size} image(s) on Kaggle GPU & saved to Pictures/Cellium!")
                                }.onFailure { localError = it.localizedMessage }
                            } else {
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
                        Text(
                            text = if (selectedProvider == "kaggle") {
                                if (kaggleBatch > 1) "Render $kaggleBatch Images on Kaggle GPU" else "Render on Kaggle GPU"
                            } else {
                                "Generate with Illume"
                            },
                            maxLines = 1,
                            softWrap = false,
                        )
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
                        text = "Your generated art is saved locally on your device (and Pictures/Cellium for Kaggle GPU). Try Kaggle GPU (30h/wk free), AI Horde, or Pollinations!",
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

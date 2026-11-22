package com.henny.cellium.ui.avatar

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.GridOn
import androidx.compose.material.icons.rounded.Pause
import androidx.compose.material.icons.rounded.PlayArrow
import androidx.compose.material.icons.rounded.RemoveRedEye
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.avatar.AVATAR_GENDERS
import com.henny.cellium.avatar.AvatarLibrary
import com.henny.cellium.avatar.DotMatrixAvatarCanvas
import com.henny.cellium.avatar.PET_PAT_GREETINGS
import com.henny.cellium.avatar.STYLE_MODIFIERS
import com.henny.cellium.core.CelliumSoundEngine
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.components.GlassPill
import com.henny.cellium.ui.theme.CelBorderActive
import com.henny.cellium.ui.theme.CelBorderGlass
import com.henny.cellium.ui.theme.CelBorderSubtle
import com.henny.cellium.ui.theme.CelCardGlass
import com.henny.cellium.ui.theme.CelDeepSpace
import com.henny.cellium.ui.theme.CelLavender
import com.henny.cellium.ui.theme.CelMagenta
import com.henny.cellium.ui.theme.CelObsidianGlass
import com.henny.cellium.ui.theme.CelPanelGlass
import com.henny.cellium.ui.theme.CelSoftLavender
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.CelViolet
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun AvatarStudioScreen(
    viewModel: CelliumViewModel,
    soundEngine: CelliumSoundEngine,
    onBack: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    if (onBack != null) {
        BackHandler { onBack() }
    }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs by viewModel.preferences.collectAsStateWithLifecycle()

    var library by remember { mutableStateOf<AvatarLibrary?>(null) }
    var selectedGender by remember(prefs.avatarGender) { mutableStateOf(prefs.avatarGender) }
    var selectedBase by remember { mutableStateOf("Happy") }
    var selectedModifier by remember { mutableStateOf("Base") }
    var searchQuery by remember { mutableStateOf("") }
    var autoPlay by remember { mutableStateOf(false) }
    var showGrid by remember { mutableStateOf(true) }
    var stageScale by remember { mutableFloatStateOf(1.0f) }
    var blinkTrigger by remember { mutableIntStateOf(0) }
    var petCaption by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(context) {
        library = withContext(Dispatchers.IO) { AvatarLibrary.load(context) }
    }

    val baseNames = remember(library, selectedGender) {
        library?.baseNames(selectedGender).orEmpty()
    }
    val filteredNames = remember(baseNames, searchQuery) {
        val q = searchQuery.trim().lowercase()
        if (q.isEmpty()) baseNames else baseNames.filter { it.lowercase().contains(q) }
    }
    val currentExpr = remember(library, selectedGender, selectedBase, selectedModifier) {
        library?.get(selectedGender, selectedBase, selectedModifier)
    }

    LaunchedEffect(autoPlay, filteredNames) {
        if (!autoPlay || filteredNames.isEmpty()) return@LaunchedEffect
        var idx = filteredNames.indexOf(selectedBase).coerceAtLeast(0)
        while (autoPlay) {
            delay(2200L)
            idx = (idx + 1) % filteredNames.size
            selectedBase = filteredNames[idx]
        }
    }

    LaunchedEffect(petCaption) {
        if (petCaption != null) {
            delay(1800L)
            petCaption = null
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(horizontal = 14.dp, vertical = 10.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        // Header Row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 760.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                if (onBack != null) {
                    IconButton(onClick = onBack, modifier = Modifier.testTag("avatar_back_button")) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Rounded.ArrowBack,
                            contentDescription = "Back to Settings",
                            tint = CelTextPrimary,
                        )
                    }
                }
                Column {
                    Text("Avatar Studio", style = MaterialTheme.typography.titleLarge, color = CelTextPrimary)
                    val totalCount = library?.totalMatrixCount() ?: 3800
                    Text(
                        text = "$totalCount expressions · ${currentExpr?.points?.size ?: 0} dots",
                        style = MaterialTheme.typography.labelMedium,
                        color = CelTextSecondary,
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                GlassPill(
                    onClick = {
                        soundEngine.playPop()
                        scope.launch { viewModel.prefsStore.updateFloatingMiniCel(!prefs.floatingMiniCel) }
                    },
                    selected = prefs.floatingMiniCel,
                    modifier = Modifier.testTag("avatar_minicel_button"),
                ) {
                    Text(if (prefs.floatingMiniCel) "Mini ON" else "Mini-Cel", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                }
                GlassPill(
                    onClick = {
                        blinkTrigger++
                        soundEngine.playPop()
                    },
                    modifier = Modifier.testTag("avatar_blink_button"),
                ) {
                    Icon(Icons.Rounded.RemoveRedEye, contentDescription = "Trigger blink", tint = CelLavender, modifier = Modifier.size(16.dp))
                    Text("Blink", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                }
                GlassPill(
                    onClick = {
                        autoPlay = !autoPlay
                        soundEngine.playClick()
                    },
                    selected = autoPlay,
                    modifier = Modifier.testTag("avatar_autoplay_button"),
                ) {
                    Icon(
                        imageVector = if (autoPlay) Icons.Rounded.Pause else Icons.Rounded.PlayArrow,
                        contentDescription = if (autoPlay) "Pause auto-play" else "Start auto-play",
                        tint = if (autoPlay) CelMagenta else CelLavender,
                        modifier = Modifier.size(16.dp),
                    )
                    Text(if (autoPlay) "Stop" else "Auto", style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                }
            }
        }

        // Live Dot-Matrix Stage
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 760.dp)
                .height(220.dp)
                .clip(RoundedCornerShape(24.dp))
                .background(
                    Brush.radialGradient(
                        listOf(Color(0xFF22133D), CelDeepSpace, Color(0xFF090512))
                    )
                )
                .border(1.2.dp, CelBorderGlass, RoundedCornerShape(24.dp)),
        ) {
            DotMatrixAvatarCanvas(
                expression = currentExpr,
                scale = stageScale,
                showGrid = showGrid,
                highFps = prefs.highFpsMode,
                blinkTrigger = blinkTrigger,
                onTapped = { soundEngine.playPop() },
                onPetted = {
                    soundEngine.playAnimalesePurr()
                    petCaption = PET_PAT_GREETINGS.random()
                },
                modifier = Modifier
                    .fillMaxSize()
                    .testTag("avatar_studio_canvas"),
            )

            // Current expression pill overlay
            Surface(
                color = CelObsidianGlass,
                shape = RoundedCornerShape(12.dp),
                border = BorderStroke(1.dp, CelBorderSubtle),
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(10.dp),
            ) {
                Text(
                    text = currentExpr?.name ?: "Loading…",
                    style = MaterialTheme.typography.labelMedium,
                    color = CelSoftLavender,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }

            // Grid toggle button
            IconButton(
                onClick = { showGrid = !showGrid },
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(4.dp)
                    .testTag("avatar_grid_toggle"),
            ) {
                Icon(
                    imageVector = Icons.Rounded.GridOn,
                    contentDescription = "Toggle stage grid",
                    tint = if (showGrid) CelViolet else CelTextMuted,
                )
            }

            // Headpat floating caption
            petCaption?.let { cap ->
                Surface(
                    color = CelViolet.copy(alpha = 0.85f),
                    shape = RoundedCornerShape(999.dp),
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = 10.dp),
                ) {
                    Text(
                        text = cap,
                        style = MaterialTheme.typography.labelLarge,
                        color = Color.White,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                    )
                }
            }
        }

        // Scale slider + Style selector
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 760.dp)
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AVATAR_GENDERS.forEach { g ->
                GlassPill(
                    onClick = {
                        selectedGender = g
                        soundEngine.playClick()
                        scope.launch { viewModel.prefsStore.updateAvatarGender(g) }
                    },
                    selected = selectedGender == g,
                    modifier = Modifier.testTag("avatar_style_$g"),
                ) {
                    Text(g, style = MaterialTheme.typography.labelMedium, color = CelTextPrimary)
                }
            }
        }

        // Modifier Chips (Base + 9 procedural style modifiers)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 760.dp)
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            (listOf("Base") + STYLE_MODIFIERS).forEach { mod ->
                GlassPill(
                    onClick = {
                        selectedModifier = mod
                        soundEngine.playClick()
                    },
                    selected = selectedModifier == mod,
                    modifier = Modifier.testTag("avatar_mod_$mod"),
                ) {
                    Text(
                        text = mod,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selectedModifier == mod) CelSoftLavender else CelTextSecondary,
                    )
                }
            }
        }

        // Search + Scale compact row
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 760.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = { searchQuery = it },
                singleLine = true,
                placeholder = { Text("Filter ${baseNames.size} bases…", color = CelTextMuted) },
                leadingIcon = { Icon(Icons.Rounded.Search, contentDescription = null, tint = CelLavender, modifier = Modifier.size(18.dp)) },
                trailingIcon = {
                    if (searchQuery.isNotEmpty()) {
                        IconButton(onClick = { searchQuery = "" }) {
                            Icon(Icons.Rounded.Close, contentDescription = "Clear filter", tint = CelTextMuted, modifier = Modifier.size(16.dp))
                        }
                    }
                },
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier
                    .weight(1.3f)
                    .testTag("avatar_search_input"),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = CelViolet,
                    unfocusedBorderColor = CelBorderSubtle,
                    focusedTextColor = CelTextPrimary,
                    unfocusedTextColor = CelTextPrimary,
                ),
            )

            Column(modifier = Modifier.weight(0.9f)) {
                Text(
                    text = "Zoom ${(stageScale * 100).toInt()}%",
                    style = MaterialTheme.typography.labelSmall,
                    color = CelTextSecondary,
                )
                Slider(
                    value = stageScale,
                    onValueChange = { stageScale = it },
                    valueRange = 0.7f..1.45f,
                    colors = SliderDefaults.colors(thumbColor = CelMagenta, activeTrackColor = CelViolet),
                )
            }
        }

        // Expression Grid
        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 112.dp),
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .widthIn(max = 760.dp),
            contentPadding = PaddingValues(bottom = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(filteredNames, key = { it }) { exprName ->
                val active = exprName == selectedBase
                Surface(
                    color = if (active) CelViolet.copy(alpha = 0.28f) else CelCardGlass,
                    shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, if (active) CelBorderActive else CelBorderSubtle),
                    modifier = Modifier
                        .clickable {
                            selectedBase = exprName
                            soundEngine.playPop()
                        }
                        .testTag("avatar_expr_$exprName"),
                ) {
                    Text(
                        text = exprName,
                        style = MaterialTheme.typography.labelMedium,
                        color = if (active) Color.White else CelTextSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
                    )
                }
            }
        }
    }
}

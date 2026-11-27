package com.henny.cellium

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Call
import androidx.compose.material.icons.rounded.ChatBubble
import androidx.compose.material.icons.rounded.CloudSync
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalScrollCaptureInProgress
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.assistant.FloatingCelOverlayService
import com.henny.cellium.core.AuthManager
import com.henny.cellium.data.sync.CloudSyncMode
import com.henny.cellium.ui.analytics.AnalyticsScreen
import com.henny.cellium.ui.arena.ArenaScreen
import com.henny.cellium.ui.avatar.AvatarStudioScreen
import com.henny.cellium.ui.avatar.FloatingMiniCelOverlay
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.chat.ChatScreen
import com.henny.cellium.ui.components.CelliumBackground
import com.henny.cellium.ui.imagine.ImagineStudioScreen
import com.henny.cellium.ui.live.LiveModeScreen
import com.henny.cellium.ui.onboarding.OnboardingScreen
import com.henny.cellium.ui.settings.SettingsScreen
import com.henny.cellium.ui.theme.CelTextMuted
import com.henny.cellium.ui.theme.CelTextPrimary
import com.henny.cellium.ui.theme.CelTextSecondary
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch

/**
 * Primary 4-tab layout:
 * Illume · Chat · Live · Settings
 */
enum class CelliumTab(
    val label: String,
    val icon: ImageVector,
    val tag: String,
) {
    IMAGINE("Illume", Icons.Rounded.AutoAwesome, "nav_illume"),
    CHAT("Chat", Icons.Rounded.ChatBubble, "nav_chat"),
    LIVE("Live", Icons.Rounded.Call, "nav_live"),
    SETTINGS("Settings", Icons.Rounded.Settings, "nav_settings"),
}

private sealed interface SubOverlay {
    data object None : SubOverlay
    data class Arena(val sessionId: String? = null) : SubOverlay
    data object AvatarStudio : SubOverlay
    data object StatsConsole : SubOverlay
}

@Composable
fun CelliumApp(
    viewModel: CelliumViewModel,
    externalChatOpenNonce: Long = 0L,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val visuals = LocalCelliumVisuals.current

    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val prefsLoaded by viewModel.preferencesLoaded.collectAsStateWithLifecycle()
    val pendingSyncConflict by remember(viewModel) {
        viewModel.uiState.map { it.pendingSyncConflict }.distinctUntilChanged()
    }.collectAsStateWithLifecycle(initialValue = false)
    val authManager = remember { AuthManager() }
    val currentUser by authManager.currentUserFlow.collectAsStateWithLifecycle(initialValue = authManager.currentUser)

    var googleBusy by remember { mutableStateOf(false) }
    var googleErr by remember { mutableStateOf<String?>(null) }

    fun triggerGoogleSignIn() {
        val activity = context.findActivity()
        if (activity == null) {
            val msg = "Unable to launch Google Sign-In from current context."
            googleErr = msg
            viewModel.showBanner(msg)
            return
        }
        googleBusy = true
        googleErr = null
        scope.launch {
            val res = authManager.signInWithGoogle(activity)
            googleBusy = false
            res.onSuccess { profile ->
                viewModel.prefsStore.setGuestMode(false)
                viewModel.showBanner("Signed in as ${profile.email ?: profile.displayName ?: "Google user"}. Syncing...")
                viewModel.checkAndSyncAfterGoogleSignIn()
            }.onFailure { err ->
                val msg = err.localizedMessage ?: "Google Sign-In failed"
                googleErr = msg
                viewModel.showBanner(msg)
            }
        }
    }

    // Sync system-wide Floating Cel overlay when toggled and overlay permission is granted
    LaunchedEffect(prefs.floatingMiniCel) {
        if (prefs.floatingMiniCel && Settings.canDrawOverlays(context)) {
            FloatingCelOverlayService.start(context, autoListen = false)
        } else if (!prefs.floatingMiniCel) {
            FloatingCelOverlayService.stop(context)
        }
    }

    if (!prefsLoaded && !prefs.onboardingCompleted) {
        Box(modifier = Modifier.fillMaxSize().background(Color(0xFF06060A)))
        return
    }

    if (!prefs.onboardingCompleted) {
        val onboardingProviders by remember(viewModel) {
            viewModel.uiState.map { it.providers }.distinctUntilChanged()
        }.collectAsStateWithLifecycle(initialValue = emptyList())
        OnboardingScreen(
            providers = onboardingProviders,
            initialTermsAccepted = prefs.termsAccepted,
            initialAvatarGender = prefs.avatarGender,
            googleAuthBusy = googleBusy,
            googleAuthError = googleErr,
            signedInEmail = currentUser?.email,
            onAcceptTerms = { scope.launch { viewModel.prefsStore.acceptTerms() } },
            onContinueAsGuest = { scope.launch { viewModel.prefsStore.setGuestMode(true) } },
            onContinueWithGoogle = { triggerGoogleSignIn() },
            onSelectAvatarGender = { gender ->
                scope.launch { viewModel.prefsStore.updateAvatarGender(gender) }
            },
            onSaveProviderConfig = { profile -> viewModel.saveProviderProfile(profile) },
            onFetchModels = { profile -> viewModel.fetchLiveModels(profile) },
            onCompleteOnboarding = { selectedId ->
                scope.launch {
                    viewModel.prefsStore.updateActiveProviderId(selectedId)
                    viewModel.prefsStore.completeOnboarding()
                }
            },
        )
        return
    }

    var currentTab by rememberSaveable { mutableStateOf(CelliumTab.CHAT) }
    var subOverlay by remember { mutableStateOf<SubOverlay>(SubOverlay.None) }

    LaunchedEffect(externalChatOpenNonce) {
        if (externalChatOpenNonce > 0L) {
            subOverlay = SubOverlay.None
            currentTab = CelliumTab.CHAT
        }
    }

    LaunchedEffect(currentTab, subOverlay) {
        val tabKey = when (subOverlay) {
            is SubOverlay.Arena -> "arena"
            is SubOverlay.None -> currentTab.name.lowercase()
            else -> "sub"
        }
        viewModel.setCurrentVisibleTab(tabKey)
    }

    // Immersive full-bleed Pure OLED Black Live Mode (no wallpaper, no bottom nav bar)
    if (currentTab == CelliumTab.LIVE && subOverlay == SubOverlay.None) {
        Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
            LiveModeScreen(
                viewModel = viewModel,
                onClose = { currentTab = CelliumTab.CHAT },
            )
        }
        return
    }

    CelliumBackground {
        when (val overlay = subOverlay) {
            is SubOverlay.Arena -> {
                ArenaScreen(
                    viewModel = viewModel,
                    initialSessionId = overlay.sessionId,
                    onBack = { subOverlay = SubOverlay.None },
                    onOpenSettingsProviders = {
                        subOverlay = SubOverlay.None
                        currentTab = CelliumTab.SETTINGS
                    },
                )
                return@CelliumBackground
            }
            SubOverlay.AvatarStudio -> {
                AvatarStudioScreen(
                    viewModel = viewModel,
                    soundEngine = viewModel.soundEngine,
                    onBack = { subOverlay = SubOverlay.None },
                )
                return@CelliumBackground
            }
            SubOverlay.StatsConsole -> {
                AnalyticsScreen(
                    viewModel = viewModel,
                    onBack = { subOverlay = SubOverlay.None },
                )
                return@CelliumBackground
            }
            SubOverlay.None -> Unit
        }

        BoxWithConstraints(modifier = Modifier.fillMaxSize()) {
            val useRail = maxWidth >= 700.dp
            val scrollCaptureActive = LocalScrollCaptureInProgress.current

            Scaffold(
                containerColor = Color.Transparent,
                contentWindowInsets = WindowInsets.safeDrawing,
                bottomBar = {
                    if (!useRail && !scrollCaptureActive) {
                        NavigationBar(
                            containerColor = visuals.surfaceBg.copy(alpha = 0.92f),
                            tonalElevation = 0.dp,
                        ) {
                            CelliumTab.entries.forEach { tab ->
                                NavigationBarItem(
                                    selected = currentTab == tab,
                                    onClick = {
                                        viewModel.soundEngine.playClick()
                                        currentTab = tab
                                    },
                                    icon = { Icon(tab.icon, contentDescription = tab.label) },
                                    label = {
                                        Text(
                                            text = tab.label,
                                            style = MaterialTheme.typography.labelSmall,
                                            maxLines = 1,
                                            softWrap = false,
                                        )
                                    },
                                    colors = NavigationBarItemDefaults.colors(
                                        selectedIconColor = visuals.primary,
                                        selectedTextColor = CelTextPrimary,
                                        unselectedIconColor = CelTextMuted,
                                        unselectedTextColor = CelTextMuted,
                                        indicatorColor = visuals.primary.copy(alpha = 0.22f),
                                    ),
                                    modifier = Modifier.testTag(tab.tag),
                                )
                            }
                        }
                    }
                },
            ) { innerPadding ->
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(innerPadding)
                        .consumeWindowInsets(innerPadding),
                ) {
                    if (useRail && !scrollCaptureActive) {
                        NavigationRail(
                            containerColor = visuals.surfaceBg.copy(alpha = 0.92f),
                            modifier = Modifier.fillMaxHeight(),
                        ) {
                            CelliumTab.entries.forEach { tab ->
                                NavigationRailItem(
                                    selected = currentTab == tab,
                                    onClick = {
                                        viewModel.soundEngine.playClick()
                                        currentTab = tab
                                    },
                                    icon = { Icon(tab.icon, contentDescription = tab.label) },
                                    label = {
                                        Text(
                                            text = tab.label,
                                            style = MaterialTheme.typography.labelSmall,
                                            maxLines = 1,
                                            softWrap = false,
                                        )
                                    },
                                    colors = NavigationRailItemDefaults.colors(
                                        selectedIconColor = visuals.primary,
                                        selectedTextColor = CelTextPrimary,
                                        unselectedIconColor = CelTextMuted,
                                        unselectedTextColor = CelTextMuted,
                                        indicatorColor = visuals.primary.copy(alpha = 0.22f),
                                    ),
                                    modifier = Modifier.testTag(tab.tag),
                                )
                            }
                        }
                    }

                    Box(modifier = Modifier.weight(1f).fillMaxSize()) {
                        when (currentTab) {
                            CelliumTab.IMAGINE -> ImagineStudioScreen(
                                viewModel = viewModel,
                                onJumpToChat = { currentTab = CelliumTab.CHAT },
                            )
                            CelliumTab.CHAT -> ChatScreen(
                                viewModel = viewModel,
                                onOpenArena = { subOverlay = SubOverlay.Arena(null) },
                                onOpenArenaSession = { sid -> subOverlay = SubOverlay.Arena(sid) },
                                onOpenSettingsProviders = { currentTab = CelliumTab.SETTINGS },
                            )
                            CelliumTab.LIVE -> LiveModeScreen(
                                viewModel = viewModel,
                                onClose = { currentTab = CelliumTab.CHAT },
                            )
                            CelliumTab.SETTINGS -> SettingsScreen(
                                viewModel = viewModel,
                                user = currentUser,
                                googleAuthBusy = googleBusy,
                                onSignInWithGoogle = { triggerGoogleSignIn() },
                                onSignOutGoogle = {
                                    scope.launch {
                                        authManager.signOut(context)
                                        viewModel.prefsStore.setGuestMode(true)
                                        viewModel.showBanner("Switched back to Guest Mode (local data preserved).")
                                    }
                                },
                                onOpenAvatarStudio = { subOverlay = SubOverlay.AvatarStudio },
                                onOpenStats = { subOverlay = SubOverlay.StatsConsole },
                                onJumpToChat = { currentTab = CelliumTab.CHAT },
                            )
                        }
                    }
                }
            }

            // Fallback in-app floating face if system overlay permission is not granted yet
            if (prefs.floatingMiniCel && !Settings.canDrawOverlays(context) && !scrollCaptureActive) {
                val currentMood by remember(viewModel) {
                    viewModel.uiState.map { it.currentMood }.distinctUntilChanged()
                }.collectAsStateWithLifecycle(initialValue = "idle")
                FloatingMiniCelOverlay(
                    mood = currentMood,
                    avatarGender = prefs.avatarGender,
                    highFps = prefs.highFpsMode,
                    onHeadpat = { viewModel.soundEngine.playAnimalesePurr() },
                    onOpenLiveMode = { currentTab = CelliumTab.LIVE },
                    onDismiss = { scope.launch { viewModel.prefsStore.updateFloatingMiniCel(false) } },
                )
            }
        }
    }

    // 3-Option Guest -> Google Sign-In Conflict Resolution Dialog (#19)
    if (pendingSyncConflict) {
        AlertDialog(
            onDismissRequest = { viewModel.dismissSyncConflict() },
            containerColor = Color(0xFF140D26),
            icon = { Icon(Icons.Rounded.CloudSync, contentDescription = null, tint = visuals.primary) },
            title = { Text("Sync Conflict Detected", color = CelTextPrimary) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        text = "You have both local Guest data on this phone and existing Cloud data in your Google account. How would you like to sync?",
                        style = MaterialTheme.typography.bodySmall,
                        color = CelTextSecondary,
                    )
                    Button(
                        onClick = { viewModel.resolveSyncConflict(CloudSyncMode.MERGE_BOTH) },
                        colors = ButtonDefaults.buttonColors(containerColor = visuals.primary),
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Merge Both (Recommended)", maxLines = 1, softWrap = false)
                    }
                    OutlinedButton(
                        onClick = { viewModel.resolveSyncConflict(CloudSyncMode.KEEP_LOCAL_REPLACE_CLOUD) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Keep Local (Replace Cloud)", maxLines = 1, softWrap = false)
                    }
                    OutlinedButton(
                        onClick = { viewModel.resolveSyncConflict(CloudSyncMode.KEEP_CLOUD_REPLACE_LOCAL) },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Keep Cloud (Replace Local)", maxLines = 1, softWrap = false)
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { viewModel.dismissSyncConflict() }) {
                    Text("Later")
                }
            },
        )
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}

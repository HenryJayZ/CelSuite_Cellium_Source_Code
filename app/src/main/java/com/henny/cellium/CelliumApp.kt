package com.henny.cellium

import android.app.Activity
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.Call
import androidx.compose.material.icons.rounded.ChatBubble
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.NavigationRailItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.henny.cellium.core.AuthManager
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
import com.henny.cellium.ui.theme.LocalCelliumVisuals
import kotlinx.coroutines.launch

/**
 * Primary 4-tab layout in the user's exact requested order:
 * Imagine · Chat · Live · Settings
 * (Avatar Studio, Stats & Dev Console, and RAM Watchdog live inside Settings.)
 */
enum class CelliumTab(
    val label: String,
    val icon: ImageVector,
    val tag: String,
) {
    IMAGINE("Imagine", Icons.Rounded.AutoAwesome, "nav_imagine"),
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
fun CelliumApp(viewModel: CelliumViewModel) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val visuals = LocalCelliumVisuals.current

    val prefs by viewModel.preferences.collectAsStateWithLifecycle()
    val prefsLoaded by viewModel.preferencesLoaded.collectAsStateWithLifecycle()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val authManager = remember { AuthManager() }
    val currentUser by authManager.currentUserFlow.collectAsStateWithLifecycle(initialValue = authManager.currentUser)

    var googleBusy by remember { mutableStateOf(false) }
    var googleErr by remember { mutableStateOf<String?>(null) }

    fun triggerGoogleSignIn() {
        val activity = context as? Activity ?: return
        googleBusy = true
        googleErr = null
        scope.launch {
            val res = authManager.signInWithGoogle(activity)
            googleBusy = false
            res.onSuccess {
                viewModel.prefsStore.setGuestMode(false)
                viewModel.syncWithGoogleCloud()
            }.onFailure { err ->
                googleErr = err.localizedMessage ?: "Google Sign-In failed"
            }
        }
    }

    // Never flash Onboarding/Welcome screen while DataStore finishes initial hydration
    if (!prefsLoaded && !prefs.onboardingCompleted) {
        Box(modifier = Modifier.fillMaxSize().background(visuals.voidBg))
        return
    }

    // Step 1-3 First-Run Onboarding (ONLY for brand-new users who have not completed onboarding)
    if (!prefs.onboardingCompleted) {
        OnboardingScreen(
            providers = uiState.providers,
            initialTermsAccepted = prefs.termsAccepted,
            googleAuthBusy = googleBusy,
            googleAuthError = googleErr,
            signedInEmail = currentUser?.email,
            onAcceptTerms = { scope.launch { viewModel.prefsStore.acceptTerms() } },
            onContinueAsGuest = { scope.launch { viewModel.prefsStore.setGuestMode(true) } },
            onContinueWithGoogle = { triggerGoogleSignIn() },
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

    // Tell ViewModel which tab is visible so WhatsApp-style bundled notifications trigger
    // whenever Cel replies while the user is on Imagine, Live, Settings, or backgrounded.
    LaunchedEffect(currentTab, subOverlay) {
        val tabKey = if (subOverlay != SubOverlay.None) "sub" else currentTab.name.lowercase()
        viewModel.setCurrentVisibleTab(tabKey)
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

            Scaffold(
                containerColor = Color.Transparent,
                contentWindowInsets = WindowInsets.safeDrawing,
                bottomBar = {
                    if (!useRail) {
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
                                    label = { Text(tab.label, style = MaterialTheme.typography.labelSmall) },
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
                        .padding(innerPadding),
                ) {
                    if (useRail) {
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
                                    label = { Text(tab.label, style = MaterialTheme.typography.labelSmall) },
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
                            )
                        }
                    }
                }
            }

            // Draggable Floating Mini-Cel Companion Overlay
            if (prefs.floatingMiniCel) {
                FloatingMiniCelOverlay(
                    mood = uiState.currentMood,
                    avatarGender = prefs.avatarGender,
                    highFps = prefs.highFpsMode,
                    onHeadpat = { viewModel.soundEngine.playAnimalesePurr() },
                    onOpenLiveMode = { currentTab = CelliumTab.LIVE },
                    onDismiss = { scope.launch { viewModel.prefsStore.updateFloatingMiniCel(false) } },
                )
            }
        }
    }
}

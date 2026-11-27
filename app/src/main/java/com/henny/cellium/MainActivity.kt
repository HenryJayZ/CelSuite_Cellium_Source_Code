package com.henny.cellium

import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.Coil
import coil.ImageLoader
import coil.disk.DiskCache
import coil.memory.MemoryCache
import com.henny.cellium.core.CelliumNotificationManager
import com.henny.cellium.core.CelliumPreferences
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.theme.CelliumTheme
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import java.io.File

class MainActivity : ComponentActivity() {
    private val viewModel: CelliumViewModel by viewModels()
    private val openChatNonceFlow = kotlinx.coroutines.flow.MutableStateFlow(0L)

    companion object {
        const val EXTRA_OPEN_SESSION_ID = "com.henny.cellium.OPEN_SESSION_ID"
        const val EXTRA_OPEN_CHAT_TAB = "com.henny.cellium.OPEN_CHAT_TAB"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        configureBoundedImageLoader()
        CelliumNotificationManager.ensureChannels(this)
        handleExternalIntent(intent)

        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            val openChatNonce by openChatNonceFlow.collectAsStateWithLifecycle()
            val visualPrefs by remember(viewModel) {
                viewModel.preferences
                    .map { p ->
                        CelliumPreferences(
                            themePresetId = p.themePresetId,
                            customPrimaryHex = p.customPrimaryHex,
                            customWallpaperUri = p.customWallpaperUri,
                            wallpaperDim = p.wallpaperDim,
                            glassOpacity = p.glassOpacity,
                            borderGlow = p.borderGlow,
                            particlesEnabled = p.particlesEnabled,
                            particleDensity = p.particleDensity,
                            highFpsMode = p.highFpsMode,
                            fontScale = p.fontScale,
                        )
                    }
                    .distinctUntilChanged()
            }.collectAsStateWithLifecycle(initialValue = remember { CelliumPreferences() })
            CelliumTheme(prefs = visualPrefs) {
                CelliumApp(viewModel = viewModel, externalChatOpenNonce = openChatNonce)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleExternalIntent(intent)
    }

    override fun onStart() {
        super.onStart()
        viewModel.setAppInForeground(true)
    }

    override fun onStop() {
        super.onStop()
        viewModel.setAppInForeground(false)
    }

    private fun handleExternalIntent(intent: Intent?) {
        if (intent == null) return
        val explicitSession = intent.getStringExtra(EXTRA_OPEN_SESSION_ID)
        val notifSession = intent.getStringExtra(CelliumNotificationManager.EXTRA_SESSION_ID)
        val targetSessionId = explicitSession?.takeIf { it.isNotBlank() } ?: notifSession
        val forceChatTab = intent.getBooleanExtra(EXTRA_OPEN_CHAT_TAB, false)
        if (!targetSessionId.isNullOrBlank()) {
            viewModel.openSessionFromExternal(targetSessionId)
            CelliumNotificationManager.clearSessionNotification(this, targetSessionId)
            openChatNonceFlow.value = System.currentTimeMillis()
        } else if (forceChatTab) {
            openChatNonceFlow.value = System.currentTimeMillis()
        }
    }

    /**
     * Caps Coil in-memory bitmap cache to 12% of available app heap and enables hardware bitmaps,
     * cutting idle RAM footprint substantially on 3–4 GB RAM devices.
     */
    private fun configureBoundedImageLoader() {
        val loader = ImageLoader.Builder(applicationContext)
            .memoryCache {
                MemoryCache.Builder(applicationContext)
                    .maxSizePercent(0.12)
                    .build()
            }
            .diskCache {
                DiskCache.Builder()
                    .directory(File(cacheDir, "cellium_img_cache"))
                    .maxSizeBytes(32L * 1024L * 1024L)
                    .build()
            }
            .allowHardware(true)
            .crossfade(false)
            .build()
        Coil.setImageLoader(loader)
    }
}

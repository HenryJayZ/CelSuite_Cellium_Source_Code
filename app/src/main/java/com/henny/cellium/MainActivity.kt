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
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.Coil
import coil.ImageLoader
import coil.disk.DiskCache
import coil.memory.MemoryCache
import com.henny.cellium.core.CelliumNotificationManager
import com.henny.cellium.ui.chat.CelliumViewModel
import com.henny.cellium.ui.theme.CelliumTheme
import java.io.File

class MainActivity : ComponentActivity() {
    private val viewModel: CelliumViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        configureBoundedImageLoader()
        CelliumNotificationManager.ensureChannels(this)
        handleNotificationIntent(intent)

        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            val prefs by viewModel.preferences.collectAsStateWithLifecycle()
            CelliumTheme(prefs = prefs) {
                CelliumApp(viewModel = viewModel)
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleNotificationIntent(intent)
    }

    override fun onStart() {
        super.onStart()
        viewModel.setAppInForeground(true)
    }

    override fun onStop() {
        super.onStop()
        viewModel.setAppInForeground(false)
    }

    private fun handleNotificationIntent(intent: Intent?) {
        val targetSessionId = intent?.getStringExtra(CelliumNotificationManager.EXTRA_SESSION_ID)
        if (!targetSessionId.isNullOrBlank()) {
            viewModel.selectSession(targetSessionId)
            CelliumNotificationManager.clearSessionNotification(this, targetSessionId)
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

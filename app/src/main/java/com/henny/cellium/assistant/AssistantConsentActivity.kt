package com.henny.cellium.assistant

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.provider.Settings
import com.henny.cellium.MainActivity
import com.henny.cellium.core.DevLogBuffer

/**
 * Translucent trampoline Activity for:
 * 1. Requesting Android MediaProjection consent so Floating Cel can capture Live Screen Vision frames.
 * 2. Handling ACTION_ASSIST / ACTION_VOICE_ASSIST / Bluetooth earpiece voice trigger intents.
 */
class AssistantConsentActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIncomingIntent(intent)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingIntent(intent)
    }

    private fun handleIncomingIntent(incoming: Intent?) {
        val action = incoming?.action
        when (action) {
            ACTION_REQUEST_SCREEN_VISION -> {
                val mpm = getSystemService(MediaProjectionManager::class.java)
                if (mpm == null) {
                    finish()
                    return
                }
                @Suppress("DEPRECATION")
                runCatching {
                    startActivityForResult(mpm.createScreenCaptureIntent(), REQ_MEDIA_PROJECTION)
                }.onFailure { finish() }
            }
            Intent.ACTION_VOICE_COMMAND,
            ACTION_VOICE_SEARCH_HANDS_FREE,
            Intent.ACTION_SEARCH_LONG_PRESS,
            Intent.ACTION_ASSIST,
            ACTION_VOICE_ASSIST -> {
                val fromEarpiece = action == Intent.ACTION_VOICE_COMMAND ||
                    action == ACTION_VOICE_SEARCH_HANDS_FREE ||
                    action == Intent.ACTION_SEARCH_LONG_PRESS
                DevLogBuffer.add("INFO", "Assistant", "AssistantConsentActivity received $action")
                val launchedNativeSession = CelliumVoiceInteractionService.requestShowSession(fromEarpiece)
                if (!launchedNativeSession) {
                    val launchedFloating = if (Settings.canDrawOverlays(this)) {
                        runCatching {
                            FloatingCelOverlayService.start(this, autoListen = true)
                            true
                        }.getOrDefault(false)
                    } else false
                    if (!launchedFloating) {
                        runCatching {
                            startActivity(
                                Intent(this, MainActivity::class.java).apply {
                                    addFlags(
                                        Intent.FLAG_ACTIVITY_NEW_TASK or
                                            Intent.FLAG_ACTIVITY_SINGLE_TOP or
                                            Intent.FLAG_ACTIVITY_CLEAR_TOP
                                    )
                                    putExtra(MainActivity.EXTRA_OPEN_LIVE_TAB, true)
                                }
                            )
                        }
                    }
                }
                finish()
            }
            else -> finish()
        }
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_MEDIA_PROJECTION && resultCode == RESULT_OK && data != null) {
            FloatingCelOverlayService.supplyMediaProjection(this, resultCode, data)
        }
        finish()
    }

    companion object {
        private const val ACTION_REQUEST_SCREEN_VISION = "com.henny.cellium.REQ_SCREEN_VISION"
        private const val ACTION_VOICE_ASSIST = "android.intent.action.VOICE_ASSIST"
        private const val ACTION_VOICE_SEARCH_HANDS_FREE = "android.speech.action.VOICE_SEARCH_HANDS_FREE"
        private const val REQ_MEDIA_PROJECTION = 8821

        fun launchScreenVisionConsent(context: Context) {
            val intent = Intent(context, AssistantConsentActivity::class.java).apply {
                action = ACTION_REQUEST_SCREEN_VISION
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            runCatching { context.startActivity(intent) }
        }
    }
}

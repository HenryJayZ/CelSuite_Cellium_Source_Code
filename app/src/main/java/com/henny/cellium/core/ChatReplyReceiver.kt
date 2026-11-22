package com.henny.cellium.core

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.RemoteInput

/**
 * Handles inline Direct Reply submissions from WhatsApp-style bundled Cel.Cellium notifications.
 */
class ChatReplyReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != CelliumNotificationManager.ACTION_DIRECT_REPLY) return
        val sessionId = intent.getStringExtra(CelliumNotificationManager.EXTRA_SESSION_ID) ?: return
        val results = RemoteInput.getResultsFromIntent(intent) ?: return
        val replyText = results.getCharSequence(CelliumNotificationManager.KEY_DIRECT_REPLY)?.toString()?.trim().orEmpty()
        if (replyText.isNotEmpty()) {
            CelliumNotificationManager.emitDirectReply(sessionId, replyText)
            CelliumNotificationManager.clearSessionNotification(context, sessionId)
        }
    }
}

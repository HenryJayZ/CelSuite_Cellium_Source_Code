package com.henny.cellium.core

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.Person
import androidx.core.app.RemoteInput
import androidx.core.content.ContextCompat
import com.henny.cellium.MainActivity
import com.henny.cellium.R
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import java.util.concurrent.ConcurrentHashMap

data class DirectReplyEvent(
    val sessionId: String,
    val replyText: String,
)

/**
 * WhatsApp-style bundled notification engine for Cel.Cellium.
 * Groups all chat replies under a single expandable notification stack ("cellium_chat_bundle")
 * using NotificationCompat.MessagingStyle + a group summary InboxStyle + inline Direct Reply.
 */
object CelliumNotificationManager {
    const val CHANNEL_CHAT = "cellium_chat_replies"
    const val GROUP_KEY_CHAT = "cellium_chat_bundle"
    const val SUMMARY_NOTIFICATION_ID = 7000
    const val KEY_DIRECT_REPLY = "key_cellium_direct_reply"
    const val EXTRA_SESSION_ID = "extra_session_id"
    const val ACTION_DIRECT_REPLY = "com.henny.cellium.ACTION_DIRECT_REPLY"

    private data class ChatNotifLine(
        val sender: String,
        val text: String,
        val timestampMs: Long,
    )

    private val sessionThreads = ConcurrentHashMap<String, MutableList<ChatNotifLine>>()

    private val _directReplies = MutableSharedFlow<DirectReplyEvent>(extraBufferCapacity = 8)
    val directReplies: SharedFlow<DirectReplyEvent> = _directReplies.asSharedFlow()

    fun emitDirectReply(sessionId: String, text: String) {
        _directReplies.tryEmit(DirectReplyEvent(sessionId, text))
    }

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            val existing = nm.getNotificationChannel(CHANNEL_CHAT)
            if (existing == null) {
                val channel = NotificationChannel(
                    CHANNEL_CHAT,
                    "Cel.Cellium Chat Replies",
                    NotificationManager.IMPORTANCE_HIGH,
                ).apply {
                    description = "Bundled replies from Cel chats and Arena conversations"
                    enableVibration(true)
                }
                nm.createNotificationChannel(channel)
            }
        }
    }

    fun hasNotificationPermission(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            NotificationManagerCompat.from(context).areNotificationsEnabled()
        }
    }

    fun notifyAssistantReply(
        context: Context,
        sessionId: String,
        sessionTitle: String,
        senderName: String,
        messageText: String,
    ) {
        if (!hasNotificationPermission(context)) return
        ensureChannels(context)

        val now = System.currentTimeMillis()
        val lines = sessionThreads.getOrPut(sessionId) { mutableListOf() }
        synchronized(lines) {
            lines.add(ChatNotifLine(senderName, messageText.take(400), now))
            if (lines.size > 6) lines.removeAt(0)
        }

        val notifId = 7100 + (sessionId.hashCode() and 0x0FFF)
        val openIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(EXTRA_SESSION_ID, sessionId)
        }
        val contentPending = PendingIntent.getActivity(
            context,
            notifId,
            openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val remoteInput = RemoteInput.Builder(KEY_DIRECT_REPLY)
            .setLabel("Reply to $senderName...")
            .build()

        val replyIntent = Intent(context, ChatReplyReceiver::class.java).apply {
            action = ACTION_DIRECT_REPLY
            putExtra(EXTRA_SESSION_ID, sessionId)
        }
        val replyFlags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE
        } else {
            PendingIntent.FLAG_UPDATE_CURRENT
        }
        val replyPending = PendingIntent.getBroadcast(context, notifId, replyIntent, replyFlags)

        val replyAction = NotificationCompat.Action.Builder(
            android.R.drawable.ic_menu_send,
            "Reply",
            replyPending,
        )
            .addRemoteInput(remoteInput)
            .setAllowGeneratedReplies(true)
            .build()

        val selfPerson = Person.Builder().setName("You").build()
        val style = NotificationCompat.MessagingStyle(selfPerson)
            .setConversationTitle(sessionTitle.ifBlank { "Cel.Cellium" })
            .setGroupConversation(sessionTitle.contains("Arena", ignoreCase = true))

        synchronized(lines) {
            lines.forEach { line ->
                val person = Person.Builder().setName(line.sender).build()
                style.addMessage(line.text, line.timestampMs, person)
            }
        }

        val childNotif = NotificationCompat.Builder(context, CHANNEL_CHAT)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setStyle(style)
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(contentPending)
            .setAutoCancel(true)
            .setGroup(GROUP_KEY_CHAT)
            .addAction(replyAction)
            .build()

        val inbox = NotificationCompat.InboxStyle()
        var totalMessages = 0
        sessionThreads.entries.forEach { (_, list) ->
            synchronized(list) {
                totalMessages += list.size
                list.lastOrNull()?.let { last ->
                    inbox.addLine("${last.sender}: ${last.text.take(90)}")
                }
            }
        }
        val chatCount = sessionThreads.size
        inbox.setBigContentTitle("Cel.Cellium · $totalMessages new ${if (totalMessages == 1) "message" else "messages"}")
            .setSummaryText("$chatCount ${if (chatCount == 1) "chat" else "chats"}")

        val summaryNotif = NotificationCompat.Builder(context, CHANNEL_CHAT)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Cel.Cellium")
            .setContentText("$totalMessages new messages across $chatCount chats")
            .setStyle(inbox)
            .setGroup(GROUP_KEY_CHAT)
            .setGroupSummary(true)
            .setGroupAlertBehavior(NotificationCompat.GROUP_ALERT_CHILDREN)
            .setContentIntent(contentPending)
            .setAutoCancel(true)
            .build()

        runCatching {
            val nm = NotificationManagerCompat.from(context)
            nm.notify(notifId, childNotif)
            nm.notify(SUMMARY_NOTIFICATION_ID, summaryNotif)
        }
    }

    fun clearSessionNotification(context: Context, sessionId: String) {
        sessionThreads.remove(sessionId)
        val notifId = 7100 + (sessionId.hashCode() and 0x0FFF)
        runCatching {
            val nm = NotificationManagerCompat.from(context)
            nm.cancel(notifId)
            if (sessionThreads.isEmpty()) {
                nm.cancel(SUMMARY_NOTIFICATION_ID)
            }
        }
    }

    fun clearAll(context: Context) {
        sessionThreads.clear()
        runCatching { NotificationManagerCompat.from(context).cancelAll() }
    }
}

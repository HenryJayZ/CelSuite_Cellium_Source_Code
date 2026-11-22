package com.henny.cellium.shizuku

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Debug
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.henny.cellium.R

/**
 * Foreground Service keeping Cel.Cellium elevated in Android's OOM/LMK priority tier whenever an
 * on-device model is loaded or process RAM crosses the configured threshold (default 1.5 GB).
 */
class MemoryGuardService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val statusText = intent?.getStringExtra(EXTRA_STATUS) ?: "Protecting local LLM memory"
        ensureChannel()
        val notification = buildNotification(statusText)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTIF_ID, notification)
        }
        return START_STICKY
    }

    private fun ensureChannel() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            val ch = NotificationChannel(
                CHANNEL_ID,
                "Cellium Memory Guard",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Keeps Cel.Cellium alive during large on-device model inference."
            }
            nm.createNotificationChannel(ch)
        }
    }

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Cel.Cellium RAM Guard Active")
            .setContentText(text)
            .setOngoing(true)
            .setSilent(true)
            .build()

    companion object {
        private const val CHANNEL_ID = "cellium_ram_guard"
        private const val NOTIF_ID = 4091
        private const val EXTRA_STATUS = "extra_status"

        fun start(context: Context, status: String) {
            val intent = Intent(context, MemoryGuardService::class.java).putExtra(EXTRA_STATUS, status)
            runCatching {
                ContextCompat.startForegroundService(context, intent)
            }
        }

        fun stop(context: Context) {
            runCatching {
                context.stopService(Intent(context, MemoryGuardService::class.java))
            }
        }

        /** Returns current process Total PSS in megabytes. */
        fun currentProcessRamMb(): Int {
            val info = Debug.MemoryInfo()
            Debug.getMemoryInfo(info)
            return (info.totalPss / 1024).coerceAtLeast(1)
        }
    }
}

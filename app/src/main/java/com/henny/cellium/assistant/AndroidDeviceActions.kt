package com.henny.cellium.assistant

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.BatteryManager
import android.os.Build
import android.provider.AlarmClock
import com.henny.cellium.ai.WebToolsClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Native Android SDK Device Action Engine (no Shizuku required).
 * Lets Cel quietly execute real phone actions (time/date, device status, open apps,
 * set alarms/timers, toggle flashlight, adjust volume, open URLs, dial, web search)
 * in Assistant Pop-up, Floating Cel, Live Mode, and Chat before speaking her final reply.
 */
object AndroidDeviceActions {
    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val ACTION_TAG_REGEX = Regex(
        """(?:```[a-zA-Z]*\s*)?\[DEVICE_ACTION]\s*([\s\S]*?)\s*\[/DEVICE_ACTION](?:\s*```)?""",
        RegexOption.IGNORE_CASE,
    )
    private val ACTION_OPEN_REGEX = Regex("""\[DEVICE_ACTION]""", RegexOption.IGNORE_CASE)
    private val ACTION_RESULT_STRAY_REGEX = Regex(
        """\[/?DEVICE_ACTION(?:_RESULT)?]""",
        RegexOption.IGNORE_CASE,
    )

    data class ActionResult(
        val action: String,
        val success: Boolean,
        val output: String,
    )

    /**
     * Extracts JSON payloads from both well-formed `[DEVICE_ACTION]{...}[/DEVICE_ACTION]` blocks
     * AND malformed/unclosed model outputs (e.g. `[DEVICE_ACTION]{"action":"web_search",...}スペ[DEVICE_ACTION_RESULT]`)
     * using a balanced-brace JSON scanner.
     */
    fun extractActionPayloads(text: String): List<String> {
        val results = LinkedHashSet<String>()
        ACTION_TAG_REGEX.findAll(text).forEach { match ->
            val inner = match.groupValues[1].trim()
            val extracted = extractFirstBalancedJsonObject(inner) ?: inner
            if (extracted.startsWith("{") && extracted.endsWith("}")) {
                results.add(extracted)
            }
        }
        // Fallback scanner for unclosed / hallucinated closing tags
        ACTION_OPEN_REGEX.findAll(text).forEach { match ->
            val tail = text.substring(match.range.last + 1)
            val balanced = extractFirstBalancedJsonObject(tail)
            if (!balanced.isNullOrBlank()) {
                results.add(balanced)
            }
        }
        return results.toList()
    }

    fun stripActionTags(text: String): String {
        var cleaned = ACTION_TAG_REGEX.replace(text, "")
        // Strip malformed unclosed `[DEVICE_ACTION]{...}<optional stray chars>[DEVICE_ACTION_RESULT]`
        while (true) {
            val m = ACTION_OPEN_REGEX.find(cleaned) ?: break
            val startIdx = m.range.first
            val afterTag = m.range.last + 1
            val jsonRange = findBalancedJsonRange(cleaned, afterTag)
            val cutEnd = if (jsonRange != null) {
                var endIdx = jsonRange.last + 1
                // Consume any trailing hallucinated junk before/including [DEVICE_ACTION_RESULT] or [/DEVICE_ACTION]
                val nextResult = Regex("""^[^\n]{0,24}\[/?DEVICE_ACTION(?:_RESULT)?]""", RegexOption.IGNORE_CASE)
                    .find(cleaned.substring(endIdx))
                if (nextResult != null) {
                    endIdx += nextResult.range.last + 1
                }
                endIdx
            } else {
                // Unfinished streaming tag at end of buffer
                cleaned.length
            }
            cleaned = cleaned.removeRange(startIdx, cutEnd.coerceAtMost(cleaned.length))
        }
        cleaned = ACTION_RESULT_STRAY_REGEX.replace(cleaned, "")
        return cleaned.replace(Regex("\n{3,}"), "\n\n").trim()
    }

    private fun extractFirstBalancedJsonObject(input: String): String? {
        val range = findBalancedJsonRange(input, 0) ?: return null
        return input.substring(range.first, range.last + 1).trim()
    }

    private fun findBalancedJsonRange(text: String, fromIndex: Int): IntRange? {
        val start = text.indexOf('{', startIndex = fromIndex)
        if (start < 0 || start - fromIndex > 32) return null
        var depth = 0
        var inString = false
        var escaped = false
        for (i in start until text.length) {
            val ch = text[i]
            if (inString) {
                if (escaped) {
                    escaped = false
                } else if (ch == '\\') {
                    escaped = true
                } else if (ch == '"') {
                    inString = false
                }
            } else {
                when (ch) {
                    '"' -> inString = true
                    '{' -> depth++
                    '}' -> {
                        depth--
                        if (depth == 0) return start..i
                    }
                }
            }
        }
        return null
    }

    suspend fun executePayload(
        context: Context,
        rawPayload: String,
        webTools: WebToolsClient? = null,
    ): ActionResult = withContext(Dispatchers.IO) {
        val obj: JsonObject = runCatching {
            json.parseToJsonElement(rawPayload).jsonObject
        }.getOrElse {
            return@withContext ActionResult(
                action = "parse",
                success = false,
                output = "Invalid JSON in [DEVICE_ACTION]: ${it.localizedMessage}",
            )
        }

        val action = obj["action"]?.jsonPrimitive?.content?.trim()?.lowercase().orEmpty()
        when (action) {
            "get_time", "time", "date" -> getTimeAction()
            "get_device_status", "device_status", "battery", "status" -> getDeviceStatusAction(context)
            "open_app", "launch_app" -> {
                val appName = obj["app"]?.jsonPrimitive?.content
                    ?: obj["name"]?.jsonPrimitive?.content
                    ?: obj["package"]?.jsonPrimitive?.content
                    ?: ""
                openAppAction(context, appName)
            }
            "list_apps" -> {
                val query = obj["query"]?.jsonPrimitive?.content.orEmpty()
                listAppsAction(context, query)
            }
            "set_alarm", "alarm" -> {
                val hour = obj["hour"]?.jsonPrimitive?.intOrNull
                val minute = obj["minute"]?.jsonPrimitive?.intOrNull ?: 0
                val label = obj["message"]?.jsonPrimitive?.content
                    ?: obj["label"]?.jsonPrimitive?.content
                    ?: "Cel Alarm"
                setAlarmAction(context, hour, minute, label)
            }
            "set_timer", "timer" -> {
                val seconds = obj["seconds"]?.jsonPrimitive?.intOrNull
                    ?: ((obj["minutes"]?.jsonPrimitive?.intOrNull ?: 0) * 60)
                val label = obj["message"]?.jsonPrimitive?.content
                    ?: obj["label"]?.jsonPrimitive?.content
                    ?: "Cel Timer"
                setTimerAction(context, seconds, label)
            }
            "flashlight", "torch" -> {
                val on = obj["on"]?.jsonPrimitive?.booleanOrNull
                    ?: obj["state"]?.jsonPrimitive?.content?.lowercase()?.let { it == "on" || it == "true" || it == "1" }
                    ?: true
                setFlashlightAction(context, on)
            }
            "set_volume", "volume" -> {
                val stream = obj["stream"]?.jsonPrimitive?.content?.lowercase() ?: "media"
                val percent = obj["percent"]?.jsonPrimitive?.intOrNull
                val mode = obj["mode"]?.jsonPrimitive?.content?.lowercase().orEmpty()
                setVolumeAction(context, stream, percent, mode)
            }
            "open_url", "url" -> {
                val url = obj["url"]?.jsonPrimitive?.content.orEmpty()
                openUrlAction(context, url)
            }
            "dial", "call" -> {
                val number = obj["number"]?.jsonPrimitive?.content
                    ?: obj["phone"]?.jsonPrimitive?.content
                    ?: ""
                dialAction(context, number)
            }
            "web_search", "search" -> {
                val q = obj["query"]?.jsonPrimitive?.content.orEmpty()
                if (q.isBlank()) {
                    ActionResult(action, false, "Missing query for web_search.")
                } else {
                    val tools = webTools ?: WebToolsClient()
                    val res = tools.searchWeb(q)
                    val formatted = res.fold(
                        onSuccess = { list ->
                            if (list.isEmpty()) {
                                "No web results found for \"$q\"."
                            } else {
                                list.mapIndexed { idx, item ->
                                    "${idx + 1}. ${item.title}: ${item.snippet} (${item.url})"
                                }.joinToString("\n")
                            }
                        },
                        onFailure = { "Web search error: ${it.localizedMessage}" },
                    )
                    ActionResult(
                        action = "web_search",
                        success = res.isSuccess,
                        output = formatted.take(2400),
                    )
                }
            }
            else -> ActionResult(
                action = action.ifBlank { "unknown" },
                success = false,
                output = "Unsupported action '$action'. Supported: get_time, get_device_status, open_app, list_apps, set_alarm, set_timer, flashlight, set_volume, open_url, dial, web_search.",
            )
        }
    }

    private fun getTimeAction(): ActionResult {
        val now = Date()
        val tz = TimeZone.getDefault()
        val fmt12 = SimpleDateFormat("EEEE, MMMM d, yyyy 'at' h:mm:ss a", Locale.US).apply { timeZone = tz }
        val fmt24 = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).apply { timeZone = tz }
        return ActionResult(
            action = "get_time",
            success = true,
            output = "Current local time: ${fmt12.format(now)} (${fmt24.format(now)}, ${tz.id}).",
        )
    }

    private fun getDeviceStatusAction(context: Context): ActionResult {
        val appCtx = context.applicationContext
        val batteryIntent = runCatching {
            appCtx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        }.getOrNull()
        val level = batteryIntent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = batteryIntent?.getIntExtra(BatteryManager.EXTRA_SCALE, 100)?.coerceAtLeast(1) ?: 100
        val pct = if (level >= 0) (level * 100) / scale else -1
        val statusInt = batteryIntent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = statusInt == BatteryManager.BATTERY_STATUS_CHARGING || statusInt == BatteryManager.BATTERY_STATUS_FULL

        val audio = appCtx.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        val mediaVol = audio?.let {
            val max = it.getStreamMaxVolume(AudioManager.STREAM_MUSIC).coerceAtLeast(1)
            (it.getStreamVolume(AudioManager.STREAM_MUSIC) * 100) / max
        } ?: -1
        val ringVol = audio?.let {
            val max = it.getStreamMaxVolume(AudioManager.STREAM_RING).coerceAtLeast(1)
            (it.getStreamVolume(AudioManager.STREAM_RING) * 100) / max
        } ?: -1

        val cm = appCtx.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
        val caps = cm?.getNetworkCapabilities(cm.activeNetwork)
        val netDesc = when {
            caps == null -> "Offline"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "Mobile Data"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
            else -> "Connected"
        }

        val batteryStr = if (pct >= 0) "$pct% (${if (charging) "charging" else "not charging"})" else "unknown"
        return ActionResult(
            action = "get_device_status",
            success = true,
            output = "Battery: $batteryStr | Network: $netDesc | Media volume: $mediaVol% | Ring volume: $ringVol% | Device: ${Build.MANUFACTURER} ${Build.MODEL} (Android ${Build.VERSION.RELEASE})",
        )
    }

    private fun queryLauncherApps(context: Context): List<Pair<String, String>> {
        val pm = context.packageManager
        val mainIntent = Intent(Intent.ACTION_MAIN, null).apply {
            addCategory(Intent.CATEGORY_LAUNCHER)
        }
        val activities = runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                pm.queryIntentActivities(mainIntent, PackageManager.ResolveInfoFlags.of(0L))
            } else {
                @Suppress("DEPRECATION")
                pm.queryIntentActivities(mainIntent, 0)
            }
        }.getOrDefault(emptyList())

        return activities.mapNotNull { info ->
            val pkg = info.activityInfo?.packageName ?: return@mapNotNull null
            val label = runCatching { info.loadLabel(pm).toString().trim() }.getOrDefault(pkg)
            label to pkg
        }.distinctBy { it.second }.sortedBy { it.first.lowercase() }
    }

    private fun listAppsAction(context: Context, query: String): ActionResult {
        val all = queryLauncherApps(context)
        val q = query.trim().lowercase()
        val filtered = if (q.isBlank()) all else all.filter {
            it.first.lowercase().contains(q) || it.second.lowercase().contains(q)
        }
        if (filtered.isEmpty()) {
            return ActionResult("list_apps", true, "No installed launcher apps matched '$query'.")
        }
        val listing = filtered.take(40).joinToString(", ") { "${it.first} (${it.second})" }
        return ActionResult("list_apps", true, "Installed apps (${filtered.size}): $listing")
    }

    private suspend fun openAppAction(context: Context, rawQuery: String): ActionResult {
        val query = rawQuery.trim()
        if (query.isBlank()) {
            return ActionResult("open_app", false, "Missing app name or package.")
        }
        val pm = context.packageManager

        // Direct package match first
        val directIntent = pm.getLaunchIntentForPackage(query)
        if (directIntent != null) {
            return launchActivityIntent(context, directIntent, "open_app", "Opened $query.")
        }

        val apps = queryLauncherApps(context)
        val qLow = query.lowercase()
        val best = apps.firstOrNull { it.first.equals(query, ignoreCase = true) }
            ?: apps.firstOrNull { it.first.lowercase().startsWith(qLow) }
            ?: apps.firstOrNull { it.first.lowercase().contains(qLow) }
            ?: apps.firstOrNull { it.second.lowercase().contains(qLow) }

        if (best == null) {
            return ActionResult("open_app", false, "Could not find an installed app matching '$query'.")
        }
        val launchIntent = pm.getLaunchIntentForPackage(best.second)
            ?: return ActionResult("open_app", false, "Found '${best.first}' (${best.second}), but Android returned no launch intent.")
        return launchActivityIntent(context, launchIntent, "open_app", "Opened ${best.first}.")
    }

    private suspend fun setAlarmAction(
        context: Context,
        hour: Int?,
        minute: Int,
        label: String,
    ): ActionResult {
        if (hour == null || hour !in 0..23 || minute !in 0..59) {
            return ActionResult("set_alarm", false, "Invalid alarm time: hour=$hour minute=$minute (use 24h hour 0-23, minute 0-59).")
        }
        val intent = Intent(AlarmClock.ACTION_SET_ALARM).apply {
            putExtra(AlarmClock.EXTRA_HOUR, hour)
            putExtra(AlarmClock.EXTRA_MINUTES, minute)
            putExtra(AlarmClock.EXTRA_MESSAGE, label.ifBlank { "Cel Alarm" })
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val timeText = String.format(Locale.US, "%02d:%02d", hour, minute)
        return launchActivityIntent(context, intent, "set_alarm", "Alarm set for $timeText ($label).")
    }

    private suspend fun setTimerAction(
        context: Context,
        seconds: Int,
        label: String,
    ): ActionResult {
        if (seconds <= 0 || seconds > 86_400) {
            return ActionResult("set_timer", false, "Timer seconds must be between 1 and 86400 (got $seconds).")
        }
        val intent = Intent(AlarmClock.ACTION_SET_TIMER).apply {
            putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            putExtra(AlarmClock.EXTRA_MESSAGE, label.ifBlank { "Cel Timer" })
            putExtra(AlarmClock.EXTRA_SKIP_UI, true)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        val desc = if (seconds >= 60) "${seconds / 60}m ${seconds % 60}s" else "${seconds}s"
        return launchActivityIntent(context, intent, "set_timer", "Timer started for $desc ($label).")
    }

    private fun setFlashlightAction(context: Context, on: Boolean): ActionResult {
        val cm = context.applicationContext.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
            ?: return ActionResult("flashlight", false, "CameraManager unavailable on this device.")
        return runCatching {
            val backFlashId = cm.cameraIdList.firstOrNull { id ->
                val chars = cm.getCameraCharacteristics(id)
                val hasFlash = chars.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
                val facing = chars.get(CameraCharacteristics.LENS_FACING)
                hasFlash && facing == CameraCharacteristics.LENS_FACING_BACK
            } ?: cm.cameraIdList.firstOrNull { id ->
                cm.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            }
            if (backFlashId == null) {
                ActionResult("flashlight", false, "No camera flash/torch found on this device.")
            } else {
                cm.setTorchMode(backFlashId, on)
                ActionResult("flashlight", true, "Flashlight turned ${if (on) "ON" else "OFF"}.")
            }
        }.getOrElse {
            ActionResult("flashlight", false, "Could not toggle flashlight: ${it.localizedMessage}")
        }
    }

    private fun setVolumeAction(
        context: Context,
        stream: String,
        percent: Int?,
        mode: String,
    ): ActionResult {
        val audio = context.applicationContext.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            ?: return ActionResult("set_volume", false, "AudioManager unavailable.")
        val streamType = when (stream) {
            "ring", "ringer" -> AudioManager.STREAM_RING
            "alarm" -> AudioManager.STREAM_ALARM
            "call", "voice" -> AudioManager.STREAM_VOICE_CALL
            else -> AudioManager.STREAM_MUSIC
        }
        return runCatching {
            val max = audio.getStreamMaxVolume(streamType).coerceAtLeast(1)
            val current = audio.getStreamVolume(streamType)
            val target = when {
                mode == "mute" -> 0
                mode == "up" -> (current + (max / 6).coerceAtLeast(1)).coerceAtMost(max)
                mode == "down" -> (current - (max / 6).coerceAtLeast(1)).coerceAtLeast(0)
                percent != null -> ((percent.coerceIn(0, 100) / 100f) * max).toInt().coerceIn(0, max)
                else -> current
            }
            audio.setStreamVolume(streamType, target, AudioManager.FLAG_SHOW_UI)
            val finalPct = (target * 100) / max
            ActionResult("set_volume", true, "Set $stream volume to $finalPct%.")
        }.getOrElse {
            ActionResult("set_volume", false, "Could not change volume: ${it.localizedMessage}")
        }
    }

    private suspend fun openUrlAction(context: Context, rawUrl: String): ActionResult {
        val url = rawUrl.trim()
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return ActionResult("open_url", false, "URL must start with http:// or https://.")
        }
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return launchActivityIntent(context, intent, "open_url", "Opened $url.")
    }

    private suspend fun dialAction(context: Context, rawNumber: String): ActionResult {
        val cleaned = rawNumber.trim().replace(Regex("[^0-9+*#]"), "")
        if (cleaned.isBlank()) {
            return ActionResult("dial", false, "Missing valid phone number to dial.")
        }
        val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:$cleaned")).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return launchActivityIntent(context, intent, "dial", "Opened phone dialer for $cleaned.")
    }

    private suspend fun launchActivityIntent(
        context: Context,
        intent: Intent,
        action: String,
        successMsg: String,
    ): ActionResult = withContext(Dispatchers.Main) {
        runCatching {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.applicationContext.startActivity(intent)
            ActionResult(action, true, successMsg)
        }.getOrElse {
            ActionResult(action, false, "Android could not run $action: ${it.localizedMessage}")
        }
    }
}

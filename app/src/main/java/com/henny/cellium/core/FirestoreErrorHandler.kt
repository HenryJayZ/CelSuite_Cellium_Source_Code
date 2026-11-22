package com.henny.cellium.core

import android.util.Log
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.FirebaseFirestoreException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class OperationType(val value: String) {
    CREATE("create"),
    UPDATE("update"),
    DELETE("delete"),
    LIST("list"),
    GET("get"),
    WRITE("write"),
}

data class DevLogEntry(
    val timestamp: String,
    val level: String,
    val tag: String,
    val message: String,
)

object DevLogBuffer {
    private const val MAX_ENTRIES = 120
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.US)
    private val _entries = MutableStateFlow<List<DevLogEntry>>(emptyList())
    val entries: StateFlow<List<DevLogEntry>> = _entries.asStateFlow()

    fun add(level: String, tag: String, message: String) {
        val entry = DevLogEntry(
            timestamp = fmt.format(Date()),
            level = level,
            tag = tag,
            message = message.take(500),
        )
        val current = _entries.value
        _entries.value = (current + entry).takeLast(MAX_ENTRIES)
    }

    fun clear() {
        _entries.value = emptyList()
    }
}

fun handleFirestoreError(
    exception: Throwable,
    operationType: OperationType,
    path: String?,
): String {
    val causes = generateSequence(exception) { it.cause }
    val rootError = causes.firstOrNull { it is FirebaseFirestoreException }
        ?: causes.firstOrNull { it !is CancellationException }
        ?: exception

    val auth = FirebaseAuth.getInstance()
    val currentUser = auth.currentUser

    val providerInfoList = currentUser?.providerData?.map { provider ->
        JSONObject().apply {
            put("providerId", provider.providerId)
            put("email", provider.email)
        }
    } ?: emptyList()

    val authInfoJson = JSONObject().apply {
        put("userId", currentUser?.uid)
        put("email", currentUser?.email)
        put("emailVerified", currentUser?.isEmailVerified)
        put("tenantId", currentUser?.tenantId)
        put("providerInfo", JSONArray(providerInfoList))
    }

    val errorInfoJson = JSONObject().apply {
        put("error", rootError.message ?: rootError.toString())
        put("operationType", operationType.value)
        put("path", path)
        put("authInfo", authInfoJson)
    }

    val jsonString = errorInfoJson.toString()
    Log.e("FirestoreError", "Firestore Error: $jsonString")
    DevLogBuffer.add("ERROR", "Firestore", "${operationType.value} $path: ${rootError.message}")
    return jsonString
}

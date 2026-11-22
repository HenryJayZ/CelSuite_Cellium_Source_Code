package com.henny.cellium.data

import com.google.firebase.Firebase
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.auth
import com.google.firebase.firestore.DocumentSnapshot
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.FirebaseFirestoreException
import com.google.firebase.firestore.Query
import com.google.firebase.firestore.snapshots
import com.henny.cellium.core.OperationType
import com.henny.cellium.core.handleFirestoreError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.tasks.await

class CelliumRepository(
    private val db: FirebaseFirestore,
    private val auth: FirebaseAuth = Firebase.auth,
) {
    private fun requireUserId(expectedUid: String? = null): String {
        val uid = auth.currentUser?.uid
            ?: throw IllegalStateException("User must be signed in with Google before accessing Firestore.")
        if (expectedUid != null && uid != expectedUid) {
            throw IllegalStateException("Signed-in user changed; refusing cross-user operation.")
        }
        return uid
    }

    private fun userDoc(userId: String) = db.collection("users").document(userId)

    // ── Real-time Observers ──────────────────────────────────────────────

    fun observeSessions(userId: String): Flow<List<ChatSession>> = flow {
        val uid = requireUserId(userId)
        val path = "users/$uid/sessions"
        emitAll(
            userDoc(uid).collection("sessions")
                .orderBy("updatedAt", Query.Direction.DESCENDING)
                .snapshots()
                .map { snap ->
                    snap.toObjects(
                        ChatSession::class.java,
                        DocumentSnapshot.ServerTimestampBehavior.ESTIMATE
                    ).sortedWith(
                        compareByDescending<ChatSession> { it.pinned }
                            .thenByDescending { it.updatedAt?.seconds ?: 0L }
                    )
                }
                .catch { error -> logFlowError(error, uid, path); throw error }
        )
    }

    fun observeMessages(userId: String, sessionId: String): Flow<List<ChatMessage>> = flow {
        val uid = requireUserId(userId)
        require(sessionId.isNotBlank()) { "sessionId must not be blank" }
        val path = "users/$uid/sessions/$sessionId/messages"
        emitAll(
            userDoc(uid).collection("sessions").document(sessionId)
                .collection("messages")
                .orderBy("createdAt", Query.Direction.ASCENDING)
                .snapshots()
                .map { snap ->
                    snap.toObjects(
                        ChatMessage::class.java,
                        DocumentSnapshot.ServerTimestampBehavior.ESTIMATE
                    )
                }
                .catch { error -> logFlowError(error, uid, path); throw error }
        )
    }

    fun observePersonas(userId: String): Flow<List<CustomPersona>> = flow {
        val uid = requireUserId(userId)
        val path = "users/$uid/personas"
        emitAll(
            userDoc(uid).collection("personas")
                .orderBy("createdAt", Query.Direction.DESCENDING)
                .snapshots()
                .map { snap ->
                    snap.toObjects(
                        CustomPersona::class.java,
                        DocumentSnapshot.ServerTimestampBehavior.ESTIMATE
                    )
                }
                .catch { error -> logFlowError(error, uid, path); throw error }
        )
    }

    fun observeMemories(userId: String): Flow<List<MemoryPreset>> = flow {
        val uid = requireUserId(userId)
        val path = "users/$uid/memories"
        emitAll(
            userDoc(uid).collection("memories")
                .orderBy("createdAt", Query.Direction.DESCENDING)
                .snapshots()
                .map { snap ->
                    snap.toObjects(
                        MemoryPreset::class.java,
                        DocumentSnapshot.ServerTimestampBehavior.ESTIMATE
                    )
                }
                .catch { error -> logFlowError(error, uid, path); throw error }
        )
    }

    // ── Session CRUD ─────────────────────────────────────────────────────

    suspend fun createSession(
        userId: String,
        title: String,
        personaId: String,
        modelName: String,
    ): Result<String> {
        var docPath = "users/$userId/sessions"
        return try {
            val uid = requireUserId(userId)
            val safeTitle = title.trim().ifBlank { "New Chat" }.take(120)
            val docRef = userDoc(uid).collection("sessions").document()
            docPath = docRef.path
            val payload = mapOf(
                "userId" to uid,
                "title" to safeTitle,
                "personaId" to personaId.take(80).ifBlank { "default" },
                "modelName" to modelName.take(80).ifBlank { "openai" },
                "pinned" to false,
                "messageCount" to 0L,
                "tokenCount" to 0L,
                "lastMessagePreview" to "",
                "createdAt" to FieldValue.serverTimestamp(),
                "updatedAt" to FieldValue.serverTimestamp(),
            )
            docRef.set(payload).await()
            Result.success(docRef.id)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.CREATE, docPath)
            Result.failure(e)
        }
    }

    suspend fun renameSession(userId: String, sessionId: String, title: String): Result<Unit> {
        val path = "users/$userId/sessions/$sessionId"
        return try {
            val uid = requireUserId(userId)
            val safeTitle = title.trim().ifBlank { "Untitled Chat" }.take(120)
            userDoc(uid).collection("sessions").document(sessionId).update(
                mapOf(
                    "title" to safeTitle,
                    "updatedAt" to FieldValue.serverTimestamp(),
                )
            ).await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.UPDATE, path)
            Result.failure(e)
        }
    }

    suspend fun togglePinSession(userId: String, sessionId: String, pinned: Boolean): Result<Unit> {
        val path = "users/$userId/sessions/$sessionId"
        return try {
            val uid = requireUserId(userId)
            userDoc(uid).collection("sessions").document(sessionId).update(
                mapOf(
                    "pinned" to pinned,
                    "updatedAt" to FieldValue.serverTimestamp(),
                )
            ).await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.UPDATE, path)
            Result.failure(e)
        }
    }

    suspend fun updateSessionConfig(
        userId: String,
        sessionId: String,
        personaId: String,
        modelName: String,
    ): Result<Unit> {
        val path = "users/$userId/sessions/$sessionId"
        return try {
            val uid = requireUserId(userId)
            userDoc(uid).collection("sessions").document(sessionId).update(
                mapOf(
                    "personaId" to personaId.take(80).ifBlank { "default" },
                    "modelName" to modelName.take(80).ifBlank { "openai" },
                    "updatedAt" to FieldValue.serverTimestamp(),
                )
            ).await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.UPDATE, path)
            Result.failure(e)
        }
    }

    suspend fun updateSessionMetrics(
        userId: String,
        sessionId: String,
        newTitle: String?,
        messageCount: Long,
        tokenCount: Long,
        lastMessagePreview: String,
    ): Result<Unit> {
        val path = "users/$userId/sessions/$sessionId"
        return try {
            val uid = requireUserId(userId)
            val updates = mutableMapOf<String, Any>(
                "messageCount" to messageCount.coerceIn(0L, 100000L),
                "tokenCount" to tokenCount.coerceIn(0L, 100000000L),
                "lastMessagePreview" to lastMessagePreview.take(300),
                "updatedAt" to FieldValue.serverTimestamp(),
            )
            if (!newTitle.isNullOrBlank()) {
                updates["title"] = newTitle.trim().take(120)
            }
            userDoc(uid).collection("sessions").document(sessionId).update(updates).await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.UPDATE, path)
            Result.failure(e)
        }
    }

    suspend fun deleteSession(userId: String, sessionId: String): Result<Unit> {
        val path = "users/$userId/sessions/$sessionId"
        return try {
            val uid = requireUserId(userId)
            val sessionRef = userDoc(uid).collection("sessions").document(sessionId)
            // Delete child messages in batches first
            val msgs = sessionRef.collection("messages").limit(200).get().await()
            if (!msgs.isEmpty) {
                val batch = db.batch()
                for (doc in msgs.documents) {
                    batch.delete(doc.reference)
                }
                batch.commit().await()
            }
            sessionRef.delete().await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.DELETE, path)
            Result.failure(e)
        }
    }

    // ── Messages CRUD ────────────────────────────────────────────────────

    suspend fun addMessage(
        userId: String,
        sessionId: String,
        role: String,
        content: String,
        thought: String = "",
        mood: String = "idle",
        modelName: String = "",
        tokenEstimate: Long = 0L,
        latencyMs: Long = 0L,
        hasAttachment: Boolean = false,
    ): Result<String> {
        var docPath = "users/$userId/sessions/$sessionId/messages"
        return try {
            val uid = requireUserId(userId)
            val validRole = if (role == "assistant") "assistant" else "user"
            val docRef = userDoc(uid).collection("sessions").document(sessionId)
                .collection("messages").document()
            docPath = docRef.path
            val payload = mapOf(
                "userId" to uid,
                "sessionId" to sessionId,
                "role" to validRole,
                "content" to content.take(40000),
                "thought" to thought.take(20000),
                "mood" to mood.take(40),
                "modelName" to modelName.take(80),
                "tokenEstimate" to tokenEstimate.coerceIn(0L, 1000000L),
                "latencyMs" to latencyMs.coerceIn(0L, 600000L),
                "hasAttachment" to hasAttachment,
                "createdAt" to FieldValue.serverTimestamp(),
            )
            docRef.set(payload).await()
            Result.success(docRef.id)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.CREATE, docPath)
            Result.failure(e)
        }
    }

    // ── Personas CRUD ────────────────────────────────────────────────────

    suspend fun addCustomPersona(
        userId: String,
        name: String,
        emoji: String,
        tagline: String,
        systemPrompt: String,
        accentHex: String = "#A855F7",
    ): Result<String> {
        var docPath = "users/$userId/personas"
        return try {
            val uid = requireUserId(userId)
            val safeName = name.trim().take(60)
            require(safeName.isNotEmpty()) { "Persona name cannot be empty." }
            val safePrompt = systemPrompt.trim().take(8000)
            require(safePrompt.isNotEmpty()) { "System prompt cannot be empty." }
            val docRef = userDoc(uid).collection("personas").document()
            docPath = docRef.path
            val payload = mapOf(
                "userId" to uid,
                "name" to safeName,
                "emoji" to emoji.trim().ifBlank { "sparkle" }.take(24),
                "tagline" to tagline.trim().take(160),
                "systemPrompt" to safePrompt,
                "accentHex" to accentHex.trim().ifBlank { "#A855F7" }.take(16),
                "createdAt" to FieldValue.serverTimestamp(),
                "updatedAt" to FieldValue.serverTimestamp(),
            )
            docRef.set(payload).await()
            Result.success(docRef.id)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.CREATE, docPath)
            Result.failure(e)
        }
    }

    suspend fun deleteCustomPersona(userId: String, personaId: String): Result<Unit> {
        val path = "users/$userId/personas/$personaId"
        return try {
            val uid = requireUserId(userId)
            userDoc(uid).collection("personas").document(personaId).delete().await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.DELETE, path)
            Result.failure(e)
        }
    }

    // ── Memories CRUD ────────────────────────────────────────────────────

    suspend fun addMemory(userId: String, title: String, content: String): Result<String> {
        var docPath = "users/$userId/memories"
        return try {
            val uid = requireUserId(userId)
            val safeTitle = title.trim().take(80)
            val safeContent = content.trim().take(4000)
            require(safeTitle.isNotEmpty() && safeContent.isNotEmpty()) {
                "Memory title and content are required."
            }
            val docRef = userDoc(uid).collection("memories").document()
            docPath = docRef.path
            val payload = mapOf(
                "userId" to uid,
                "title" to safeTitle,
                "content" to safeContent,
                "enabled" to true,
                "createdAt" to FieldValue.serverTimestamp(),
                "updatedAt" to FieldValue.serverTimestamp(),
            )
            docRef.set(payload).await()
            Result.success(docRef.id)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.CREATE, docPath)
            Result.failure(e)
        }
    }

    suspend fun toggleMemory(userId: String, memoryId: String, enabled: Boolean): Result<Unit> {
        val path = "users/$userId/memories/$memoryId"
        return try {
            val uid = requireUserId(userId)
            userDoc(uid).collection("memories").document(memoryId).update(
                mapOf(
                    "enabled" to enabled,
                    "updatedAt" to FieldValue.serverTimestamp(),
                )
            ).await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.UPDATE, path)
            Result.failure(e)
        }
    }

    suspend fun deleteMemory(userId: String, memoryId: String): Result<Unit> {
        val path = "users/$userId/memories/$memoryId"
        return try {
            val uid = requireUserId(userId)
            userDoc(uid).collection("memories").document(memoryId).delete().await()
            Result.success(Unit)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            handleFirestoreError(e, OperationType.DELETE, path)
            Result.failure(e)
        }
    }

    private fun logFlowError(error: Throwable, uid: String, path: String) {
        val firestoreError = generateSequence(error) { it.cause }
            .filterIsInstance<FirebaseFirestoreException>()
            .firstOrNull()
        if (firestoreError == null && error is CancellationException) return
        val exceptionToLog = firestoreError ?: (error as? Exception)
        if (exceptionToLog != null && auth.currentUser?.uid == uid) {
            handleFirestoreError(exceptionToLog, OperationType.LIST, path)
        }
    }
}

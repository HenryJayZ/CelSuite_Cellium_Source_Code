package com.henny.cellium.ui.chat

import com.henny.cellium.data.local.MessageEntity
import com.henny.cellium.data.local.SessionEntity
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

data class BranchSlotInfo(
    val siblingIds: List<String>,
    val currentIndex: Int,
) {
    val total: Int get() = siblingIds.size
    val hasPrev: Boolean get() = currentIndex > 0
    val hasNext: Boolean get() = currentIndex < siblingIds.lastIndex
    val prevId: String? get() = if (hasPrev) siblingIds[currentIndex - 1] else null
    val nextId: String? get() = if (hasNext) siblingIds[currentIndex + 1] else null
}

data class ActiveBranchView(
    val messages: List<MessageEntity>,
    val branchInfoById: Map<String, BranchSlotInfo>,
    val activeLeafId: String?,
)

/**
 * Resolves tree-based chat branching (PC Cellium parity) from flat Room MessageEntity rows.
 */
object ChatTreeHelper {

    fun buildActivePath(allMessages: List<MessageEntity>, preferredLeafId: String?): ActiveBranchView {
        if (allMessages.isEmpty()) {
            return ActiveBranchView(emptyList(), emptyMap(), null)
        }
        val byId = allMessages.associateBy { it.id }
        val childrenByParent = allMessages.groupBy { it.parentId }

        val targetLeaf = if (!preferredLeafId.isNullOrBlank() && byId.containsKey(preferredLeafId)) {
            descendToLatestLeaf(preferredLeafId, childrenByParent)
        } else {
            // Default to the most recently created message in the session
            allMessages.maxByOrNull { it.createdAtMs }?.id ?: allMessages.last().id
        }

        // Walk up to root
        val reversedPath = mutableListOf<MessageEntity>()
        val visited = mutableSetOf<String>()
        var cursor: String? = targetLeaf
        while (cursor != null && visited.add(cursor)) {
            val node = byId[cursor] ?: break
            reversedPath.add(node)
            cursor = node.parentId
        }
        val path = reversedPath.reversed()

        val branchInfo = mutableMapOf<String, BranchSlotInfo>()
        for (msg in path) {
            val siblings = childrenByParent[msg.parentId]
                ?.sortedBy { it.createdAtMs }
                ?.map { it.id }
                ?: listOf(msg.id)
            if (siblings.size > 1) {
                val idx = siblings.indexOf(msg.id).coerceAtLeast(0)
                branchInfo[msg.id] = BranchSlotInfo(siblings, idx)
            }
        }
        return ActiveBranchView(
            messages = path,
            branchInfoById = branchInfo,
            activeLeafId = path.lastOrNull()?.id,
        )
    }

    /**
     * Strict upward walk from [upToId] to root with ZERO downward descent.
     * Used when building LLM conversation history prior to a user prompt so
     * Retry/Edit NEVER accidentally descends into the target message or its children.
     */
    fun buildAncestorPath(allMessages: List<MessageEntity>, upToId: String?): List<MessageEntity> {
        if (allMessages.isEmpty() || upToId.isNullOrBlank()) return emptyList()
        val byId = allMessages.associateBy { it.id }
        val reversedPath = mutableListOf<MessageEntity>()
        val visited = mutableSetOf<String>()
        var cursor: String? = upToId
        while (cursor != null && visited.add(cursor)) {
            val node = byId[cursor] ?: break
            reversedPath.add(node)
            cursor = node.parentId
        }
        return reversedPath.reversed()
    }

    fun descendToLatestLeaf(
        startId: String,
        childrenByParent: Map<String?, List<MessageEntity>>,
    ): String {
        var current = startId
        val visited = mutableSetOf(current)
        while (true) {
            val children = childrenByParent[current].orEmpty()
            if (children.isEmpty()) return current
            val next = children.maxByOrNull { it.createdAtMs } ?: return current
            if (!visited.add(next.id)) return current
            current = next.id
        }
    }

    fun exportAsMarkdown(session: SessionEntity, messages: List<MessageEntity>): String = buildString {
        appendLine("# ${session.title}")
        appendLine()
        appendLine("- **App:** Cel.Cellium")
        appendLine("- **Persona:** ${session.personaId}")
        appendLine("- **Model:** ${session.modelName.ifBlank { "Multi-Provider" }}")
        appendLine("- **Messages:** ${messages.size}")
        appendLine()
        appendLine("---")
        appendLine()
        for (m in messages) {
            val speaker = when (m.role) {
                "assistant" -> "Cel (${m.modelName.ifBlank { m.providerName.ifBlank { "AI" } }})"
                "tool" -> "Shizuku Shell"
                else -> "You"
            }
            appendLine("### $speaker")
            if (m.thought.isNotBlank()) {
                appendLine("<details><summary>Thought Process</summary>")
                appendLine()
                appendLine(m.thought)
                appendLine("</details>")
                appendLine()
            }
            if (m.toolCommand.isNotBlank()) {
                appendLine("```bash")
                appendLine("$ ${m.toolCommand}")
                appendLine(m.toolOutput)
                appendLine("```")
            }
            appendLine(m.content)
            appendLine()
        }
    }

    fun exportAsJson(session: SessionEntity, messages: List<MessageEntity>): String {
        val obj = buildJsonObject {
            put("app", "Cel.Cellium")
            put("sessionId", session.id)
            put("title", session.title)
            put("personaId", session.personaId)
            put("providerId", session.providerId)
            put("modelName", session.modelName)
            put("exportedAtMs", System.currentTimeMillis())
            put("messages", buildJsonArray {
                messages.forEach { m ->
                    add(buildJsonObject {
                        put("id", m.id)
                        put("parentId", m.parentId ?: "")
                        put("role", m.role)
                        put("content", m.content)
                        put("thought", m.thought)
                        put("toolCommand", m.toolCommand)
                        put("toolOutput", m.toolOutput)
                        put("mood", m.mood)
                        put("providerName", m.providerName)
                        put("modelName", m.modelName)
                        put("tokenEstimate", m.tokenEstimate)
                        put("latencyMs", m.latencyMs)
                        put("createdAtMs", m.createdAtMs)
                    })
                }
            })
        }
        return obj.toString()
    }
}

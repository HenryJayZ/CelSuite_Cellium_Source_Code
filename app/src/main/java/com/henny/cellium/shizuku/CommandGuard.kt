package com.henny.cellium.shizuku

enum class CommandSafetyTier {
    SAFE,
    CAUTION,
    BLOCKED,
}

data class CommandAssessment(
    val command: String,
    val tier: CommandSafetyTier,
    val reason: String,
)

/**
 * Classifies AI Agent shell commands into SAFE (read-only), CAUTION (requires confirmation),
 * or BLOCKED (destructive / bricking patterns), and extracts clean executable commands
 * strictly from assistant response body text (never from reasoning/thought blocks).
 */
object CommandGuard {
    private val BLOCKED_PATTERNS = listOf(
        Regex("""rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(/|/system|/data|/vendor|/sdcard\b|\*)""", RegexOption.IGNORE_CASE),
        Regex("""\b(mkfs|mke2fs|fastboot|flash_image|wipe|format)\b""", RegexOption.IGNORE_CASE),
        Regex("""\bdd\s+.*\bof=/dev/""", RegexOption.IGNORE_CASE),
        Regex("""\breboot\s+(bootloader|recovery|edl|download)\b""", RegexOption.IGNORE_CASE),
        Regex("""\bpm\s+(uninstall|clear)\s+(--user\s+\d+\s+)?(android|com\.android\.systemui|com\.android\.settings)\b""", RegexOption.IGNORE_CASE),
        Regex("""\bchmod\s+-R\s+000\b"""),
        Regex(""":\(\)\s*\{\s*:\|:&\s*\};:"""),
    )

    private val SAFE_PREFIXES = listOf(
        "getprop", "uname", "id", "whoami", "pwd", "date", "uptime", "df", "free", "top -n 1",
        "ls", "stat", "cat /proc/", "cat /sys/", "dumpsys battery", "dumpsys meminfo",
        "dumpsys power", "dumpsys activity", "dumpsys window", "dumpsys connectivity",
        "pm list packages", "pm path", "settings list", "settings get", "wm size", "wm density",
        "ip addr", "ip route", "ps ", "echo ", "du ", "find ",
    )

    private val SHELL_BLOCK_REGEX = Regex(
        """(?:\[SHIZUKU_RUN]([\s\S]*?)\[/SHIZUKU_RUN]|```(?:shizuku|shell_tool)\s*\n([\s\S]*?)```)""",
        RegexOption.IGNORE_CASE,
    )

    private val THOUGHT_STRIP_REGEX = Regex(
        """<(think|thought|thinking|reasoning)\b[^>]*>[\s\S]*?</\1>""",
        RegexOption.IGNORE_CASE,
    )

    fun assess(rawCommand: String): CommandAssessment {
        val cmd = sanitizeCommand(rawCommand)
        if (cmd.isEmpty()) {
            return CommandAssessment(cmd, CommandSafetyTier.BLOCKED, "Empty command.")
        }
        for (pattern in BLOCKED_PATTERNS) {
            if (pattern.containsMatchIn(cmd)) {
                return CommandAssessment(
                    command = cmd,
                    tier = CommandSafetyTier.BLOCKED,
                    reason = "Blocked by Command Guard: matches destructive system pattern.",
                )
            }
        }
        val lower = cmd.lowercase()
        val hasChaining = listOf(";", "&&", "||", "|", ">", "`", "$(").any { it in cmd }
        if (!hasChaining && SAFE_PREFIXES.any { lower == it.trim() || lower.startsWith(it) }) {
            return CommandAssessment(
                command = cmd,
                tier = CommandSafetyTier.SAFE,
                reason = "Read-only diagnostic command.",
            )
        }
        return CommandAssessment(
            command = cmd,
            tier = CommandSafetyTier.CAUTION,
            reason = "Modifies state or chains commands — review before executing.",
        )
    }

    /**
     * Extracts ONLY the first clean shell command from assistant body text (stripping any
     * stray reasoning blocks, markdown fences, or leading shell comments).
     */
    fun extractAgentCommand(assistantBodyOnly: String): String? {
        val bodyWithoutThoughts = assistantBodyOnly.replace(THOUGHT_STRIP_REGEX, "")
        val match = SHELL_BLOCK_REGEX.find(bodyWithoutThoughts) ?: return null
        val raw = match.groupValues[1].ifBlank { match.groupValues[2] }
        val cleaned = sanitizeCommand(raw)
        return cleaned.ifEmpty { null }
    }

    private fun sanitizeCommand(raw: String): String {
        val lines = raw.replace("\r\n", "\n")
            .lines()
            .map { it.trim() }
            .filter { line ->
                line.isNotEmpty() &&
                    !line.startsWith("```") &&
                    !line.startsWith("#") &&
                    !line.equals("[SHIZUKU_RUN]", ignoreCase = true) &&
                    !line.equals("[/SHIZUKU_RUN]", ignoreCase = true)
            }
        return lines.joinToString(" && ").trim()
    }
}

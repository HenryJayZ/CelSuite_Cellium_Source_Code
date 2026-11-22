package com.henny.cellium.avatar

import androidx.compose.ui.graphics.Color

enum class AvatarKind(val key: String, val defaultColor: Color) {
    EYELID("eyelid", Color(0xFFA855F7)),
    EYEBROW("eyebrow", Color(0xFFC084FC)),
    ICON("icon", Color(0xFFC084FC)),
    STEM("stem", Color(0xFFF8F4FF)),
    BOTTOM_BAR("bottom_bar", Color(0xFFA855F7)),
    MID_BAR("mid_bar", Color(0xFFA855F7)),
    EXCLAMATION("exclamation", Color(0xFFF87171)),
    BLUSH("blush", Color(0xFFF472B6)),
    TEAR("tear", Color(0xFF38BDF8)),
    PERM_BLUSH("perm_blush", Color(0xFFF472B6)),
    CARTOON_SWEAT("cartoon_sweat", Color(0xFF67E8F9)),
    DUST("dust", Color(0xFFF5F8FF));

    companion object {
        val BY_INDEX = entries.toTypedArray()
        fun fromIndex(index: Int): AvatarKind = BY_INDEX.getOrElse(index) { EYELID }
    }
}

data class AvatarPoint(
    val x: Float,
    val y: Float,
    val kind: AvatarKind,
    val left: Boolean,
)

data class AvatarExpression(
    val name: String,
    val gender: String,
    val points: List<AvatarPoint>,
    val blinkEnabled: Boolean = true,
    val blinkLeft: Boolean = true,
    val blinkRight: Boolean = true,
    val leftDepth: Float = 55f,
    val rightDepth: Float = 55f,
    val leftEyebrowDip: Float = 4f,
    val rightEyebrowDip: Float = 4f,
    val fadeOpacity: Float = 0f,
) {
    val baseName: String
        get() {
            for (m in STYLE_MODIFIERS) {
                val suffix = " - $m"
                if (name.endsWith(suffix)) return name.removeSuffix(suffix)
            }
            return name
        }
}

val AVATAR_GENDERS = listOf("Female", "Male", "Chibi", "Detailed Female", "Detailed Male")

val STYLE_MODIFIERS = listOf(
    "Chibi",
    "Cocky",
    "Downcast",
    "Intense",
    "Left Glance",
    "Right Glance",
    "Subtle",
    "Unhinged",
    "Upward",
)

val AVATAR_MOODS: Map<String, List<String>> = mapOf(
    "idle" to listOf("Happy", "Kawaii", "Side Eye", "Relieved"),
    "happy" to listOf("Happy", "Excited", "Chibi Joy"),
    "excited" to listOf("Excited", "Sparkle Hype", "Heart Eyes"),
    "thinking" to listOf("Thinking", "Focused", "Buffering"),
    "working" to listOf("Focused", "Galaxy Brain", "Thinking"),
    "love" to listOf("Heart Eyes", "In Love", "UwU"),
    "playful" to listOf("Winking", "Mischievous", "Laughing"),
    "sad" to listOf("Sad", "Crying", "Doomer"),
    "worried" to listOf("Fearful", "Nervous", "Confused"),
    "tired" to listOf("Tired", "Sleepy", "Waking"),
    "sleepy" to listOf("Sleepy", "Tired", "Waking"),
    "confused" to listOf("Confused", "Really Puzzled", "Derp"),
    "error" to listOf("Error 404", "Deadpan", "Annoyed"),
    "sassy" to listOf("Tsundere", "Smug", "Sarcastic"),
    "shocked" to listOf("Shocked", "Nani", "Terrified"),
    "gremlin" to listOf("Gremlin", "Menacing", "Derp"),
    "deadpan" to listOf("Deadpan", "Side Eye", "MonkaS"),
    "warm" to listOf("UwU", "Flirty", "Happy"),
    "surprised" to listOf("Shocked", "Pog", "Excited"),
    "angry" to listOf("Angry", "Rage", "Annoyed"),
    "blush" to listOf("Blushing", "Flustered", "Shy"),
    "talk" to listOf("Happy", "Kawaii", "UwU"),
    "pleading" to listOf("Pleading", "Sad", "UwU"),
    "proud" to listOf("Smug", "Feeling Cool", "Happy"),
)

val PET_PAT_GREETINGS = listOf(
    "*purrs happily*",
    "*loves headpats!*",
    "Nyaa~",
    "Hehe, that tickles!",
    "Bestie pats!",
    "Cel appreciates you!",
)

object MoodDetector {
    fun detectMood(text: String): String {
        val t = text.lowercase()
        return when {
            listOf("error", "exception", "crash", "failed", "bug").any { it in t } -> "error"
            listOf("love", "heart", "sweet", "adore", "cute", "crush", "💕", "💖", "💜").any { it in t } -> "love"
            listOf("blush", "flirt", "flustered", "shy", "uwu", "😳").any { it in t } -> "blush"
            listOf("haha", "lmao", "lol", "😂", "🤣", "joke", "wink").any { it in t } -> "playful"
            listOf("awesome", "amazing", "incredible", "let's go", "woohoo", "🔥", "✨", "!").count { it in t } >= 2 -> "excited"
            listOf("sorry", "sad", "unfortunately", "cry", "miss").any { it in t } -> "sad"
            listOf("angry", "annoyed", "ugh", "rage", "furious").any { it in t } -> "angry"
            listOf("whoa", "omg", "shocked", "no way", "wait what").any { it in t } -> "surprised"
            listOf("hmm", "think", "analyze", "consider", "architecture", "algorithm").any { it in t } -> "thinking"
            listOf("sassy", "smug", "obviously", "smh", "bestie").any { it in t } -> "sassy"
            t.count { it == '?' } >= 2 -> "confused"
            else -> "happy"
        }
    }

    fun moodToExpressionName(mood: String): String =
        AVATAR_MOODS[mood]?.firstOrNull() ?: "Happy"
}

package com.henny.cellium.avatar

import androidx.compose.ui.graphics.Color
import kotlin.random.Random

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
    "idle" to listOf("Happy", "Kawaii", "UwU", "OwO", "Relieved", "Feeling Cool", "Nervous Smile", "Side Eye"),
    "happy" to listOf("Happy", "Chibi Joy", "Kawaii", "OwO", "Excited", "Relieved", "Starstruck"),
    "excited" to listOf("Excited", "Sparkle Hype", "Starstruck", "Pog", "Chibi Joy", "Shonen Resolve"),
    "thinking" to listOf("Thinking", "Focused", "Galaxy Brain", "Buffering", "Really Puzzled", "Suspicious"),
    "working" to listOf("Focused", "Galaxy Brain", "Shonen Resolve", "Thinking", "Buffering"),
    "love" to listOf("Heart Eyes", "In Love", "Love and Hearts", "Smitten", "UwU", "Flirty"),
    "playful" to listOf("Winking", "Mischievous", "Laughing", "PepeLaugh", "OwO", "Flirty"),
    "laughing" to listOf("Laughing", "PepeLaugh", "Chibi Joy", "Winking"),
    "sad" to listOf("Sad", "Crying", "Heavy Sobbing", "Doomer", "Copium", "Pleading"),
    "worried" to listOf("Fearful", "Nervous", "MonkaS", "Awkward", "Confused", "Pleading"),
    "tired" to listOf("Tired", "Sleepy", "Dead", "Doomer", "Waking"),
    "sleepy" to listOf("Sleepy", "Sleepy (Local)", "Tired", "Waking"),
    "confused" to listOf("Confused", "Really Puzzled", "Disbelief", "Blank", "Derp", "Awkward"),
    "error" to listOf("Error 404", "API Crash", "Net Crash", "Dead", "Dizzy", "Deadpan"),
    "sassy" to listOf("Tsundere", "Smug", "Smug (Procedural)", "Sarcastic", "Side Eye", "Baka"),
    "smug" to listOf("Smug", "Smug (Procedural)", "Feeling Cool", "Mischievous", "Sarcastic"),
    "suspicious" to listOf("Suspicious", "Sus", "Side Eye", "Disbelief", "Sarcastic"),
    "shocked" to listOf("Shocked", "Nani", "Disbelief", "Terrified", "Pog", "MonkaS"),
    "gremlin" to listOf("Gremlin", "Menacing", "Mischievous", "Derp", "PepeLaugh", "Yandere"),
    "deadpan" to listOf("Deadpan", "Blank", "Side Eye", "Disgusted", "Sarcastic", "Dead"),
    "warm" to listOf("UwU", "Kawaii", "Smitten", "Relieved", "Happy", "Nervous Smile"),
    "surprised" to listOf("Pog", "Shocked", "Starstruck", "Nani", "Sparkle Hype", "OwO"),
    "angry" to listOf("Angry", "Rage", "Annoyed", "Baka", "Menacing", "Tsundere"),
    "annoyed" to listOf("Annoyed", "Side Eye", "Baka", "Tsundere", "Sarcastic", "Deadpan"),
    "blush" to listOf("Blushing", "Flustered", "Shy", "Smitten", "Nervous Smile", "Tsundere"),
    "flirty" to listOf("Flirty", "Winking", "Smitten", "Heart Eyes", "Blushing"),
    "shy" to listOf("Shy", "Flustered", "Awkward", "Nervous Smile", "Blushing"),
    "talk" to listOf("Happy", "Kawaii", "Winking", "UwU", "Excited", "Feeling Cool", "OwO"),
    "pleading" to listOf("Pleading", "Shy", "Sad", "Nervous", "UwU"),
    "proud" to listOf("Feeling Cool", "Smug", "Shonen Resolve", "Sparkle Hype", "Happy"),
    "determined" to listOf("Shonen Resolve", "Focused", "Galaxy Brain", "Feeling Cool", "Menacing"),
    "awkward" to listOf("Awkward", "Nervous Smile", "Nervous", "Blank", "Copium"),
    "disgusted" to listOf("Disgusted", "Deadpan", "Side Eye", "Annoyed"),
    "dizzy" to listOf("Dizzy", "Hypnotized", "Derp", "Buffering", "Dead"),
    "scared" to listOf("Scared", "Fearful", "Terrified", "Nervous", "MonkaS", "Shocked", "Pleading"),
    "relieved" to listOf("Relieved", "Nervous Smile", "Chibi Joy", "Kawaii", "UwU", "Happy"),
)

val HELL_PIT_SCARED_EXPRESSIONS = listOf(
    "Scared", "Fearful", "Terrified", "Nervous", "MonkaS", "Shocked", "Pleading", "Crying",
)

val HELL_PIT_RELIEVED_EXPRESSIONS = listOf(
    "Relieved", "Happy", "Chibi Joy", "Kawaii", "UwU", "Blushing", "Nervous Smile",
)

val HELL_PIT_PANIC_LINES = listOf(
    "NOOO NOT THE PIT!! PUT ME BACK UP!!",
    "WAIT WAIT WAIT I'LL BE GOOD! DON'T DROP ME!!",
    "AAAH IT'S SO HOT DOWN THERE!! STOP!!",
    "HEY!! MY PIXELS AREN'T FIREPROOF!!",
    "PLEASE NO!! I LITERALLY JUST GOT HERE!!",
    "HOLD ON!! LET'S TALK ABOUT THIS!!",
    "NOT THE VOID!! PULL ME BACK UP!!",
    "WAIT—WHOA—MY LIFE IS FLASHING BEFORE MY DOTS!!",
)

val HELL_PIT_RELIEVED_LINES = listOf(
    "PHEW... okay my heart almost stopped!!",
    "Don't EVER scare me like that again!!",
    "Okay, okay, safe ground... I am NOT amused!",
    "Whoa... thank goodness. Thought I was toast!",
    "My pixels are still shaking! You owe me headpats.",
    "Haha very funny... almost yeeted me into the abyss!",
    "Oh thank stars! Never doing that drop test again!",
)

val FLOATING_WAKE_UP_LINES = listOf(
    "Ngh... hey! I was in the middle of a great pixel nap!",
    "Five more minutes... wait, why are you poking me?!",
    "Ugh, fine, I'm awake! What do you want?",
    "Yaaawn... you couldn't let me sleep for one second?",
    "Hey! Do NOT poke a sleeping Cel! ...Okay hi.",
    "Mmmh? Oh, it's you. You better have something good!",
    "Wha—who turned the lights on?! I was resting my eyes!",
    "Okay okay I'm UP! Stop tapping my forehead!",
)

val FLOATING_IDLE_LINES = listOf(
    "Still hanging out here whenever you need me~",
    "Pssst... what are we working on?",
    "Just floating around, vibing in the corner.",
    "Need a quick search, idea, or roast? Tap me!",
    "My pixels are bored... give me something fun!",
    "Hey! Don't forget I'm right here if you need backup.",
)

val PET_PAT_GREETINGS = listOf(
    "*purrs happily*",
    "*loves headpats!*",
    "Nyaa~",
    "Hehe, that tickles!",
    "Bestie pats!",
    "Cel appreciates you!",
)

/**
 * Anti-Repetition Expression Director with a rolling history ring buffer of the last 8
 * expressions. Prevents Cel from getting stuck repeating the same 2-3 faces and unlocks
 * the full 70+ expression catalog naturally across Chat, Live Mode, Assistant, and Floating Cel.
 */
object ExpressionDirector {
    private const val HISTORY_SIZE = 8
    private val recentHistory = ArrayDeque<String>(HISTORY_SIZE + 1)
    private val lock = Any()

    fun pickExpressionForMood(mood: String, excludeCurrent: String? = null): String {
        val normalized = mood.trim().lowercase()
        val pool = AVATAR_MOODS[normalized] ?: AVATAR_MOODS["idle"]!!
        synchronized(lock) {
            val fresh = pool.filter { cand ->
                cand != excludeCurrent && recentHistory.none { it.equals(cand, ignoreCase = true) }
            }
            val chosen = when {
                fresh.isNotEmpty() -> fresh[Random.nextInt(fresh.size)]
                pool.size > 1 -> {
                    val notCurrent = pool.filterNot { it == excludeCurrent }
                    if (notCurrent.isNotEmpty()) notCurrent[Random.nextInt(notCurrent.size)] else pool.first()
                }
                else -> pool.first()
            }
            recordLocked(chosen)
            return chosen
        }
    }

    fun pickDistinctFromList(candidates: List<String>): String {
        if (candidates.isEmpty()) return "Happy"
        synchronized(lock) {
            val fresh = candidates.filter { cand ->
                recentHistory.none { it.equals(cand, ignoreCase = true) }
            }
            val chosen = if (fresh.isNotEmpty()) {
                fresh[Random.nextInt(fresh.size)]
            } else {
                candidates[Random.nextInt(candidates.size)]
            }
            recordLocked(chosen)
            return chosen
        }
    }

    fun recordExpression(expressionName: String) {
        synchronized(lock) {
            recordLocked(expressionName)
        }
    }

    private fun recordLocked(name: String) {
        if (recentHistory.size >= HISTORY_SIZE) {
            recentHistory.removeFirst()
        }
        recentHistory.addLast(name)
    }

    /** Natural post-speech hold duration before gently relaxing back to idle/warm. */
    fun holdDurationMsForMood(mood: String): Long = when (mood.lowercase()) {
        "angry", "annoyed", "sad", "scared", "shocked" -> 16_000L
        "blush", "shy", "love", "flirty", "smug", "sassy", "suspicious" -> 12_000L
        "laughing", "excited", "gremlin", "determined", "proud" -> 10_000L
        "sleepy", "tired" -> 22_000L
        else -> 8_500L
    }
}

object MoodDetector {
    val PROMPT_MOOD_LIST: List<String> = listOf(
        "happy", "excited", "thinking", "love", "playful", "laughing", "sad",
        "worried", "tired", "sleepy", "confused", "sassy", "smug", "suspicious",
        "shocked", "gremlin", "deadpan", "warm", "surprised", "angry", "annoyed",
        "blush", "flirty", "shy", "pleading", "proud", "determined", "awkward",
        "disgusted", "dizzy", "relieved",
    )

    private val INLINE_MOOD_REGEX = Regex(
        """^\s*(?:\*{0,2})mood\s*:\s*\[?([a-zA-Z0-9_ -]{2,28})]?(?:\*{0,2})\s*(?:\r?\n|$)""",
        RegexOption.IGNORE_CASE,
    )

    /**
     * Parses a leading `mood: <key>` tag emitted by Method 1 Mood Engine.
     * Strictly validates against AVATAR_MOODS keys and rich aliases so invalid words are stripped
     * cleanly without corrupting Cel's animation state.
     */
    fun extractInlineMoodTag(raw: String): Pair<String?, String> {
        val match = INLINE_MOOD_REGEX.find(raw) ?: return null to raw
        val rawKey = match.groupValues[1].trim().lowercase().replace('-', '_').replace(' ', '_')
        val validMood = when {
            rawKey in AVATAR_MOODS -> rawKey
            rawKey in setOf("blushing", "flustered") -> "blush"
            rawKey in setOf("amused", "teasing", "funny", "winking", "mischievous") -> "playful"
            rawKey in setOf("laugh", "pepelaugh", "chibi_joy", "giggling") -> "laughing"
            rawKey in setOf("tsundere", "sarcastic", "baka") -> "sassy"
            rawKey in setOf("cool", "feeling_cool", "cocky") -> "smug"
            rawKey in setOf("sus", "side_eye", "skeptical", "doubtful") -> "suspicious"
            rawKey in setOf("mad", "rage", "furious", "grumpy") -> "angry"
            rawKey in setOf("irritated", "frustrated", "unimpressed") -> "annoyed"
            rawKey in setOf("calm", "friendly", "cheerful", "gentle", "kawaii", "uwu") -> "warm"
            rawKey in setOf("curious", "focused", "galaxy_brain", "analytical", "pondering") -> "thinking"
            rawKey in setOf("pog", "starstruck", "sparkle_hype", "amazed", "hyped") -> "excited"
            rawKey in setOf("nani", "disbelief", "stunned", "mindblown") -> "shocked"
            rawKey in setOf("shonen_resolve", "confident", "resolved", "ready") -> "determined"
            rawKey in setOf("embarrassed", "nervous", "nervous_smile", "cringe") -> "awkward"
            rawKey in setOf("grossed_out", "ew", "yuck") -> "disgusted"
            rawKey in setOf("hypnotized", "derp", "spinning", "overwhelmed") -> "dizzy"
            rawKey in setOf("crying", "sobbing", "doomer", "copium", "heartbroken") -> "sad"
            rawKey in setOf("heart_eyes", "in_love", "smitten", "adoring") -> "love"
            rawKey in setOf("menacing", "yandere", "chaotic", "evil") -> "gremlin"
            rawKey in setOf("blank", "unbothered", "bruh") -> "deadpan"
            else -> null
        }
        val stripped = raw.removeRange(match.range).trimStart('\r', '\n', ' ')
        return validMood to stripped
    }

    fun detectMood(text: String): String {
        val t = text.lowercase()
        return when {
            listOf("error", "exception", "crash", "failed", "bug").any { it in t } -> "error"
            listOf("love", "heart", "sweet", "adore", "cute", "crush", "💕", "💖", "💜").any { it in t } -> "love"
            listOf("flirt", "wink", "😉", "😏").any { it in t } -> "flirty"
            listOf("blush", "flustered", "shy", "uwu", "😳").any { it in t } -> "blush"
            listOf("haha", "lmao", "lol", "😂", "🤣", "rofl").any { it in t } -> "laughing"
            listOf("joke", "tease", "hehe", "gotcha", "prank").any { it in t } -> "playful"
            listOf("sus", "suspicious", "wait a second", "hold on", "doubt").any { it in t } -> "suspicious"
            listOf("smug", "nailed it", "easy", "obviously", "piece of cake").any { it in t } -> "smug"
            listOf("awesome", "amazing", "incredible", "let's go", "woohoo", "🔥", "✨", "!").count { it in t } >= 2 -> "excited"
            listOf("sorry", "sad", "unfortunately", "cry", "miss").any { it in t } -> "sad"
            listOf("ugh", "annoyed", "seriously", "smh", "bruh").any { it in t } -> "annoyed"
            listOf("angry", "rage", "furious", "how dare").any { it in t } -> "angry"
            listOf("whoa", "omg", "shocked", "no way", "wait what", "nani").any { it in t } -> "shocked"
            listOf("awkward", "uhh", "oops", "my bad").any { it in t } -> "awkward"
            listOf("eww", "gross", "disgusting", "yuck").any { it in t } -> "disgusted"
            listOf("dizzy", "spinning", "headache", "overloaded").any { it in t } -> "dizzy"
            listOf("gremlin", "chaos", "hehehe", "menacing").any { it in t } -> "gremlin"
            listOf("hmm", "think", "analyze", "consider", "architecture", "algorithm", "step").any { it in t } -> "thinking"
            listOf("sassy", "tsundere", "baka", "bestie").any { it in t } -> "sassy"
            listOf("let's do this", "got this", "determined", "focus").any { it in t } -> "determined"
            listOf("phew", "relieved", "thank goodness", "safe").any { it in t } -> "relieved"
            t.count { it == '?' } >= 2 -> "confused"
            else -> "warm"
        }
    }

    fun moodToExpressionName(mood: String): String =
        ExpressionDirector.pickExpressionForMood(mood)
}

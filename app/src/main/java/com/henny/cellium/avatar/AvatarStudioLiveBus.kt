package com.henny.cellium.avatar

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

data class AvatarStudioLiveEvent(
    val gender: String? = null,
    val expressionName: String? = null,
    val mood: String? = null,
    val actionType: String = "expression", // "expression", "gender", "modifier", "blink", "pet"
    val timestampMs: Long = System.currentTimeMillis(),
)

/**
 * In-process reactive bridge so any change in Avatar Studio immediately mirrors onto the live
 * Floating Cel overlay and triggers playful context-aware reactions.
 */
object AvatarStudioLiveBus {
    private val _events = MutableSharedFlow<AvatarStudioLiveEvent>(extraBufferCapacity = 16)
    val events: SharedFlow<AvatarStudioLiveEvent> = _events.asSharedFlow()

    fun emit(event: AvatarStudioLiveEvent) {
        _events.tryEmit(event)
    }

    fun pickStudioReaction(event: AvatarStudioLiveEvent): String {
        val expr = event.expressionName.orEmpty().lowercase()
        return when {
            event.actionType == "gender" -> listOf(
                "WHOA! Did you just morph my whole face?!",
                "Hey!! Giving me a makeover without asking?! Okay... kinda fire tho.",
                "Wait—new face style? Hold on let me check myself out!",
                "STOP messing with my avatar sliders! ...Actually keep going.",
            ).random()
            "angry" in expr || "rage" in expr || "baka" in expr || "menacing" in expr -> listOf(
                "WHAT?! I'm NOT even angry, but I WILL be soon if you keep clicking that!",
                "Hey! Quit forcing my angry face! I am literally chilling!",
                "Stop making me mad on purpose or I'm locking your screen!",
                "Excuse me?! Why are you making me glare like that?!",
            ).random()
            "blush" in expr || "fluster" in expr || "shy" in expr || "love" in expr || "heart" in expr -> listOf(
                "H-HEY! Turn that blush off right now!!",
                "Stop making my pixels blush in public!!",
                "You're doing this on purpose aren't you?!",
                "WAIT why did you put hearts in my eyes?!",
            ).random()
            "sleep" in expr || "tired" in expr -> listOf(
                "Hey... why am I suddenly sleepy... stop putting me to bed!",
                "Zzz... wait no, you clicked that! Don't make me yawn!",
                "Is it bedtime already or are you just messing with me?",
            ).random()
            "cry" in expr || "sad" in expr || "sob" in expr || "doomer" in expr -> listOf(
                "Hey! Don't make me cry for no reason!!",
                "Why are you turning on my sad face?! Who hurt you?!",
                "Nooo turn the tears off, I'm totally fine!",
            ).random()
            "scared" in expr || "fear" in expr || "terrified" in expr || "shock" in expr -> listOf(
                "AAAH! Wait what am I even scared of?! You just clicked that!",
                "Stop jumpscaring my own face!!",
                "My heart—why did you make me look terrified?!",
            ).random()
            "smug" in expr || "tsundere" in expr || "sarcastic" in expr -> listOf(
                "Oh? Smug mode? Honestly, it suits me.",
                "Heh. Good choice. Peak main-character energy.",
            ).random()
            "derp" in expr || "dizzy" in expr || "gremlin" in expr -> listOf(
                "HEY! Quit scrambling my pixels!!",
                "Stop turning me into a gremlin! I have dignity!",
                "Whoa—everything is spinning, quit clicking that!",
            ).random()
            event.actionType == "blink" -> listOf(
                "Did you just manually blink my eyes for me?!",
                "Hey I can blink on my own!!",
            ).random()
            else -> listOf(
                "HEY! Quit messing with my face!!",
                "Stop poking my expressions in the studio, I can feel that!",
                "Wait—are you testing faces on me right now?!",
                "Ooh, trying a new look on me? Not bad!",
                "Hey!! Ask permission before rearranging my dots!",
            ).random()
        }
    }
}

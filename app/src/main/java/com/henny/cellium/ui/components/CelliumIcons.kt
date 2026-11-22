package com.henny.cellium.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.AutoFixHigh
import androidx.compose.material.icons.rounded.Bolt
import androidx.compose.material.icons.rounded.Brush
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.Code
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.DataObject
import androidx.compose.material.icons.rounded.Diamond
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Explore
import androidx.compose.material.icons.rounded.Favorite
import androidx.compose.material.icons.rounded.Forum
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Hub
import androidx.compose.material.icons.rounded.Language
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.LocalFireDepartment
import androidx.compose.material.icons.rounded.Memory
import androidx.compose.material.icons.rounded.MusicNote
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.PhoneAndroid
import androidx.compose.material.icons.rounded.Public
import androidx.compose.material.icons.rounded.RocketLaunch
import androidx.compose.material.icons.rounded.Router
import androidx.compose.material.icons.rounded.Science
import androidx.compose.material.icons.rounded.Security
import androidx.compose.material.icons.rounded.SmartToy
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.Star
import androidx.compose.material.icons.rounded.Storage
import androidx.compose.material.icons.rounded.Terminal
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.Verified
import androidx.compose.material.icons.rounded.Waves
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Zero-emoji vector icon registry for Cel.Cellium.
 * Maps icon keys (and any legacy strings from older DB entries) to crisp Material Rounded vector icons.
 */
object CelliumIcons {
    val SELECTABLE_PERSONA_KEYS: List<Pair<String, String>> = listOf(
        "heart" to "Companion",
        "sparkle" to "Ethereal",
        "diamond" to "Luxury",
        "galaxy" to "Cosmos",
        "code" to "Engineer",
        "rocket" to "Velocity",
        "bulb" to "Vision",
        "music" to "Lyric",
        "brain" to "Analyst",
        "science" to "Research",
        "terminal" to "Hacker",
        "palette" to "Artist",
        "shield" to "Guardian",
        "star" to "Creator",
        "bolt" to "Flash",
        "bot" to "Synth",
    )

    fun resolve(key: String?): ImageVector = when (key?.trim()?.lowercase()) {
        "heart", "cel", "companion" -> Icons.Rounded.Favorite
        "sparkle", "celeste", "free", "pollinations", "magic" -> Icons.Rounded.AutoAwesome
        "diamond", "gemini", "google", "celysia", "luxury", "celene" -> Icons.Rounded.Diamond
        "galaxy", "celestia", "cosmos", "public", "globe", "openrouter" -> Icons.Rounded.Public
        "code", "coder", "dev", "deepseek" -> Icons.Rounded.Code
        "rocket", "xai", "grok", "celanova", "launch" -> Icons.Rounded.RocketLaunch
        "bulb", "celumina", "idea", "vision" -> Icons.Rounded.Lightbulb
        "music", "celyra", "audio", "voice" -> Icons.Rounded.MusicNote
        "bolt", "groq", "fast", "flash", "speed" -> Icons.Rounded.Bolt
        "fire", "cerebras", "fireworks", "flame" -> Icons.Rounded.LocalFireDepartment
        "brain", "openai", "reasoning", "think" -> Icons.Rounded.Memory
        "hub", "together", "aggregator", "network" -> Icons.Rounded.Hub
        "cloud", "azure", "aws", "gcp", "vertex", "bedrock" -> Icons.Rounded.Cloud
        "server", "dns", "enterprise", "sambanova", "nvidia" -> Icons.Rounded.Dns
        "router", "lan", "custom", "ollama", "lmstudio", "local" -> Icons.Rounded.Router
        "phone", "on_device", "offline", "gguf", "device" -> Icons.Rounded.PhoneAndroid
        "waves", "mistral", "flow" -> Icons.Rounded.Waves
        "verified", "anthropic", "claude", "trust" -> Icons.Rounded.Verified
        "science", "research", "kaggle", "lab" -> Icons.Rounded.Science
        "terminal", "shizuku", "agent", "shell" -> Icons.Rounded.Terminal
        "palette", "imagine", "art" -> Icons.Rounded.Palette
        "brush", "draw" -> Icons.Rounded.Brush
        "shield", "security", "privacy" -> Icons.Rounded.Security
        "star", "favorite", "pin" -> Icons.Rounded.Star
        "bot", "huggingface", "ai", "model" -> Icons.Rounded.SmartToy
        "language", "regional", "web", "search" -> Icons.Rounded.Language
        "explore", "perplexity", "browse" -> Icons.Rounded.Explore
        "storage", "backup", "db" -> Icons.Rounded.Storage
        "computer", "desktop", "pc" -> Icons.Rounded.Computer
        "forum", "arena", "group" -> Icons.Rounded.Forum
        "wave", "live", "call" -> Icons.Rounded.GraphicEq
        "speed", "turbo" -> Icons.Rounded.Speed
        "json", "data" -> Icons.Rounded.DataObject
        "tune", "settings" -> Icons.Rounded.Tune
        "fix", "wand" -> Icons.Rounded.AutoFixHigh
        else -> Icons.Rounded.AutoAwesome
    }

    fun accentForCategory(category: String): Color = when (category.lowercase()) {
        "free", "keyless" -> Color(0xFF34D399)
        "popular", "frontier" -> Color(0xFFC084FC)
        "fast", "inference" -> Color(0xFFFBBF24)
        "aggregator", "router" -> Color(0xFF38BDF8)
        "regional", "global" -> Color(0xFFF472B6)
        "enterprise", "cloud" -> Color(0xFF818CF8)
        "local", "self-hosted", "offline", "on-device" -> Color(0xFF2DD4BF)
        else -> Color(0xFFA855F7)
    }
}

@Composable
fun VectorBadgeIcon(
    iconKey: String,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    tint: Color = MaterialTheme.colorScheme.primary,
    containerSize: Dp = 28.dp,
    iconSize: Dp = 16.dp,
) {
    Box(
        modifier = modifier
            .size(containerSize)
            .clip(CircleShape)
            .background(tint.copy(alpha = 0.16f))
            .border(0.8.dp, tint.copy(alpha = 0.45f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = CelliumIcons.resolve(iconKey),
            contentDescription = contentDescription,
            tint = tint,
            modifier = Modifier.size(iconSize),
        )
    }
}

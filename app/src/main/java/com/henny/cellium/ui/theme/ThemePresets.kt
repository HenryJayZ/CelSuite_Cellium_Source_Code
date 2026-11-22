package com.henny.cellium.ui.theme

import androidx.compose.ui.graphics.Color

data class CelliumThemePreset(
    val id: String,
    val name: String,
    val primary: Color,
    val secondary: Color,
    val tertiary: Color,
    val voidBg: Color,
    val surfaceBg: Color,
    val previewHex: String,
)

object CelliumThemePresets {
    val ALL: List<CelliumThemePreset> = listOf(
        CelliumThemePreset(
            id = "neon_violet",
            name = "Neon Violet",
            primary = CelViolet,
            secondary = CelMagenta,
            tertiary = CelCyanTear,
            voidBg = Color(0xFF0A0614),
            surfaceBg = Color(0xFF140D26),
            previewHex = "#A855F7",
        ),
        CelliumThemePreset(
            id = "cyber_cyan",
            name = "Cyber Cyan",
            primary = Color(0xFF06B6D4),
            secondary = Color(0xFF38BDF8),
            tertiary = Color(0xFF818CF8),
            voidBg = Color(0xFF040D16),
            surfaceBg = Color(0xFF0B1C2C),
            previewHex = "#06B6D4",
        ),
        CelliumThemePreset(
            id = "sakura_rose",
            name = "Sakura Glass",
            primary = Color(0xFFEC4899),
            secondary = Color(0xFFF472B6),
            tertiary = Color(0xFFC084FC),
            voidBg = Color(0xFF140610),
            surfaceBg = Color(0xFF250D1E),
            previewHex = "#EC4899",
        ),
        CelliumThemePreset(
            id = "emerald_matrix",
            name = "Emerald Matrix",
            primary = Color(0xFF10B981),
            secondary = Color(0xFF34D399),
            tertiary = Color(0xFF22D3EE),
            voidBg = Color(0xFF04120D),
            surfaceBg = Color(0xFF0A221A),
            previewHex = "#10B981",
        ),
        CelliumThemePreset(
            id = "solar_amber",
            name = "Solar Amber",
            primary = Color(0xFFF59E0B),
            secondary = Color(0xFFFB7185),
            tertiary = Color(0xFFFDE047),
            voidBg = Color(0xFF140D05),
            surfaceBg = Color(0xFF241709),
            previewHex = "#F59E0B",
        ),
        CelliumThemePreset(
            id = "oled_midnight",
            name = "OLED Midnight",
            primary = Color(0xFF8B5CF6),
            secondary = Color(0xFFE879F9),
            tertiary = Color(0xFF60A5FA),
            voidBg = Color(0xFF000000),
            surfaceBg = Color(0xFF0C0A14),
            previewHex = "#8B5CF6",
        ),
    )

    fun byId(id: String): CelliumThemePreset =
        ALL.firstOrNull { it.id == id } ?: ALL.first()

    fun parseHexColor(hex: String, fallback: Color = CelViolet): Color {
        val cleaned = hex.trim().removePrefix("#")
        if (cleaned.length != 6 && cleaned.length != 8) return fallback
        return runCatching {
            val value = cleaned.toLong(16)
            if (cleaned.length == 6) Color((0xFF000000L or value).toInt())
            else Color(value.toInt())
        }.getOrDefault(fallback)
    }
}

package com.henny.cellium.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.henny.cellium.core.CelliumPreferences

data class CelliumVisuals(
    val primary: Color = CelViolet,
    val secondary: Color = CelMagenta,
    val tertiary: Color = CelCyanTear,
    val voidBg: Color = CelVoid,
    val surfaceBg: Color = CelDeepSpace,
    val glassOpacity: Float = 0.84f,
    val borderGlow: Float = 0.65f,
    val wallpaperDim: Float = 0.48f,
    val customWallpaperUri: String = "",
    val particlesEnabled: Boolean = true,
    val particleDensity: Int = 24,
    val highFpsMode: Boolean = true,
    val fontScale: Float = 1.0f,
) {
    val glassSurface: Color = surfaceBg.copy(alpha = glassOpacity.coerceIn(0.35f, 0.96f))
    val activeBorder: Color = primary.copy(alpha = (0.35f + borderGlow * 0.55f).coerceIn(0.25f, 0.95f))
    val subtleBorder: Color = primary.copy(alpha = (0.12f + borderGlow * 0.22f).coerceIn(0.10f, 0.42f))
}

val LocalCelliumVisuals = staticCompositionLocalOf { CelliumVisuals() }

val CelliumShapes = Shapes(
    small = RoundedCornerShape(10.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(22.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

@Composable
fun CelliumTheme(
    prefs: CelliumPreferences = CelliumPreferences(),
    content: @Composable () -> Unit,
) {
    val visuals = remember(
        prefs.themePresetId,
        prefs.customPrimaryHex,
        prefs.glassOpacity,
        prefs.borderGlow,
        prefs.wallpaperDim,
        prefs.customWallpaperUri,
        prefs.particlesEnabled,
        prefs.particleDensity,
        prefs.highFpsMode,
        prefs.fontScale,
    ) {
        val preset = CelliumThemePresets.byId(prefs.themePresetId)
        val primaryColor = if (prefs.themePresetId == "custom") {
            CelliumThemePresets.parseHexColor(prefs.customPrimaryHex, CelViolet)
        } else {
            preset.primary
        }
        CelliumVisuals(
            primary = primaryColor,
            secondary = preset.secondary,
            tertiary = preset.tertiary,
            voidBg = preset.voidBg,
            surfaceBg = preset.surfaceBg,
            glassOpacity = prefs.glassOpacity,
            borderGlow = prefs.borderGlow,
            wallpaperDim = prefs.wallpaperDim,
            customWallpaperUri = prefs.customWallpaperUri,
            particlesEnabled = prefs.particlesEnabled,
            particleDensity = prefs.particleDensity,
            highFpsMode = prefs.highFpsMode,
            fontScale = prefs.fontScale,
        )
    }

    val scheme = remember(visuals) {
        darkColorScheme(
            primary = visuals.primary,
            onPrimary = Color.White,
            primaryContainer = visuals.primary.copy(alpha = 0.28f),
            onPrimaryContainer = CelSoftLavender,
            secondary = visuals.secondary,
            onSecondary = Color(0xFF1F0930),
            secondaryContainer = visuals.secondary.copy(alpha = 0.24f),
            onSecondaryContainer = Color(0xFFFBD5FF),
            tertiary = visuals.tertiary,
            onTertiary = Color(0xFF042235),
            tertiaryContainer = visuals.tertiary.copy(alpha = 0.24f),
            onTertiaryContainer = Color(0xFFBAE6FD),
            background = visuals.voidBg,
            onBackground = CelTextPrimary,
            surface = visuals.surfaceBg,
            onSurface = CelTextPrimary,
            surfaceVariant = Color(0xFF21173C),
            onSurfaceVariant = CelTextSecondary,
            outline = visuals.activeBorder,
            outlineVariant = visuals.subtleBorder,
            error = CelDangerRed,
            onError = Color(0xFF2E0707),
            errorContainer = Color(0xFF4C1419),
            onErrorContainer = Color(0xFFFECACA),
        )
    }

    CompositionLocalProvider(LocalCelliumVisuals provides visuals) {
        MaterialTheme(
            colorScheme = scheme,
            typography = CelliumTypography,
            shapes = CelliumShapes,
            content = content,
        )
    }
}

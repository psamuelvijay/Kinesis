package com.kinesis.ui.shared.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/** Spacing scale and minimum touch target. */
object Spacing {
    val xs = 4.dp
    val sm = 8.dp
    val md = 16.dp
    val lg = 24.dp
    val minTouch = 48.dp
    val cardRadius = 16.dp
}

/** Status colours that Material 3 does not provide. Never the only carrier of meaning. */
@Immutable
data class StatusColors(val amber: Color, val red: Color)

private val LightStatus = StatusColors(amber = Color(0xFF8A5A00), red = Color(0xFFB3261E))
private val DarkStatus = StatusColors(amber = Color(0xFFFFB84D), red = Color(0xFFFFB4AB))

private val LocalStatusColors = staticCompositionLocalOf { LightStatus }

private val LightColors = lightColorScheme(
    primary = Color(0xFF2563A6),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFD3E4FF),
    onPrimaryContainer = Color(0xFF001C3B),
    secondaryContainer = Color(0xFFD3E4FF),
    onSecondaryContainer = Color(0xFF001C3B),
    background = Color(0xFFF8F9FC),
    onBackground = Color(0xFF191C20),
    surface = Color(0xFFF8F9FC),
    onSurface = Color(0xFF191C20),
    surfaceVariant = Color(0xFFDFE2EB),
    onSurfaceVariant = Color(0xFF43474E),
    surfaceContainer = Color(0xFFECEEF3),
    outline = Color(0xFF73777F),
    outlineVariant = Color(0xFFC3C6CF),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFA4C8FF),
    onPrimary = Color(0xFF00315C),
    primaryContainer = Color(0xFF00497F),
    onPrimaryContainer = Color(0xFFD3E4FF),
    secondaryContainer = Color(0xFF00497F),
    onSecondaryContainer = Color(0xFFD3E4FF),
    background = Color(0xFF111418),
    onBackground = Color(0xFFE1E2E8),
    surface = Color(0xFF111418),
    onSurface = Color(0xFFE1E2E8),
    surfaceVariant = Color(0xFF43474E),
    onSurfaceVariant = Color(0xFFC3C6CF),
    surfaceContainer = Color(0xFF1D2024),
    outline = Color(0xFF8D9199),
    outlineVariant = Color(0xFF43474E),
)

private val KinesisShapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(Spacing.cardRadius),
    large = RoundedCornerShape(Spacing.cardRadius),
)

val MaterialTheme.statusColors: StatusColors
    @Composable @ReadOnlyComposable get() = LocalStatusColors.current

/** Static colours only: dynamic colour would make the two apps look different per device. */
@Composable
fun KinesisTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalStatusColors provides if (darkTheme) DarkStatus else LightStatus) {
        MaterialTheme(
            colorScheme = if (darkTheme) DarkColors else LightColors,
            shapes = KinesisShapes,
            content = content,
        )
    }
}

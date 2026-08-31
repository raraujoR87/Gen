package com.arbitrage.engine.presentation.theme

import android.app.Activity
import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val DarkColors = darkColorScheme(
    primary = AccentBlue,
    onPrimary = OnBackgroundDark,
    secondary = ProfitGreen,
    onSecondary = BackgroundDark,
    error = LossRed,
    onError = OnBackgroundDark,
    background = BackgroundDark,
    onBackground = OnBackgroundDark,
    surface = SurfaceDark,
    onSurface = OnBackgroundDark,
    surfaceVariant = CardDark,
    onSurfaceVariant = OnSurfaceVariantDark,
    outline = OutlineDark
)

private val LightColors = lightColorScheme(
    primary = AccentBlueVariant,
    onPrimary = SurfaceLight,
    secondary = ProfitGreen,
    onSecondary = SurfaceLight,
    error = LossRed,
    onError = SurfaceLight,
    background = BackgroundLight,
    onBackground = OnBackgroundLight,
    surface = SurfaceLight,
    onSurface = OnBackgroundLight,
    surfaceVariant = CardLight,
    onSurfaceVariant = OnSurfaceVariantLight,
    outline = OutlineLight
)

/**
 * App-wide Material3 theme. Dark-first: the trading dashboard is designed to be
 * read at a glance in low-light conditions, so [darkTheme] defaults to true
 * unless the caller overrides it (e.g. to follow the system setting instead).
 *
 * [dynamicColor] opts into Android 12+ wallpaper-derived color when available;
 * it is off by default so the P&L green/red semantics stay consistent across
 * devices.
 */
@Composable
fun ArbitrageEngineTheme(
    darkTheme: Boolean = true,
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }

    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? Activity)?.window ?: return@SideEffect
            window.statusBarColor = colorScheme.background.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = ArbitrageTypography,
        content = content
    )
}

/** True when the effective color scheme should be treated as dark for custom (non-M3) styling. */
@Composable
fun isArbitrageDarkTheme(): Boolean = isSystemInDarkTheme()

/** Semantic color for a P&L / spread value: green when >= 0, red when negative. */
@Composable
fun pnlColor(value: Double) = if (value >= 0.0) ProfitGreen else LossRed

package com.arbitrage.engine.presentation.theme

import androidx.compose.ui.graphics.Color

// Base surfaces — dark-first palette per ARCHITECTURE.md section 8.
val BackgroundDark = Color(0xFF121212)
val SurfaceDark = Color(0xFF1E1E1E)
val CardDark = Color(0xFF2A2A2A)
val CardDarkElevated = Color(0xFF333333)
val OutlineDark = Color(0xFF3D3D3D)

val OnBackgroundDark = Color(0xFFECECEC)
val OnSurfaceVariantDark = Color(0xFFA0A0A0)

// Brand / primary accent — used for interactive controls (switches, buttons, links).
val AccentBlue = Color(0xFF3D8BFF)
val AccentBlueVariant = Color(0xFF2563EB)

// Semantic P&L colors.
val ProfitGreen = Color(0xFF00E676)
val LossRed = Color(0xFFFF5252)
val WarningAmber = Color(0xFFFFB74D)

// Light theme (secondary — the app is dark-first, but a light palette is provided
// so the theme respects the system setting instead of forcing dark everywhere).
val BackgroundLight = Color(0xFFF7F7F8)
val SurfaceLight = Color(0xFFFFFFFF)
val CardLight = Color(0xFFF0F0F2)
val OutlineLight = Color(0xFFD8D8DC)
val OnBackgroundLight = Color(0xFF1A1A1A)
val OnSurfaceVariantLight = Color(0xFF5C5C63)

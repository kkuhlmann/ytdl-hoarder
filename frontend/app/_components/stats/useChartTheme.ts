"use client"

import { useMemo } from "react"
import type { CSSProperties } from "react"
import { useThemeColors } from "@/app/_hooks/useThemeColors"

export interface ChartColors {
  matrix: string
  matrixDim: string
  blue: string
  purple: string
  orange: string
  red: string
  surface: string
  elevated: string
  text: string
  textMuted: string
}

export interface ChartTooltipStyle {
  contentStyle: CSSProperties
  labelStyle: CSSProperties
  itemStyle: CSSProperties
  cursor: { fill: string; fillOpacity: number }
}

export interface ChartTheme {
  colors: ChartColors
  tooltipStyle: ChartTooltipStyle
}

// Theme-aware chart colors (Recharts renders SVG attributes that don't
// resolve CSS var(); read concrete values and re-read on theme change).
export function useChartTheme(): ChartTheme {
  const themeColors = useThemeColors({
    matrix: "--matrix-green",
    matrixDim: "--matrix-dim",
    blue: "--status-info",
    purple: "--status-queued",
    orange: "--status-warning",
    red: "--status-error",
    surface: "--bg-surface",
    elevated: "--bg-elevated",
    text: "--text-primary",
    textMuted: "--text-muted",
  })
  const colors = useMemo<ChartColors>(
    () => ({
      matrix: themeColors.matrix || "#00ff41",
      matrixDim: themeColors.matrixDim || "#00b32d",
      blue: themeColors.blue || "#58a6ff",
      purple: themeColors.purple || "#bc8cff",
      orange: themeColors.orange || "#d29922",
      red: themeColors.red || "#f85149",
      surface: themeColors.surface || "#161b22",
      elevated: themeColors.elevated || "#21262d",
      text: themeColors.text || "#c9d1d9",
      textMuted: themeColors.textMuted || "#adb8c4",
    }),
    [themeColors],
  )
  const tooltipStyle = useMemo<ChartTooltipStyle>(
    () => ({
      contentStyle: {
        backgroundColor: colors.elevated,
        border: `1px solid ${colors.matrixDim}`,
        borderRadius: "6px",
        fontSize: "12px",
        fontFamily: "monospace",
      },
      labelStyle: { color: colors.text },
      itemStyle: { color: colors.text },
      cursor: { fill: colors.matrix, fillOpacity: 0.08 },
    }),
    [colors],
  )
  return { colors, tooltipStyle }
}

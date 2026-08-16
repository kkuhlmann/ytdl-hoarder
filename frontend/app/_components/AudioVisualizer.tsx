"use client"

import { useEffect, useRef, type RefObject } from "react"
import { useThemeColors } from "@/app/_hooks/useThemeColors"
import { cn } from "@/lib/utils"
import type { AudioAnalyserHandle } from "@/app/_hooks/useAudioAnalyser"

export type VisualizerStyle = "bars" | "area"

interface AudioVisualizerProps {
  /** Shared handle populated by the AudioPlayer; read every frame. */
  analyserRef: RefObject<AudioAnalyserHandle | null>
  /** Whether the visualizer feature is on. When false the rAF loop is idle. */
  enabled: boolean
  /** Which renderer to draw. Read via a ref so switching never restarts rAF. */
  style: VisualizerStyle
  className?: string
}

// Shared: translucency + fast-attack / slow-release smoothing, and the vertical
// alpha fade (transparent base -> opaque tip) so shapes melt away at the bottom.
const ALPHA = 0.13
const ATTACK = 0.5 // rise rate toward a higher level
const RELEASE = 0.12 // fall rate (slower = smoother)
const FADE_BASE_ALPHA = 0
const FADE_TIP_ALPHA = 1

const BAR_COUNT = 112
const GAP = 1
const MIN_WIDTH = 2

// Area / mountain: one smooth filled curve with a faint crest line. Kept about
// as translucent as the bars (ALPHA) so it reads as a subtle backdrop.
const AREA_POINTS = 64
const AREA_ALPHA = 0.1
const AREA_RIDGE_ALPHA = 0.25
const AREA_RIDGE_WIDTH = 2
const AREA_GLOW = 6

/** Parse a hex or rgb()/rgba() color string to [r, g, b], or null. */
function parseRgb(color: string): [number, number, number] | null {
  const c = color.trim()
  const hex = c.match(/^#?([0-9a-f]{3}|[0-9a-f]{6})$/i)
  if (hex) {
    let h = hex[1]
    if (h.length === 3) h = h.split("").map((x) => x + x).join("")
    const n = parseInt(h, 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  }
  const rgb = c.match(/rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i)
  if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]
  return null
}

/**
 * Canvas visualizer for the audio player. Presentational: reads bars/levels off
 * the shared analyser handle each animation frame and paints them in the active
 * theme's accent colors (re-read live on theme switch via useThemeColors). Draws
 * nothing meaningful while the audio is paused / the feature is off.
 */
export function AudioVisualizer({
  analyserRef,
  enabled,
  style,
  className,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const styleRef = useRef(style)
  styleRef.current = style

  // Concrete theme colors for the canvas (can't use the CSS cascade here).
  const colors = useThemeColors({ bar: "--matrix-green", barDim: "--matrix-dim" })
  const colorsRef = useRef(colors)
  colorsRef.current = colors

  useEffect(() => {
    if (!enabled) return
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const reduceMotion = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches

    let width = 0
    let height = 0
    const setSize = () => {
      const dpr = window.devicePixelRatio || 1
      const rect = canvas.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = Math.max(1, Math.round(width * dpr))
      canvas.height = Math.max(1, Math.round(height * dpr))
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    setSize()
    const resizeObserver = new ResizeObserver(setSize)
    resizeObserver.observe(canvas)

    const freqBars = new Uint8Array(BAR_COUNT)
    const heightsBars = new Float32Array(BAR_COUNT) // smoothed 0..1
    const freqArea = new Uint8Array(AREA_POINTS)
    const heightsArea = new Float32Array(AREA_POINTS)
    const ptsX = new Float32Array(AREA_POINTS)
    const ptsY = new Float32Array(AREA_POINTS)

    // Ease heights[i] toward freq[i]/255 (fast up, slow down) so a steady tone
    // settles instead of strobing frame-to-frame.
    const ease = (heights: Float32Array, freq: Uint8Array, i: number) => {
      const target = freq[i] / 255
      if (reduceMotion) {
        heights[i] = target
      } else {
        const rate = target > heights[i] ? ATTACK : RELEASE
        heights[i] += (target - heights[i]) * rate
      }
    }

    const themeColors = () => {
      const [br, bg, bb] = parseRgb(colorsRef.current.bar) ?? [0, 255, 65]
      const [dr, dg, db] = parseRgb(colorsRef.current.barDim) ?? [0, 179, 45]
      return {
        tip: `rgba(${br}, ${bg}, ${bb}, ${FADE_TIP_ALPHA})`,
        base: `rgba(${dr}, ${dg}, ${db}, ${FADE_BASE_ALPHA})`,
        accent: `rgb(${br}, ${bg}, ${bb})`,
      }
    }

    const drawBars = () => {
      const analyser = analyserRef.current
      const active = !!analyser && analyser.isActive()
      if (active) analyser!.getBars(freqBars)
      else freqBars.fill(0)

      const totalGap = GAP * (BAR_COUNT - 1)
      const barWidth = Math.max(MIN_WIDTH, (width - totalGap) / BAR_COUNT)
      const step = barWidth + GAP
      const { tip, base } = themeColors()

      ctx.globalAlpha = ALPHA
      for (let i = 0; i < BAR_COUNT; i++) {
        ease(heightsBars, freqBars, i)
        const h = heightsBars[i] * height
        const x = i * step
        const y = height - h
        const grad = ctx.createLinearGradient(0, height, 0, y)
        grad.addColorStop(0, base)
        grad.addColorStop(1, tip)
        ctx.fillStyle = grad
        ctx.fillRect(x, y, barWidth, h)
      }
      ctx.globalAlpha = 1
    }

    const drawArea = () => {
      const analyser = analyserRef.current
      const active = !!analyser && analyser.isActive()
      if (active) analyser!.getBars(freqArea)
      else freqArea.fill(0)

      const N = AREA_POINTS
      for (let i = 0; i < N; i++) {
        ease(heightsArea, freqArea, i)
        ptsX[i] = (i / (N - 1)) * width
        ptsY[i] = height - heightsArea[i] * height
      }

      const { tip, base, accent } = themeColors()

      // Smooth ridge: quadratic curves through the midpoints of adjacent points.
      const ridge = new Path2D()
      ridge.moveTo(ptsX[0], ptsY[0])
      let i = 1
      for (; i < N - 2; i++) {
        const xc = (ptsX[i] + ptsX[i + 1]) / 2
        const yc = (ptsY[i] + ptsY[i + 1]) / 2
        ridge.quadraticCurveTo(ptsX[i], ptsY[i], xc, yc)
      }
      ridge.quadraticCurveTo(ptsX[i], ptsY[i], ptsX[i + 1], ptsY[i + 1])

      // Fill the area under the ridge with the base->tip vertical gradient.
      const fill = new Path2D(ridge)
      fill.lineTo(width, height)
      fill.lineTo(0, height)
      fill.closePath()
      const grad = ctx.createLinearGradient(0, height, 0, 0)
      grad.addColorStop(0, base)
      grad.addColorStop(1, tip)
      ctx.globalAlpha = AREA_ALPHA
      ctx.fillStyle = grad
      ctx.fill(fill)

      // Bright glowing crest line for definition.
      ctx.globalAlpha = AREA_RIDGE_ALPHA
      ctx.lineWidth = AREA_RIDGE_WIDTH
      ctx.lineJoin = "round"
      ctx.lineCap = "round"
      ctx.strokeStyle = accent
      ctx.shadowBlur = AREA_GLOW
      ctx.shadowColor = accent
      ctx.stroke(ridge)

      ctx.shadowBlur = 0
      ctx.globalAlpha = 1
    }

    let raf = 0
    const draw = () => {
      raf = requestAnimationFrame(draw)
      ctx.clearRect(0, 0, width, height)
      if (styleRef.current === "area") drawArea()
      else drawBars()
    }
    raf = requestAnimationFrame(draw)

    return () => {
      cancelAnimationFrame(raf)
      resizeObserver.disconnect()
    }
  }, [enabled, analyserRef])

  if (!enabled) return null

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={cn("h-full w-full", className)}
    />
  )
}

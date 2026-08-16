"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

interface RangeSliderProps {
  startValue: number
  endValue: number
  onStartChange: (value: number) => void
  onEndChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  className?: string
  disabled?: boolean
  // Viewport props for zoomed view
  viewMin?: number // Viewport start (undefined = use min)
  viewMax?: number // Viewport end (undefined = use max)
}

const RangeSlider = React.forwardRef<HTMLDivElement, RangeSliderProps>(
  (
    {
      startValue,
      endValue,
      onStartChange,
      onEndChange,
      min = 0,
      max = 100,
      step = 0.1,
      className,
      disabled,
      viewMin,
      viewMax,
    },
    ref
  ) => {
    const trackRef = React.useRef<HTMLDivElement>(null)
    const [dragging, setDragging] = React.useState<"start" | "end" | null>(null)

    // Use viewport bounds if provided, otherwise use full range
    const displayMin = viewMin ?? min
    const displayMax = viewMax ?? max
    const displayRange = displayMax - displayMin

    // Calculate percentages relative to viewport
    // Clamp to 0-100% when handle is outside viewport
    const startPercent = displayRange > 0
      ? Math.max(0, Math.min(100, ((startValue - displayMin) / displayRange) * 100))
      : 0
    const endPercent = displayRange > 0
      ? Math.max(0, Math.min(100, ((endValue - displayMin) / displayRange) * 100))
      : 100

    const getValueFromPosition = React.useCallback(
      (clientX: number): number => {
        if (!trackRef.current) return min
        const rect = trackRef.current.getBoundingClientRect()
        const percent = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
        // Map percent to viewport range, then clamp to full range
        const rawValue = displayMin + percent * displayRange
        // Round to step precision
        const stepped = Math.round(rawValue / step) * step
        return Math.max(min, Math.min(max, stepped))
      },
      [min, max, displayMin, displayRange, step]
    )

    const handleMouseDown = React.useCallback(
      (handle: "start" | "end") => (e: React.MouseEvent) => {
        if (disabled) return
        e.preventDefault()
        setDragging(handle)
      },
      [disabled]
    )

    // Holds the 1-second minimum gap, and keeps a degenerate range from pushing a
    // handle off the track: with max === 0 the gap alone would emit -1 for start.
    const commitDrag = React.useCallback(
      (handle: "start" | "end", newValue: number) => {
        if (handle === "start") {
          onStartChange(Math.max(min, Math.min(newValue, endValue - 1)))
        } else {
          onEndChange(Math.min(max, Math.max(newValue, startValue + 1)))
        }
      },
      [min, max, startValue, endValue, onStartChange, onEndChange]
    )

    const handleMouseMove = React.useCallback(
      (e: MouseEvent) => {
        if (!dragging) return
        commitDrag(dragging, getValueFromPosition(e.clientX))
      },
      [dragging, getValueFromPosition, commitDrag]
    )

    const handleMouseUp = React.useCallback(() => {
      setDragging(null)
    }, [])

    React.useEffect(() => {
      if (dragging) {
        window.addEventListener("mousemove", handleMouseMove)
        window.addEventListener("mouseup", handleMouseUp)
        return () => {
          window.removeEventListener("mousemove", handleMouseMove)
          window.removeEventListener("mouseup", handleMouseUp)
        }
      }
    }, [dragging, handleMouseMove, handleMouseUp])

    // Touch support
    const handleTouchStart = React.useCallback(
      (handle: "start" | "end") => (e: React.TouchEvent) => {
        if (disabled) return
        e.preventDefault()
        setDragging(handle)
      },
      [disabled]
    )

    const handleTouchMove = React.useCallback(
      (e: TouchEvent) => {
        if (!dragging || e.touches.length === 0) return
        const touch = e.touches[0]
        commitDrag(dragging, getValueFromPosition(touch.clientX))
      },
      [dragging, getValueFromPosition, commitDrag]
    )

    const handleTouchEnd = React.useCallback(() => {
      setDragging(null)
    }, [])

    React.useEffect(() => {
      if (dragging) {
        window.addEventListener("touchmove", handleTouchMove, { passive: false })
        window.addEventListener("touchend", handleTouchEnd)
        return () => {
          window.removeEventListener("touchmove", handleTouchMove)
          window.removeEventListener("touchend", handleTouchEnd)
        }
      }
    }, [dragging, handleTouchMove, handleTouchEnd])

    return (
      <div
        ref={ref}
        className={cn(
          "relative w-full h-6 flex items-center select-none",
          disabled && "opacity-50 cursor-not-allowed",
          className
        )}
      >
        {/* Track */}
        <div
          ref={trackRef}
          className="absolute w-full h-2 rounded-full bg-bg-surface border border-border"
        >
          {/* Selected range highlight */}
          <div
            className="absolute h-full rounded-full bg-matrix/50"
            style={{
              left: `${startPercent}%`,
              width: `${endPercent - startPercent}%`,
            }}
          />
        </div>

        {/* Start handle */}
        <div
          className={cn(
            "absolute w-4 h-4 -ml-2 rounded-full border-2 border-matrix bg-bg-terminal cursor-grab shadow-md",
            "hover:scale-110 hover:bg-matrix/20 transition-transform",
            dragging === "start" && "cursor-grabbing scale-110 bg-matrix/30",
            disabled && "cursor-not-allowed"
          )}
          style={{ left: `${startPercent}%` }}
          onMouseDown={handleMouseDown("start")}
          onTouchStart={handleTouchStart("start")}
        />

        {/* End handle */}
        <div
          className={cn(
            "absolute w-4 h-4 -ml-2 rounded-full border-2 border-matrix bg-bg-terminal cursor-grab shadow-md",
            "hover:scale-110 hover:bg-matrix/20 transition-transform",
            dragging === "end" && "cursor-grabbing scale-110 bg-matrix/30",
            disabled && "cursor-not-allowed"
          )}
          style={{ left: `${endPercent}%` }}
          onMouseDown={handleMouseDown("end")}
          onTouchStart={handleTouchStart("end")}
        />
      </div>
    )
  }
)
RangeSlider.displayName = "RangeSlider"

export { RangeSlider }

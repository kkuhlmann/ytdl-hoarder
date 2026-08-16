"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

interface SliderProps {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  className?: string
  disabled?: boolean
}

const Slider = React.forwardRef<HTMLInputElement, SliderProps>(
  ({ value, onChange, min = 0, max = 100, step = 1, className, disabled }, ref) => {
    const percentage = max > min ? ((value - min) / (max - min)) * 100 : 0

    return (
      <div className={cn("relative w-full", className)}>
        <input
          ref={ref}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          disabled={disabled}
          className={cn(
            "slider-matrix w-full h-2 appearance-none cursor-pointer rounded-full",
            "bg-bg-surface border border-border",
            "focus:outline-hidden focus:ring-1 focus:ring-matrix",
            "disabled:cursor-not-allowed disabled:opacity-50"
          )}
          style={{
            background: `linear-gradient(to right, var(--matrix-green) 0%, var(--matrix-green) ${percentage}%, var(--bg-surface) ${percentage}%, var(--bg-surface) 100%)`,
          }}
        />
      </div>
    )
  }
)
Slider.displayName = "Slider"

export { Slider }

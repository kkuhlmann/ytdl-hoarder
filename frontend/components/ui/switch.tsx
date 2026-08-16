"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

type SwitchProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "onChange" | "type"
> & {
  checked: boolean
  onCheckedChange?: (checked: boolean) => void
}

/**
 * The track must stay clear of `bg-matrix/10`, `hover:bg-matrix/20` and
 * `bg-transparent` + `border-border`: the light-theme blocks at the bottom of
 * globals.css restyle those exact class combinations on `button` elements with
 * `!important` across ~24 themes, and a switch is a button.
 */
const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ className, checked, onCheckedChange, disabled, ...props }, ref) => (
    <button
      ref={ref}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      data-state={checked ? "checked" : "unchecked"}
      onClick={() => onCheckedChange?.(!checked)}
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-all",
        "focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-matrix",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked
          ? "bg-matrix border-matrix shadow-glow-sm"
          : "bg-bg-surface border-border hover:border-matrix/50",
        className
      )}
      {...props}
    >
      <span
        className={cn(
          "pointer-events-none block h-3.5 w-3.5 rounded-full transition-transform",
          checked
            ? "translate-x-4 bg-primary-foreground"
            : "translate-x-0.5 bg-text-muted"
        )}
      />
    </button>
  )
)
Switch.displayName = "Switch"

export { Switch }

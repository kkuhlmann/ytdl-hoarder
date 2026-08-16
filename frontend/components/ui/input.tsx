import * as React from "react"

import { cn } from "@/lib/utils"

export interface InputProps extends React.ComponentProps<"input"> {
  label?: string
  wrapperClassName?: string
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, label, id, wrapperClassName, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, "-")

    if (label) {
      return (
        <div className={cn("space-y-1.5", wrapperClassName)}>
          <label
            htmlFor={inputId}
            className="text-sm font-mono text-text-secondary"
          >
            {label}
          </label>
          <input
            id={inputId}
            type={type}
            className={cn(
              "flex h-10 w-full rounded-md border border-border bg-bg-surface px-3 py-2 text-sm font-mono text-text-primary",
              "placeholder:text-text-muted",
              "focus:outline-hidden focus:ring-1 focus:ring-matrix focus:border-matrix",
              "hover:border-matrix/50 transition-colors",
              "disabled:cursor-not-allowed disabled:opacity-50",
              className
            )}
            ref={ref}
            {...props}
          />
        </div>
      )
    }

    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full rounded-md border border-border bg-bg-surface px-3 py-2 text-sm font-mono text-text-primary",
          "placeholder:text-text-muted",
          "focus:outline-hidden focus:ring-1 focus:ring-matrix focus:border-matrix",
          "hover:border-matrix/50 transition-colors",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }

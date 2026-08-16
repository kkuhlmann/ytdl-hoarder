"use client"

import * as React from "react"
import * as CheckboxPrimitive from "@radix-ui/react-checkbox"
import { CheckIcon } from "@heroicons/react/20/solid"

import { cn } from "@/lib/utils"

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      "peer h-4 w-4 shrink-0 rounded-sm border border-border bg-bg-surface transition-all",
      "focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-matrix",
      "disabled:cursor-not-allowed disabled:opacity-50",
      "data-[state=checked]:bg-matrix data-[state=checked]:border-matrix data-[state=checked]:shadow-glow-sm",
      "hover:border-matrix/50",
      className
    )}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className={cn("flex items-center justify-center text-primary-foreground")}
    >
      <CheckIcon className="h-3.5 w-3.5" />
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = CheckboxPrimitive.Root.displayName

export { Checkbox }

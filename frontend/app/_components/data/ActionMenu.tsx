"use client"

import React, { useState } from "react"
import { EllipsisHorizontalIcon } from "@heroicons/react/20/solid"

import { cn } from "@/lib/utils"
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover"

/**
 * A row's or card's actions behind a single ⋯ chip.
 *
 * Shared by the mobile list row and the touch form of CardActionOverlay: both
 * need the same popover behaviour, and a full action strip costs more width
 * than either has. The popover is portalled, which is what lets it escape a
 * card's overflow-hidden — an inline expanding strip gets clipped by it.
 */
export function ActionMenu({
  actions,
  className,
  side = "top",
  align = "end",
}: {
  actions: React.ReactNode
  /** Positioning and chrome for the trigger, which differs per surface. */
  className?: string
  side?: "top" | "bottom"
  align?: "start" | "center" | "end"
}) {
  const [open, setOpen] = useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          // Every surface that renders these also makes the row or card itself
          // clickable, and opening the menu must never start playback behind it.
          onClick={(e) => e.stopPropagation()}
          title="Actions"
          aria-label="Actions"
          className={className}
        >
          <EllipsisHorizontalIcon className="h-4 w-4" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={side}
        align={align}
        className="w-auto p-1.5"
        // Capture phase: every action handler calls stopPropagation, so a
        // bubble-phase handler here would never run. Closing matters because
        // several actions open dialogs that would fight the popover for focus.
        onClickCapture={() => setOpen(false)}
      >
        {/* One row, always. The longest strips run to nine icons, so the button
            size is chosen to fit that many across the narrowest phone: 9 × 28px
            plus 8 × 4px of gap is 284px, inside the ~290px a 320px viewport
            leaves after collision padding and this popover's own padding.
            Bigger touch targets and a single row are mutually exclusive at nine
            icons — 44px each would need 396px — and overflow-x is the escape
            hatch if a surface ever adds a tenth. */}
        <div
          className={cn(
            "flex flex-nowrap items-center gap-1 overflow-x-auto",
            "[&_svg]:h-4 [&_svg]:w-4 [&_button]:shrink-0 [&_button]:p-1.5",
          )}
        >
          {actions}
        </div>
      </PopoverContent>
    </Popover>
  )
}

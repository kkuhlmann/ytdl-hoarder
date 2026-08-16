"use client"

import { useState } from "react"
import { StarIcon as StarSolid, XMarkIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { StarIcon as StarOutline } from "@heroicons/react/24/outline"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"

type RatingFilterProps = {
  minRating: number | null
  onChange: (minRating: number | null) => void
}

export function RatingFilter({ minRating, onChange }: RatingFilterProps) {
  const [open, setOpen] = useState(false)
  const active = minRating !== null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors ${
            active
              ? "bg-matrix/20 text-matrix border border-matrix/30"
              : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
          }`}
          title={active ? `Filtering ${minRating}+ stars` : "Filter by rating"}
        >
          {active ? (
            <StarSolid className="h-3.5 w-3.5" />
          ) : (
            <StarOutline className="h-3.5 w-3.5" />
          )}
          {active ? (
            <>
              <span className="hidden sm:inline">{minRating}+</span>
              <span
                role="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange(null)
                }}
                className="hover:text-status-error cursor-pointer"
              >
                <XMarkIcon className="h-3 w-3" />
              </span>
            </>
          ) : (
            <>
              <span className="hidden sm:inline">Rating</span>
              <ChevronDownIcon className="h-3 w-3 hidden sm:block" />
            </>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-2">
        <div className="inline-flex items-center gap-0.5">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              onClick={() => {
                onChange(minRating === star ? null : star)
                setOpen(false)
              }}
              className="p-0 transition-colors"
              title={minRating === star ? "Clear filter" : `${star}+ stars`}
            >
              {minRating !== null && star <= minRating ? (
                <StarSolid className="h-4 w-4 text-status-warning" />
              ) : (
                <StarOutline className="h-4 w-4 text-text-muted/40 hover:text-status-warning/60" />
              )}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

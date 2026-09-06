"use client"

import { useState, useRef, useEffect } from "react"
import { StarIcon as StarSolid } from "@heroicons/react/20/solid"
import { StarIcon as StarOutline } from "@heroicons/react/24/outline"

type StarRatingProps = {
  rating: number | null | undefined
  onRate: (rating: number | null) => void
  compact?: boolean
  /** Overrides the tooltip, for surfaces where a star means something other than "rate this". */
  titleFor?: (star: number, isSelected: boolean) => string
}

const rateTitle = (star: number, isSelected: boolean) =>
  isSelected ? "Clear rating" : `Rate ${star} star${star > 1 ? "s" : ""}`

export function StarRating({ rating, onRate, compact = false, titleFor = rateTitle }: StarRatingProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverRating, setHoverRating] = useState<number | null>(null)
  const displayRating = hoverRating ?? rating ?? 0
  const size = compact ? "h-3.5 w-3.5" : "h-4 w-4"

  // Safety net: if onMouseLeave was missed on a fast mouse exit,
  // check on the next frame whether the container is still hovered
  useEffect(() => {
    if (hoverRating === null) return
    const id = requestAnimationFrame(() => {
      if (containerRef.current && !containerRef.current.matches(':hover')) {
        setHoverRating(null)
      }
    })
    return () => cancelAnimationFrame(id)
  }, [hoverRating])

  return (
    <div
      ref={containerRef}
      className="inline-flex items-center gap-0"
      onMouseLeave={() => setHoverRating(null)}
    >
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          onClick={(e) => {
            e.stopPropagation()
            onRate(rating === star ? null : star)
          }}
          onMouseEnter={() => setHoverRating(star)}
          className="p-0 transition-colors"
          title={titleFor(star, rating === star)}
        >
          {star <= displayRating ? (
            <StarSolid className={`${size} text-status-warning`} />
          ) : (
            <StarOutline className={`${size} text-text-muted/40 hover:text-status-warning/60`} />
          )}
        </button>
      ))}
    </div>
  )
}

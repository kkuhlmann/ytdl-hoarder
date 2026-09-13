"use client"

import { useState, useRef, useEffect } from "react"
import { StarIcon as StarSolid } from "@heroicons/react/20/solid"
import { StarIcon as StarOutline } from "@heroicons/react/24/outline"

type StarRatingProps = {
  rating: number | null | undefined
  /** Omit to render the rating read-only: no buttons, no hover preview. */
  onRate?: (rating: number | null) => void
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
  const star = (index: number) =>
    index <= displayRating ? (
      <StarSolid className={`${size} text-status-warning`} />
    ) : (
      <StarOutline
        className={`${size} text-text-muted/40 ${onRate ? "hover:text-status-warning/60" : ""}`}
      />
    )

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

  if (!onRate) {
    return (
      <div
        className="inline-flex items-center gap-0"
        title={rating ? `Rated ${rating} star${rating > 1 ? "s" : ""}` : "Not rated"}
      >
        {[1, 2, 3, 4, 5].map((index) => (
          <span key={index}>{star(index)}</span>
        ))}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="inline-flex items-center gap-0"
      onMouseLeave={() => setHoverRating(null)}
    >
      {[1, 2, 3, 4, 5].map((index) => (
        <button
          key={index}
          onClick={(e) => {
            e.stopPropagation()
            onRate(rating === index ? null : index)
          }}
          onMouseEnter={() => setHoverRating(index)}
          className="p-0 transition-colors"
          title={titleFor(index, rating === index)}
        >
          {star(index)}
        </button>
      ))}
    </div>
  )
}

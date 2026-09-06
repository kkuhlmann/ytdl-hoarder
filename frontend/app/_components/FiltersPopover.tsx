"use client"

import { useState } from "react"
import { FunnelIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { TagFilterBody } from "@/app/_components/TagFilter"
import { StarRating } from "@/app/_components/StarRating"
import { TagInfo } from "@/app/types/DownloadsOptions"

type FiltersPopoverProps = {
  allTags: TagInfo[]
  selectedTagIds: number[]
  onTagsChange: (tagIds: number[]) => void
  minRating: number | null
  onRatingChange: (minRating: number | null) => void
}

const filterTitle = (star: number, isSelected: boolean) =>
  isSelected ? "Clear filter" : `${star}+ stars`

export function FiltersPopover({
  allTags,
  selectedTagIds,
  onTagsChange,
  minRating,
  onRatingChange,
}: FiltersPopoverProps) {
  const [open, setOpen] = useState(false)
  const activeCount = (selectedTagIds.length > 0 ? 1 : 0) + (minRating !== null ? 1 : 0)

  const clearAll = () => {
    onTagsChange([])
    onRatingChange(null)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors ${
            activeCount > 0
              ? "bg-matrix/20 text-matrix border border-matrix/30"
              : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
          }`}
          title={activeCount > 0 ? `${activeCount} filter${activeCount > 1 ? "s" : ""} active` : "Filter by tag or rating"}
        >
          <FunnelIcon className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Filters</span>
          {activeCount > 0 && (
            <span className="min-w-4 px-1 rounded-full bg-matrix text-bg-void text-[10px] leading-4 text-center">
              {activeCount}
            </span>
          )}
          <ChevronDownIcon className={`h-3 w-3 hidden sm:block transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-0 overflow-hidden">
        <div className="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide font-mono text-text-muted">
          Tags
        </div>
        {allTags.length === 0 ? (
          <div className="px-3 py-3 text-center text-xs font-mono text-text-muted">No tags yet</div>
        ) : (
          <TagFilterBody
            allTags={allTags}
            selectedTagIds={selectedTagIds}
            onChange={onTagsChange}
          />
        )}
        <div className="flex items-center justify-between gap-2 px-3 py-2 border-t border-border">
          <span className="text-[10px] uppercase tracking-wide font-mono text-text-muted">
            Rating
          </span>
          <StarRating
            rating={minRating}
            onRate={onRatingChange}
            compact
            titleFor={filterTitle}
          />
        </div>
        {activeCount > 0 && (
          <div className="border-t border-border p-1">
            <button
              onClick={clearAll}
              className="w-full px-2 py-1.5 rounded text-xs font-mono text-text-secondary hover:bg-bg-surface hover:text-status-error transition-colors"
            >
              Clear all
            </button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

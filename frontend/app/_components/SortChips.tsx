"use client"

import { cn } from "@/lib/utils"
import { ChevronUpIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { SortDirection } from "@/app/types/DownloadsOptions"

export const MEDIA_SORT_OPTIONS = [
  { key: "downloaded_at", label: "Downloaded" },
  { key: "last_accessed", label: "Last Watched" },
  { key: "release_timestamp", label: "Released" },
  { key: "rating", label: "Rating" },
  { key: "duration", label: "Duration" },
]

type SortChipsProps = {
  sortBy: string | null
  sortDirection: SortDirection
  onSort: (column: string) => void
  /** Defaults to the media library's fields; playlists pass their own. */
  options?: { key: string; label: string }[]
  className?: string
}

/**
 * Horizontally scrolling sort control. Used by the grid view at every width and
 * by the table view on mobile only, where the sortable column headers are hidden.
 */
export function SortChips({
  sortBy,
  sortDirection,
  onSort,
  options = MEDIA_SORT_OPTIONS,
  className,
}: SortChipsProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 flex-nowrap overflow-x-auto scrollbar-none [&::-webkit-scrollbar]:hidden",
        className,
      )}
    >
      <span className="text-[11px] font-mono text-text-muted mr-0.5 shrink-0">
        Sort:
      </span>
      {options.map((opt) => {
        const isActive = sortBy === opt.key
        return (
          <button
            key={opt.key}
            onClick={() => onSort(opt.key)}
            className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[11px] font-mono transition-colors shrink-0 ${
              isActive
                ? "bg-matrix/20 text-matrix border border-matrix/30"
                : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
            }`}
          >
            {opt.label}
            {isActive &&
              (sortDirection === "asc" ? (
                <ChevronUpIcon className="h-3 w-3" />
              ) : (
                <ChevronDownIcon className="h-3 w-3" />
              ))}
          </button>
        )
      })}
    </div>
  )
}

"use client"

import { useState, useMemo } from "react"
import { TagIcon, XMarkIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { TagInfo } from "@/app/types/DownloadsOptions"

type TagFilterProps = {
  allTags: TagInfo[]
  selectedTagIds: number[]
  onChange: (tagIds: number[]) => void
}

/**
 * The searchable tag checklist, without a trigger of its own, so it can also be
 * rendered as one section of a larger filter popover (popovers don't nest).
 */
export function TagFilterBody({ allTags, selectedTagIds, onChange }: TagFilterProps) {
  const [search, setSearch] = useState("")

  const toggleTag = (id: number) => {
    if (selectedTagIds.includes(id)) {
      onChange(selectedTagIds.filter((t) => t !== id))
    } else {
      onChange([...selectedTagIds, id])
    }
  }

  const filtered = useMemo(
    () => allTags.filter((t) => t.name.toLowerCase().includes(search.toLowerCase())),
    [allTags, search]
  )

  return (
    <>
      <div className="p-2 border-b border-border">
        <input
          type="text"
          placeholder="Search tags..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-2 py-1 bg-bg-surface border border-border rounded text-xs font-mono text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-matrix/50"
        />
      </div>
      <div className="max-h-56 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="px-3 py-3 text-center text-xs font-mono text-text-muted">No matches</div>
        ) : (
          filtered.map((tag) => (
            <button
              key={tag.id}
              onClick={() => toggleTag(tag.id)}
              className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors flex items-center gap-2 ${
                selectedTagIds.includes(tag.id)
                  ? "bg-matrix/10 text-matrix"
                  : "text-text-primary hover:bg-bg-surface"
              }`}
            >
              <span className={`w-3 h-3 rounded border shrink-0 flex items-center justify-center ${
                selectedTagIds.includes(tag.id)
                  ? "border-matrix bg-matrix"
                  : "border-border"
              }`}>
                {selectedTagIds.includes(tag.id) && (
                  <svg className="w-2 h-2 text-bg-base" viewBox="0 0 12 12" fill="currentColor">
                    <path d="M10 3L4.5 8.5 2 6" stroke="currentColor" strokeWidth="2" fill="none" />
                  </svg>
                )}
              </span>
              {tag.name}
            </button>
          ))
        )}
      </div>
    </>
  )
}

export function TagFilter({ allTags, selectedTagIds, onChange }: TagFilterProps) {
  const [open, setOpen] = useState(false)

  const selectedNames = allTags
    .filter((t) => selectedTagIds.includes(t.id))
    .map((t) => t.name)

  return (
    <Popover open={open && allTags.length > 0} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors ${
            selectedTagIds.length > 0
              ? "bg-matrix/20 text-matrix border border-matrix/30"
              : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
          }`}
        >
          <TagIcon className="h-3.5 w-3.5" />
          {selectedTagIds.length > 0 ? (
            <>
              <span className="hidden sm:inline">
                {selectedNames.length <= 2
                  ? selectedNames.join(", ")
                  : `${selectedNames.length} tags`}
              </span>
              <span
                role="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onChange([])
                }}
                className="hover:text-status-error cursor-pointer"
              >
                <XMarkIcon className="h-3 w-3" />
              </span>
            </>
          ) : (
            <>
              <span className="hidden sm:inline">Tags</span>
              <ChevronDownIcon className={`hidden sm:block h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
            </>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-0 overflow-hidden">
        <TagFilterBody allTags={allTags} selectedTagIds={selectedTagIds} onChange={onChange} />
      </PopoverContent>
    </Popover>
  )
}

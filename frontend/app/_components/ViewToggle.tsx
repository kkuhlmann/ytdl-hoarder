"use client"

import { TableCellsIcon, Squares2X2Icon } from "@heroicons/react/20/solid"

import type { ViewMode } from "@/app/_hooks/useViewMode"

type ViewToggleProps = {
  mode: ViewMode
  onChange: (next: ViewMode) => void
}

/**
 * Table/grid flip button. Shows the mode you'd switch *to*, not the current one.
 *
 * Lifted verbatim out of DownloadsCard so every list surface gets the same
 * control. Note this is a two-state flip, not a segmented control — the
 * Playlists/Tag Mix segmented control in PlaylistsCard is a different thing
 * (a mode switch, not a view switch) and deliberately keeps its own styling.
 */
export function ViewToggle({ mode, onChange }: ViewToggleProps) {
  const isGrid = mode === "grid"

  return (
    <button
      onClick={() => onChange(isGrid ? "table" : "grid")}
      className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors ${
        isGrid
          ? "bg-matrix/20 text-matrix border border-matrix/30"
          : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
      }`}
      title={isGrid ? "Switch to table view" : "Switch to grid view"}
    >
      {isGrid ? (
        <TableCellsIcon className="h-3.5 w-3.5" />
      ) : (
        <Squares2X2Icon className="h-3.5 w-3.5" />
      )}
      <span className="hidden sm:inline">{isGrid ? "Table" : "Grid"}</span>
    </button>
  )
}

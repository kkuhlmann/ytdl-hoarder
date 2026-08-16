"use client"

import { Button } from "@/components/ui/button"
import {
  MinusIcon,
  PlusIcon,
  MagnifyingGlassIcon,
  ArrowsPointingOutIcon,
} from "@heroicons/react/24/solid"

interface ZoomControlsProps {
  zoomLevel: number
  onZoomIn: () => void
  onZoomOut: () => void
  onZoomToSelection: () => void
  onResetZoom: () => void
  isZoomed: boolean
  compact?: boolean
}

export function ZoomControls({
  zoomLevel,
  onZoomIn,
  onZoomOut,
  onZoomToSelection,
  onResetZoom,
  isZoomed,
  compact = false,
}: ZoomControlsProps) {
  const maxZoom = 20
  const minZoom = 1

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={onZoomOut}
          disabled={zoomLevel <= minZoom}
          className="h-7 w-7 p-0"
          title="Zoom out"
        >
          <MinusIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onZoomIn}
          disabled={zoomLevel >= maxZoom}
          className="h-7 w-7 p-0"
          title="Zoom in"
        >
          <PlusIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onZoomToSelection}
          className="h-7 w-7 p-0"
          title="Zoom to selection"
        >
          <MagnifyingGlassIcon className="h-3.5 w-3.5" />
        </Button>
        {isZoomed && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onResetZoom}
            className="h-7 w-7 p-0"
            title="Reset zoom"
          >
            <ArrowsPointingOutIcon className="h-3.5 w-3.5" />
          </Button>
        )}
        <span className="text-xs font-mono text-text-muted ml-1">
          {zoomLevel.toFixed(1)}x
        </span>
      </div>
    )
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={onZoomOut}
        disabled={zoomLevel <= minZoom}
        className="h-8 w-8 p-0"
        title="Zoom out"
      >
        <MinusIcon className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={onZoomIn}
        disabled={zoomLevel >= maxZoom}
        className="h-8 w-8 p-0"
        title="Zoom in"
      >
        <PlusIcon className="h-4 w-4" />
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={onZoomToSelection}
        className="gap-1.5"
        title="Zoom to selection"
      >
        <MagnifyingGlassIcon className="h-4 w-4" />
        Zoom to Selection
      </Button>
      {isZoomed && (
        <Button
          variant="outline"
          size="sm"
          onClick={onResetZoom}
          className="gap-1.5"
          title="Reset zoom to full view"
        >
          <ArrowsPointingOutIcon className="h-4 w-4" />
          Reset
        </Button>
      )}
      <span className="text-sm font-mono text-text-muted">
        {zoomLevel.toFixed(1)}x
      </span>
    </div>
  )
}

"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { MediaStats } from "@/app/types/DownloadsOptions"
import { formatCount } from "@/app/_components/stats/format"

type MediaStatsBarProps = {
  stats: MediaStats | null
  loading?: boolean
}

type StatBadgeProps = {
  variant: "matrix" | "success" | "queued"
  value: number
  label: string
  /** Which edge of the badge the tooltip should anchor to, so it doesn't overflow the viewport. */
  align?: "left" | "center" | "right"
}

const TOOLTIP_POSITION_CLASSES: Record<NonNullable<StatBadgeProps["align"]>, string> = {
  left: "left-0",
  center: "left-1/2 -translate-x-1/2",
  right: "right-0",
}

function StatBadge({ variant, value, label, align = "center" }: StatBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false)

  return (
    <div className="relative flex items-center gap-1.5">
      <Badge
        variant={variant}
        className="min-w-7 sm:min-w-10 justify-center cursor-pointer sm:cursor-default"
        onClick={() => setShowTooltip((v) => !v)}
        onMouseLeave={() => setShowTooltip(false)}
      >
        {formatCount(value)}
      </Badge>
      <span className="hidden sm:inline text-xs text-text-muted font-mono">{label}</span>
      {showTooltip && (
        <div
          className={`absolute -top-2 -translate-y-full bg-bg-elevated border border-matrix-dim rounded px-2 py-1 text-xs font-mono text-text-primary whitespace-nowrap z-10 sm:hidden ${TOOLTIP_POSITION_CLASSES[align]}`}
          role="tooltip"
        >
          {label}: {value.toLocaleString()}
        </div>
      )}
    </div>
  )
}

export function MediaStatsBar({ stats, loading }: MediaStatsBarProps) {
  if (loading || !stats) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-muted font-mono animate-pulse">
          Loading...
        </span>
      </div>
    )
  }

  return (
    <div className="flex flex-nowrap w-max items-center gap-x-1.5 sm:gap-x-3">
      <StatBadge variant="matrix" value={stats.total_downloads} label="downloads" />
      <Separator orientation="vertical" className="h-3 hidden sm:block" />
      <StatBadge variant="success" value={stats.downloads_with_transcripts} label="with transcripts" />
      <Separator orientation="vertical" className="h-3 hidden sm:block" />
      <StatBadge variant="queued" value={stats.total_transcript_blocks} label="transcript blocks" align="right" />
    </div>
  )
}

"use client"

import { Fragment, useState } from "react"
import { badgeVariants } from "@/components/ui/badge"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { MediaStats } from "@/app/types/DownloadsOptions"
import { formatCount } from "@/app/_components/stats/format"
import { cn } from "@/lib/utils"

type MediaStatsBarProps = {
  stats: MediaStats | null
  loading?: boolean
}

type Stat = {
  key: keyof MediaStats
  label: string
  className: string
}

const STATS: Stat[] = [
  { key: "total_downloads", label: "downloads", className: "text-matrix" },
  { key: "downloads_with_transcripts", label: "with transcripts", className: "text-status-success" },
  { key: "total_transcript_blocks", label: "transcript blocks", className: "text-status-queued" },
]

/**
 * The three media counts as one chip, with the labels behind it.
 *
 * The breakdown is a portalled Popover, not a positioned div: the strip this sits
 * in scrolls horizontally, and an `overflow-x-auto` box clips both axes, so
 * anything drawn outside the 32px-tall header is invisible.
 */
export function MediaStatsBar({ stats, loading }: MediaStatsBarProps) {
  const [open, setOpen] = useState(false)

  if (loading || !stats) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-muted font-mono animate-pulse">
          Loading...
        </span>
      </div>
    )
  }

  const summary = STATS.map((s) => `${stats[s.key].toLocaleString()} ${s.label}`).join(", ")

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn(badgeVariants({ variant: "outline" }), "gap-1 whitespace-nowrap")}
        aria-label={summary}
        // Touch fires a synthetic enter before the click, which would open the
        // popover only for the click to toggle it shut again.
        onPointerEnter={(e) => e.pointerType === "mouse" && setOpen(true)}
        onPointerLeave={(e) => e.pointerType === "mouse" && setOpen(false)}
      >
        {STATS.map((stat, i) => (
          <Fragment key={stat.key}>
            {i > 0 && <span className="text-text-muted">·</span>}
            <span className={stat.className}>{formatCount(stats[stat.key])}</span>
          </Fragment>
        ))}
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-auto p-2"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {STATS.map((stat) => (
          <div key={stat.key} className="flex items-center justify-between gap-3 text-xs font-mono">
            <span className={stat.className}>{stats[stat.key].toLocaleString()}</span>
            <span className="text-text-muted">{stat.label}</span>
          </div>
        ))}
      </PopoverContent>
    </Popover>
  )
}

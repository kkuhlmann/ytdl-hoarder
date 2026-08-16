"use client"

import type { LibraryOverview } from "@/app/types/StatsOptions"
import { StatsPanel } from "./StatsPanel"
import { StatSummaryCard } from "./StatSummaryCard"
import { formatCount, formatDurationLong } from "./format"
import { formatBytes } from "@/app/utils"

interface LibraryOverviewSectionProps {
  overview: LibraryOverview | null
}

export function LibraryOverviewSection({ overview }: LibraryOverviewSectionProps) {
  if (!overview) return null

  return (
    <StatsPanel id="overview" title="Library Overview">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatSummaryCard label="Total Media" value={formatCount(overview.total_media)} />
        <StatSummaryCard label="Audio" value={formatCount(overview.audio_count)} />
        <StatSummaryCard label="Video" value={formatCount(overview.video_count)} />
        <StatSummaryCard
          label="Total Duration"
          value={formatDurationLong(overview.total_duration_seconds)}
        />
        <StatSummaryCard label="Channels" value={overview.unique_channels} />
        <StatSummaryCard
          label="Subscriptions"
          value={overview.active_subscriptions !== null ? overview.active_subscriptions : "N/A"}
        />
        <StatSummaryCard label="Transcribed" value={formatCount(overview.transcripts_count)} />
        <StatSummaryCard label="Disk Usage" value={formatBytes(overview.total_disk_bytes)} />
      </div>
    </StatsPanel>
  )
}

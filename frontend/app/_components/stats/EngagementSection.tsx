"use client"

import type { EngagementStats } from "@/app/types/StatsOptions"
import type { ChartColors } from "./useChartTheme"
import { StatsPanel } from "./StatsPanel"
import { RankedBarList } from "./RankedBarList"

interface EngagementSectionProps {
  engagement: EngagementStats | null
  colors: ChartColors
}

export function EngagementSection({ engagement, colors }: EngagementSectionProps) {
  if (!engagement || (engagement.most_replayed.length === 0 && engagement.top_channels.length === 0)) {
    return null
  }

  return (
    <StatsPanel id="engagement" title="Engagement">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {engagement.most_replayed.length > 0 && (
          <div className="min-w-0">
            <p className="text-sm text-text-secondary font-mono mb-2">Top 10 Most Played</p>
            <RankedBarList
              items={engagement.most_replayed.slice(0, 10).map((m) => ({ label: m.title, value: m.access_count }))}
              color={colors.matrix}
              formatValue={(v) => `${v} plays`}
            />
          </div>
        )}

        {engagement.top_channels.length > 0 && (
          <div className="min-w-0">
            <p className="text-sm text-text-secondary font-mono mb-2">
              Top Channels by Play Count
            </p>
            <RankedBarList
              items={engagement.top_channels.map((c) => ({ label: c.channel, value: c.total_plays }))}
              color={colors.blue}
              formatValue={(v) => `${v} plays`}
            />
          </div>
        )}
      </div>
    </StatsPanel>
  )
}

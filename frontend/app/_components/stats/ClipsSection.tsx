"use client"

import type { ClipsStats, Granularity } from "@/app/types/StatsOptions"
import type { ChartColors, ChartTooltipStyle } from "./useChartTheme"
import { StatsPanel } from "./StatsPanel"
import { RankedBarList } from "./RankedBarList"
import { StatSummaryCard } from "./StatSummaryCard"
import { formatPeriodLabel } from "./format"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts"

interface ClipsSectionProps {
  clips: ClipsStats | null
  granularity: Granularity
  colors: ChartColors
  tooltipStyle: ChartTooltipStyle
  isMobile: boolean
}

export function ClipsSection({ clips, granularity, colors, tooltipStyle, isMobile }: ClipsSectionProps) {
  if (!clips || clips.total_clips <= 0) return null

  return (
    <StatsPanel id="clips" title="Clips">
      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatSummaryCard
          label="Total Clips"
          value={clips.total_clips}
          sub={clips.complete_clips < clips.total_clips
            ? `${clips.complete_clips} complete`
            : undefined}
        />
        <StatSummaryCard label="Sources Clipped" value={clips.most_clipped_sources.length} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {clips.most_clipped_sources.length > 0 && (
          <div className="min-w-0">
            <p className="text-sm text-text-secondary font-mono mb-2">Most Clipped Sources</p>
            <RankedBarList
              items={clips.most_clipped_sources.map((s) => ({ label: s.title, value: s.clip_count }))}
              color={colors.purple}
              formatValue={(v) => `${v} clips`}
            />
          </div>
        )}

        {clips.over_time.length > 0 && (
          <div className="min-w-0">
            <p className="text-sm text-text-secondary font-mono mb-2">Clips Over Time</p>
            <ResponsiveContainer width="100%" height={isMobile ? 200 : 250}>
              <BarChart data={clips.over_time}>
                <CartesianGrid strokeDasharray="3 3" stroke={colors.elevated} />
                <XAxis
                  dataKey="period"
                  tickFormatter={(v) => formatPeriodLabel(v, granularity)}
                  tick={{ fill: colors.textMuted, fontSize: 11 }}
                  interval={granularity === "day" ? "preserveStartEnd" : 0}
                  angle={granularity === "day" ? -45 : 0}
                  textAnchor={granularity === "day" ? "end" : "middle"}
                  height={granularity === "day" ? 60 : 30}
                />
                <YAxis tick={{ fill: colors.textMuted, fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  labelFormatter={(v) => formatPeriodLabel(v, granularity)}
                  {...tooltipStyle}
                />
                <Bar
                  dataKey="count"
                  fill={colors.purple}
                  fillOpacity={0.35}
                  stroke={colors.purple}
                  strokeOpacity={0.8}
                  name="Clips"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </StatsPanel>
  )
}

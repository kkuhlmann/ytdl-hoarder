"use client"

import type { DownloadsOverTime, DownloadSuccessRate, Granularity } from "@/app/types/StatsOptions"
import type { ChartColors, ChartTooltipStyle } from "./useChartTheme"
import { StatsPanel } from "./StatsPanel"
import { StatSummaryCard } from "./StatSummaryCard"
import { formatPeriodLabel } from "./format"
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts"

interface DownloadsOverTimeSectionProps {
  downloads: DownloadsOverTime | null
  successRate: DownloadSuccessRate | null
  granularity: Granularity
  colors: ChartColors
  tooltipStyle: ChartTooltipStyle
  isMobile: boolean
}

export function DownloadsOverTimeSection({
  downloads,
  successRate,
  granularity,
  colors,
  tooltipStyle,
  isMobile,
}: DownloadsOverTimeSectionProps) {
  if (!downloads || !(downloads.periods?.length > 0)) return null

  return (
    <StatsPanel id="downloads" title="Downloads Over Time">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="min-w-0">
          <p className="text-sm text-text-secondary font-mono mb-2">
            {granularity === "day" ? "Daily" : granularity === "week" ? "Weekly" : "Monthly"} Downloads
          </p>
          <ResponsiveContainer width="100%" height={isMobile ? 220 : 300}>
            <BarChart data={downloads.periods}>
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
              <YAxis tick={{ fill: colors.textMuted, fontSize: 11 }} />
              <Tooltip
                labelFormatter={(v) => formatPeriodLabel(v, granularity)}
                {...tooltipStyle}
              />
              <Legend
                wrapperStyle={{ fontSize: "12px", fontFamily: "monospace" }}
              />
              <Bar
                dataKey="audio"
                stackId="a"
                fill={colors.matrix}
                fillOpacity={0.35}
                stroke={colors.matrix}
                strokeOpacity={0.8}
                name="Audio"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="video"
                stackId="a"
                fill={colors.blue}
                fillOpacity={0.35}
                stroke={colors.blue}
                strokeOpacity={0.8}
                name="Video"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="min-w-0">
          <p className="text-sm text-text-secondary font-mono mb-2">Cumulative Total</p>
          <ResponsiveContainer width="100%" height={isMobile ? 220 : 300}>
            <LineChart data={downloads.cumulative}>
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
              <YAxis tick={{ fill: colors.textMuted, fontSize: 11 }} />
              <Tooltip
                labelFormatter={(v) => formatPeriodLabel(v, granularity)}
                {...tooltipStyle}
              />
              <Legend
                wrapperStyle={{ fontSize: 11, fontFamily: "monospace" }}
              />
              <Line
                type="monotone"
                dataKey="total"
                stroke={colors.matrix}
                strokeWidth={2}
                dot={granularity === "day" ? false : { fill: colors.matrix, r: 3 }}
                name="Total"
              />
              <Line
                type="monotone"
                dataKey="audio"
                stroke={colors.blue}
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                name="Audio"
              />
              <Line
                type="monotone"
                dataKey="video"
                stroke={colors.purple}
                strokeWidth={1.5}
                strokeDasharray="5 3"
                dot={false}
                name="Video"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {successRate && successRate.periods.length > 0 && (
        <div className="mt-4">
          <p className="text-sm text-text-secondary font-mono mb-3">
            Download Success Rate
          </p>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <StatSummaryCard
              label="Success Rate"
              value={`${successRate.success_rate}%`}
              sub={`${successRate.totals.success} of ${successRate.totals.total}`}
            />
            <StatSummaryCard
              label="Failed"
              value={successRate.totals.failed}
            />
            <StatSummaryCard
              label="Retries"
              value={successRate.totals.retry}
            />
          </div>
          <ResponsiveContainer width="100%" height={isMobile ? 220 : 300}>
            <BarChart data={successRate.periods}>
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
              <Legend
                wrapperStyle={{ fontSize: "12px", fontFamily: "monospace" }}
              />
              <Bar
                dataKey="success"
                stackId="a"
                fill={colors.matrix}
                fillOpacity={0.35}
                stroke={colors.matrix}
                strokeOpacity={0.8}
                name="Success"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="retry"
                stackId="a"
                fill={colors.orange}
                fillOpacity={0.35}
                stroke={colors.orange}
                strokeOpacity={0.8}
                name="Retry"
                radius={[0, 0, 0, 0]}
              />
              <Bar
                dataKey="failed"
                stackId="a"
                fill={colors.red}
                fillOpacity={0.35}
                stroke={colors.red}
                strokeOpacity={0.8}
                name="Failed"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </StatsPanel>
  )
}

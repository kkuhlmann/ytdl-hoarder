"use client"

import { useState } from "react"
import type { MouseEvent as ReactMouseEvent } from "react"
import type { DownloadActivityHeatmap } from "@/app/types/StatsOptions"
import { StatsPanel } from "./StatsPanel"

// Theme-aware heatmap scale: blend the accent into the surface at increasing
// strength. CSS color-mix in inline styles re-resolves live on theme change.
const HEATMAP_LEVELS = [
  "var(--bg-elevated)", // 0: no downloads
  "color-mix(in srgb, var(--matrix-green) 22%, var(--bg-surface))", // 1: low
  "color-mix(in srgb, var(--matrix-green) 45%, var(--bg-surface))", // 2: medium-low
  "color-mix(in srgb, var(--matrix-green) 70%, var(--bg-surface))", // 3: medium-high
  "var(--matrix-green)", // 4: high
]

function getHeatmapColor(count: number, maxCount: number): string {
  if (count === 0 || maxCount === 0) return HEATMAP_LEVELS[0]
  const ratio = count / maxCount
  if (ratio <= 0.25) return HEATMAP_LEVELS[1]
  if (ratio <= 0.5) return HEATMAP_LEVELS[2]
  if (ratio <= 0.75) return HEATMAP_LEVELS[3]
  return HEATMAP_LEVELS[4]
}

const DAY_LABELS = ["", "Mon", "", "Wed", "", "Fri", ""]
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function ActivityHeatmap({ data, isMobile }: { data: DownloadActivityHeatmap; isMobile: boolean }) {
  const countMap = new Map<string, number>()
  for (const d of data.data) {
    countMap.set(d.date, d.count)
  }

  // Build weeks grid: 7 rows, one column per week.
  // Desktop shows ~52 weeks; mobile shows ~13 weeks so the cells stay tappable
  // and fit-to-width instead of side-scrolling.
  const endDate = new Date()
  const startDate = new Date(endDate)
  startDate.setDate(startDate.getDate() - (isMobile ? 90 : 363))
  // Align to Sunday
  startDate.setDate(startDate.getDate() - startDate.getDay())

  const weeks: { date: Date; count: number; dateStr: string }[][] = []
  const current = new Date(startDate)

  while (current <= endDate) {
    const week: { date: Date; count: number; dateStr: string }[] = []
    for (let d = 0; d < 7; d++) {
      const dateStr = current.toISOString().slice(0, 10)
      week.push({
        date: new Date(current),
        count: countMap.get(dateStr) || 0,
        dateStr,
      })
      current.setDate(current.getDate() + 1)
    }
    weeks.push(week)
  }

  const totalDownloads = data.data.reduce((sum, d) => sum + d.count, 0)

  const [tooltip, setTooltip] = useState<{ text: string; x: number; y: number } | null>(null)

  // Show the tooltip for a cell — used by both hover (desktop) and tap (mobile).
  const showTip = (
    e: ReactMouseEvent<HTMLDivElement>,
    day: { date: Date; count: number; dateStr: string },
  ) => {
    if (day.date > endDate) return
    const rect = e.currentTarget.getBoundingClientRect()
    const parentRect = e.currentTarget.closest(".relative")?.getBoundingClientRect()
    if (parentRect) {
      setTooltip({
        text: `${day.count} download${day.count !== 1 ? "s" : ""} on ${day.dateStr}`,
        x: rect.left - parentRect.left + rect.width / 2,
        y: rect.top - parentRect.top - 28,
      })
    }
  }

  const numWeeks = weeks.length

  return (
    <div>
      <div
        className={`${isMobile ? "" : "overflow-x-auto"} pb-2`}
        onClick={() => setTooltip(null)}
      >
        {/* Month labels — use CSS grid matching the weeks grid */}
        <div
          className="ml-[34px]"
          style={{
            display: "grid",
            gridTemplateColumns: `repeat(${numWeeks}, 1fr)`,
            gap: "2px",
            marginBottom: "2px",
          }}
        >
          {weeks.map((week, wi) => {
            const month = week[0].date.getMonth()
            const prevMonth = wi > 0 ? weeks[wi - 1][0].date.getMonth() : -1
            const showLabel = month !== prevMonth
            return (
              <div key={wi} className="text-xs text-text-muted font-mono overflow-hidden whitespace-nowrap">
                {showLabel ? MONTH_NAMES[month] : ""}
              </div>
            )
          })}
        </div>

        {/* Grid: day labels + cells */}
        <div className="flex gap-0">
          {/* Day of week labels — uses a 7-row grid to match the cells */}
          <div
            className="shrink-0 mr-1"
            style={{
              display: "grid",
              gridTemplateRows: "repeat(7, 1fr)",
              gap: "2px",
              width: "28px",
            }}
          >
            {DAY_LABELS.map((label, i) => (
              <div
                key={i}
                className="text-xs text-text-muted font-mono text-right flex items-center justify-end"
              >
                {label}
              </div>
            ))}
          </div>

          {/* Weeks grid — fluid CSS grid */}
          <div
            className="relative flex-1"
            style={{
              display: "grid",
              gridTemplateColumns: `repeat(${numWeeks}, 1fr)`,
              gap: "2px",
            }}
            onMouseLeave={() => setTooltip(null)}
          >
            {weeks.map((week, wi) => (
              <div key={wi} style={{ display: "grid", gridTemplateRows: "repeat(7, 1fr)", gap: "2px" }}>
                {week.map((day, di) => (
                  <div
                    key={di}
                    style={{
                      aspectRatio: "1",
                      width: "100%",
                      backgroundColor: day.date > endDate
                        ? "transparent"
                        : getHeatmapColor(day.count, data.max_count),
                      borderRadius: "2px",
                      cursor: day.date <= endDate ? "pointer" : "default",
                    }}
                    onMouseEnter={(e) => showTip(e, day)}
                    onClick={(e) => {
                      e.stopPropagation()
                      showTip(e, day)
                    }}
                  />
                ))}
              </div>
            ))}
            {/* Tooltip */}
            {tooltip && (
              <div
                className="absolute pointer-events-none bg-bg-elevated border border-matrix-dim rounded px-2 py-1 text-xs font-mono text-text-primary whitespace-nowrap z-10"
                style={{ left: tooltip.x, top: tooltip.y, transform: "translateX(-50%)" }}
              >
                {tooltip.text}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Summary + legend — both left-aligned */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-3 text-xs font-mono text-text-muted">
        <span>
          {data.total_days_active} days active &middot; {totalDownloads.toLocaleString()} total downloads
        </span>
        <div className="flex items-center gap-1">
          <span>Less</span>
          {HEATMAP_LEVELS.map((color, i) => (
            <div
              key={i}
              style={{
                width: "12px",
                height: "12px",
                backgroundColor: color,
                borderRadius: "2px",
              }}
            />
          ))}
          <span>More</span>
        </div>
      </div>
    </div>
  )
}

export function ActivityHeatmapSection({
  heatmap,
  isMobile,
}: {
  heatmap: DownloadActivityHeatmap | null
  isMobile: boolean
}) {
  if (!heatmap || heatmap.data.length === 0) return null

  return (
    <StatsPanel id="activity" title="Download Activity">
      <ActivityHeatmap data={heatmap} isMobile={isMobile} />
    </StatsPanel>
  )
}

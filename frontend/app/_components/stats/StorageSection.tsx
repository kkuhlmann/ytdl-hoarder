"use client"

import type { StorageStats, StorageByType } from "@/app/types/StatsOptions"
import type { ChartColors, ChartTooltipStyle } from "./useChartTheme"
import { StatsPanel } from "./StatsPanel"
import { RankedBarList } from "./RankedBarList"
import { formatBytes } from "@/app/utils"
import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from "recharts"
import type { PieLabelRenderProps } from "recharts"

interface StorageSectionProps {
  storage: StorageStats | null
  colors: ChartColors
  tooltipStyle: ChartTooltipStyle
  isMobile: boolean
}

export function StorageSection({ storage, colors, tooltipStyle, isMobile }: StorageSectionProps) {
  if (!storage || storage.total_bytes <= 0) return null

  return (
    <StatsPanel id="storage" title="Storage">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="min-w-0">
          <p className="text-sm text-text-secondary font-mono mb-2">
            Disk Usage by Type ({formatBytes(storage.total_bytes)} total)
          </p>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={storage.by_type}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                dataKey="size_bytes"
                nameKey="media_type"
                label={isMobile ? false : (props: PieLabelRenderProps) => {
                  // Recharts spreads the datum into the label props but cannot
                  // type it: https://github.com/recharts/recharts/issues/6380
                  const { cx, cy, outerRadius, index } = props
                  const midAngle = props.midAngle ?? 0
                  const { media_type, size_bytes } = props as PieLabelRenderProps & StorageByType
                  const RADIAN = Math.PI / 180
                  const radius = outerRadius + 16
                  const x = cx + radius * Math.cos(-midAngle * RADIAN)
                  const y = cy + radius * Math.sin(-midAngle * RADIAN)
                  return (
                    <text
                      x={x}
                      y={y}
                      fill={index === 0 ? colors.matrix : colors.blue}
                      fontSize={12}
                      fontFamily="monospace"
                      textAnchor={x > cx ? "start" : "end"}
                      dominantBaseline="central"
                    >
                      {`${media_type} (${formatBytes(size_bytes)})`}
                    </text>
                  )
                }}
                labelLine={false}
              >
                {storage.by_type.map((_, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={index === 0 ? colors.matrix : colors.blue}
                    fillOpacity={0.35}
                    stroke={index === 0 ? colors.matrix : colors.blue}
                    strokeOpacity={0.8}
                    strokeWidth={1.5}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => formatBytes(Number(value))}
                {...tooltipStyle}
              />
            </PieChart>
          </ResponsiveContainer>
          {isMobile && (
            <div className="flex justify-center gap-4 mt-2 text-xs font-mono">
              {storage.by_type.map((t, i) => (
                <span key={t.media_type} className="flex items-center gap-1.5 text-text-secondary">
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ backgroundColor: i === 0 ? colors.matrix : colors.blue, opacity: 0.6 }}
                  />
                  {t.media_type} ({formatBytes(t.size_bytes)})
                </span>
              ))}
            </div>
          )}
        </div>

        {storage.by_channel.length > 0 && (
          <div className="min-w-0">
            <p className="text-sm text-text-secondary font-mono mb-2">
              Top Channels by Storage
            </p>
            <RankedBarList
              items={storage.by_channel.map((c) => ({ label: c.channel, value: c.size_bytes }))}
              color={colors.matrix}
              formatValue={formatBytes}
            />
          </div>
        )}
      </div>

      {storage.largest_files.length > 0 && (
        <div className="mt-4">
          <p className="text-sm text-text-secondary font-mono mb-2">Largest Files</p>
          <div className="sm:hidden flex flex-col gap-2">
            {storage.largest_files.map((f) => (
              <div key={f.id} className="bg-bg-elevated border border-border rounded-lg p-3">
                <p className="text-sm font-mono text-text-primary truncate">{f.title}</p>
                <div className="flex justify-between gap-2 text-xs font-mono text-text-muted mt-1">
                  <span className="truncate">{f.channel} · {f.media_type}</span>
                  <span className="text-matrix shrink-0">{formatBytes(f.size_bytes)}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm font-mono">
              <thead>
                <tr className="border-b border-border text-text-muted">
                  <th className="text-left py-2 px-3">Title</th>
                  <th className="text-left py-2 px-3">Channel</th>
                  <th className="text-left py-2 px-3">Type</th>
                  <th className="text-right py-2 px-3">Size</th>
                </tr>
              </thead>
              <tbody>
                {storage.largest_files.map((f) => (
                  <tr
                    key={f.id}
                    className="border-b border-border/50 hover:bg-bg-elevated/60"
                  >
                    <td className="py-2 px-3 text-text-primary truncate max-w-[300px]">
                      {f.title}
                    </td>
                    <td className="py-2 px-3 text-text-secondary truncate max-w-[150px]">
                      {f.channel}
                    </td>
                    <td className="py-2 px-3 text-text-muted">{f.media_type}</td>
                    <td className="py-2 px-3 text-matrix text-right whitespace-nowrap">
                      {formatBytes(f.size_bytes)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </StatsPanel>
  )
}

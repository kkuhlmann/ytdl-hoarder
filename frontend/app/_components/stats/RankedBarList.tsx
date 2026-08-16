"use client"

export interface RankedBarItem {
  label: string
  value: number
  sub?: string
}

interface RankedBarListProps {
  items: RankedBarItem[]
  color: string
  formatValue?: (v: number) => string
}

// Ranked horizontal bars as plain divs. The label sits on its own full-width
// line above the bar, so there is no fixed left gutter — this is what removes
// the "charts pushed right" problem on mobile.
export function RankedBarList({ items, color, formatValue }: RankedBarListProps) {
  const maxValue = Math.max(1, ...items.map((i) => i.value))
  return (
    <div className="flex flex-col gap-2.5">
      {items.map((item, i) => (
        <div key={i} className="min-w-0">
          <div className="flex items-baseline justify-between gap-2 mb-1">
            <span className="text-xs font-mono text-text-secondary truncate">{item.label}</span>
            <span className="text-xs font-mono text-text-primary shrink-0 tabular-nums">
              {formatValue ? formatValue(item.value) : item.value}
            </span>
          </div>
          <div className="h-2.5 rounded bg-bg-elevated overflow-hidden">
            <div
              className="h-full rounded"
              style={{ width: `${(item.value / maxValue) * 100}%`, backgroundColor: color, opacity: 0.55 }}
            />
          </div>
          {item.sub && <p className="text-[10px] font-mono text-text-muted mt-0.5">{item.sub}</p>}
        </div>
      ))}
    </div>
  )
}

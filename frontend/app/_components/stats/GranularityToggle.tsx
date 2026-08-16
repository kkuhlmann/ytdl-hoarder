"use client"

import type { Granularity } from "@/app/types/StatsOptions"

const GRANULARITY_OPTIONS: { value: Granularity; label: string }[] = [
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
]

export function GranularityToggle({
  value,
  onChange,
}: {
  value: Granularity
  onChange: (g: Granularity) => void
}) {
  return (
    <div className="flex w-full sm:inline-flex sm:w-auto rounded-md border border-border overflow-hidden">
      {GRANULARITY_OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`flex-1 sm:flex-none px-3 py-1 text-xs font-mono text-center transition-colors ${
            value === opt.value
              ? "bg-matrix/20 text-matrix"
              : "bg-bg-surface text-text-muted hover:text-text-secondary hover:bg-bg-elevated"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

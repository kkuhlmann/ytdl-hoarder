"use client"

import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { TaskStats, StatCategory } from "@/app/types/TasksOptions"
import { cn } from "@/lib/utils"

type TaskStatsBarProps = {
  stats: TaskStats | null
  loading?: boolean
  onStatClick?: (category: StatCategory) => void
  activeCategory?: StatCategory | null
}

function StatItem({
  label,
  value,
  variant,
  onClick,
  isActive,
}: {
  label: string
  value: number
  variant: "success" | "queued" | "info" | "warning" | "error" | "secondary"
  onClick?: () => void
  isActive?: boolean
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md px-2 py-1 -mx-2 -my-1 transition-all",
        onClick && "cursor-pointer hover:bg-bg-surface/80",
        isActive && "bg-bg-surface ring-1 ring-border"
      )}
      onClick={onClick}
    >
      <Badge variant={variant} className="min-w-8 justify-center">
        {value}
      </Badge>
      <span className="text-xs text-text-muted font-mono">{label}</span>
    </div>
  )
}

export function TaskStatsBar({ stats, loading, onStatClick, activeCategory }: TaskStatsBarProps) {
  if (loading || !stats) {
    return (
      <div className="flex items-center gap-2 md:gap-4 py-1.5 px-2 md:py-2 md:px-3 bg-bg-surface/50 rounded-md border border-border/50">
        <div className="text-xs text-text-muted font-mono animate-pulse">
          Loading stats...
        </div>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 md:flex md:flex-wrap md:items-center md:gap-x-4 md:gap-y-2 py-1.5 px-2 md:py-2 md:px-3 bg-bg-surface/50 rounded-md border border-border/50">
      <StatItem
        label="Processing"
        value={stats.processing}
        variant="info"
        onClick={onStatClick ? () => onStatClick('processing') : undefined}
        isActive={activeCategory === 'processing'}
      />

      <Separator orientation="vertical" className="h-4 hidden md:block" />

      <div
        className={cn(
          "flex items-center gap-2 rounded-md px-2 py-1 -mx-2 -my-1 transition-all",
          onStatClick && "cursor-pointer hover:bg-bg-surface/80",
          activeCategory === 'queued' && "bg-bg-surface ring-1 ring-border"
        )}
        onClick={onStatClick ? () => onStatClick('queued') : undefined}
      >
        <Badge variant="queued" className="min-w-8 justify-center">
          {stats.queued_total}
        </Badge>
        <span className="text-xs text-text-muted font-mono">Queued</span>
        {stats.queued_total > 0 && (
          <span className="text-xs text-text-muted font-mono opacity-70">
            ({stats.queued_downloads}d / {stats.queued_transcripts}t)
          </span>
        )}
      </div>

      <Separator orientation="vertical" className="h-4 hidden md:block" />

      {/* Not Released (unreleased videos: live / premiere / post-live) */}
      <StatItem
        label="Not Released"
        value={stats.not_ready}
        variant="warning"
        onClick={onStatClick ? () => onStatClick('not_ready') : undefined}
        isActive={activeCategory === 'not_ready'}
      />

      <Separator orientation="vertical" className="h-4 hidden md:block" />

      <StatItem
        label="Done (24h)"
        value={stats.completed_24h}
        variant="success"
        onClick={onStatClick ? () => onStatClick('completed') : undefined}
        isActive={activeCategory === 'completed'}
      />

      <Separator orientation="vertical" className="h-4 hidden md:block" />

      <StatItem
        label="Failed"
        value={stats.failed}
        variant="error"
        onClick={onStatClick ? () => onStatClick('failed') : undefined}
        isActive={activeCategory === 'failed'}
      />

      <Separator orientation="vertical" className="h-4 hidden md:block" />

      <StatItem
        label="Retry"
        value={stats.retry}
        variant="warning"
        onClick={onStatClick ? () => onStatClick('retry') : undefined}
        isActive={activeCategory === 'retry'}
      />
    </div>
  )
}

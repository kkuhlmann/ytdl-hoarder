"use client"

import { ArrowLeftIcon, ChevronRightIcon } from "@heroicons/react/20/solid"

type Props = {
  breadcrumb: { dimLabel: string; segments: { key: string; label: string }[] }
  canGoUp: boolean
  onGoUp: () => void
}

export function GroupBreadcrumb({ breadcrumb, canGoUp, onGoUp }: Props) {
  return (
    <div className="flex items-center gap-1.5 px-2 pt-2 pb-1 flex-wrap">
      {canGoUp && (
        <button
          onClick={onGoUp}
          className="inline-flex items-center justify-center h-6 w-6 rounded-md text-text-muted hover:text-matrix hover:bg-matrix/10 transition-colors"
          title="Back"
          aria-label="Back"
        >
          <ArrowLeftIcon className="h-4 w-4" />
        </button>
      )}
      <span className="text-[11px] font-mono text-text-muted">Grouped by</span>
      <span className="text-[11px] font-mono text-text-secondary">{breadcrumb.dimLabel}</span>
      {breadcrumb.segments.map((seg) => (
        <span key={seg.key} className="inline-flex items-center gap-1.5">
          <ChevronRightIcon className="h-3 w-3 text-text-muted" />
          <span className="text-[11px] font-mono text-matrix">{seg.label}</span>
        </span>
      ))}
    </div>
  )
}

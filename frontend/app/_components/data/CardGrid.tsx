"use client"

import React from "react"
import { motion } from "framer-motion"

import { cn } from "@/lib/utils"
import { LoadingSpinner } from "@/app/_components/LoadingSpinner"
import { SortChips } from "@/app/_components/SortChips"
import type { SortDirection } from "@/app/types/DownloadsOptions"

/** Shared by every card grid, so column counts stay consistent across surfaces. */
export const GRID_CLASS =
  "grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 p-2"

export type CardGridProps<T> = {
  rows: T[]
  loading: boolean
  emptyMessage: string
  getRowKey: (row: T) => React.Key
  renderCard: (row: T, index: number) => React.ReactNode
  sortBy?: string | null
  sortDirection?: SortDirection
  onSort?: (column: string) => void
  sortOptions?: { key: string; label: string }[]
  className?: string
}

/**
 * Responsive card grid with an optional sort strip.
 *
 * The sort strip renders above the loading and empty states too, so it never
 * disappears out from under a user mid-interaction.
 */
export function CardGrid<T>({
  rows,
  loading,
  emptyMessage,
  getRowKey,
  renderCard,
  sortBy,
  sortDirection,
  onSort,
  sortOptions,
  className,
}: CardGridProps<T>) {
  const sortBar = onSort ? (
    <SortChips
      sortBy={sortBy ?? null}
      sortDirection={sortDirection ?? null}
      onSort={onSort}
      options={sortOptions}
      className="px-2 pt-2 pb-1"
    />
  ) : null

  if (loading && rows.length === 0) {
    return (
      <>
        {sortBar}
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      </>
    )
  }

  if (rows.length === 0) {
    return (
      <>
        {sortBar}
        <div className="p-8 text-center text-text-muted font-mono">
          {emptyMessage}
        </div>
      </>
    )
  }

  return (
    <>
      {sortBar}
      <div className={cn(GRID_CLASS, className)}>
        {rows.map((row, index) => (
          <React.Fragment key={getRowKey(row)}>
            {renderCard(row, index)}
          </React.Fragment>
        ))}
      </div>
    </>
  )
}

/**
 * The shared card chrome: entrance animation, hover border, and a thumbnail
 * region that action overlays and badges position against.
 */
export function CardShell({
  index,
  onClick,
  thumbnail,
  /**
   * Badges, action overlays and progress bars. Rendered *after* the theme tint
   * so the tint darkens only the image — passing these via `thumbnail` would
   * put them underneath it.
   */
  thumbnailOverlay,
  children,
  className,
}: {
  index: number
  onClick?: () => void
  thumbnail: React.ReactNode
  thumbnailOverlay?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2, delay: index * 0.03 }}
      onClick={onClick}
      className={cn(
        "group cursor-pointer rounded-lg border border-border bg-bg-base hover:border-matrix/40 hover:bg-bg-surface/50 transition-all duration-200 overflow-hidden flex flex-col",
        className,
      )}
    >
      <div className="relative aspect-video bg-bg-surface overflow-hidden isolate">
        {thumbnail}
        {/* Theme tint overlay (toggled via data-thumbnail-tint) */}
        <div className="thumb-tint" aria-hidden />
        {thumbnailOverlay}
      </div>
      <div className="p-2 flex flex-col gap-1 flex-1">{children}</div>
    </motion.div>
  )
}

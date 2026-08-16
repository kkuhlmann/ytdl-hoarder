"use client"

import React from "react"
import { QueueListIcon } from "@heroicons/react/20/solid"

import { CardShell } from "@/app/_components/data/CardGrid"
import { CardActionOverlay } from "@/app/_components/data/CardActionOverlay"
import { Collage } from "@/app/_components/data/Thumb"
import { formatDurationCompact } from "@/app/utils"
import type { Playlist } from "@/app/types/PlaylistOptions"

export function PlaylistCard({
  playlist,
  index,
  onClick,
  actions,
}: {
  playlist: Playlist
  index: number
  onClick?: () => void
  actions: React.ReactNode
}) {
  return (
    <CardShell
      index={index}
      onClick={onClick}
      thumbnail={<Collage mediaIds={playlist.sample_media_ids ?? []} />}
      thumbnailOverlay={
        <>
          <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-black/75 text-[11px] font-mono text-matrix leading-none">
            <QueueListIcon className="h-3 w-3" />
            {playlist.media_count}
          </span>
          <CardActionOverlay actions={actions} />
        </>
      }
    >
      <h3
        className="text-sm text-text-primary font-medium leading-tight line-clamp-2 min-h-8.5"
        title={playlist.name}
      >
        {playlist.name}
      </h3>

      <div className="flex items-center gap-1.5 text-[11px] text-text-secondary font-mono flex-wrap mt-auto">
        <span className="text-matrix">{playlist.media_count} items</span>
        {playlist.total_duration > 0 && (
          <>
            <span className="text-text-muted">·</span>
            <span>{formatDurationCompact(playlist.total_duration)}</span>
          </>
        )}
      </div>
    </CardShell>
  )
}

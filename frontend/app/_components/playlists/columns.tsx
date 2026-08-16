"use client"

import { LinkIcon } from "@heroicons/react/20/solid"

import type { Column } from "@/app/_components/data/DataTable"
import {
  formatDuration,
  formatRelativeTime,
  getFullTimestamp,
} from "@/app/utils"
import type { Playlist } from "@/app/types/PlaylistOptions"

const monoCell = "text-xs md:text-sm text-text-muted font-mono"

const timestampCell = (value: string | undefined) => (
  <span
    className={`${monoCell} cursor-help`}
    title={value ? getFullTimestamp(value) : undefined}
  >
    {value ? formatRelativeTime(value) : "-"}
  </span>
)

/** Where a playlist came from: an imported YouTube playlist, or hand-made. */
export function PlaylistSource({ playlist }: { playlist: Playlist }) {
  if (playlist.source_url?.includes("youtube.com")) {
    return (
      <a
        href={playlist.source_url}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-1 text-xs font-mono text-matrix hover:underline"
        title={playlist.source_url}
      >
        <LinkIcon className="h-3.5 w-3.5" />
        YouTube
      </a>
    )
  }
  return <span className="text-xs font-mono text-text-muted">Manual</span>
}

export function buildPlaylistColumns({
  renderActions,
  actionsLabel,
}: {
  renderActions: (playlist: Playlist) => React.ReactNode
  actionsLabel: React.ReactNode
}): Column<Playlist>[] {
  return [
    {
      key: "name",
      label: "Name",
      sortable: true,
      mobile: "title",
      renderMobile: (playlist) => playlist.name,
      // No max-w cap: pinning a width here forces the whole table wider than a
      // phone and makes it scroll sideways. Truncation handles long names instead.
      render: (playlist) => (
        <div className="min-w-0">
          <span
            className="block truncate text-xs md:text-sm text-text-primary"
            title={playlist.name}
          >
            {playlist.name}
          </span>
          {playlist.description && (
            <span
              className="block truncate text-[11px] text-text-muted"
              title={playlist.description}
            >
              {playlist.description}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "source_url",
      label: "Source",
      breakpoint: "lg",
      mobile: "hidden",
      render: (playlist) => <PlaylistSource playlist={playlist} />,
    },
    {
      key: "media_count",
      label: "Items",
      mobile: "meta",
      mobileOrder: 1,
      renderMobile: (playlist) => `${playlist.media_count} items`,
      render: (playlist) => (
        <span className="text-xs md:text-sm font-mono text-matrix">
          {playlist.media_count}
        </span>
      ),
    },
    {
      key: "total_duration",
      label: "Duration",
      breakpoint: "md",
      mobile: "meta",
      mobileOrder: 2,
      renderMobile: (playlist) => formatDuration(playlist.total_duration),
      render: (playlist) => (
        <span className={monoCell}>{formatDuration(playlist.total_duration)}</span>
      ),
    },
    {
      key: "created_at",
      label: "Created",
      sortable: true,
      breakpoint: "lg",
      mobile: "hidden",
      render: (playlist) => timestampCell(playlist.created_at),
    },
    {
      key: "updated_at",
      label: "Updated",
      sortable: true,
      breakpoint: "lg",
      mobile: "hidden",
      render: (playlist) => timestampCell(playlist.updated_at),
    },
    {
      key: "actions",
      label: actionsLabel,
      stopRowClick: true,
      mobile: "hidden",
      render: (playlist) => (
        <div className="flex items-center gap-1 [&_svg]:h-4 [&_svg]:w-4">
          {renderActions(playlist)}
        </div>
      ),
    },
  ]
}

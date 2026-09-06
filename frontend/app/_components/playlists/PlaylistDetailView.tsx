"use client"

import { useCallback, useState } from "react"
import axios from "axios"
import toast from "react-hot-toast"
import {
  Bars2Icon,
  ChevronUpIcon,
  ChevronDownIcon,
  ChevronDoubleUpIcon,
  ChevronDoubleDownIcon,
  MinusCircleIcon,
} from "@heroicons/react/20/solid"
import { TrashIcon as TrashOutlineIcon } from "@heroicons/react/24/outline"

import { Button } from "@/components/ui/button"
import { MediaListView } from "@/app/_components/media/MediaListView"
import {
  MediaBulkActions,
  useMediaBulkSelection,
} from "@/app/_components/media/MediaBulkActions"
import { ConfirmDialog } from "@/app/_components/ConfirmDialog"
import { positionColumn } from "@/app/_components/media/columns"
import { ViewToggle } from "@/app/_components/ViewToggle"
import { PlaybackControls } from "@/app/_components/PlaybackControls"
import { useViewMode } from "@/app/_hooks/useViewMode"
import { useResumePlayback } from "@/app/_hooks/useResumePlayback"
import type { ActionDescriptor } from "@/app/_components/data/ActionList"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"
import { apiUrl } from "@/app/lib/api"
import type { Download, SortDirection } from "@/app/types/DownloadsOptions"
import type { PlaylistTrack } from "@/app/types/PlaylistOptions"

/** Sort fields offered on mobile, where column headers aren't available. */
export const PLAYLIST_TRACK_SORT_OPTIONS = [
  { key: "position", label: "Position" },
  { key: "added_at", label: "Added" },
  { key: "duration", label: "Duration" },
  { key: "rating", label: "Rating" },
  { key: "release_timestamp", label: "Released" },
  { key: "last_accessed", label: "Last Watched" },
]

type PlaylistDetailViewProps = {
  playlistId: number
  playlistName: string
  tracks: PlaylistTrack[]
  loading: boolean
  /** Total across all pages — the move-down arrow needs the real last position. */
  totalTracks: number
  sortBy: string
  sortDirection: SortDirection
  onSort: (column: string) => void
  onTracksChanged: () => void
  onPlaylistDeleted: () => void
  onVideoPlayback?: () => void
  /** Opens the clip editor for a track. Omit and the clip action is inert. */
  onClip?: (track: Download) => void
  patchRow: (mediaDetailsId: number, patch: Partial<Download>) => void
  /** Optimistic within-page move, applied before the request goes out. */
  reorderTracks: (fromIndex: number, toIndex: number) => void
  /** Rollback, for a move the server rejected. */
  restoreTracks: (tracks: PlaylistTrack[]) => void
}

export function PlaylistDetailView({
  playlistId,
  playlistName,
  tracks,
  loading,
  totalTracks,
  sortBy,
  sortDirection,
  onSort,
  onTracksChanged,
  onPlaylistDeleted,
  onVideoPlayback,
  onClip,
  patchRow,
  reorderTracks,
  restoreTracks,
}: PlaylistDetailViewProps) {
  const { playPlaylist, mediaPlayer, syncPlaylistQueue, setQueueResume } = useMediaPlayer()
  const [viewMode, setViewMode] = useViewMode("playlistDetail")
  const [resumeEnabled, setResumeEnabled] = useResumePlayback(playlistId)
  const bulk = useMediaBulkSelection(tracks)
  const [showPlaylistDelete, setShowPlaylistDelete] = useState(false)
  const [showBulkRemove, setShowBulkRemove] = useState(false)
  const [bulkLoading, setBulkLoading] = useState(false)

  // Reordering only makes sense while the view is in playlist order. Sorting by
  // any other column leaves the end-stop actions visible but disabled, rather
  // than hidden: hiding them would change the actions column's width per sort
  // mode and make the fixed header icon legend lie about what's below it. The
  // drag handle does go away, but it lives in the fixed-width # column.
  const reorderEnabled = sortBy === "position" && sortDirection === "asc"

  const startPlayback = useCallback(
    async (track: PlaylistTrack) => {
      if (!track.file_path) {
        toast.error("Media file not available")
        return
      }
      // Awaited: the player must have set videoVisible before the parent
      // decides whether to swap in the inline video player.
      await playPlaylist(playlistId, playlistName, false, track.media_details_id, resumeEnabled)
      if (track.media_type === "VIDEO") onVideoPlayback?.()
    },
    [playPlaylist, playlistId, playlistName, onVideoPlayback, resumeEnabled],
  )

  const toggleResume = useCallback(
    (next: boolean) => {
      setResumeEnabled(next)
      setQueueResume(playlistId, next)
    },
    [setResumeEnabled, setQueueResume, playlistId],
  )

  const handlePlayAll = async () => {
    const firstPlayable = tracks.find((t) => t.file_path)
    if (!firstPlayable) {
      toast.error("No playable tracks in this playlist")
      return
    }
    await playPlaylist(playlistId, playlistName, false, firstPlayable.media_details_id, resumeEnabled)
    if (firstPlayable.media_type === "VIDEO") onVideoPlayback?.()
  }

  const handleShufflePlay = async () => {
    const playable = tracks.filter((t) => t.file_path)
    if (playable.length === 0) {
      toast.error("No playable tracks in this playlist")
      return
    }
    const random = playable[Math.floor(Math.random() * playable.length)]
    await playPlaylist(playlistId, playlistName, true, random.media_details_id, resumeEnabled)
    if (random.media_type === "VIDEO") onVideoPlayback?.()
  }

  /**
   * A jump to an absolute position, which can land on another page. Refetches,
   * and says where the track went: without that, a row leaving the page reads
   * as it simply vanishing.
   */
  const reorder = async (mediaId: number, newPosition: number) => {
    try {
      await axios.patch(
        apiUrl(`/playlists/${playlistId}/media/${mediaId}/reorder`),
        { new_position: newPosition },
      )
      toast.success(`Moved to #${newPosition}`)
      onTracksChanged()
      syncPlaylistQueue(playlistId)
    } catch {
      toast.error("Failed to reorder")
    }
  }

  /**
   * A drag, which can only land somewhere already on screen.
   *
   * No toast and no table refetch on success, unlike `reorder`: you watched the
   * row land, and the optimistic renumbering already matches what the server
   * computed, so a refetch would only flash the loading path. The playback queue
   * still resyncs — it holds the whole playlist, not this page, so the optimistic
   * move can't be replayed onto it.
   */
  const handleDragReorder = async (fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return
    const track = tracks[fromIndex]
    // The playlist-wide position, not the array index: a page is a window into
    // a global 1..N sequence, so index 0 of page 3 is position 51.
    const newPosition = tracks[toIndex].position
    // Props are captured before the optimistic setState lands, so this is
    // already the pre-move array.
    const snapshot = tracks

    reorderTracks(fromIndex, toIndex)
    try {
      await axios.patch(
        apiUrl(`/playlists/${playlistId}/media/${track.media_details_id}/reorder`),
        { new_position: newPosition },
      )
      syncPlaylistQueue(playlistId)
    } catch {
      toast.error("Failed to reorder")
      restoreTracks(snapshot)
    }
  }

  const removeTrack = async (mediaId: number) => {
    try {
      await axios.delete(apiUrl(`/playlists/${playlistId}/media/${mediaId}`))
      toast.success("Removed from playlist")
      onTracksChanged()
      syncPlaylistQueue(playlistId)
    } catch {
      toast.error("Failed to remove from playlist")
    }
  }

  const removeSelected = async () => {
    setBulkLoading(true)
    try {
      const response = await axios.post(
        apiUrl(`/playlists/${playlistId}/media/bulk-remove`),
        { media_details_ids: Array.from(bulk.selectedIds) },
      )
      toast.success(`Removed ${response.data.removed} from playlist`)
      bulk.clear()
      onTracksChanged()
      syncPlaylistQueue(playlistId)
    } catch {
      toast.error("Failed to remove from playlist")
    } finally {
      setBulkLoading(false)
      setShowBulkRemove(false)
    }
  }

  const deletePlaylist = async () => {
    try {
      await axios.delete(apiUrl(`/playlists/${playlistId}`))
      toast.success("Playlist deleted")
      onPlaylistDeleted()
    } catch {
      toast.error("Failed to delete playlist")
    }
  }

  // Positions are contiguous 1..N (the backend renumbers on every removal), so
  // these compare against the playlist total rather than the current page —
  // which is what lets a track move across a page boundary.
  const reorderButton = {
    buttonClassName: "hover:bg-matrix/20",
    iconClassName: "text-text-muted hover:text-matrix",
  }

  const moveUp: ActionDescriptor<PlaylistTrack> = {
    key: "moveUp",
    title: "Move up",
    icon: ChevronUpIcon,
    disabled: (track) => !reorderEnabled || track.position <= 1,
    disabledTitle: reorderEnabled ? "Already first" : "Sort by # to reorder",
    onClick: (track) => reorder(track.media_details_id, track.position - 1),
    ...reorderButton,
  }

  const moveDown: ActionDescriptor<PlaylistTrack> = {
    key: "moveDown",
    title: "Move down",
    icon: ChevronDownIcon,
    disabled: (track) => !reorderEnabled || track.position >= totalTracks,
    disabledTitle: reorderEnabled ? "Already last" : "Sort by # to reorder",
    onClick: (track) => reorder(track.media_details_id, track.position + 1),
    ...reorderButton,
  }

  const moveToTop: ActionDescriptor<PlaylistTrack> = {
    key: "moveToTop",
    title: "Move to top",
    icon: ChevronDoubleUpIcon,
    disabled: (track) => !reorderEnabled || track.position <= 1,
    disabledTitle: reorderEnabled ? "Already first" : "Sort by # to reorder",
    onClick: (track) => reorder(track.media_details_id, 1),
    ...reorderButton,
  }

  const moveToBottom: ActionDescriptor<PlaylistTrack> = {
    key: "moveToBottom",
    title: "Move to bottom",
    icon: ChevronDoubleDownIcon,
    disabled: (track) => !reorderEnabled || track.position >= totalTracks,
    disabledTitle: reorderEnabled ? "Already last" : "Sort by # to reorder",
    onClick: (track) => reorder(track.media_details_id, totalTracks),
    ...reorderButton,
  }

  const removeFromPlaylist: ActionDescriptor<PlaylistTrack> = {
    key: "removeFromPlaylist",
    title: "Remove from playlist",
    icon: MinusCircleIcon,
    onClick: (track) => removeTrack(track.media_details_id),
    buttonClassName: "hover:bg-status-error/20",
    iconClassName: "text-text-muted hover:text-status-error",
  }

  // The grid has no drag target — its cards reflow at every breakpoint and the
  // order doesn't read as a list — so it keeps the one-step arrows. The table
  // and the mobile card list trade them for dragging plus the two end stops.
  // Either way it's three icons, so the header legend keeps its width.
  const trackActions: ActionDescriptor<PlaylistTrack>[] =
    viewMode === "grid"
      ? [moveUp, moveDown, removeFromPlaylist]
      : [moveToTop, moveToBottom, removeFromPlaylist]

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3">
        <div className="flex items-center gap-2">
          <PlaybackControls
            onPlayAll={handlePlayAll}
            onShuffle={handleShufflePlay}
            playAllTitle="Play this playlist in order"
            shuffleTitle="Shuffle this playlist"
            resume={{ checked: resumeEnabled, onChange: toggleResume }}
          />
          <ViewToggle mode={viewMode} onChange={setViewMode} />
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowPlaylistDelete(true)}
          className="gap-1.5 text-status-error hover:text-status-error"
        >
          <TrashOutlineIcon className="h-4 w-4" />
          <span className="hidden sm:inline">Delete Playlist</span>
        </Button>
      </div>

      <MediaBulkActions
        selectedItems={bulk.selectedItems}
        onClearSelection={bulk.clear}
        onRefresh={onTracksChanged}
        extraActions={[
          {
            key: "removeFromPlaylist",
            label: "Remove from Playlist",
            loadingLabel: "Removing...",
            onClick: () => setShowBulkRemove(true),
            isLoading: bulkLoading,
          },
        ]}
      />

      <div className="rounded-lg border border-border overflow-hidden">
        <MediaListView
          viewMode={viewMode}
          rows={tracks}
          loading={loading}
          status="COMPLETE"
          onRefresh={onTracksChanged}
          patchRow={patchRow}
          sortBy={sortBy}
          sortDirection={sortDirection}
          onSort={onSort}
          sortOptions={PLAYLIST_TRACK_SORT_OPTIONS}
          onRowClick={startPlayback}
          onClip={onClip}
          extraActions={trackActions}
          leadingColumns={[
            positionColumn<PlaylistTrack>({ draggable: viewMode === "table" }),
          ]}
          emptyMessage="No tracks in this playlist"
          showPlaybackProgress={resumeEnabled}
          // Derived from the player, not from the last row clicked, so autoplay
          // carries the highlight to the next track. The playlistId check scopes
          // it to this playlist — a track shared with the playing one shouldn't
          // light up here.
          rowClassName={(track) =>
            (mediaPlayer.audioVisible || mediaPlayer.videoVisible) &&
            mediaPlayer.playlistId === playlistId &&
            mediaPlayer.media_details_id === track.media_details_id
              ? "bg-matrix/10"
              : undefined
          }
          selection={bulk.selection}
          dragAndDrop={{
            // Always supplied, gated by `disabled`: dropping the prop instead
            // would remount the list on every sort change.
            disabled: !reorderEnabled,
            onReorder: handleDragReorder,
            renderOverlay: (track) => (
              <div className="pointer-events-none flex scale-[1.02] items-center gap-2 rounded-md border border-matrix/40 bg-bg-elevated px-3 py-2 shadow-glow">
                <Bars2Icon className="h-4 w-4 shrink-0 text-matrix" />
                <span className="shrink-0 font-mono text-xs text-matrix">
                  {track.position}
                </span>
                <span className="max-w-[60vw] truncate text-sm text-text-primary">
                  {track.title}
                </span>
              </div>
            ),
          }}
        />
      </div>

      {showPlaylistDelete && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setShowPlaylistDelete(false)}
          icon={<TrashOutlineIcon className="h-5 w-5 text-status-error" />}
          title="Delete Playlist"
          description={`Delete "${playlistName}"? The media itself is not deleted.`}
          descriptionClassName="text-status-error/80"
          confirmLabel="Delete"
          onConfirm={() => {
            deletePlaylist()
            setShowPlaylistDelete(false)
          }}
          onCancel={() => setShowPlaylistDelete(false)}
        />
      )}

      {showBulkRemove && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setShowBulkRemove(false)}
          icon={<TrashOutlineIcon className="h-5 w-5 text-status-error" />}
          title="Remove from Playlist"
          description={`Remove ${bulk.selectedItems.length} track${bulk.selectedItems.length === 1 ? "" : "s"} from "${playlistName}"? The media itself is not deleted.`}
          descriptionClassName="text-status-error/80"
          confirmLabel="Remove"
          onConfirm={removeSelected}
          onCancel={() => setShowBulkRemove(false)}
        />
      )}
    </>
  )
}

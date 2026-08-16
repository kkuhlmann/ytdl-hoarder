"use client"

import { useState, useEffect, useMemo, useCallback, useRef } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import axios from "axios"
import toast from "react-hot-toast"
import { arrayMove } from "@dnd-kit/sortable"
import {
  Bars2Icon,
  BookmarkIcon,
  PlayIcon,
  ArrowsRightLeftIcon,
} from "@heroicons/react/20/solid"

import { Button } from "@/components/ui/button"
import { TagFilter } from "@/app/_components/TagFilter"
import { CreatePlaylistDialog } from "@/app/_components/CreatePlaylistDialog"
import { MediaListView } from "@/app/_components/media/MediaListView"
import { positionColumn } from "@/app/_components/media/columns"
import { ViewToggle } from "@/app/_components/ViewToggle"
import { Switch } from "@/components/ui/switch"
import { useViewMode } from "@/app/_hooks/useViewMode"
import { useResumePlayback } from "@/app/_hooks/useResumePlayback"
import {
  useMediaPlayer,
  TAG_MIX_PLAYLIST_ID,
} from "@/app/context/MediaPlayerContext"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import type {
  Download,
  SortDirection,
  TagInfo,
} from "@/app/types/DownloadsOptions"
import type { PlaylistMedia } from "@/app/types/PlaylistOptions"

/**
 * A tag mix track: a full media row plus the queue fields.
 *
 * Keeping the whole row is what lets the mix render with the same components
 * (and the same actions) as the media library.
 */
type MixTrack = Download & {
  position: number
  playlist_id: number
  added_at: string
}

/** Positions are the display index, so they're reassigned after every move. */
const renumber = (rows: MixTrack[]): MixTrack[] =>
  rows.map((row, i) => ({ ...row, position: i + 1 }))

/**
 * Re-applies a hand-arranged order to a freshly fetched mix.
 *
 * Tracks that newly match the tags have no saved rank and sort to the end,
 * keeping the fetch's newest-first order among themselves — `sort` is stable,
 * so equal ranks don't shuffle.
 */
const applyStickyOrder = (
  rows: MixTrack[],
  order: number[] | null,
): MixTrack[] => {
  if (!order) return rows
  const rank = new Map(order.map((id, i) => [id, i]))
  return [...rows].sort(
    (a, b) =>
      (rank.get(a.media_details_id) ?? Infinity) -
      (rank.get(b.media_details_id) ?? Infinity),
  )
}

type TagMixViewProps = {
  selectedTagIds: number[]
  onChangeTags: (tagIds: number[]) => void
  // Notify parent to show the inline video player when a VIDEO track starts.
  onVideoPlayback?: () => void
  /** Opens the clip editor for a track. Omit and the clip action is inert. */
  onClip?: (track: Download) => void
}

export function TagMixView({
  selectedTagIds,
  onChangeTags,
  onVideoPlayback,
  onClip,
}: TagMixViewProps) {
  const { mediaPlayer, playMediaQueue, replaceQueue, setQueueResume } = useMediaPlayer()
  const [resumeEnabled, setResumeEnabled] = useResumePlayback(TAG_MIX_PLAYLIST_ID)

  const [allTags, setAllTags] = useState<TagInfo[]>([])
  const [media, setMedia] = useState<MixTrack[]>([])
  const [viewMode, setViewMode] = useViewMode("playlistDetail")
  const [sortBy, setSortBy] = useState<string | null>("position")
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc")
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)

  /**
   * A hand-arranged order, by media id.
   *
   * A mix has no rows of its own — `position` is just the index the fetch came
   * back in — so there is nowhere on the server to write a dragged order to.
   * Holding it here and re-applying it after each fetch is what keeps a
   * rearranged mix from snapping back every time a rating or tag edit triggers
   * a refresh. It is deliberately not persisted: changing the tag selection or
   * reloading the page starts over.
   */
  const orderOverride = useRef<number[] | null>(null)

  const tagKey = selectedTagIds.join(",")

  // Declared before the fetch effect so a tag change clears the old arrangement
  // in the same commit that refetches, rather than one render later.
  useEffect(() => {
    orderOverride.current = null
  }, [tagKey])

  const loadTags = useCallback(() => {
    axios
      .get(apiUrl(mediaApi.allTags))
      .then((response) => setAllTags(response.data))
      .catch(() => {})
  }, [])

  // Load the user's tags for the picker (same source as the Downloads view).
  useEffect(() => {
    loadTags()
  }, [loadTags])

  // Human-readable mix name (e.g. "trance + house") — used as the footer "album".
  const mixName = useMemo(() => {
    const names = allTags
      .filter((t) => selectedTagIds.includes(t.id))
      .map((t) => t.name)
    return names.length > 0 ? names.join(" + ") : "Tag Mix"
  }, [allTags, selectedTagIds])

  /**
   * The backend returns media matching ANY of the selected tags (OR logic),
   * newest first.
   */
  const loadMix = useCallback(
    (signal?: AbortSignal) => {
      if (selectedTagIds.length === 0) {
        setMedia([])
        return
      }
      return axios
      .get(apiUrl(mediaApi.list), {
        params: {
          tag_ids: selectedTagIds.join(","),
          page: 1,
          page_size: 1000,
          sort_direction: "desc",
        },
        signal,
      })
      .then((response) => {
        const records: (Download & { id: number })[] = response.data.records ?? []
        // Only playable rows can join the queue. The whole row is kept; the
        // list endpoint keys on `id`, which the client exposes as
        // media_details_id (same mapping the media library does).
        const rows = records
          .filter((row) => row.file_path)
          .map((row) => ({
            ...row,
            media_details_id: row.id,
            playlist_id: TAG_MIX_PLAYLIST_ID,
            position: 0,
            added_at: row.downloaded_at || row.created_at || "",
          }))
        setMedia(renumber(applyStickyOrder(rows, orderOverride.current)))
      })
      .catch(() => {})
    },
    [selectedTagIds],
  )

  const { isLoading: loading, refetch: reloadMix } = useFetchEffect(loadMix, [loadMix])

  const patchRow = useCallback(
    (mediaId: number, patch: Partial<Download>) =>
      setMedia((rows) =>
        rows.map((r) =>
          r.media_details_id === mediaId ? { ...r, ...patch } : r,
        ),
      ),
    [],
  )

  const startFrom = useCallback(
    (targetMediaDetailsId: number, shuffle: boolean) => {
      if (media.length === 0) return
      playMediaQueue({
        playlistId: TAG_MIX_PLAYLIST_ID,
        playlistName: mixName,
        media: media as unknown as PlaylistMedia[],
        shuffle,
        targetMediaDetailsId,
        resume: resumeEnabled,
      })
      const started = media.find(
        (m) => m.media_details_id === targetMediaDetailsId,
      )
      if (started?.media_type === "VIDEO") onVideoPlayback?.()
    },
    [media, mixName, playMediaQueue, onVideoPlayback, resumeEnabled],
  )

  const toggleResume = useCallback(
    (next: boolean) => {
      setResumeEnabled(next)
      setQueueResume(TAG_MIX_PLAYLIST_ID, next)
    },
    [setResumeEnabled, setQueueResume],
  )

  /**
   * Reorders `media` itself rather than the sorted view, so the playback queue
   * — which `startFrom` builds from `media` — follows what you rearranged.
   *
   * Safe to index into `media` because dragging is gated on `sortBy` being
   * "position", which is exactly when `sortedMedia` returns `media` unchanged.
   *
   * The new order is computed outside the setState updater so it can also be
   * pushed into an already-running queue: updaters must stay pure, so the
   * replaceQueue call cannot live inside one.
   */
  const reorderMix = useCallback(
    (fromIndex: number, toIndex: number) => {
      if (
        fromIndex === toIndex ||
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= media.length ||
        toIndex >= media.length
      ) {
        return
      }
      const next = renumber(arrayMove(media, fromIndex, toIndex))
      orderOverride.current = next.map((row) => row.media_details_id)
      setMedia(next)
      // Every mix shares the one sentinel playlist id, so replaceQueue's own
      // id check can't tell two mixes apart. The name is the mix's identity
      // (it's derived from the tag selection) — without this, dragging here
      // after changing tags would swap a running mix out for this one.
      if (mediaPlayer.playlistName === mixName) {
        replaceQueue(TAG_MIX_PLAYLIST_ID, next as unknown as PlaylistMedia[])
      }
    },
    [media, mediaPlayer.playlistName, mixName, replaceQueue],
  )

  /**
   * Materializes the mix as a real playlist, which unlike a mix does persist an
   * order. The bulk endpoint assigns positions sequentially from the order it's
   * given, so the saved playlist matches what's on screen.
   */
  const saveAsPlaylist = useCallback(
    async (playlist: { id: number; name: string }) => {
      const response = await axios.post(
        apiUrl(`/playlists/${playlist.id}/media/bulk`),
        { media_details_ids: media.map((row) => row.media_details_id) },
      )
      const { added = 0, no_access = 0 } = response.data ?? {}
      toast.success(
        `Saved ${added} track${added === 1 ? "" : "s"} to "${playlist.name}"` +
          (no_access > 0 ? ` (${no_access} skipped, no access)` : ""),
      )
    },
    [media],
  )

  const handleRowClick = (item: MixTrack) => {
    if (!item.file_path) {
      toast.error("Media file not available")
      return
    }
    startFrom(item.media_details_id, false)
  }

  const handlePlayAll = () => {
    if (media.length === 0) return
    startFrom(media[0].media_details_id, false)
  }

  const handleShuffle = () => {
    if (media.length === 0) return
    const random = media[Math.floor(Math.random() * media.length)]
    startFrom(random.media_details_id, true)
  }

  const handleSort = (column: string) => {
    // A mix has no persisted order to return to, so the cycle is just desc→asc.
    const direction: SortDirection =
      sortBy === column && sortDirection === "desc" ? "asc" : "desc"
    setSortBy(column)
    setSortDirection(direction)
  }

  // Client-side: the mix is already fully loaded (page_size=1000).
  const sortedMedia = useMemo(() => {
    if (!sortBy || sortBy === "position") return media
    const factor = sortDirection === "asc" ? 1 : -1
    return [...media].sort((a, b) => {
      const av = a[sortBy as keyof MixTrack]
      const bv = b[sortBy as keyof MixTrack]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return av < bv ? -factor : av > bv ? factor : 0
    })
  }, [media, sortBy, sortDirection])

  const emptyMessage =
    selectedTagIds.length === 0
      ? "Pick one or more tags to build a mix."
      : "No media matches these tags."

  return (
    <>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 overflow-x-auto scrollbar-none [&::-webkit-scrollbar]:hidden">
        <div className="flex items-center gap-3 shrink-0">
          <TagFilter
            allTags={allTags}
            selectedTagIds={selectedTagIds}
            onChange={onChangeTags}
          />
          {selectedTagIds.length > 0 && !loading && (
            <span className="text-sm text-text-secondary font-mono">
              → <span className="text-matrix">{media.length}</span> matching{" "}
              {media.length === 1 ? "track" : "tracks"}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <ViewToggle mode={viewMode} onChange={setViewMode} />
          <label
            className="flex items-center gap-2 cursor-pointer select-none"
            title="Resume each track from where you left off, and show how far through each one you are"
          >
            <Switch checked={resumeEnabled} onCheckedChange={toggleResume} />
            <span className="hidden sm:inline font-mono text-xs text-text-secondary">
              Resume
            </span>
          </label>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSaveDialogOpen(true)}
            disabled={media.length === 0}
            className="gap-2"
            title="Save this mix, in its current order, as a playlist"
          >
            <BookmarkIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Save as Playlist</span>
          </Button>
          <Button
            variant="matrix"
            size="sm"
            onClick={handlePlayAll}
            disabled={media.length === 0}
            className="gap-2"
          >
            <PlayIcon className="h-4 w-4" />
            Play All
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleShuffle}
            disabled={media.length === 0}
            className="gap-2"
          >
            <ArrowsRightLeftIcon className="h-4 w-4" />
            Shuffle
          </Button>
        </div>
      </div>

      <div className="rounded-lg border border-border overflow-hidden">
        <MediaListView
          viewMode={viewMode}
          rows={sortedMedia}
          loading={loading}
          status="COMPLETE"
          onRefresh={reloadMix}
          patchRow={patchRow}
          sortBy={sortBy}
          sortDirection={sortDirection}
          onSort={handleSort}
          allTags={allTags}
          onTagsChange={loadTags}
          onRowClick={handleRowClick}
          onClip={onClip}
          showPlaybackProgress={resumeEnabled}
          leadingColumns={[
            positionColumn<MixTrack>({ draggable: viewMode === "table" }),
          ]}
          dragAndDrop={{
            // Only coherent while the view is in mix order — any other sort is
            // a derived view, so a drop index wouldn't map back to `media`.
            disabled: sortBy !== "position",
            onReorder: reorderMix,
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
          emptyMessage={emptyMessage}
          rowClassName={(item) =>
            mediaPlayer.playlistId === TAG_MIX_PLAYLIST_ID &&
            mediaPlayer.media_details_id === item.media_details_id
              ? "bg-matrix/10"
              : undefined
          }
        />
      </div>

      <CreatePlaylistDialog
        open={saveDialogOpen}
        onOpenChange={setSaveDialogOpen}
        onPlaylistCreated={() => {}}
        title="Save Mix as Playlist"
        submitLabel="Save"
        defaultName={mixName}
        onCreated={saveAsPlaylist}
      />
    </>
  )
}

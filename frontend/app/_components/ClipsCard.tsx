"use client"

import { useState, useEffect, useCallback } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { useTriStateSort } from "@/app/_hooks/useTriStateSort"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { ClipsTable } from "@/app/_components/ClipsTable"
import { TablePagination } from "@/app/_components/TablePagination"
import { VideoPlayer } from "@/app/_components/MediaPlayer"
import { ClipStats, Clip, SortDirection } from "@/app/types/ClipsOptions"
import { ClipsBulkActionsBar } from "@/app/_components/ClipsBulkActionsBar"
import { ConfirmDialog } from "@/app/_components/ConfirmDialog"
import { MagnifyingGlassIcon, ArrowLeftIcon } from "@heroicons/react/20/solid"
import { TrashIcon } from "@heroicons/react/24/outline"
import axios from "axios"
import toast from "react-hot-toast"
import { motion } from "framer-motion"
import { apiUrl, downloadBlob } from "@/app/lib/api"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"

type ClipStatsBarProps = {
  stats: ClipStats | null
  loading: boolean
}

function ClipStatsBar({ stats, loading }: ClipStatsBarProps) {
  if (loading && !stats) {
    return (
      <div className="flex gap-4 text-sm text-text-muted font-mono animate-pulse">
        <span>Loading stats...</span>
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="flex gap-4 text-sm font-mono">
      <span className="text-text-secondary">
        Total: <span className="text-matrix">{stats.total_clips}</span>
      </span>
      <span className="text-text-secondary">
        Video: <span className="text-text-primary">{stats.video_clips}</span>
      </span>
      <span className="text-text-secondary">
        Audio: <span className="text-text-primary">{stats.audio_clips}</span>
      </span>
    </div>
  )
}

// Stable identity so an empty selection doesn't re-render the table every pass.
const NO_SELECTION: Set<number> = new Set()

export function ClipsCard() {
  const [tableRows, setTableRows] = useState<Clip[]>([])
  const [pageCount, setPageCount] = useState(0)
  const [pageNumber, setPageNumber] = useState(1)
  const [search, setSearch] = useState("")
  const { sortBy, sortDirection, handleSort } = useTriStateSort()
  const [stats, setStats] = useState<ClipStats | null>(null)
  const [displayVideo, setDisplayVideo] = useState(false)
  const [viewingSource, setViewingSource] = useState(false)
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null)
  // A selection only means anything for the rows it was made on, so it carries
  // the page/search/sort combination it belongs to and stops applying the moment
  // that changes. Deriving the clear beats an effect that re-renders to do it.
  const [selection, setSelection] = useState<{ key: string; ids: Set<number> }>({
    key: "",
    ids: NO_SELECTION,
  })
  const selectionKey = JSON.stringify([pageNumber, search, sortBy, sortDirection])
  const selectedIds = selection.key === selectionKey ? selection.ids : NO_SELECTION
  const setSelectedIds = useCallback(
    (ids: Set<number>) => setSelection({ key: selectionKey, ids }),
    [selectionKey]
  )
  const [bulkActionLoading, setBulkActionLoading] = useState<"delete" | "download" | null>(null)
  const [showBulkDelete, setShowBulkDelete] = useState(false)
  const { openVideoPlayer, closeVideoPlayer } = useMediaPlayer()

  const fetchClips = useCallback(
    async (
      searchQuery: string,
      page: number,
      sortByParam: string | null,
      sortDirectionParam: SortDirection
    ) => {
      const params: Record<string, string | number | null> = {
        page,
        sort_by: sortByParam,
        sort_direction: sortDirectionParam,
      }

      if (searchQuery && searchQuery.length >= 3) {
        params.search = searchQuery
      }

      const response = await axios.get(
        apiUrl('/clips'),
        { params }
      )
      return response.data
    },
    []
  )

  const fetchStats = useCallback(async () => {
    const response = await axios.get(
      apiUrl('/clips/stats')
    )
    return response.data
  }, [])

  const loadStats = useCallback(
    () =>
      fetchStats()
        .then((data) => setStats(data))
        .catch(() => {}),
    [fetchStats]
  )

  const loadClips = useCallback(
    () =>
      fetchClips(search, pageNumber, sortBy, sortDirection)
        .then((data) => {
          setPageCount(data.page_count)
          setTableRows(data.records)
        })
        .catch(() => {}),
    [fetchClips, search, pageNumber, sortBy, sortDirection]
  )

  const { isLoading: loading, refetch: reloadClips } = useFetchEffect(
    loadClips,
    [loadClips],
    { enabled: search.length === 0 || search.length >= 3, pollMs: 10_000 }
  )

  // Only a spinner while there are no stats to show: a 10s poll tick must not
  // blank the numbers.
  const { isLoading: statsFetching, refetch: reloadStats } = useFetchEffect(
    loadStats,
    [loadStats],
    { pollMs: 10_000 }
  )
  const statsLoading = stats === null && statsFetching

  const handleInputChange = (event: { target: { value: string } }) => {
    setSearch(event.target.value)
    setPageNumber(1)
  }

  const handleVideoClipClick = useCallback((clip: Clip) => {
    setSelectedClip(clip)
    setViewingSource(false)
    setDisplayVideo(true)
  }, [])

  const handleJumpToSourceVideo = useCallback((clip: Clip) => {
    setSelectedClip(clip)
    setViewingSource(true)
    setDisplayVideo(true)
  }, [])

  const handleReturnToClips = useCallback(() => {
    setDisplayVideo(false)
    setViewingSource(false)
    setSelectedClip(null)
  }, [])

  const selectedItems = tableRows.filter((clip) => selectedIds.has(clip.id))
  const allSelected =
    tableRows.length > 0 && tableRows.every((clip) => selectedIds.has(clip.id))

  const handleSelectAll = (selected: boolean) => {
    setSelectedIds(selected ? new Set(tableRows.map((clip) => clip.id)) : new Set())
  }

  const handleBulkDelete = async () => {
    setBulkActionLoading("delete")
    try {
      const res = await axios.delete(apiUrl(`/clips/bulk`), {
        data: { clip_ids: selectedItems.map((clip) => clip.id) },
      })
      const removed = (res.data.deleted_count ?? 0) + (res.data.access_removed ?? 0)
      toast.success(`Deleted ${removed} ${removed === 1 ? "clip" : "clips"}`)
      setSelectedIds(new Set())
      setShowBulkDelete(false)
      reloadClips()
      reloadStats()
    } catch {
      toast.error("Failed to delete clips")
    } finally {
      setBulkActionLoading(null)
    }
  }

  const handleDownloadSelected = async () => {
    if (selectedItems.length !== 1) return
    const clip = selectedItems[0]
    if (clip.status !== "COMPLETE" || !clip.file_path) return
    const ext = clip.media_type === "VIDEO" ? "mp4" : "mp3"
    const safeTitle = (clip.title || "clip").replace(/[\\/:*?"<>|]/g, "").trim() || "clip"
    setBulkActionLoading("download")
    try {
      await downloadBlob(`/media/clip/${clip.id}/download`, `${safeTitle}.${ext}`)
      setSelectedIds(new Set())
    } catch {
      toast.error("Failed to download clip")
    } finally {
      setBulkActionLoading(null)
    }
  }

  // Feed the shared media-session metadata so the iOS lock screen shows a thumbnail
  // during clip playback. Artwork comes from the SOURCE media (the clip itself has no
  // thumbnail); the context fills thumbnail_path from /media-details/{id}. Cleared on
  // return/unmount so videoVisible never leaks into the playlist video surface.
  useEffect(() => {
    if (!displayVideo || !selectedClip) return
    openVideoPlayer({
      media_details_id: selectedClip.media_details_id ?? 0,
      title: viewingSource
        ? selectedClip.source_title || selectedClip.title
        : selectedClip.title,
      channel: selectedClip.source_channel ?? "",
      thumbnail_path: undefined,
      duration: selectedClip.duration,
      start_time: viewingSource ? selectedClip.start_time : 0,
    })
    return () => closeVideoPlayer()
  }, [displayVideo, selectedClip, viewingSource, openVideoPlayer, closeVideoPlayer])

  if (displayVideo && selectedClip) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <Card className="mt-4">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <Button
                variant="ghost"
                size="sm"
                onClick={handleReturnToClips}
                className="gap-2"
              >
                <ArrowLeftIcon className="h-4 w-4" />
                Return to Clips
              </Button>
              <CardTitle className="text-lg truncate">
                {viewingSource ? selectedClip.source_title || selectedClip.title : selectedClip.title}
              </CardTitle>
            </div>
          </CardHeader>

          <CardContent>
            {viewingSource ? (
              <VideoPlayer
                id={selectedClip.media_details_id!}
                startTime={selectedClip.start_time}
                isClip={false}
              />
            ) : (
              <VideoPlayer
                id={selectedClip.id}
                duration={selectedClip.duration}
                isClip={true}
              />
            )}
          </CardContent>
        </Card>
      </motion.div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="mt-4">
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <CardTitle className="text-lg">Clips</CardTitle>
            <ClipStatsBar stats={stats} loading={statsLoading} />
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="relative max-w-md">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <Input
              placeholder="Search clips..."
              value={search}
              onChange={handleInputChange}
              className="pl-9"
            />
          </div>

          <ClipsBulkActionsBar
            selectedItems={selectedItems}
            onDelete={() => setShowBulkDelete(true)}
            onDownload={handleDownloadSelected}
            onClearSelection={() => setSelectedIds(new Set())}
            loadingAction={bulkActionLoading}
          />

          <div className="rounded-lg border border-border overflow-hidden">
            <ClipsTable
              tableRows={tableRows}
              loading={loading}
              refreshClips={reloadClips}
              sortBy={sortBy}
              sortDirection={sortDirection}
              onSort={handleSort}
              onVideoClipClick={handleVideoClipClick}
              onJumpToSourceVideo={handleJumpToSourceVideo}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              allSelected={allSelected}
              onSelectAll={handleSelectAll}
            />
          </div>

          <TablePagination
            pageNumber={pageNumber}
            pageCount={pageCount}
            setPageNumber={setPageNumber}
          />
        </CardContent>
      </Card>

      <ConfirmDialog
        open={showBulkDelete}
        onOpenChange={setShowBulkDelete}
        icon={<TrashIcon className="h-5 w-5 text-status-error" />}
        title={`Delete ${selectedItems.length} ${selectedItems.length === 1 ? "Item" : "Items"}`}
        description={`Are you sure you want to delete ${selectedItems.length} selected ${
          selectedItems.length === 1 ? "item" : "items"
        }? This action cannot be undone.`}
        descriptionClassName="text-status-error/80"
        confirmLabel={`Delete ${selectedItems.length} ${selectedItems.length === 1 ? "Item" : "Items"}`}
        loadingLabel="Deleting..."
        isLoading={bulkActionLoading === "delete"}
        onConfirm={handleBulkDelete}
      />
    </motion.div>
  )
}

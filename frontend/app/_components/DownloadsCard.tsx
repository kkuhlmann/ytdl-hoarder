"use client"

import { useState, useEffect, useCallback, useRef, Dispatch, SetStateAction } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { TrashIcon, BookOpenIcon, ArrowLeftIcon, MagnifyingGlassIcon, CalendarIcon, EyeIcon, ForwardIcon, ChevronDownIcon } from "@heroicons/react/20/solid"
import { ArrowDownTrayIcon } from "@heroicons/react/24/outline"
import { MediaListView } from "@/app/_components/media/MediaListView"
import { GroupBySelector } from "@/app/_components/GroupBySelector"
import { ViewToggle } from "@/app/_components/ViewToggle"
import { useViewMode } from "@/app/_hooks/useViewMode"
import { GroupFolderGrid } from "@/app/_components/GroupFolderGrid"
import { GroupBreadcrumb } from "@/app/_components/GroupBreadcrumb"
import { useDownloadGrouping } from "@/app/_hooks/useDownloadGrouping"
import { useElementDuration } from "@/app/_hooks/useElementDuration"
import { useTriStateSort } from "@/app/_hooks/useTriStateSort"
import { MediaBulkActions } from "@/app/_components/media/MediaBulkActions"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"
import { DownloadButton } from "./DownloadButton"
import { TablePagination } from "@/app/_components/TablePagination"
import { VideoPlayer } from "@/app/_components/MediaPlayer"
import { VideoClippingControls } from "@/app/_components/VideoClippingControls"
import { MediaClipEditor } from "@/app/_components/media/MediaClipEditor"
import { Download, DownloadOptionsType, SortDirection, MediaStats, TagInfo, GroupLeafFilter } from "../types/DownloadsOptions"
import { TranscriptSegmentTable } from "./TranscriptSegmentTable"
import { MediaStatsBar } from "./MediaStatsBar"
import { TagFilter } from "./TagFilter"
import { RatingFilter } from "./RatingFilter"
import { StarRating } from "./StarRating"
import { Slider } from "@/components/ui/slider"
import { Separator } from "@/components/ui/separator"
import { motion, AnimatePresence } from "framer-motion"
import { formatDate } from "@/app/utils"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import { saveRating } from "@/app/_hooks/useMediaActions"

// Stable identity so an empty selection doesn't re-render the table every pass.
const NO_SELECTION: Set<number> = new Set()

// Same reason: these are what the key-tagged derivations below fall back to
// when the tag doesn't match, so they must not be fresh literals.
type VideoMetadata = {
  release_timestamp?: string
  access_count?: number
  rating?: number | null
}
const NO_METADATA: VideoMetadata = {}
const NO_SEMANTIC_ROWS: any[] = []

const TRANSCRIPT_TABLE_HEAD = [
  "Score",
  "FTS",
  "Text",
  "Channel",
  "Title",
  "Start",
]

type DownloadsCardProps = {
  fetchDownloads: (
    search: string,
    status: string | null,
    pageNumber: number,
    sortBy?: string | null,
    sortDirection?: SortDirection,
    tagIds?: number[] | null,
    minRating?: number | null,
    groupFilter?: GroupLeafFilter | null
  ) => Promise<any>
  fetchTranscriptSegments: (
    standard_search: string,
    semantic_search: string,
    semanticWeight: number
  ) => Promise<any>
  fetchStats: (search?: string, status?: string) => Promise<MediaStats>
  downloadOptions: DownloadOptionsType
  setDownloadOptions: (downloadOptions: DownloadOptionsType) => void
  status: string
  setStatus: Dispatch<SetStateAction<string>>
  search: string
  setSearch: Dispatch<SetStateAction<string>>
  semanticSearch: string
  setSemanticSearch: Dispatch<SetStateAction<string>>
  semanticWeight: number
  setSemanticWeight: Dispatch<SetStateAction<number>>
}

export function DownloadsCard({
  fetchDownloads,
  fetchTranscriptSegments,
  fetchStats,
  downloadOptions,
  setDownloadOptions,
  status,
  setStatus,
  search,
  setSearch,
  semanticSearch,
  setSemanticSearch,
  semanticWeight,
  setSemanticWeight,
}: DownloadsCardProps) {
  const [tableRows, setTableRows] = useState<any[]>([])
  const [semanticState, setSemanticState] = useState<{ key: string; rows: any[] }>({
    key: "",
    rows: NO_SEMANTIC_ROWS,
  })
  const [pageCount, setPageCount] = useState(0)
  // Tagged with the group folder it was paged within — see below, next to
  // `grouping`, where the two are combined.
  const [page, setPage] = useState<{ leafKey: string | null; n: number }>({
    leafKey: null,
    n: 1,
  })
  // Both the rows and the page reset when the query changes — same
  // value-plus-its-key derivation as `selectedIds` and `pageNumber` above.
  const semanticKey = `${semanticSearch}|${search}|${semanticWeight}`
  const semanticTableRows =
    semanticState.key === semanticKey ? semanticState.rows : NO_SEMANTIC_ROWS
  const [semanticPage, setSemanticPage] = useState<{ key: string; n: number }>({
    key: "",
    n: 1,
  })
  const semanticPageNumber = semanticPage.key === semanticKey ? semanticPage.n : 1
  const setSemanticPageNumber = useCallback(
    (n: number) => setSemanticPage({ key: semanticKey, n }),
    [semanticKey]
  )
  const SEMANTIC_PAGE_SIZE = 15
  const [stats, setStats] = useState<MediaStats | null>(null)

  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([])
  const [minRating, setMinRating] = useState<number | null>(null)
  const [allTags, setAllTags] = useState<TagInfo[]>([])

  // Multi-select state. Tagged with the filter/page combination it was made
  // under — see NO_SELECTION below.
  const [selection, setSelection] = useState<{ key: string; ids: Set<number> }>({
    key: "",
    ids: NO_SELECTION,
  })
  const { openAudioPlayer, closeAudioPlayer, openVideoPlayer, closeVideoPlayer } = useMediaPlayer()

  const [showDownloadForm, setShowDownloadForm] = useState(false)
  const [viewMode, setViewMode] = useViewMode("downloads")
  const [displayVideo, setDisplayVideo] = useState(false)
  // Clip editor target. Audio and video both go through MediaClipEditor, so the
  // scissors action lands on the same surface here as it does in playlists.
  const [clipTarget, setClipTarget] = useState<Download | null>(null)
  const { sortBy, sortDirection, handleSort } = useTriStateSort()
  const [videoCurrentTime, setVideoCurrentTime] = useState(0)
  const videoRefRef = useRef<HTMLVideoElement | null>(null)
  // Only feeds the clip editor. VideoPlayer keeps taking the stored duration, so
  // its seek effect doesn't re-fire (and re-seek) when metadata lands.
  const { duration: videoElementDuration, refCallback: handleVideoRef } =
    useElementDuration(videoRefRef)

  // Grid view only exists for COMPLETE media; SKIPPED and DELETED are table-only.
  // Derived rather than written back into viewMode, because viewMode is now a
  // persisted preference — forcing "table" on it would clobber the user's choice
  // the moment they clicked "Show Deleted".
  const effectiveViewMode = status === "COMPLETE" ? viewMode : "table"

  // "Group by" folder navigation for the grid view (COMPLETE status only)
  const grouping = useDownloadGrouping({
    enabled: effectiveViewMode === "grid" && status === "COMPLETE" && !semanticSearch,
    status,
    search,
    tagIds: selectedTagIds,
    minRating,
  })

  // Drilling into or out of a group folder is a different list, so the page
  // number doesn't carry over. Deriving it covers every path that moves the leaf
  // — openFolder, goUp, setGroupDim and the reset when grouping is switched off.
  const pageNumber = page.leafKey === grouping.leafKey ? page.n : 1
  const setPageNumber = useCallback(
    (n: number) => setPage({ leafKey: grouping.leafKey, n }),
    [grouping.leafKey]
  )

  const [rowSelect, setRowSelect] = useState<{
    media_details_id: number
    title: string
    channel: string
    url: string
    duration: number
    playback_position: number
    thumbnail_path?: string
    /**
     * Set when playback_position carries a timestamp the user picked (a
     * transcript hit) rather than a resume position, so a hit near the end of a
     * video isn't bounced back to 0.
     */
    exact_start?: boolean
  }>({
    media_details_id: 0,
    title: "",
    channel: "",
    url: "",
    duration: 0,
    playback_position: 0,
  })
  // Tagged with the video it describes, so closing the player or switching
  // videos drops the old metadata by comparison during render rather than by an
  // effect that resets it. handleVideoRate still writes it optimistically.
  const [metadataState, setMetadataState] = useState<{
    key: string
    data: VideoMetadata
  }>({ key: "", data: NO_METADATA })
  const metadataKey =
    displayVideo && rowSelect.media_details_id ? String(rowSelect.media_details_id) : ""
  const videoMetadata = metadataState.key === metadataKey ? metadataState.data : NO_METADATA

  useFetchEffect(
    (signal) =>
      axios
        .get(apiUrl(mediaApi.detail(rowSelect.media_details_id)), { signal })
        .then((response) => {
          const data = response.data
          setMetadataState({
            key: metadataKey,
            data: {
              release_timestamp: data.release_timestamp,
              access_count: data.access_count,
              rating: data.rating ?? null,
            },
          })
        })
        .catch((err) => {
          if (axios.isCancel(err)) return
          console.error("Failed to fetch media details:", err)
        }),
    [metadataKey, rowSelect.media_details_id],
    { enabled: metadataKey !== "" }
  )

  // Feed the shared media-session metadata so the iOS lock screen shows the video's
  // thumbnail during standalone (non-playlist) playback, matching audio. Cleared on
  // return-to-library / tab-switch unmount so videoVisible never leaks into the
  // playlist video surface.
  useEffect(() => {
    if (!displayVideo || !rowSelect.media_details_id) return
    openVideoPlayer({
      media_details_id: rowSelect.media_details_id,
      title: rowSelect.title,
      channel: rowSelect.channel,
      thumbnail_path: rowSelect.thumbnail_path,
      duration: rowSelect.duration,
      start_time: rowSelect.playback_position,
    })
    return () => closeVideoPlayer()
  }, [
    displayVideo,
    rowSelect.media_details_id,
    rowSelect.title,
    rowSelect.channel,
    rowSelect.thumbnail_path,
    rowSelect.duration,
    rowSelect.playback_position,
    openVideoPlayer,
    closeVideoPlayer,
  ])

  const handleVideoRate = async (mediaId: number, rating: number | null) => {
    const previousRating = videoMetadata.rating
    const patchRating = (value: number | null | undefined) =>
      setMetadataState((prev) => ({ ...prev, data: { ...prev.data, rating: value } }))
    patchRating(rating)
    try {
      await saveRating(mediaId, rating)
    } catch {
      toast.error('Failed to update rating')
      patchRating(previousRating)
    }
  }

  const loadTags = useCallback(() => {
    axios
      .get(apiUrl(mediaApi.allTags))
      .then((response) => setAllTags(response.data))
      .catch(() => {})
  }, [])

  useEffect(() => {
    loadTags()
  }, [loadTags])

  const loadStats = useCallback(
    () =>
      fetchStats(search, status)
        .then((data) => setStats(data))
        .catch(() => {}),
    [fetchStats, search, status]
  )

  const handleInputChange = (event: { target: { value: string } }) => {
    setSearch(event.target.value)
    setPageNumber(1)
  }

  const handleSemanticInputChange = (event: { target: { value: string } }) => {
    setSemanticSearch(event.target.value)
  }

  const loadDownloads = useCallback(() => {
    // When drilled into a group folder, the leaf overrides the tag filter and adds
    // channel/untagged/date params so this reuses the normal paginated list path.
    const leaf = grouping.leaf
    const effectiveTagIds = leaf?.tagIds ?? selectedTagIds
    return fetchDownloads(
      search,
      status,
      pageNumber,
      sortBy,
      sortDirection,
      effectiveTagIds,
      minRating,
      leaf?.filter ?? null
    )
      .then(({ pageCount: newPageCount, tableRows }) => {
        setPageCount(newPageCount)
        setTableRows(
          tableRows.map((row: any) => ({
            ...row,
            media_details_id: row.id,
          }))
        )
        // If we're on a page beyond available data (e.g. deleted last item on last page),
        // navigate back to the last available page
        if (tableRows.length === 0 && pageNumber > 1 && newPageCount > 0) {
          setPageNumber(newPageCount)
        }
      })
      .catch(() => {})
  }, [
    fetchDownloads,
    grouping.leaf,
    search,
    status,
    pageNumber,
    sortBy,
    sortDirection,
    selectedTagIds,
    minRating,
    setPageNumber,
  ])

  // The media list is hidden behind the video player, the clip editor, group
  // folders and semantic search, so none of those should be fetching it. Stats
  // share the condition: they poll alongside the list, as they did when both
  // lived in one interval.
  const listActive =
    !semanticSearch &&
    !(search.length > 0 && search.length < 3) &&
    !displayVideo &&
    !clipTarget &&
    !grouping.showFolders

  const { isLoading: downloadsFetching, refetch: reloadDownloads } = useFetchEffect(
    loadDownloads,
    [loadDownloads],
    { enabled: listActive, pollMs: 10_000 }
  )

  const { isLoading: statsFetching, refetch: reloadStats } = useFetchEffect(
    loadStats,
    [loadStats],
    { pollMs: listActive ? 10_000 : null }
  )
  // Only a spinner while there are no stats yet: a poll tick must not blank the
  // numbers.
  const statsLoading = stats === null && statsFetching

  const handleRefresh = useCallback(() => {
    reloadDownloads()
    reloadStats()
    loadTags()
  }, [reloadDownloads, reloadStats, loadTags])

  const patchRow = useCallback(
    (mediaId: number, patch: Partial<Download>) =>
      setTableRows((rows) =>
        rows.map((r) =>
          r.media_details_id === mediaId ? { ...r, ...patch } : r,
        ),
      ),
    [],
  )

  const selectMediaRow = (row: Download) => {
    setRowSelect({
      media_details_id: row.media_details_id,
      title: row.title,
      channel: row.channel,
      url: row.url,
      duration: row.duration || 0,
      playback_position: row.playback_position || 0,
      thumbnail_path: row.thumbnail_path,
      exact_start: false,
    })
  }

  const handleMediaOpen = (row: Download) => {
    selectMediaRow(row)
    if (row.media_type === "VIDEO") {
      closeAudioPlayer()
      setDisplayVideo(true)
    } else if (row.media_type === "AUDIO") {
      setDisplayVideo(false)
      openAudioPlayer({
        media_details_id: row.media_details_id,
        title: row.title,
        channel: row.channel,
        url: row.url,
        start_time: row.playback_position || 0,
        duration: row.duration,
        thumbnail_path: row.thumbnail_path,
      })
    }
  }

  /**
   * Table row click. Unlike a grid card, a DELETED row opens the source URL and
   * a SKIPPED row fills the download form — the file itself isn't playable.
   */
  const handleRowActivate = (row: Download) => {
    if (status === "DELETED") {
      if (row.url) window.open(row.url, "_blank", "noopener,noreferrer")
      return
    }
    if (status === "SKIPPED") {
      populateDownloadFromSkipped(row)
      return
    }
    handleMediaOpen(row)
  }

  const handleMediaClip = (row: Download) => {
    if (!row.file_path) {
      toast.error("Media file not available")
      return
    }
    if (row.media_type !== "AUDIO" && row.media_type !== "VIDEO") return
    setClipTarget(row)
  }

  const populateDownloadFromSkipped = (row: Download) => {
    setDownloadOptions({
      ...downloadOptions,
      url: row.url,
      audio_only: row.media_type === "AUDIO",
      overwrite: false,
    })
    toast.success(`Download options populated for: ${row.title}`)
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  // Multi-select derived values.
  //
  // A selection only means anything for the rows it was made on, so it carries
  // the filter/page combination it belongs to and stops applying the moment that
  // changes. Deriving the clear beats an effect that re-renders to do the same.
  const selectionKey = JSON.stringify([
    pageNumber,
    status,
    search,
    sortBy,
    sortDirection,
    selectedTagIds,
    minRating,
  ])
  const selectedIds = selection.key === selectionKey ? selection.ids : NO_SELECTION
  const setSelectedIds = useCallback(
    (ids: Set<number>) => setSelection({ key: selectionKey, ids }),
    [selectionKey]
  )

  const selectedItems = (tableRows as Download[]).filter((r) => selectedIds.has(r.media_details_id))
  const allSelected = tableRows.length > 0 && tableRows.every((r: any) => selectedIds.has(r.media_details_id))
  const selectionActive = status === "COMPLETE" && effectiveViewMode === "table"

  const handleSelectAll = (selected: boolean) => {
    if (selected) {
      setSelectedIds(new Set(tableRows.map((r: any) => r.media_details_id)))
    } else {
      setSelectedIds(new Set())
    }
  }

  // Semantic results, tagged with the query they belong to, so clearing or
  // retyping the query drops them by comparison during render rather than
  // needing an effect to reset them.
  const { isLoading: semanticFetching } = useFetchEffect(
    () =>
      fetchTranscriptSegments(search, semanticSearch, semanticWeight).then(
        (rows: any[]) =>
          setSemanticState({
            key: semanticKey,
            rows: rows.map((row: any) => ({
              ...row,
              media_details_id: row.media_details.id,
            })),
          })
      ),
    [semanticKey, search, semanticSearch, semanticWeight, fetchTranscriptSegments],
    { enabled: semanticSearch.length >= 3 }
  )

  const loading = downloadsFetching || semanticFetching

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="space-y-4"
    >
      <div className="md:hidden">
        <button
          onClick={() => setShowDownloadForm(!showDownloadForm)}
          className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-mono transition-colors bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
        >
          <ArrowDownTrayIcon className="h-3.5 w-3.5" />
          New Download
          <ChevronDownIcon className={`h-3.5 w-3.5 transition-transform ${showDownloadForm ? "rotate-180" : ""}`} />
        </button>
        <AnimatePresence>
          {showDownloadForm && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <div className="pt-2">
                <DownloadButton
                  options={downloadOptions}
                  setOptions={setDownloadOptions}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="hidden md:block">
        <DownloadButton
          options={downloadOptions}
          setOptions={setDownloadOptions}
        />
      </div>

      <Card>
        {clipTarget ? (
          <CardContent className="pt-6">
            <MediaClipEditor
              media={clipTarget}
              onBack={() => setClipTarget(null)}
              backLabel="Return to Library"
            />
          </CardContent>
        ) : displayVideo ? (
          <CardContent className="pt-6 space-y-4">
            <Button
              variant="outline"
              onClick={() => setDisplayVideo(false)}
              className="gap-2 mt-4"
            >
              <ArrowLeftIcon className="h-4 w-4" />
              Return to Library
            </Button>
            <VideoPlayer
              id={rowSelect.media_details_id}
              startTime={rowSelect.playback_position}
              duration={rowSelect.duration}
              exactStart={rowSelect.exact_start}
              onTimeUpdate={setVideoCurrentTime}
              videoRefCallback={handleVideoRef}
            />
            <div className="text-center space-y-1">
              <h3 className="font-mono text-lg text-text-primary">
                {rowSelect.title}
              </h3>
              <p className="text-sm text-text-secondary">{rowSelect.channel}</p>
              {videoMetadata.rating !== undefined && (
                <div className="flex justify-center mt-0.5">
                  <StarRating
                    rating={videoMetadata.rating}
                    onRate={(r) => handleVideoRate(rowSelect.media_details_id, r)}
                  />
                </div>
              )}
              {rowSelect.url && (
                <a
                  href={rowSelect.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-text-muted hover:text-matrix transition-colors font-mono truncate block"
                >
                  {rowSelect.url}
                </a>
              )}
              {(videoMetadata.release_timestamp || videoMetadata.access_count !== undefined) && (
                <div className="flex items-center justify-center gap-4 text-xs text-text-muted font-mono mt-1">
                  {videoMetadata.release_timestamp && (
                    <span className="flex items-center gap-1">
                      <CalendarIcon className="h-3 w-3" />
                      {formatDate(videoMetadata.release_timestamp)}
                    </span>
                  )}
                  {videoMetadata.access_count !== undefined && (
                    <span className="flex items-center gap-1">
                      <EyeIcon className="h-3 w-3" />
                      {videoMetadata.access_count} {videoMetadata.access_count === 1 ? "play" : "plays"}
                    </span>
                  )}
                </div>
              )}
            </div>
            <VideoClippingControls
              mediaDetailsId={rowSelect.media_details_id}
              duration={rowSelect.duration || videoElementDuration}
              currentTime={videoCurrentTime}
              onSeek={(time) => {
                if (videoRefRef.current) {
                  videoRefRef.current.currentTime = time
                }
              }}
              videoRef={videoRefRef}
            />
          </CardContent>
        ) : (
          <>
            <CardHeader className="pb-3">
              <div className="flex flex-row items-center justify-between gap-2 sm:gap-3 overflow-x-auto scrollbar-none [&::-webkit-scrollbar]:hidden">
                <div className="flex items-center flex-nowrap shrink-0 gap-1.5 sm:gap-3">
                  <CardTitle className="text-lg hidden sm:block">Media Library</CardTitle>
                  <button
                    onClick={() => {
                      const newStatus = status === "SKIPPED" ? "COMPLETE" : "SKIPPED"
                      setStatus(newStatus)
                      setPageNumber(1)
                    }}
                    className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors justify-center ${
                      status === "SKIPPED"
                        ? "bg-status-warning/20 text-status-warning border border-status-warning/30"
                        : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
                    }`}
                    title={status === "SKIPPED" ? "Viewing skipped media" : "Show skipped media"}
                  >
                    <ForwardIcon className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">{status === "SKIPPED" ? "Skipped" : "Show Skipped"}</span>
                  </button>
                  <button
                    onClick={() => {
                      const newStatus = status === "DELETED" ? "COMPLETE" : "DELETED"
                      setStatus(newStatus)
                      setPageNumber(1)
                    }}
                    className={`inline-flex items-center gap-1.5 px-2 sm:px-2.5 py-1 rounded-md text-xs font-mono transition-colors justify-center ${
                      status === "DELETED"
                        ? "bg-status-error/20 text-status-error border border-status-error/30"
                        : "bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
                    }`}
                    title={status === "DELETED" ? "Viewing deleted media" : "Show deleted media"}
                  >
                    <TrashIcon className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">{status === "DELETED" ? "Deleted" : "Show Deleted"}</span>
                  </button>
                  {status === "COMPLETE" && (
                    <>
                      <TagFilter
                        allTags={allTags}
                        selectedTagIds={selectedTagIds}
                        onChange={(ids) => { setSelectedTagIds(ids); setPageNumber(1) }}
                      />
                      <RatingFilter
                        minRating={minRating}
                        onChange={(r) => { setMinRating(r); setPageNumber(1) }}
                      />
                      <div className="flex items-center gap-1.5 sm:gap-3">
                        <Separator orientation="vertical" className="h-4" />
                        <ViewToggle mode={effectiveViewMode} onChange={setViewMode} />
                        {effectiveViewMode === "grid" && (
                          <GroupBySelector
                            value={grouping.groupDim}
                            onChange={grouping.setGroupDim}
                          />
                        )}
                      </div>
                    </>
                  )}
                </div>
                <div className="shrink-0">
                  <MediaStatsBar stats={stats} loading={statsLoading} />
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4 px-0">
              <div className="flex flex-col sm:flex-row gap-3">
                <div className="relative flex-1">
                  <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
                  <Input
                    placeholder="Search downloads  (use && / ||)..."
                    title={'Combine terms: "lofi && mix" matches both, "cats || dogs" matches either. Each term matches channel or title.'}
                    value={search}
                    onChange={handleInputChange}
                    className="pl-9"
                  />
                </div>
                <div className="relative flex-1">
                  <BookOpenIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
                  <Input
                    placeholder="Semantic transcript search..."
                    value={semanticSearch}
                    onChange={handleSemanticInputChange}
                    className="pl-9"
                  />
                </div>
              </div>

              {semanticSearch.length >= 3 && (
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-text-muted whitespace-nowrap">Keyword</span>
                  <Slider
                    value={semanticWeight * 100}
                    onChange={(v) => setSemanticWeight(v / 100)}
                    min={0}
                    max={100}
                    step={5}
                    className="flex-1"
                  />
                  <span className="text-xs font-mono text-text-muted whitespace-nowrap">Semantic</span>
                  <span className="text-xs font-mono text-matrix w-8 text-right">{Math.round(semanticWeight * 100)}%</span>
                </div>
              )}

              {selectionActive && (
                <MediaBulkActions
                  selectedItems={selectedItems}
                  allTags={allTags}
                  onClearSelection={() => setSelectedIds(new Set())}
                  onRefresh={handleRefresh}
                />
              )}

              <div className={semanticSearch || effectiveViewMode === "table" ? "md:rounded-lg md:border md:border-border overflow-hidden" : ""}>
                {semanticSearch ? (
                  <TranscriptSegmentTable
                    tableColumns={TRANSCRIPT_TABLE_HEAD}
                    tableRows={semanticTableRows.slice(
                      (semanticPageNumber - 1) * SEMANTIC_PAGE_SIZE,
                      semanticPageNumber * SEMANTIC_PAGE_SIZE
                    )}
                    loading={loading}
                    setRowSelect={setRowSelect}
                    setDisplayVideo={setDisplayVideo}
                    searchQuery={semanticSearch}
                  />
                ) : effectiveViewMode === "grid" ? (
                  grouping.showFolders ? (
                    <GroupFolderGrid
                      breadcrumb={grouping.breadcrumb}
                      folders={grouping.folders}
                      loading={grouping.foldersLoading}
                      pageCount={grouping.foldersPageCount}
                      pageNumber={grouping.folderPage}
                      setPageNumber={grouping.setFolderPage}
                      canGoUp={grouping.groupPath.length > 0}
                      onGoUp={grouping.goUp}
                      onOpen={grouping.openFolder}
                    />
                  ) : (
                  <>
                  {grouping.atLeaf && (
                    <GroupBreadcrumb
                      breadcrumb={grouping.breadcrumb}
                      canGoUp
                      onGoUp={grouping.goUp}
                    />
                  )}
                  <MediaListView
                    viewMode="grid"
                    rows={tableRows as Download[]}
                    loading={loading}
                    status={status}
                    onRefresh={handleRefresh}
                    patchRow={patchRow}
                    sortBy={sortBy}
                    sortDirection={sortDirection}
                    onSort={handleSort}
                    allTags={allTags}
                    onTagsChange={loadTags}
                    onRowClick={handleMediaOpen}
                    onClip={handleMediaClip}
                    onPopulateSkipped={populateDownloadFromSkipped}
                  />
                  </>
                  )
                ) : (
                  <MediaListView
                    viewMode="table"
                    rows={!semanticSearch ? (tableRows as Download[]) : []}
                    loading={loading}
                    status={status}
                    onRefresh={handleRefresh}
                    patchRow={patchRow}
                    sortBy={sortBy}
                    sortDirection={sortDirection}
                    onSort={handleSort}
                    allTags={allTags}
                    onTagsChange={loadTags}
                    onRowClick={handleRowActivate}
                    onClip={handleMediaClip}
                    onPopulateSkipped={populateDownloadFromSkipped}
                    {...(selectionActive && {
                      selection: {
                        selectedIds,
                        onSelectionChange: setSelectedIds,
                        allSelected,
                        onSelectAll: handleSelectAll,
                        idOf: (row: Download) => row.media_details_id,
                      },
                    })}
                  />
                )}
              </div>

              {semanticSearch ? (
                Math.ceil(semanticTableRows.length / SEMANTIC_PAGE_SIZE) > 1 && (
                  <TablePagination
                    pageNumber={semanticPageNumber}
                    pageCount={Math.ceil(semanticTableRows.length / SEMANTIC_PAGE_SIZE)}
                    setPageNumber={setSemanticPageNumber}
                  />
                )
              ) : grouping.showFolders ? null : (
                <TablePagination
                  pageNumber={pageNumber}
                  pageCount={pageCount}
                  setPageNumber={setPageNumber}
                />
              )}
            </CardContent>
          </>
        )}
      </Card>

    </motion.div>
  )
}

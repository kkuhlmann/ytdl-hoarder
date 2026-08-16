"use client"

import { useState } from "react"
import axios from "axios"
import toast from "react-hot-toast"
import { TrashIcon as TrashOutlineIcon } from "@heroicons/react/24/outline"

import {
  ConfirmDialog,
  KeepTranscriptsCheckbox,
} from "@/app/_components/ConfirmDialog"
import { TagsDialog } from "@/app/_components/TagsDialog"
import { AddToPlaylistDialog } from "@/app/_components/AddToPlaylistDialog"
import { ShareDialog } from "@/app/_components/ShareDialog"
import { MediaBulkActionsBar } from "@/app/_components/MediaBulkActionsBar"
import { useBulkSelection } from "@/app/_hooks/useBulkSelection"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import { useAuth } from "@/app/context/AuthContext"
import type { Download, TagInfo } from "@/app/types/DownloadsOptions"

export type BulkActionType = "delete" | "tag" | "share" | "playlist" | null

const mediaId = (row: Download) => row.media_details_id

/**
 * Multi-select state for media rows, plus the `selection` bundle `MediaListView`
 * takes as one prop.
 */
export function useMediaBulkSelection<T extends Download>(rows: T[]) {
  const bulk = useBulkSelection(rows, mediaId)

  return {
    ...bulk,
    selection: {
      selectedIds: bulk.selectedIds,
      onSelectionChange: bulk.setSelectedIds,
      allSelected: bulk.allSelected,
      onSelectAll: bulk.selectAll,
      idOf: mediaId,
    },
  }
}

type MediaBulkActionsProps<T extends Download> = {
  selectedItems: T[]
  allTags?: TagInfo[]
  onClearSelection: () => void
  onRefresh: () => void
  /** Extra buttons after the shared ones, e.g. "Remove from playlist". */
  extraActions?: {
    key: string
    label: string
    loadingLabel: string
    onClick: () => void
    isLoading?: boolean
  }[]
}

/**
 * The bulk bar and every dialog it can open. Renders nothing visible when the
 * selection is empty, so callers mount it unconditionally — returning null there
 * would unmount the bar's AnimatePresence and lose its collapse animation.
 */
export function MediaBulkActions<T extends Download>({
  selectedItems,
  allTags = [],
  onClearSelection,
  onRefresh,
  extraActions,
}: MediaBulkActionsProps<T>) {
  const { user } = useAuth()
  const [loadingAction, setLoadingAction] = useState<BulkActionType>(null)
  const [showDelete, setShowDelete] = useState(false)
  const [keepTranscripts, setKeepTranscripts] = useState(true)
  const [showTag, setShowTag] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [showPlaylist, setShowPlaylist] = useState(false)

  const ids = selectedItems.map((item) => item.media_details_id)

  const handleDelete = async () => {
    setLoadingAction("delete")
    try {
      const res = await axios.delete(apiUrl(mediaApi.bulkDelete), {
        data: { media_details_ids: ids, keep_transcripts: keepTranscripts },
      })
      const {
        deleted = 0,
        transferred = 0,
        access_removed: accessRemoved = 0,
        forbidden = 0,
        not_found: notFound = 0,
      } = res.data
      const removed = deleted + transferred + accessRemoved
      const skipped = forbidden + notFound
      if (skipped === 0) {
        toast.success(
          keepTranscripts
            ? `Deleted ${removed} items (transcripts kept)`
            : `Deleted ${removed} items`,
        )
      } else {
        toast.success(
          `Deleted ${removed} of ${selectedItems.length} items (${skipped} skipped)`,
        )
      }
      onClearSelection()
      setShowDelete(false)
      onRefresh()
    } catch {
      toast.error("Failed to delete items")
    } finally {
      setLoadingAction(null)
    }
  }

  const handleTag = async (tagNames: string[]) => {
    setLoadingAction("tag")
    try {
      const res = await axios.put(apiUrl(mediaApi.bulkTags), {
        media_details_ids: ids,
        tag_names: tagNames,
      })
      toast.success(`Tagged ${res.data.tagged_count} items`)
      onClearSelection()
      setShowTag(false)
      onRefresh()
    } catch {
      toast.error("Failed to tag items")
    } finally {
      setLoadingAction(null)
    }
  }

  return (
    <>
      <MediaBulkActionsBar
        selectedItems={selectedItems}
        currentUserId={user?.id ?? null}
        onDelete={() => {
          // A previous delete's unchecked box must not silently carry over into
          // the next one — the destructive choice is re-made every time.
          setKeepTranscripts(true)
          setShowDelete(true)
        }}
        onTag={() => setShowTag(true)}
        onShare={() => setShowShare(true)}
        onPlaylist={() => setShowPlaylist(true)}
        onClearSelection={onClearSelection}
        loadingAction={loadingAction}
        extraActions={extraActions}
      />

      <ConfirmDialog
        open={showDelete}
        onOpenChange={setShowDelete}
        icon={<TrashOutlineIcon className="h-5 w-5 text-status-error" />}
        title={`Delete ${selectedItems.length} ${selectedItems.length === 1 ? "Item" : "Items"}`}
        description={`Are you sure you want to delete ${selectedItems.length} selected ${
          selectedItems.length === 1 ? "item" : "items"
        }? This action cannot be undone.`}
        descriptionClassName="text-status-error/80"
        confirmLabel={`Delete ${selectedItems.length} ${selectedItems.length === 1 ? "Item" : "Items"}`}
        loadingLabel="Deleting..."
        isLoading={loadingAction === "delete"}
        onConfirm={handleDelete}
      >
        <KeepTranscriptsCheckbox
          id="bulk-keep-transcripts"
          checked={keepTranscripts}
          onChange={setKeepTranscripts}
        />
      </ConfirmDialog>

      {showTag && (
        <TagsDialog
          open={showTag}
          onOpenChange={(open) => {
            if (!open && loadingAction === "tag") return
            setShowTag(open)
          }}
          mediaTitle=""
          tags={[]}
          allTags={allTags}
          onSave={handleTag}
          bulkMode
          bulkCount={selectedItems.length}
        />
      )}

      {showPlaylist && (
        <AddToPlaylistDialog
          open={showPlaylist}
          onOpenChange={(open) => {
            setShowPlaylist(open)
            if (!open) {
              onClearSelection()
              onRefresh()
            }
          }}
          mediaDetailsIds={ids}
          mediaTitle=""
        />
      )}

      {showShare && (
        <ShareDialog
          open={showShare}
          onOpenChange={(open) => {
            setShowShare(open)
            if (!open) onClearSelection()
          }}
          entityIds={selectedItems
            .filter((i) => i.owner_id === user?.id)
            .map((i) => i.media_details_id)}
          entityType="media-details"
          entityTitle=""
          bulkMode
        />
      )}
    </>
  )
}

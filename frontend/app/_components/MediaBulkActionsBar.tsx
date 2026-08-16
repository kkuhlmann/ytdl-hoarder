"use client"

import { Download } from "@/app/types/DownloadsOptions"
import { BulkBar, BulkBarButton } from "./BulkBar"

type BulkActionType = "delete" | "tag" | "share" | "playlist" | null

type ExtraBulkAction = {
  key: string
  label: string
  loadingLabel: string
  onClick: () => void
  isLoading?: boolean
}

type MediaBulkActionsBarProps = {
  selectedItems: Download[]
  currentUserId: number | null
  onDelete: () => void
  onTag: () => void
  onShare: () => void
  onPlaylist: () => void
  onClearSelection: () => void
  loadingAction?: BulkActionType
  /** Surface-specific buttons, e.g. playlist detail's "Remove from playlist". */
  extraActions?: ExtraBulkAction[]
}

export function MediaBulkActionsBar({
  selectedItems,
  currentUserId,
  onDelete,
  onTag,
  onShare,
  onPlaylist,
  onClearSelection,
  loadingAction = null,
  extraActions = [],
}: MediaBulkActionsBarProps) {
  const totalCount = selectedItems.length
  const ownedCount = selectedItems.filter((i) => i.owner_id === currentUserId).length

  const buttons: BulkBarButton[] = [
    {
      key: "delete",
      onClick: onDelete,
      variant: "destructive",
      isLoading: loadingAction === "delete",
      loadingLabel: "Deleting...",
      content: <>Delete ({totalCount})</>,
    },
    {
      key: "tag",
      onClick: onTag,
      variant: "secondary",
      isLoading: loadingAction === "tag",
      loadingLabel: "Tagging...",
      content: "Tags",
    },
    {
      key: "playlist",
      onClick: onPlaylist,
      variant: "secondary",
      isLoading: loadingAction === "playlist",
      loadingLabel: "Adding...",
      content: "Add to Playlist",
    },
    {
      key: "share",
      onClick: onShare,
      variant: "secondary",
      disabled: ownedCount === 0,
      isLoading: loadingAction === "share",
      loadingLabel: "Sharing...",
      content: (
        <>
          Share
          {ownedCount > 0 && ownedCount !== totalCount && (
            <span className="text-xs opacity-80">({ownedCount} owned)</span>
          )}
        </>
      ),
    },
    ...extraActions.map((action) => ({
      key: action.key,
      onClick: action.onClick,
      variant: "secondary" as const,
      isLoading: action.isLoading,
      loadingLabel: action.loadingLabel,
      content: `${action.label} (${totalCount})`,
    })),
  ]

  return (
    <BulkBar
      count={totalCount}
      onClearSelection={onClearSelection}
      isLoading={loadingAction !== null || extraActions.some((a) => a.isLoading)}
      buttons={buttons}
    />
  )
}

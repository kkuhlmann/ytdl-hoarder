"use client"

import { ArrowDownTrayIcon } from "@heroicons/react/24/outline"
import { Clip } from "@/app/types/ClipsOptions"
import { BulkBar, BulkBarButton } from "./BulkBar"

type ClipsBulkAction = "delete" | "download" | null

type ClipsBulkActionsBarProps = {
  selectedItems: Clip[]
  onDelete: () => void
  onDownload: () => void
  onClearSelection: () => void
  loadingAction?: ClipsBulkAction
}

export function ClipsBulkActionsBar({
  selectedItems,
  onDelete,
  onDownload,
  onClearSelection,
  loadingAction = null,
}: ClipsBulkActionsBarProps) {
  const totalCount = selectedItems.length

  // Only one clip may be downloaded at a time, and only when it is ready on disk.
  const single = totalCount === 1 ? selectedItems[0] : null
  const canDownload = single !== null && single.status === "COMPLETE" && !!single.file_path

  const buttons: BulkBarButton[] = [
    {
      key: "delete",
      onClick: onDelete,
      variant: "destructive",
      isLoading: loadingAction === "delete",
      loadingLabel: "Deleting...",
      content: <>Delete ({totalCount})</>,
    },
  ]

  if (totalCount === 1) {
    buttons.push({
      key: "download",
      onClick: onDownload,
      variant: "secondary",
      disabled: !canDownload,
      isLoading: loadingAction === "download",
      loadingLabel: "Downloading...",
      content: (
        <>
          <ArrowDownTrayIcon className="h-4 w-4" />
          Download
        </>
      ),
    })
  }

  return (
    <BulkBar
      count={totalCount}
      onClearSelection={onClearSelection}
      isLoading={loadingAction !== null}
      buttons={buttons}
    />
  )
}

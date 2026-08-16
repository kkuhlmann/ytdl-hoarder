"use client"

import { TaskRecord } from "@/app/types/TasksOptions"
import { canCancel, isRetryable } from "@/app/lib/taskStatus"
import { BulkBar, BulkBarButton } from "./BulkBar"

type BulkActionType = "cancel" | "delete" | "retry" | null

type BulkActionsBarProps = {
  selectedTasks: TaskRecord[]
  onCancel: () => void
  onDelete: () => void
  onRetry: () => void
  onClearSelection: () => void
  loadingAction?: BulkActionType
}

export function BulkActionsBar({
  selectedTasks,
  onCancel,
  onDelete,
  onRetry,
  onClearSelection,
  loadingAction = null,
}: BulkActionsBarProps) {
  const totalCount = selectedTasks.length
  const cancellableCount = selectedTasks.filter((t) => canCancel(t.status)).length
  const retryableCount = selectedTasks.filter((t) => isRetryable(t.status)).length

  const buttons: BulkBarButton[] = [
    {
      key: "cancel",
      onClick: onCancel,
      variant: "destructive",
      disabled: cancellableCount === 0,
      isLoading: loadingAction === "cancel",
      loadingLabel: "Cancelling...",
      content: (
        <>
          Cancel
          {cancellableCount > 0 && cancellableCount !== totalCount && (
            <span className="text-xs opacity-80">({cancellableCount})</span>
          )}
        </>
      ),
    },
    {
      key: "delete",
      onClick: onDelete,
      variant: "secondary",
      isLoading: loadingAction === "delete",
      loadingLabel: "Deleting...",
      content: <>Delete ({totalCount})</>,
    },
    {
      key: "retry",
      onClick: onRetry,
      variant: "matrix",
      disabled: retryableCount === 0,
      isLoading: loadingAction === "retry",
      loadingLabel: "Retrying...",
      content: (
        <>
          Retry
          {retryableCount > 0 && retryableCount !== totalCount && (
            <span className="text-xs opacity-80">({retryableCount})</span>
          )}
        </>
      ),
    },
  ]

  return (
    <BulkBar
      count={totalCount}
      onClearSelection={onClearSelection}
      isLoading={loadingAction !== null}
      buttons={buttons}
    />
  )
}

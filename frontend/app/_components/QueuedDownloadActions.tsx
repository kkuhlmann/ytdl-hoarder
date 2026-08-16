"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { LoadingSpinner } from "./LoadingSpinner"
import { TaskRecord } from "@/app/types/TasksOptions"
import { ClockIcon } from "@heroicons/react/24/outline"

type QueuedDownloadActionsProps = {
  open: boolean
  handleOpen: () => void
  task: TaskRecord
  onPrioritize: () => void
  onCancel: () => void
  onDismiss: () => void
  isLoading?: "prioritize" | "cancel" | null
}

export function QueuedDownloadActions({
  open,
  handleOpen,
  task,
  onPrioritize,
  onCancel,
  onDismiss,
  isLoading = null,
}: QueuedDownloadActionsProps) {
  return (
    <Dialog open={open} onOpenChange={handleOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClockIcon className="h-5 w-5 text-status-queued" />
            Queued Download
          </DialogTitle>
          <DialogDescription className="text-text-muted">
            This download is waiting in the queue.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-4">
          <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
            <span className="text-text-muted font-mono">Type:</span>
            <span className="text-text-primary">{task.task_type}</span>

            <span className="text-text-muted font-mono">Title:</span>
            <span className="text-text-primary truncate">{task.title || "N/A"}</span>

            <span className="text-text-muted font-mono">Channel:</span>
            <span className="text-text-primary">{task.channel || "N/A"}</span>

            <span className="text-text-muted font-mono">Status:</span>
            <span className="text-status-queued">{task.status_message || task.status}</span>

            <span className="text-text-muted font-mono">Position:</span>
            <span className="text-text-primary">
              {task.queue_position === 0
                ? "Next up"
                : task.queue_position != null && task.queue_position > 0
                ? `${task.queue_position} task(s) ahead`
                : "Unknown"}
            </span>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="secondary" onClick={onDismiss} disabled={!!isLoading}>
            Close
          </Button>
          <Button
            variant="destructive"
            onClick={onCancel}
            disabled={!!isLoading}
            className="gap-2"
          >
            {isLoading === "cancel" ? (
              <>
                <LoadingSpinner />
                Cancelling...
              </>
            ) : (
              "Cancel Task"
            )}
          </Button>
          <Button
            variant="matrix"
            onClick={onPrioritize}
            disabled={!!isLoading}
            className="gap-2"
          >
            {isLoading === "prioritize" ? (
              <>
                <LoadingSpinner />
                Prioritizing...
              </>
            ) : (
              "Prioritize"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

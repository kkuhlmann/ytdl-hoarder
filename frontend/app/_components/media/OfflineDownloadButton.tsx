"use client"

import { ArrowDownTrayIcon, CheckCircleIcon, XMarkIcon } from "@heroicons/react/20/solid"
import toast from "react-hot-toast"

import { useOfflineItem } from "@/app/_hooks/useOfflineDownloads"
import { useOfflineSupported } from "@/app/_hooks/useOfflineSupported"
import type { Download } from "@/app/types/DownloadsOptions"

/**
 * Save this item to the device, or drop it again.
 *
 * Reads its own state rather than taking handlers from the surface that renders
 * it. Offline capability is global, not per-list, so wiring it through
 * buildMediaActions' arguments would repeat the onClip trap — an optional prop
 * whose button renders regardless and silently does nothing where it was
 * forgotten.
 */
export function OfflineDownloadButton({ row }: { row: Download }) {
  const supported = useOfflineSupported()
  const { progress, percent, download, cancel, remove } = useOfflineItem(row.media_details_id)

  if (!supported) return null

  const state = progress?.state

  if (state === "ready") {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation()
          void remove().then(() => toast.success("Removed from this device"))
        }}
        className="group/offline p-1 rounded hover:bg-status-warning/20 transition-colors inline-flex"
        title="Saved for offline — click to remove from this device"
      >
        <CheckCircleIcon className="text-matrix group-hover/offline:hidden" />
        <XMarkIcon className="text-status-warning hidden group-hover/offline:inline" />
      </button>
    )
  }

  if (state === "queued" || state === "downloading") {
    return (
      <button
        onClick={(e) => {
          e.stopPropagation()
          cancel()
        }}
        className="p-1 rounded hover:bg-status-warning/20 transition-colors inline-flex"
        title={percent === null ? "Queued — click to cancel" : `Saving ${percent}% — click to cancel`}
      >
        <ArrowDownTrayIcon className="text-status-info animate-pulse" />
      </button>
    )
  }

  const failed = state === "error"

  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        if (!row.file_size_bytes) {
          toast.error("This item has no recorded file size yet")
          return
        }
        download(row)
      }}
      className="p-1 rounded hover:bg-matrix/20 transition-colors inline-flex"
      title={failed ? `${progress?.error ?? "Failed"} — click to retry` : "Save for offline"}
    >
      <ArrowDownTrayIcon
        className={failed ? "text-status-error" : "text-text-muted hover:text-matrix"}
      />
    </button>
  )
}

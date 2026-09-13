"use client"

import { useCallback, useSyncExternalStore } from "react"

import {
  cancelDownload,
  downloadSnapshot,
  queueDownload,
  removeDownload,
  subscribeToDownloads,
  type DownloadProgress,
  type DownloadableRow,
} from "@/app/lib/offlineDownloader"
import type { OfflineSource } from "@/app/lib/offlineDb"

/** Stable identity for the prerender, which useSyncExternalStore compares with Object.is. */
const EMPTY: ReadonlyMap<number, DownloadProgress> = new Map()

export function useOfflineDownloads(): ReadonlyMap<number, DownloadProgress> {
  return useSyncExternalStore(subscribeToDownloads, downloadSnapshot, () => EMPTY)
}

export type OfflineItemHandle = {
  progress: DownloadProgress | undefined
  /** 0-100, or null when nothing is in flight. */
  percent: number | null
  download: (row: DownloadableRow, source?: OfflineSource) => void
  cancel: () => void
  remove: () => Promise<void>
}

export function useOfflineItem(mediaId: number): OfflineItemHandle {
  const progress = useOfflineDownloads().get(mediaId)

  const download = useCallback(
    (row: DownloadableRow, source: OfflineSource = "manual") => queueDownload(row, source),
    []
  )
  const cancel = useCallback(() => cancelDownload(mediaId), [mediaId])
  const remove = useCallback(() => removeDownload(mediaId), [mediaId])

  const percent =
    progress && progress.state === "downloading" && progress.totalBytes > 0
      ? Math.min(100, Math.floor((progress.storedBytes / progress.totalBytes) * 100))
      : null

  return { progress, percent, download, cancel, remove }
}

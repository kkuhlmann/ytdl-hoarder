"use client"

import { ArrowPathIcon } from "@heroicons/react/20/solid"

import { useCollectionSync } from "@/app/_hooks/useOfflineSync"
import { useOfflineSupported } from "@/app/_hooks/useOfflineSupported"
import type { OfflineSource } from "@/app/lib/offlineDb"
import { readSyncLimit } from "@/app/lib/offlineSync"

/**
 * "Keep this collection offline" for a playlist or a subscription.
 *
 * Reads its own state, like OfflineDownloadButton, so a surface that renders it
 * cannot forget to wire it up.
 */
export function CollectionOfflineButton({ source }: { source: OfflineSource }) {
  const supported = useOfflineSupported()
  const { enabled, toggle } = useCollectionSync(source)

  if (!supported) return null

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        toggle()
      }}
      aria-pressed={enabled}
      className={`p-1 rounded transition-colors inline-flex ${
        enabled ? "hover:bg-status-warning/20" : "hover:bg-matrix/20"
      }`}
      title={
        enabled
          ? "Keeping the newest items offline — click to stop and remove them"
          : `Keep the newest ${readSyncLimit()} items offline`
      }
    >
      <ArrowPathIcon
        className={enabled ? "text-matrix" : "text-text-muted hover:text-matrix"}
      />
    </button>
  )
}

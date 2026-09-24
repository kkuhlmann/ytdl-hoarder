"use client"

import { useCallback } from "react"

import { useStoredValue, writeStored } from "@/app/_hooks/useStoredValue"
import type { OfflineSource } from "@/app/lib/offlineDb"
import { readSyncMarks, SYNC_MARKS_KEY, syncMarkedCollections } from "@/app/lib/offlineSync"

/**
 * Whether one collection is marked to keep offline.
 *
 * `read` must return a primitive for useSyncExternalStore's Object.is comparison,
 * so this resolves membership to a boolean rather than handing back the array.
 */
export function useCollectionSync(source: OfflineSource) {
  const enabled = useStoredValue(
    useCallback(() => readSyncMarks().includes(source), [source]),
    false
  )

  const toggle = useCallback(() => {
    const marks = readSyncMarks()
    const next = marks.includes(source)
      ? marks.filter((mark) => mark !== source)
      : [...marks, source]
    writeStored(SYNC_MARKS_KEY, JSON.stringify(next))
    // Unmarking has cleanup to do too — syncMarkedCollections drops what is no
    // longer marked, so it runs on both edges.
    void syncMarkedCollections()
  }, [source])

  return { enabled, toggle }
}

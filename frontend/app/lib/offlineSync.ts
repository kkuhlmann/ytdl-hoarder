"use client"

/**
 * Keeping a playlist or a subscription downloaded.
 *
 * "Keep offline" means keep the newest N items, not everything: a subscription can
 * hold hundreds of videos, and the alternative — queue them all and let the storage
 * budget refuse the overflow — turns one setting into a screen full of failed rows.
 * A rolling window is also what makes the LRU pool meaningful, since synced items
 * are exactly the ones eviction is allowed to reclaim.
 */

import axios from "axios"

import { apiUrl } from "./api"
import { mediaApi } from "./mediaApi"
import { allItems, type OfflineSource } from "./offlineDb"
import { queueDownload, removeDownload, type DownloadableRow } from "./offlineDownloader"

export const SYNC_MARKS_KEY = "offline:sync"
export const SYNC_LIMIT_KEY = "offline:syncLimit"
export const DEFAULT_SYNC_LIMIT = 20

export type SyncedRecord = {
  id: number
  status?: string
  media_type?: string
  file_size_bytes?: number
}

export function readSyncMarks(): OfflineSource[] {
  try {
    const raw = localStorage.getItem(SYNC_MARKS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? (parsed as OfflineSource[]) : []
  } catch {
    return []
  }
}

export function readSyncLimit(): number {
  try {
    const parsed = Number(localStorage.getItem(SYNC_LIMIT_KEY))
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_SYNC_LIMIT
  } catch {
    return DEFAULT_SYNC_LIMIT
  }
}

export function playlistSource(id: number): OfflineSource {
  return `playlist:${id}`
}

export function subscriptionSource(id: number): OfflineSource {
  return `subscription:${id}`
}

/** Newest-first members of a marked collection, capped at the rolling window. */
async function membersOf(source: OfflineSource, limit: number): Promise<SyncedRecord[]> {
  const [kind, rawId] = source.split(":")
  const id = Number(rawId)

  if (kind === "playlist") {
    const response = await axios.get(apiUrl(`/playlists/${id}/media`), {
      params: { page: 1, page_size: limit, sort_by: "position", sort_direction: "asc" },
    })
    return (response.data.records ?? response.data ?? []) as SyncedRecord[]
  }

  // Subscriptions have no membership endpoint — their media is discovered by the
  // pipeline and identified only by channel, which is how the group-folder
  // drill-down finds it too.
  const subscription = await axios.get(apiUrl(`/subscriptions/${id}`))
  const channel = subscription.data?.channel
  if (!channel) return []

  const response = await axios.get(apiUrl(mediaApi.list), {
    params: {
      channel,
      status: "COMPLETE",
      page: 1,
      page_size: limit,
      sort_by: "downloaded_at",
      sort_direction: "desc",
    },
  })
  return (response.data.records ?? []) as SyncedRecord[]
}

function toDownloadable(record: SyncedRecord): DownloadableRow {
  return {
    media_details_id: record.id,
    media_type: record.media_type,
    file_size_bytes: record.file_size_bytes,
  }
}

/**
 * Bring every marked collection into line: queue what is missing, drop what has
 * fallen out of the window or off the collection entirely.
 *
 * Manual pins are untouched even when they belong to a synced collection — the
 * item's source is promoted to "manual" on a hand download, which is what takes it
 * out of this routine's reach.
 */
export async function syncMarkedCollections(): Promise<void> {
  const marks = readSyncMarks()
  const limit = readSyncLimit()
  const keep = new Set<number>()
  // A collection whose listing failed is left alone below rather than emptied:
  // an unreachable server must not read as "every item was removed upstream".
  const failedSources = new Set<OfflineSource>()

  for (const source of marks) {
    let members: SyncedRecord[] = []
    try {
      members = await membersOf(source, limit)
    } catch {
      failedSources.add(source)
      continue
    }

    for (const record of members) {
      if (record.status && record.status !== "COMPLETE") continue
      if (!record.file_size_bytes) continue
      keep.add(record.id)
      queueDownload(toDownloadable(record), source)
    }
  }

  // Dropped through removeDownload rather than deleteItem: an item that fell out
  // of the window may still be queued or mid-chunk from this same pass, and a bare
  // delete would either be re-written underneath or simply downloaded again.
  for (const item of await allItems()) {
    if (item.pinned) continue
    if (!marks.includes(item.source)) {
      await removeDownload(item.id)
      continue
    }
    if (failedSources.has(item.source)) continue
    if (!keep.has(item.id)) await removeDownload(item.id)
  }
}

"use client"

/**
 * Downloads media into IndexedDB for offline playback.
 *
 * Runs in the page rather than the service worker on purpose: Background Fetch is
 * Chrome-only, and iOS tears the worker down when the app is backgrounded anyway,
 * so a worker-side queue would buy nothing and cost a second code path. What makes
 * that survivable is resumability — progress is committed after every chunk, so a
 * download interrupted by a phone locking picks up where it stopped.
 *
 * Chunks are fetched with explicit Range headers. Those requests pass straight
 * through the service worker untouched, because it only answers from storage for
 * items already marked complete.
 */

import { apiUrl } from "./api"
import { mediaApi } from "./mediaApi"
import { NUM_PEAKS } from "@/app/_hooks/usePeaks"
import { planEviction, readBudgetBytes } from "./offlineBudget"
import {
  allItems,
  deleteItem,
  getItem,
  putAsset,
  putChunk,
  putItem,
  putMeta,
  type OfflineAssetKind,
  type OfflineItem,
  type OfflineSource,
} from "./offlineDb"
import { CHUNK_SIZE, chunkByteRange, chunkCountFor } from "./offlineRange"

export type DownloadState = "queued" | "downloading" | "ready" | "error"

export type DownloadProgress = {
  mediaId: number
  state: DownloadState
  storedBytes: number
  totalBytes: number
  error?: string
}

/** Enough to start a download; a list row already carries all of it. */
export type DownloadableRow = {
  media_details_id: number
  media_type?: string
  file_size_bytes?: number
}

type Listener = () => void

function ignore() {}

const listeners = new Set<Listener>()
let snapshot: ReadonlyMap<number, DownloadProgress> = new Map()

const queue: { row: DownloadableRow; source: OfflineSource }[] = []
const controllers = new Map<number, AbortController>()
/** Settle-only promises for running downloads, so a delete can wait one out. */
const inFlight = new Map<number, Promise<void>>()
let running = false
let persistenceRequested = false

function emit(next: Map<number, DownloadProgress>) {
  snapshot = next
  for (const listener of listeners) listener()
}

function update(mediaId: number, patch: Partial<DownloadProgress>) {
  const next = new Map(snapshot)
  const current = next.get(mediaId) ?? {
    mediaId,
    state: "queued" as DownloadState,
    storedBytes: 0,
    totalBytes: 0,
  }
  next.set(mediaId, { ...current, ...patch })
  emit(next)
}

function forget(mediaId: number) {
  const next = new Map(snapshot)
  next.delete(mediaId)
  emit(next)
}

export function subscribeToDownloads(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function downloadSnapshot(): ReadonlyMap<number, DownloadProgress> {
  return snapshot
}

/**
 * Ask the browser to exempt this origin from eviction.
 *
 * Deferred to the first download rather than done at startup: this is where the
 * user has expressed intent, and it is the only moment at which a browser that
 * prompts (Firefox) asks a question the user can answer.
 */
async function requestPersistence() {
  if (persistenceRequested) return
  persistenceRequested = true
  try {
    await navigator.storage?.persist?.()
  } catch {
    // Advisory only — eviction risk, not a failure.
  }
}

async function fetchAsset(
  mediaId: number,
  kind: OfflineAssetKind,
  path: string,
  signal: AbortSignal
): Promise<void> {
  const response = await fetch(apiUrl(path), { credentials: "include", signal })
  if (!response.ok) return
  const blob = await response.blob()
  await putAsset({
    mediaId,
    kind,
    blob,
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
  })
}

/**
 * Cache the record and the derived assets that make the offline library look
 * normal. Each is best-effort: a missing sprite sheet is a cosmetic loss, and
 * failing the whole download over one would be worse than shipping without it.
 */
async function fetchSidecars(row: DownloadableRow, signal: AbortSignal) {
  const id = row.media_details_id

  try {
    const response = await fetch(apiUrl(mediaApi.detail(id)), {
      credentials: "include",
      signal,
    })
    if (response.ok) await putMeta(id, await response.json())
  } catch {
    // Falls back to whatever the list already stored for this row.
  }

  const assets: [OfflineAssetKind, string][] = [
    ["thumbnail", mediaApi.thumbnail(id)],
    ["peaks", `${mediaApi.peaks(id)}?num_peaks=${NUM_PEAKS}`],
  ]
  if (row.media_type === "VIDEO") {
    assets.push(["sprites", mediaApi.sprites(id)])
    assets.push(["spriteMetadata", mediaApi.spriteMetadata(id)])
  }

  for (const [kind, path] of assets) {
    try {
      await fetchAsset(id, kind, path, signal)
    } catch {
      // Best-effort; see above.
    }
  }
}

async function makeRoom(row: DownloadableRow, needBytes: number) {
  const plan = planEviction(await allItems(), needBytes, readBudgetBytes(), row.media_details_id)
  for (const id of plan.evict) await deleteItem(id)
  if (!plan.fits) {
    throw new Error("Not enough offline storage. Remove a download or raise the budget.")
  }
}

async function downloadOne(row: DownloadableRow, source: OfflineSource) {
  const id = row.media_details_id
  const totalBytes = row.file_size_bytes ?? 0
  if (totalBytes <= 0) throw new Error("This item has no recorded file size yet.")

  const controller = new AbortController()
  controllers.set(id, controller)

  try {
    const existing = await getItem(id)
    // Resuming keeps the chunks already on disk, so only the shortfall is charged
    // against the budget.
    const alreadyStored = existing ? Math.min(existing.chunksStored * CHUNK_SIZE, totalBytes) : 0
    await makeRoom(row, totalBytes - alreadyStored)

    const chunkCount = chunkCountFor(totalBytes)
    let item: OfflineItem = existing ?? {
      id,
      pinned: source === "manual",
      source,
      bytes: totalBytes,
      contentType: "application/octet-stream",
      chunkCount,
      chunksStored: 0,
      complete: false,
      addedAt: Date.now(),
      lastPlayedAt: 0,
    }
    // A re-download after the file changed size upstream must not stitch old and
    // new bytes together.
    if (item.bytes !== totalBytes) {
      await deleteItem(id)
      item = { ...item, bytes: totalBytes, chunkCount, chunksStored: 0, complete: false }
    }
    // A manual download over a synced one promotes it out of the eviction pool.
    if (source === "manual") item = { ...item, pinned: true, source }
    await putItem(item)

    update(id, {
      state: "downloading",
      totalBytes,
      storedBytes: item.chunksStored * CHUNK_SIZE,
    })

    for (let index = item.chunksStored; index < chunkCount; index++) {
      const range = chunkByteRange(index, totalBytes)
      const response = await fetch(apiUrl(mediaApi.stream(id)), {
        credentials: "include",
        signal: controller.signal,
        headers: { Range: `bytes=${range.start}-${range.end}` },
      })
      if (!response.ok && response.status !== 206) {
        throw new Error(`Download failed (HTTP ${response.status})`)
      }

      await putChunk(id, index, await response.blob())
      item = {
        ...item,
        chunksStored: index + 1,
        // Taken from the origin rather than guessed from the extension, so the
        // worker replays exactly the type the server would have sent — including
        // its deliberate video/mp4 for every video container.
        contentType: response.headers.get("content-type") ?? item.contentType,
      }
      await putItem(item)
      update(id, { storedBytes: Math.min((index + 1) * CHUNK_SIZE, totalBytes) })
    }

    await putItem({ ...item, complete: true })
    await fetchSidecars(row, controller.signal)
    update(id, { state: "ready", storedBytes: totalBytes })
  } finally {
    controllers.delete(id)
  }
}

async function drain() {
  if (running) return
  running = true
  try {
    while (queue.length > 0) {
      const next = queue.shift()
      if (!next) break
      const task = downloadOne(next.row, next.source)
      inFlight.set(next.row.media_details_id, task.then(ignore, ignore))
      try {
        await task
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          forget(next.row.media_details_id)
          continue
        }
        update(next.row.media_details_id, {
          state: "error",
          error: error instanceof Error ? error.message : "Download failed",
        })
      } finally {
        inFlight.delete(next.row.media_details_id)
      }
    }
  } finally {
    running = false
  }
}

/** Queue an item for offline storage. Downloads run one at a time. */
export function queueDownload(row: DownloadableRow, source: OfflineSource = "manual") {
  const id = row.media_details_id
  if (controllers.has(id) || queue.some((entry) => entry.row.media_details_id === id)) return
  void requestPersistence()
  update(id, { state: "queued", storedBytes: 0, totalBytes: row.file_size_bytes ?? 0 })
  queue.push({ row, source })
  void drain()
}

export function cancelDownload(mediaId: number) {
  const queuedAt = queue.findIndex((entry) => entry.row.media_details_id === mediaId)
  if (queuedAt >= 0) queue.splice(queuedAt, 1)
  controllers.get(mediaId)?.abort()
  forget(mediaId)
}

export async function removeDownload(mediaId: number) {
  cancelDownload(mediaId)
  // Aborting only stops the fetch; the loop may still be committing the chunk it
  // already holds. Deleting before it unwinds leaves that chunk and its item row
  // behind, occupying storage nothing can account for.
  await inFlight.get(mediaId)
  await deleteItem(mediaId)
  forget(mediaId)
}

/** Seed the store from IndexedDB so the UI shows what is already downloaded. */
export async function hydrateDownloads() {
  const items = await allItems()
  const next = new Map(snapshot)
  for (const item of items) {
    if (next.has(item.id)) continue
    next.set(item.id, {
      mediaId: item.id,
      state: item.complete ? "ready" : "error",
      storedBytes: Math.min(item.chunksStored * CHUNK_SIZE, item.bytes),
      totalBytes: item.bytes,
      // An incomplete row means the app closed mid-download. Surfaced as an error
      // with a resume affordance rather than restarted silently, so a metered
      // connection never re-downloads a video without being asked.
      error: item.complete ? undefined : "Download interrupted",
    })
  }
  emit(next)
}

/** Resume every interrupted download, e.g. from an explicit "resume all". */
export async function resumeInterrupted() {
  const items = await allItems()
  for (const item of items) {
    if (item.complete) continue
    queueDownload(
      { media_details_id: item.id, file_size_bytes: item.bytes },
      item.source
    )
  }
}

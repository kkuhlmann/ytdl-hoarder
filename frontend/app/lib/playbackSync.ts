"use client"

/**
 * Playback-position persistence that survives being offline.
 *
 * The player writes a position every 5 seconds of drift. Online that is a fire-
 * and-forget PATCH; offline the write is parked in IndexedDB and replayed when the
 * app is next online, so a film watched on a plane resumes in the right place.
 */

import axios from "axios"

import { apiUrl } from "./api"
import { mediaApi } from "./mediaApi"
import { clearOutboxEntries, enqueueOutbox, readOutbox } from "./offlineDb"
import { readOfflineMode } from "./offlineMode"

function patchPosition(mediaId: number, playbackPosition: number, lastAccessed: string) {
  return axios.patch(apiUrl(mediaApi.playback(mediaId)), {
    playback_position: playbackPosition,
    last_accessed: lastAccessed,
  })
}

/** No response at all — the server is unreachable, as opposed to refusing. */
function isNetworkError(error: unknown): boolean {
  return axios.isAxiosError(error) && !error.response
}

/** Record a position, queueing it when the server is out of reach. */
export function savePlaybackPosition(mediaId: number, playbackPosition: number): void {
  const lastAccessed = new Date().toISOString()

  if (readOfflineMode()) {
    void enqueueOutbox({ mediaId, playbackPosition, lastAccessed })
    return
  }

  void patchPosition(mediaId, playbackPosition, lastAccessed).catch((error) => {
    // Only a dropped connection is worth parking. A 4xx means the server saw the
    // request and refused it, so replaying it later would only fail again.
    if (isNetworkError(error)) {
      void enqueueOutbox({ mediaId, playbackPosition, lastAccessed })
    }
  })
}

/** Replay parked positions. Safe to call when the outbox is empty. */
export async function flushPlaybackOutbox(): Promise<void> {
  if (readOfflineMode()) return

  const entries = await readOutbox()
  if (entries.length === 0) return

  const done: number[] = []
  for (const entry of entries) {
    try {
      await patchPosition(entry.mediaId, entry.playbackPosition, entry.lastAccessed)
      done.push(entry.mediaId)
    } catch (error) {
      if (isNetworkError(error)) break // Still offline; keep the rest for next time.
      // The server refused this one — most likely the media was deleted while the
      // device was away. Drop it, or one dead entry blocks the queue forever.
      done.push(entry.mediaId)
    }
  }
  if (done.length > 0) await clearOutboxEntries(done)
}

"use client"

import { useCallback } from "react"
import { useStoredValue, writeStored } from "./useStoredValue"

const storageKey = (playlistId: number) => `resumePlayback:${playlistId}`

/**
 * Whether a playlist resumes each track from its saved playback position, and
 * therefore whether the per-row progress bar means anything here.
 *
 * Stored per playlist in localStorage rather than on the playlist row: a
 * playback position is per-user (the playback_state table), so a column on
 * `playlists` would let one user's choice change what a co-owner sees.
 *
 * Tag Mix passes TAG_MIX_PLAYLIST_ID, giving that whole surface one setting —
 * the toggle is a playback preference, not part of a mix's identity.
 */
export function useResumePlayback(
  playlistId: number
): readonly [boolean, (next: boolean) => void] {
  const enabled = useStoredValue(
    () => localStorage.getItem(storageKey(playlistId)) === "1",
    false
  )

  const setEnabled = useCallback(
    (next: boolean) => writeStored(storageKey(playlistId), next ? "1" : "0"),
    [playlistId]
  )

  return [enabled, setEnabled] as const
}

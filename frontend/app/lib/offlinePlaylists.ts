"use client"

/**
 * Playlists, served from IndexedDB while offline.
 *
 * Membership is a snapshot of server truth taken while online (see
 * `OfflinePlaylist`), and which playlists to show is decided here at read time:
 * one whose members are all still on the server has nothing to play, so it is
 * left out rather than listed empty. Responses use the API's envelope so
 * PlaylistsCard consumes either source with the same code.
 */

import axios from "axios"

import type { Playlist, PlaylistMedia, PlaylistTrack } from "@/app/types/PlaylistOptions"

import { apiUrl } from "./api"
import { allPlaylists, replacePlaylists, type OfflinePlaylist } from "./offlineDb"
import { OFFLINE_PAGE_SIZE, playableRecords, sortRecords, type MediaRecord } from "./offlineLibrary"

/** Above any real library; the player already asks for a playlist's media 1000 at a time. */
const SNAPSHOT_PAGE_SIZE = 1000

/**
 * Refresh the membership snapshot from the server. Best-effort: on any failure
 * the previous snapshot stands, since stale membership beats none at all.
 */
export async function snapshotPlaylists(): Promise<void> {
  let records: Playlist[]
  try {
    const response = await axios.get(apiUrl("/playlists"), {
      params: { page_size: SNAPSHOT_PAGE_SIZE, include_media_ids: true },
    })
    records = response.data.records ?? []
  } catch {
    return
  }

  const snapshotAt = Date.now()
  await replacePlaylists(
    records.map((playlist) => ({
      id: playlist.id,
      name: playlist.name,
      description: playlist.description,
      source_url: playlist.source_url,
      created_at: playlist.created_at,
      updated_at: playlist.updated_at,
      mediaIds: playlist.media_ids ?? [],
      snapshotAt,
    }))
  )
}

type Envelope<T> = { count_records: number; page_count: number; records: T[] }

function paginate<T>(rows: T[], pageNumber: number, pageSize: number): Envelope<T> {
  const start = (Math.max(1, pageNumber) - 1) * pageSize
  return {
    count_records: rows.length,
    page_count: Math.max(1, Math.ceil(rows.length / pageSize)),
    records: rows.slice(start, start + pageSize),
  }
}

/** A playlist's downloaded members, in playlist order. */
function downloadedMembers(
  playlist: OfflinePlaylist,
  recordsById: Map<number, MediaRecord>
): MediaRecord[] {
  return playlist.mediaIds.flatMap((id) => {
    const record = recordsById.get(id)
    return record ? [record] : []
  })
}

async function playableById(): Promise<Map<number, MediaRecord>> {
  return new Map((await playableRecords()).map((record) => [record.id, record]))
}

export type OfflinePlaylistsQuery = {
  search?: string | null
  pageNumber?: number
  sortBy?: string | null
  sortDirection?: string | null
  pageSize?: number
}

/**
 * The playlists worth showing offline: those with at least one downloaded member.
 * Counts and durations describe what is on the device, not the playlist upstream.
 */
export async function fetchOfflinePlaylists({
  search,
  pageNumber = 1,
  sortBy,
  sortDirection,
  pageSize = OFFLINE_PAGE_SIZE,
}: OfflinePlaylistsQuery): Promise<Envelope<Playlist>> {
  const [playlists, recordsById] = await Promise.all([allPlaylists(), playableById()])

  let rows = playlists.flatMap((playlist) => {
    const members = downloadedMembers(playlist, recordsById)
    if (members.length === 0) return []
    const row: Playlist = {
      id: playlist.id,
      name: playlist.name,
      description: playlist.description,
      source_url: playlist.source_url,
      created_at: playlist.created_at,
      updated_at: playlist.updated_at,
      media_count: members.length,
      total_duration: members.reduce(
        (sum, record) => sum + (typeof record.duration === "number" ? record.duration : 0),
        0
      ),
      sample_media_ids: members.slice(0, 4).map((record) => record.id),
    }
    return [row]
  })

  if (search && search.length > 2) {
    const needle = search.toLowerCase()
    rows = rows.filter((row) => row.name.toLowerCase().includes(needle))
  }

  // The list's sort keys are all plain playlist columns, so the library's sorter
  // applies directly. Its default key (downloaded_at) is absent here; mirror the
  // server's created_at DESC instead.
  return paginate(sortRecords(rows, sortBy || "created_at", sortDirection), pageNumber, pageSize)
}

/**
 * Downloaded tracks of one playlist as `PlaylistTrack`s. Positions are renumbered
 * over what is on the device, so the `#` column counts the queue that will
 * actually play rather than showing gaps where the missing members were.
 */
async function downloadedTracks(playlistId: number): Promise<PlaylistTrack[]> {
  const [playlists, recordsById] = await Promise.all([allPlaylists(), playableById()])
  const playlist = playlists.find((candidate) => candidate.id === playlistId)
  if (!playlist) return []

  return downloadedMembers(playlist, recordsById).map((record, index) => ({
    ...(record as unknown as PlaylistTrack),
    media_details_id: record.id,
    playlist_id: playlistId,
    playlist_media_id: record.id,
    position: index + 1,
    added_at: "",
  }))
}

export async function fetchOfflinePlaylistMedia(
  playlistId: number,
  { pageNumber = 1, pageSize = OFFLINE_PAGE_SIZE }: { pageNumber?: number; pageSize?: number } = {}
): Promise<Envelope<PlaylistTrack>> {
  return paginate(await downloadedTracks(playlistId), pageNumber, pageSize)
}

/** The whole playlist as a player queue, the shape `playMediaQueue` takes. */
export async function offlinePlaylistQueue(playlistId: number): Promise<PlaylistMedia[]> {
  return (await downloadedTracks(playlistId)) as unknown as PlaylistMedia[]
}

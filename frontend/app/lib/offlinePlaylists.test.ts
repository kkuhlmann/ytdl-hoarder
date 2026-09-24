import "fake-indexeddb/auto"

import { describe, it, expect, beforeEach } from "vitest"

import {
  openOfflineDb,
  putItem,
  putMeta,
  replacePlaylists,
  type OfflineItem,
  type OfflinePlaylist,
} from "./offlineDb"
import {
  fetchOfflinePlaylistMedia,
  fetchOfflinePlaylists,
  offlinePlaylistQueue,
} from "./offlinePlaylists"

const item = (overrides: Partial<OfflineItem> & { id: number }): OfflineItem => ({
  pinned: false,
  source: "manual",
  bytes: 100,
  contentType: "video/mp4",
  chunkCount: 1,
  chunksStored: 1,
  complete: true,
  addedAt: 1,
  lastPlayedAt: 0,
  ...overrides,
})

const playlist = (
  id: number,
  mediaIds: number[],
  overrides: Partial<OfflinePlaylist> = {}
): OfflinePlaylist => ({
  id,
  name: `Playlist ${id}`,
  description: null,
  source_url: null,
  created_at: `2026-01-0${id}T00:00:00Z`,
  updated_at: `2026-01-0${id}T00:00:00Z`,
  mediaIds,
  snapshotAt: 1,
  ...overrides,
})

async function wipe() {
  const db = await openOfflineDb()
  const stores = Array.from(db.objectStoreNames)
  const tx = db.transaction(stores, "readwrite")
  for (const name of stores) tx.objectStore(name).clear()
  await new Promise((resolve) => (tx.oncomplete = resolve))
}

async function download(id: number, overrides: Partial<OfflineItem> = {}) {
  await putItem(item({ id, ...overrides }))
  await putMeta(id, { id, title: `Track ${id}`, duration: 10 * id })
}

beforeEach(wipe)

describe("fetchOfflinePlaylists", () => {
  it("lists only playlists with a downloaded member, described by what is on the device", async () => {
    await download(1)
    await download(2)
    await replacePlaylists([
      playlist(1, [5, 2, 1, 6]),
      playlist(2, [7, 8]),
      playlist(3, []),
    ])

    const { records, count_records } = await fetchOfflinePlaylists({})

    expect(count_records).toBe(1)
    expect(records[0]).toMatchObject({
      id: 1,
      media_count: 2,
      total_duration: 30,
      sample_media_ids: [2, 1],
    })
  })

  it("ignores a member whose download has not finished", async () => {
    await download(1, { complete: false, chunksStored: 0 })
    await replacePlaylists([playlist(1, [1])])

    expect((await fetchOfflinePlaylists({})).records).toEqual([])
  })

  it("searches by name from three characters and pages like the server", async () => {
    await download(1)
    await replacePlaylists([
      playlist(1, [1], { name: "Road trip" }),
      playlist(2, [1], { name: "Focus" }),
      playlist(3, [1], { name: "Road works" }),
    ])

    const searched = await fetchOfflinePlaylists({ search: "road", sortBy: "name", sortDirection: "asc" })
    expect(searched.records.map((row) => row.name)).toEqual(["Road trip", "Road works"])

    const tooShort = await fetchOfflinePlaylists({ search: "ro" })
    expect(tooShort.count_records).toBe(3)

    const paged = await fetchOfflinePlaylists({ pageNumber: 2, pageSize: 2 })
    expect(paged.page_count).toBe(2)
    expect(paged.records).toHaveLength(1)
  })

  it("defaults to newest first, as the server list does", async () => {
    await download(1)
    await replacePlaylists([playlist(1, [1]), playlist(2, [1])])

    expect((await fetchOfflinePlaylists({})).records.map((row) => row.id)).toEqual([2, 1])
  })
})

describe("fetchOfflinePlaylistMedia", () => {
  it("returns downloaded tracks in playlist order with positions renumbered", async () => {
    await download(1)
    await download(2)
    await download(3)
    await replacePlaylists([playlist(1, [3, 9, 1, 2])])

    const { records } = await fetchOfflinePlaylistMedia(1)

    expect(records.map((track) => track.media_details_id)).toEqual([3, 1, 2])
    expect(records.map((track) => track.position)).toEqual([1, 2, 3])
    expect(records.every((track) => track.playlist_id === 1)).toBe(true)
  })

  it("is empty for an unknown playlist", async () => {
    expect((await fetchOfflinePlaylistMedia(42)).records).toEqual([])
  })
})

describe("offlinePlaylistQueue", () => {
  it("hands the player every downloaded track, not just one page", async () => {
    for (let id = 1; id <= 30; id++) await download(id)
    await replacePlaylists([playlist(1, Array.from({ length: 30 }, (_, i) => i + 1))])

    const queue = await offlinePlaylistQueue(1)

    expect(queue).toHaveLength(30)
    expect(queue[0]).toMatchObject({ media_details_id: 1, title: "Track 1" })
  })
})

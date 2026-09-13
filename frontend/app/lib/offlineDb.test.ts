import "fake-indexeddb/auto"

import { describe, it, expect, beforeEach } from "vitest"

import {
  allItems,
  clearOutboxEntries,
  deleteItem,
  enqueueOutbox,
  getAsset,
  getItem,
  openOfflineDb,
  putAsset,
  putChunk,
  putItem,
  putMeta,
  readOutbox,
  readRange,
  storedBytesOf,
  touchItem,
  usedBytes,
  type OfflineItem,
} from "./offlineDb"
import { CHUNK_SIZE } from "./offlineRange"

/** Deterministic filler so an assembled range can be checked byte for byte. */
function chunkOf(byte: number, size: number): Blob {
  return new Blob([new Uint8Array(size).fill(byte)])
}

async function bytesOf(blob: Blob): Promise<Uint8Array> {
  return new Uint8Array(await blob.arrayBuffer())
}

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

async function wipe() {
  const db = await openOfflineDb()
  const stores = Array.from(db.objectStoreNames)
  const tx = db.transaction(stores, "readwrite")
  for (const name of stores) tx.objectStore(name).clear()
  await new Promise((resolve) => (tx.oncomplete = resolve))
}

beforeEach(wipe)

describe("chunk storage", () => {
  it("assembles a range that spans two chunks", async () => {
    // Small chunks would not exercise the real offsets, so use the real size.
    await putChunk(1, 0, chunkOf(0xaa, CHUNK_SIZE))
    await putChunk(1, 1, chunkOf(0xbb, 10))

    const blob = await readRange(1, { start: CHUNK_SIZE - 2, end: CHUNK_SIZE + 1 })
    expect(blob).not.toBeNull()
    expect(Array.from(await bytesOf(blob!))).toEqual([0xaa, 0xaa, 0xbb, 0xbb])
  })

  it("reads a range inside a single chunk at the right offset", async () => {
    await putChunk(2, 0, new Blob([new Uint8Array([1, 2, 3, 4, 5])]))

    const blob = await readRange(2, { start: 1, end: 3 })
    expect(Array.from(await bytesOf(blob!))).toEqual([2, 3, 4])
  })

  it("returns null when a needed chunk is missing", async () => {
    // Chunk 1 was never stored: serving a hole would corrupt playback silently.
    await putChunk(3, 0, chunkOf(0xaa, CHUNK_SIZE))

    expect(await readRange(3, { start: 0, end: CHUNK_SIZE + 5 })).toBeNull()
  })

  it("does not read another item's chunks", async () => {
    await putChunk(4, 0, new Blob([new Uint8Array([9])]))

    expect(await readRange(5, { start: 0, end: 0 })).toBeNull()
  })
})

describe("deleteItem", () => {
  it("removes the item's chunks, assets and metadata but leaves other items alone", async () => {
    await putItem(item({ id: 10 }))
    await putItem(item({ id: 11 }))
    await putChunk(10, 0, new Blob([new Uint8Array([1])]))
    await putChunk(11, 0, new Blob([new Uint8Array([2])]))
    await putMeta(10, { id: 10 })
    await putAsset({ mediaId: 10, kind: "thumbnail", blob: new Blob(["t"]), contentType: "image/jpeg" })
    await putAsset({ mediaId: 11, kind: "peaks", blob: new Blob(["p"]), contentType: "application/json" })

    await deleteItem(10)

    expect(await getItem(10)).toBeUndefined()
    expect(await readRange(10, { start: 0, end: 0 })).toBeNull()
    expect(await getAsset(10, "thumbnail")).toBeUndefined()

    // The compound-key bounds must not spill into the neighbouring item.
    expect(await getItem(11)).toBeDefined()
    expect(await getAsset(11, "peaks")).toBeDefined()
    expect(await readRange(11, { start: 0, end: 0 })).not.toBeNull()
  })

  it("is not undone by a concurrent touch", async () => {
    await putItem(item({ id: 12 }))
    await putChunk(12, 0, new Blob([new Uint8Array([1])]))

    // Deleting mid-playback: the worker touches the item on every range it serves,
    // so a touch that read before the delete must not write the row back after it.
    const touch = touchItem(12)
    await deleteItem(12)
    await touch

    expect(await allItems()).toHaveLength(0)
  })
})

describe("accounting", () => {
  it("charges a complete item its full size and a partial one what it holds", async () => {
    await putItem(item({ id: 20, bytes: 500, complete: true }))
    await putItem(
      item({ id: 21, bytes: 10 ** 9, complete: false, chunksStored: 2, chunkCount: 300 })
    )

    expect(await usedBytes()).toBe(500 + 2 * CHUNK_SIZE)
  })

  it("never charges a partial item more than its declared size", async () => {
    const partial = item({ id: 22, bytes: 10, complete: false, chunksStored: 1 })
    expect(storedBytesOf(partial)).toBe(10)
  })

  it("touchItem records playback and is a no-op for an unknown id", async () => {
    await putItem(item({ id: 23, lastPlayedAt: 0 }))

    await touchItem(23)
    expect((await getItem(23))!.lastPlayedAt).toBeGreaterThan(0)

    await touchItem(999)
    expect(await allItems()).toHaveLength(1)
  })
})

describe("playback outbox", () => {
  it("keeps one entry per media id, holding the latest position", async () => {
    await enqueueOutbox({ mediaId: 1, playbackPosition: 10, lastAccessed: "a" })
    await enqueueOutbox({ mediaId: 1, playbackPosition: 90, lastAccessed: "b" })
    await enqueueOutbox({ mediaId: 2, playbackPosition: 5, lastAccessed: "c" })

    const entries = await readOutbox()
    expect(entries).toHaveLength(2)
    expect(entries.find((e) => e.mediaId === 1)!.playbackPosition).toBe(90)
  })

  it("clears only the entries it is given", async () => {
    await enqueueOutbox({ mediaId: 1, playbackPosition: 10, lastAccessed: "a" })
    await enqueueOutbox({ mediaId: 2, playbackPosition: 20, lastAccessed: "b" })

    await clearOutboxEntries([1])

    expect((await readOutbox()).map((e) => e.mediaId)).toEqual([2])
  })
})

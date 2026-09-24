import "fake-indexeddb/auto"

import { describe, it, expect, beforeEach } from "vitest"

import { openOfflineDb, putItem, putMeta, type OfflineItem } from "./offlineDb"
import {
  fetchOfflineStats,
  matchesSearch,
  offlineTags,
  sortRecords,
  type MediaRecord,
} from "./offlineLibrary"

const record = (title: string, channel = ""): MediaRecord =>
  ({ id: 1, title, channel }) as MediaRecord

describe("matchesSearch", () => {
  it("matches a substring of the title or the channel, case-insensitively", () => {
    expect(matchesSearch(record("The Big Show"), "big")).toBe(true)
    expect(matchesSearch(record("x", "Some Channel"), "channel")).toBe(true)
    expect(matchesSearch(record("The Big Show"), "small")).toBe(false)
  })

  it("requires every && term", () => {
    expect(matchesSearch(record("rust and go"), "rust && go")).toBe(true)
    expect(matchesSearch(record("rust only"), "rust && go")).toBe(false)
  })

  it("accepts any || group", () => {
    expect(matchesSearch(record("only go"), "rust || go")).toBe(true)
    expect(matchesSearch(record("neither"), "rust || go")).toBe(false)
  })

  it("binds && tighter than ||", () => {
    // (rust && go) || python
    expect(matchesSearch(record("python talk"), "rust && go || python")).toBe(true)
    expect(matchesSearch(record("rust talk"), "rust && go || python")).toBe(false)
    expect(matchesSearch(record("rust and go"), "rust && go || python")).toBe(true)
  })

  it("treats single & and | as literal characters", () => {
    expect(matchesSearch(record("Law & Order"), "law & order")).toBe(true)
    expect(matchesSearch(record("Rock | Roll"), "rock | roll")).toBe(true)
  })

  it("matches everything when the search parses to no terms", () => {
    expect(matchesSearch(record("anything"), "&&")).toBe(true)
    expect(matchesSearch(record("anything"), "  ")).toBe(true)
  })
})

describe("sortRecords", () => {
  const rows = [
    { id: 1, title: "b", duration: 20 },
    { id: 2, title: "a", duration: 30 },
    { id: 3, title: "c", duration: 10 },
  ] as MediaRecord[]

  it("defaults to newest downloaded first", () => {
    const dated = [
      { id: 1, downloaded_at: "2026-01-01" },
      { id: 2, downloaded_at: "2026-03-01" },
    ] as MediaRecord[]
    expect(sortRecords(dated, null, null).map((r) => r.id)).toEqual([2, 1])
  })

  it("sorts numbers numerically, not lexically", () => {
    expect(sortRecords(rows, "duration", "asc").map((r) => r.duration)).toEqual([10, 20, 30])
  })

  it("honours the direction", () => {
    expect(sortRecords(rows, "title", "asc").map((r) => r.title)).toEqual(["a", "b", "c"])
    expect(sortRecords(rows, "title", "desc").map((r) => r.title)).toEqual(["c", "b", "a"])
  })

  it("puts nulls last when ascending, as NULLS LAST does", () => {
    const withNulls = [
      { id: 1, rating: null },
      { id: 2, rating: 5 },
      { id: 3, rating: 1 },
    ] as MediaRecord[]
    expect(sortRecords(withNulls, "rating", "asc").map((r) => r.id)).toEqual([3, 2, 1])
  })

  it("does not mutate its input", () => {
    const original = [...rows]
    sortRecords(rows, "title", "asc")
    expect(rows).toEqual(original)
  })
})

describe("stats and tags from the device", () => {
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

  beforeEach(async () => {
    await wipe()
    await putItem(item({ id: 1 }))
    await putMeta(1, {
      id: 1,
      title: "Rust talk",
      transcript_block_count: 12,
      tags: [{ id: 3, name: "tech" }, { id: 1, name: "talks" }],
    })
    await putItem(item({ id: 2 }))
    await putMeta(2, { id: 2, title: "Go talk", transcript_block_count: 0, tags: [{ id: 3, name: "tech" }] })
    // Not finished, so never part of the library.
    await putItem(item({ id: 3, complete: false, chunksStored: 0 }))
    await putMeta(3, { id: 3, title: "Rust half", transcript_block_count: 4, tags: [{ id: 9, name: "half" }] })
  })

  it("counts downloads and transcript blocks, honouring the search", async () => {
    expect(await fetchOfflineStats()).toEqual({
      total_downloads: 2,
      total_transcript_blocks: 12,
      downloads_with_transcripts: 1,
    })
    expect((await fetchOfflineStats("rust")).total_downloads).toBe(1)
  })

  it("lists each tag once, by name, from finished downloads only", async () => {
    expect(await offlineTags()).toEqual([
      { id: 1, name: "talks" },
      { id: 3, name: "tech" },
    ])
  })
})

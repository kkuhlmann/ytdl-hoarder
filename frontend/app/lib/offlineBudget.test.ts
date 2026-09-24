import { describe, it, expect } from "vitest"
import { planEviction } from "./offlineBudget"
import { CHUNK_SIZE } from "./offlineRange"
import type { OfflineItem } from "./offlineDb"

function item(overrides: Partial<OfflineItem> & { id: number }): OfflineItem {
  return {
    pinned: false,
    source: "playlist:1",
    bytes: 100,
    contentType: "video/mp4",
    chunkCount: 1,
    chunksStored: 1,
    complete: true,
    addedAt: 0,
    lastPlayedAt: 0,
    ...overrides,
  }
}

describe("planEviction", () => {
  it("evicts nothing when the download already fits", () => {
    const plan = planEviction([item({ id: 1 })], 50, 1000)
    expect(plan).toEqual({ evict: [], fits: true, freedBytes: 0 })
  })

  it("evicts least recently played first", () => {
    const items = [
      item({ id: 1, lastPlayedAt: 300 }),
      item({ id: 2, lastPlayedAt: 100 }),
      item({ id: 3, lastPlayedAt: 200 }),
    ]
    const plan = planEviction(items, 100, 300)
    expect(plan.evict).toEqual([2])
    expect(plan.fits).toBe(true)
  })

  it("breaks a lastPlayedAt tie on insertion order", () => {
    const items = [
      item({ id: 1, lastPlayedAt: 0, addedAt: 200 }),
      item({ id: 2, lastPlayedAt: 0, addedAt: 100 }),
    ]
    expect(planEviction(items, 100, 200).evict).toEqual([2])
  })

  it("never evicts a pinned item, even as the only candidate", () => {
    const items = [item({ id: 1, pinned: true, source: "manual", lastPlayedAt: 0 })]
    const plan = planEviction(items, 100, 100)
    expect(plan.evict).toEqual([])
    expect(plan.fits).toBe(false)
  })

  it("reports fits: false when every candidate still isn't enough", () => {
    const items = [item({ id: 1, bytes: 10 }), item({ id: 2, pinned: true, bytes: 500 })]
    const plan = planEviction(items, 1000, 600)
    expect(plan.evict).toEqual([1])
    expect(plan.fits).toBe(false)
    expect(plan.freedBytes).toBe(10)
  })

  it("evicts as many as the shortfall needs and no more", () => {
    const items = [
      item({ id: 1, lastPlayedAt: 1 }),
      item({ id: 2, lastPlayedAt: 2 }),
      item({ id: 3, lastPlayedAt: 3 }),
    ]
    const plan = planEviction(items, 150, 300)
    expect(plan.evict).toEqual([1, 2])
  })

  it("does not evict the item being resumed", () => {
    const items = [item({ id: 1, lastPlayedAt: 0 }), item({ id: 2, lastPlayedAt: 5 })]
    const plan = planEviction(items, 100, 250, 1)
    expect(plan.evict).toEqual([2])
  })

  it("counts a partial download at its stored size, not its final size", () => {
    // 1 chunk stored of a nominally huge file: it occupies one chunk, so evicting
    // it frees a chunk -- charging the full declared size would over-evict.
    const partial = item({ id: 1, complete: false, chunksStored: 1, bytes: 10 ** 9 })
    const plan = planEviction([partial], 10, 100)
    expect(plan.evict).toEqual([1])
    expect(plan.freedBytes).toBe(CHUNK_SIZE)
  })
})

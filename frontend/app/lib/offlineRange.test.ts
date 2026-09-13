import { describe, it, expect } from "vitest"
import {
  CHUNK_SIZE,
  chunkByteRange,
  chunkCountFor,
  chunkIndexRange,
  fullResponseInit,
  parseRangeHeader,
  partialResponseInit,
  sliceWithinChunks,
  unsatisfiableResponseInit,
} from "./offlineRange"

const TOTAL = 1000

describe("parseRangeHeader", () => {
  it("parses Safari's opening two-byte probe", () => {
    expect(parseRangeHeader("bytes=0-1", TOTAL)).toEqual({ start: 0, end: 1 })
  })

  it("runs an open-ended range to the last byte", () => {
    expect(parseRangeHeader("bytes=500-", TOTAL)).toEqual({ start: 500, end: 999 })
  })

  it("clamps an end past the resource rather than rejecting it", () => {
    expect(parseRangeHeader("bytes=900-99999", TOTAL)).toEqual({ start: 900, end: 999 })
  })

  it("resolves a suffix range from the end", () => {
    expect(parseRangeHeader("bytes=-100", TOTAL)).toEqual({ start: 900, end: 999 })
  })

  it("clamps a suffix range longer than the resource", () => {
    expect(parseRangeHeader("bytes=-5000", TOTAL)).toEqual({ start: 0, end: 999 })
  })

  it("tolerates surrounding whitespace", () => {
    expect(parseRangeHeader("  bytes=0-1  ", TOTAL)).toEqual({ start: 0, end: 1 })
  })

  it("rejects a start at or past the end of the resource", () => {
    expect(parseRangeHeader("bytes=1000-", TOTAL)).toBeNull()
    expect(parseRangeHeader("bytes=1500-1600", TOTAL)).toBeNull()
  })

  it("rejects an inverted range", () => {
    expect(parseRangeHeader("bytes=500-400", TOTAL)).toBeNull()
  })

  it("rejects multi-range, other units and malformed input", () => {
    expect(parseRangeHeader("bytes=0-1,5-6", TOTAL)).toBeNull()
    expect(parseRangeHeader("items=0-1", TOTAL)).toBeNull()
    expect(parseRangeHeader("bytes=-", TOTAL)).toBeNull()
    expect(parseRangeHeader("", TOTAL)).toBeNull()
  })

  it("rejects a zero-length suffix", () => {
    expect(parseRangeHeader("bytes=-0", TOTAL)).toBeNull()
  })

  it("returns null for an empty resource rather than a negative range", () => {
    expect(parseRangeHeader("bytes=0-", 0)).toBeNull()
  })
})

describe("response inits", () => {
  it("builds a 206 whose length matches the inclusive span", () => {
    const init = partialResponseInit({ start: 0, end: 1 }, TOTAL, "video/mp4")
    expect(init.status).toBe(206)
    expect(init.headers["Content-Range"]).toBe("bytes 0-1/1000")
    expect(init.headers["Content-Length"]).toBe("2")
    expect(init.headers["Accept-Ranges"]).toBe("bytes")
    expect(init.headers["Content-Type"]).toBe("video/mp4")
  })

  it("advertises range support on the unranged 200 too", () => {
    const init = fullResponseInit(TOTAL, "audio/mpeg")
    expect(init.status).toBe(200)
    expect(init.headers["Content-Length"]).toBe("1000")
    expect(init.headers["Accept-Ranges"]).toBe("bytes")
    expect(init.headers["Content-Range"]).toBeUndefined()
  })

  it("reports the total size on a 416", () => {
    const init = unsatisfiableResponseInit(TOTAL)
    expect(init.status).toBe(416)
    expect(init.headers["Content-Range"]).toBe("bytes */1000")
  })
})

describe("chunk arithmetic", () => {
  it("counts a partial trailing chunk", () => {
    expect(chunkCountFor(CHUNK_SIZE)).toBe(1)
    expect(chunkCountFor(CHUNK_SIZE + 1)).toBe(2)
    expect(chunkCountFor(0)).toBe(0)
  })

  it("clamps the final chunk to the end of the file", () => {
    const total = CHUNK_SIZE + 10
    expect(chunkByteRange(0, total)).toEqual({ start: 0, end: CHUNK_SIZE - 1 })
    expect(chunkByteRange(1, total)).toEqual({ start: CHUNK_SIZE, end: total - 1 })
  })

  it("spans every chunk a range crosses", () => {
    const range = { start: CHUNK_SIZE - 1, end: CHUNK_SIZE + 1 }
    expect(chunkIndexRange(range)).toEqual({ first: 0, last: 1 })
  })

  it("keeps a range inside one chunk to that chunk", () => {
    expect(chunkIndexRange({ start: 10, end: 20 })).toEqual({ first: 0, last: 0 })
  })

  it("offsets a cross-boundary range against the first chunk it needs", () => {
    const range = { start: CHUNK_SIZE + 5, end: CHUNK_SIZE + 9 }
    // The assembled blob starts at chunk 1, so the slice offset is 5, not CHUNK_SIZE + 5.
    expect(sliceWithinChunks(range)).toEqual({ offset: 5, length: 5 })
  })
})

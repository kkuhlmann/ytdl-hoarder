/**
 * HTTP Range arithmetic for media served out of local storage.
 *
 * Shared by the page-side downloader and the service worker, so it must stay free
 * of `window`/`document`: sw/tsconfig.json compiles the worker with lib "WebWorker"
 * and no DOM, and a DOM-only global reached from here fails that build.
 *
 * Getting the 206 shape exactly right is what makes seeking work. Safari probes a
 * media element's source with `bytes=0-1` before anything else and abandons the
 * element if the reply is malformed, which surfaces as "it downloaded but won't
 * play" rather than as a range error.
 */

/** Inclusive byte offsets, matching the Range/Content-Range wire format. */
export type ByteRange = { start: number; end: number }

export type ResponseInit206 = { status: number; headers: Record<string, string> }

/** 4 MiB balances request overhead against how much work an interrupted chunk loses. */
export const CHUNK_SIZE = 4 * 1024 * 1024

const RANGE_PATTERN = /^bytes=(\d*)-(\d*)$/

/**
 * Parse a single byte range against a known total size.
 *
 * Returns null when the range is unsatisfiable, malformed, or a multi-range set —
 * the caller turns that into a 416. A suffix range (`bytes=-500`) is accepted even
 * though the backend refuses it: serving from local storage costs nothing extra,
 * and being stricter than the spec here would only break a client the origin never
 * had to satisfy.
 */
export function parseRangeHeader(header: string, totalSize: number): ByteRange | null {
  if (totalSize <= 0) return null

  const match = RANGE_PATTERN.exec(header.trim())
  if (!match) return null

  const [, rawStart, rawEnd] = match
  if (rawStart === "" && rawEnd === "") return null

  if (rawStart === "") {
    const suffixLength = Number(rawEnd)
    if (suffixLength <= 0) return null
    return { start: Math.max(0, totalSize - suffixLength), end: totalSize - 1 }
  }

  const start = Number(rawStart)
  if (start >= totalSize) return null

  // An open-ended range runs to the end of the resource; a closed one is clamped,
  // since a client may ask past the end and still expects what exists.
  const end = rawEnd === "" ? totalSize - 1 : Math.min(Number(rawEnd), totalSize - 1)
  if (end < start) return null

  return { start, end }
}

export function partialResponseInit(
  range: ByteRange,
  totalSize: number,
  contentType: string
): ResponseInit206 {
  return {
    status: 206,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(range.end - range.start + 1),
      "Content-Range": `bytes ${range.start}-${range.end}/${totalSize}`,
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store",
    },
  }
}

export function fullResponseInit(totalSize: number, contentType: string): ResponseInit206 {
  return {
    status: 200,
    headers: {
      "Content-Type": contentType,
      "Content-Length": String(totalSize),
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store",
    },
  }
}

export function unsatisfiableResponseInit(totalSize: number): ResponseInit206 {
  return {
    status: 416,
    headers: {
      "Content-Range": `bytes */${totalSize}`,
      "Accept-Ranges": "bytes",
      "Cache-Control": "no-store",
    },
  }
}

export function chunkCountFor(totalBytes: number, chunkSize = CHUNK_SIZE): number {
  if (totalBytes <= 0) return 0
  return Math.ceil(totalBytes / chunkSize)
}

/** The byte span chunk `index` occupies, clamped to the final short chunk. */
export function chunkByteRange(
  index: number,
  totalBytes: number,
  chunkSize = CHUNK_SIZE
): ByteRange {
  const start = index * chunkSize
  return { start, end: Math.min(start + chunkSize - 1, totalBytes - 1) }
}

/** The inclusive span of chunk indices needed to answer `range`. */
export function chunkIndexRange(
  range: ByteRange,
  chunkSize = CHUNK_SIZE
): { first: number; last: number } {
  return {
    first: Math.floor(range.start / chunkSize),
    last: Math.floor(range.end / chunkSize),
  }
}

/**
 * Where `range` falls inside the concatenation of chunks `first..last`, so a
 * caller can slice the assembled blob without re-deriving the offsets.
 */
export function sliceWithinChunks(
  range: ByteRange,
  chunkSize = CHUNK_SIZE
): { offset: number; length: number } {
  const { first } = chunkIndexRange(range, chunkSize)
  const offset = range.start - first * chunkSize
  return { offset, length: range.end - range.start + 1 }
}

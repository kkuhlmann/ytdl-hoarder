/**
 * The media list, served from IndexedDB instead of the API.
 *
 * Swapped in at the single call site that fetches the library (page.tsx's
 * fetchDownloadJobs) rather than intercepted in the service worker. The list
 * endpoint's responses vary by search, sort, page and filter, so worker-level
 * caching would hit only on a query the user had already run; reading the stored
 * records directly answers every query offline.
 *
 * The filter and sort semantics below deliberately mirror
 * repositories/media_details.py — a search that works online should not quietly
 * return nothing here.
 */

import { allItems, allMeta } from "./offlineDb"

/**
 * Matches AppSettings.download_table_page_size' default. That setting lives in
 * app_settings and is unreachable offline, so a server whose admin changed it
 * paginates the offline list slightly differently. Cosmetic: the same rows are
 * reachable either way.
 */
export const OFFLINE_PAGE_SIZE = 25

export type OfflineLibraryQuery = {
  search?: string | null
  pageNumber?: number
  sortBy?: string | null
  sortDirection?: string | null
  tagIds?: number[] | null
  minRating?: number | null
  pageSize?: number
}

export type MediaRecord = Record<string, unknown> & { id: number }

/**
 * Mirrors _build_search_condition: '||' splits first, then '&&', so '&&' binds
 * tighter. Single '&' / '|' stay literal, which is what keeps 'Law & Order'
 * matching. Returns true when the search parses to no usable terms.
 */
export function matchesSearch(record: MediaRecord, search: string): boolean {
  const haystack = `${record.title ?? ""}\n${record.channel ?? ""}`.toLowerCase()

  const groups = search
    .split("||")
    .map((group) =>
      group
        .split("&&")
        .map((term) => term.trim().toLowerCase())
        .filter(Boolean)
    )
    .filter((terms) => terms.length > 0)

  if (groups.length === 0) return true
  return groups.some((terms) => terms.every((term) => haystack.includes(term)))
}

function compareValues(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0
  // Nulls sort last ascending, matching Postgres's NULLS LAST default for ASC.
  if (a == null) return 1
  if (b == null) return -1
  if (typeof a === "number" && typeof b === "number") return a - b
  return String(a).localeCompare(String(b))
}

export function sortRecords(
  records: MediaRecord[],
  sortBy: string | null | undefined,
  sortDirection: string | null | undefined
): MediaRecord[] {
  const field = sortBy || "downloaded_at"
  const factor = sortDirection === "asc" ? 1 : -1
  // Sorted by field name against the flat serialized record, which already carries
  // the playback and rating columns the online sort reaches through joins.
  return [...records].sort((a, b) => factor * compareValues(a[field], b[field]))
}

export async function fetchOfflineLibrary({
  search,
  pageNumber = 1,
  sortBy,
  sortDirection,
  tagIds,
  minRating,
  pageSize = OFFLINE_PAGE_SIZE,
}: OfflineLibraryQuery): Promise<{ pageCount: number; tableRows: MediaRecord[] }> {
  const [items, metas] = await Promise.all([allItems(), allMeta()])
  const playable = new Set(items.filter((item) => item.complete).map((item) => item.id))

  let rows = metas
    .filter((meta) => playable.has(meta.id))
    .map((meta) => meta.record as MediaRecord)

  // Below three characters the online search sends nothing, so neither does this.
  if (search && search.length > 2) {
    rows = rows.filter((row) => matchesSearch(row, search))
  }

  if (tagIds && tagIds.length > 0) {
    const wanted = new Set(tagIds)
    // "Has any of these tags", as the backend's tag_id.in_(...) subquery does.
    rows = rows.filter((row) => {
      const tags = (row.tags as { id: number }[] | undefined) ?? []
      return tags.some((tag) => wanted.has(tag.id))
    })
  }

  if (minRating != null) {
    rows = rows.filter((row) => typeof row.rating === "number" && row.rating >= minRating)
  }

  rows = sortRecords(rows, sortBy, sortDirection)

  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const start = (Math.max(1, pageNumber) - 1) * pageSize
  return { pageCount, tableRows: rows.slice(start, start + pageSize) }
}

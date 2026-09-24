/**
 * Storage budget and LRU eviction.
 *
 * The split that makes this predictable: an item the user downloaded by hand is
 * `pinned` and is never evicted, so the thing someone deliberately saved for a
 * flight cannot be thrown away to make room for a background playlist sync. Only
 * collection-synced items form the LRU pool.
 */

import { storedBytesOf, type OfflineItem } from "./offlineDb"

export const DEFAULT_BUDGET_BYTES = 4 * 1024 * 1024 * 1024

export const BUDGET_STORAGE_KEY = "offline:budgetBytes"

/** Reads the budget, falling back whenever storage is unreadable or holds junk. */
export function readBudgetBytes(): number {
  try {
    const raw = localStorage.getItem(BUDGET_STORAGE_KEY)
    if (!raw) return DEFAULT_BUDGET_BYTES
    const parsed = Number(raw)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_BUDGET_BYTES
  } catch {
    return DEFAULT_BUDGET_BYTES
  }
}

export type EvictionPlan = {
  /** Item ids to remove, least recently played first. */
  evict: number[]
  /** False when evicting every candidate still leaves too little room. */
  fits: boolean
  freedBytes: number
}

/**
 * Choose what to drop so `needBytes` can be stored within `budgetBytes`.
 *
 * `lastPlayedAt` is written when the worker actually serves a byte range, so the
 * ordering reflects playback rather than a list having rendered a thumbnail.
 */
export function planEviction(
  items: OfflineItem[],
  needBytes: number,
  budgetBytes: number,
  keepId?: number
): EvictionPlan {
  const used = items.reduce((total, item) => total + storedBytesOf(item), 0)
  let overBy = used + needBytes - budgetBytes
  if (overBy <= 0) return { evict: [], fits: true, freedBytes: 0 }

  const candidates = items
    .filter((item) => !item.pinned && item.id !== keepId)
    .sort((a, b) => a.lastPlayedAt - b.lastPlayedAt || a.addedAt - b.addedAt)

  const evict: number[] = []
  let freedBytes = 0
  for (const item of candidates) {
    if (overBy <= 0) break
    const freed = storedBytesOf(item)
    evict.push(item.id)
    freedBytes += freed
    overBy -= freed
  }

  return { evict, fits: overBy <= 0, freedBytes }
}

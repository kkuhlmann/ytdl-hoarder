import { useCallback, useState } from "react"

/**
 * Multi-select state plus the values every bulk bar needs from it.
 *
 * For surfaces whose selection has to stop applying when the row set changes,
 * see the key-tagged selections in ClipsCard and DownloadsCard — those own their
 * id Set so they can tag it, which a hook-owned Set can't express.
 */
export function useBulkSelection<T>(rows: T[], idOf: (row: T) => number) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const selectedItems = rows.filter((r) => selectedIds.has(idOf(r)))
  const allSelected = rows.length > 0 && rows.every((r) => selectedIds.has(idOf(r)))

  const clear = useCallback(() => setSelectedIds(new Set()), [])

  const selectAll = useCallback(
    (selected: boolean) => setSelectedIds(selected ? new Set(rows.map(idOf)) : new Set()),
    [rows, idOf],
  )

  return { selectedIds, setSelectedIds, selectedItems, allSelected, clear, selectAll }
}

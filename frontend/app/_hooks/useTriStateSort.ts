import { useState } from "react"

export type SortDirection = "asc" | "desc" | null

/** Column sort cycling desc → asc → off, shared by every sortable card. */
export function useTriStateSort(
  initialBy: string | null = null,
  initialDirection: SortDirection = null,
) {
  const [sortBy, setSortBy] = useState<string | null>(initialBy)
  const [sortDirection, setSortDirection] = useState<SortDirection>(initialDirection)

  // sortBy/sortDirection are fetch deps at every call site, so committing them
  // refetches — a direct fetch call here would double-request.
  const handleSort = (column: string) => {
    let newDirection: SortDirection
    if (sortBy === column) {
      if (sortDirection === "desc") {
        newDirection = "asc"
      } else if (sortDirection === "asc") {
        newDirection = null
      } else {
        newDirection = "desc"
      }
    } else {
      newDirection = "desc"
    }

    setSortBy(newDirection === null ? null : column)
    setSortDirection(newDirection)
  }

  return { sortBy, sortDirection, handleSort }
}

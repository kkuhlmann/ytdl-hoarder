import type { GroupLeafFilter } from "@/app/types/DownloadsOptions"

/**
 * Map a group-folder filter onto the query params the media endpoints take.
 *
 * Shared by the media list and the transcript search so the two can't disagree
 * about what folder they are looking at.
 */
export function groupFilterParams(
  filter: GroupLeafFilter | null | undefined
): Record<string, string | number | boolean> {
  if (!filter) return {}

  const params: Record<string, string | number | boolean> = {}
  if (filter.channel != null) params.channel = filter.channel
  if (filter.untagged) params.untagged = true
  if (filter.dateField && filter.year != null) {
    params.date_field = filter.dateField
    params.date_year = filter.year
    // Absent when only a year is open — the backend reads that as the whole year.
    if (filter.month != null) params.date_month = filter.month
  }
  return params
}

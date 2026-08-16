import { Download } from "./DownloadsOptions"

export type Playlist = {
  id: number
  name: string
  description: string | null
  source_url: string | null
  created_at: string
  updated_at: string
  media_count: number
  total_duration: number
  user_id?: number
  /** First four member media ids, for the grid view's collage. */
  sample_media_ids?: number[]
}

/**
 * A track inside a playlist: a full media library row plus the join fields.
 *
 * `GET /playlists/{id}/media` returns the same serialized shape as the media
 * library, so these render with the same components.
 *
 * Note there is deliberately no `id` here. On the wire `id` is media_details.id
 * (matching the media library), while the join row's PK is `playlist_media_id`.
 * Leaving `id` off the type makes TypeScript flag any code that assumes the old
 * meaning, where `id` was the join PK.
 */
export type PlaylistTrack = Download & {
  playlist_media_id: number
  playlist_id: number
  position: number
  added_at: string
}

/**
 * The trimmed shape the media player queue works with (`light=true`).
 * `id` is optional because the enriched endpoint no longer leads with it.
 */
export type PlaylistMedia = {
  id?: number
  playlist_id: number
  media_details_id: number
  position: number
  added_at: string
  title?: string
  channel?: string
  duration?: number
  media_type?: string
  file_path?: string
  thumbnail_path?: string
  /** Only present when the queue was fetched with include_playback. */
  playback_position?: number
}

export type { SortDirection } from "@/app/_hooks/useTriStateSort"

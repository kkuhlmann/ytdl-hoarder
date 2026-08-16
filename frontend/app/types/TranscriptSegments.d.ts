import { Download } from "./DownloadsOptions"

export type TranscriptSegment = {
  transcript_block_id: number
  similarity: number
  fts_rank: number | null
  text: string
  start_time: number
  end_time: number
  media_details_id: number
  media_details: Download
}

export type Clip = {
  id: number
  media_details_id?: number
  title: string
  description?: string
  start_time: number
  end_time: number
  duration?: number
  file_path?: string
  media_type: string
  status: string
  created_at: string
  source_title?: string
  source_channel?: string
}

export type ClipStats = {
  total_clips: number
  audio_clips: number
  video_clips: number
}

export type { SortDirection } from "@/app/_hooks/useTriStateSort"

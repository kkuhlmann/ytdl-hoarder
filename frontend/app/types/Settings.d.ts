export interface Settings {
  download_sleep_seconds: number
  download_rate_limit_kbps: number
  request_sleep_seconds: number
  cleanup_age_hours: number
  player_client: string[]
  cookies_mode: string
  cookies_player_client: string[]
  transcript_chunk_duration: number
  transcript_block_duration: number
  force_whisper_transcription: boolean
  subscription_table_page_size: number
  download_table_page_size: number
  subscription_check_minutes: number
  default_lane_concurrency: number
  downloads_lane_concurrency: number
  subscriptions_lane_concurrency: number
  ml_lane_concurrency: number
  updated_at: string
}

export interface OptionMeta {
  value: string
  label: string
  description?: string
}

export interface SettingMeta {
  key: keyof Settings
  label: string
  description: string
  type: "number" | "list" | "boolean"
  min?: number
  max?: number
  options?: OptionMeta[] // For list type settings
}

export interface SettingsConfig {
  download: SettingMeta[]
  tasks: SettingMeta[]
  transcript: SettingMeta[]
  display: SettingMeta[]
}

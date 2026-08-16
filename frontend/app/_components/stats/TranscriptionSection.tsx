import type { TranscriptionStats } from "@/app/types/StatsOptions"
import { StatsPanel } from "./StatsPanel"
import { StatSummaryCard } from "./StatSummaryCard"
import { formatCount } from "./format"

export function TranscriptionSection({ transcription }: { transcription: TranscriptionStats | null }) {
  if (!transcription) return null

  return (
    <StatsPanel id="transcription" title="Transcription">
      <div className="grid grid-cols-2 gap-3">
        <StatSummaryCard
          label="Coverage"
          value={`${transcription.coverage_percent}%`}
          sub={`${transcription.with_transcripts} of ${transcription.total_media} media`}
        />
        <StatSummaryCard label="Total Blocks" value={formatCount(transcription.total_blocks)} />
      </div>
    </StatsPanel>
  )
}

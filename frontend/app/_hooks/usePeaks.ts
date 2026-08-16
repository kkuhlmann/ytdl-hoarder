import { useState } from 'react'
import axios from 'axios'
import { apiUrl, errorMessage } from '@/app/lib/api'
import { mediaApi } from '@/app/lib/mediaApi'
import { useFetchEffect } from '@/app/_hooks/useFetchEffect'

interface UsePeaksOptions {
  mediaDetailsId: number
  enabled?: boolean
}

interface UsePeaksResult {
  peaks: number[] | null
  duration: number | null
  isLoading: boolean
  error: string | null
  reload: () => void
}

// Slightly above the backend's ffmpeg ceiling so the backend's clean error wins.
const PEAKS_REQUEST_TIMEOUT_MS = 330_000

// Enough resolution for ~12x zoom without blocky bars.
const NUM_PEAKS = 8000

export function usePeaks({
  mediaDetailsId,
  enabled = true,
}: UsePeaksOptions): UsePeaksResult {
  const [peaks, setPeaks] = useState<number[] | null>(null)
  const [duration, setDuration] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const { isLoading, refetch } = useFetchEffect(
    (signal) => {
      setError(null)
      return axios
        .get(apiUrl(mediaApi.peaks(mediaDetailsId)), {
          params: { num_peaks: NUM_PEAKS },
          signal,
          timeout: PEAKS_REQUEST_TIMEOUT_MS,
        })
        .then((response) => {
          setPeaks(response.data.peaks)
          setDuration(response.data.duration)
        })
        .catch((err) => {
          if (axios.isCancel(err)) return
          setError(errorMessage(err, 'Failed to load waveform peaks'))
        })
    },
    [mediaDetailsId],
    { enabled }
  )

  return { peaks, duration, isLoading, error, reload: refetch }
}

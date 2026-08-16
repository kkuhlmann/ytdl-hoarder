import { useCallback, useRef } from 'react'

interface UseClipRegionProps {
  startTime: number
  setStartTime: (time: number) => void
  endTime: number
  setEndTime: (time: number) => void
  onSeek: (time: number) => void
}

/**
 * Hook for managing clip region seeking behavior.
 *
 * Seeking rules:
 * - Seek when start time changes (left edge drag or RangeSlider start)
 * - Don't seek when end time changes (right edge drag or RangeSlider end)
 * - Seek to start when dragging the whole region (both edges move together)
 *
 * This ensures playback isn't interrupted when adjusting the end boundary.
 */
export function useClipRegion({
  startTime,
  setStartTime,
  endTime,
  setEndTime,
  onSeek,
}: UseClipRegionProps) {
  // Track previous region bounds to detect which edge is being dragged
  const prevRegionStartRef = useRef(startTime)
  const prevRegionEndRef = useRef(endTime)

  const handleStartTimeChange = useCallback(
    (newStartTime: number) => {
      setStartTime(newStartTime)
      onSeek(newStartTime)
      prevRegionStartRef.current = newStartTime
    },
    [setStartTime, onSeek]
  )

  const handleEndTimeChange = useCallback(
    (newEndTime: number) => {
      setEndTime(newEndTime)
      prevRegionEndRef.current = newEndTime
    },
    [setEndTime]
  )

  const handleRegionChange = useCallback(
    (start: number, end: number) => {
      const startChanged = Math.abs(start - prevRegionStartRef.current) > 0.01

      setStartTime(start)
      setEndTime(end)

      if (startChanged) {
        onSeek(start)
      }

      prevRegionStartRef.current = start
      prevRegionEndRef.current = end
    },
    [setStartTime, setEndTime, onSeek]
  )

  return {
    handleStartTimeChange,
    handleEndTimeChange,
    handleRegionChange,
  }
}

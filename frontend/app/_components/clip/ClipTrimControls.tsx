"use client"

import { Button } from "@/components/ui/button"
import { RangeSlider } from "@/components/ui/range-slider"
import { formatTime } from "@/app/utils"

export function ClipTrimControls({
  startTime,
  endTime,
  clipDuration,
  duration,
  currentTime,
  isZoomed,
  viewStart,
  viewEnd,
  onStartChange,
  onEndChange,
  onSetStartFromCurrent,
  onSetEndFromCurrent,
}: {
  startTime: number
  endTime: number
  clipDuration: number
  duration: number
  currentTime: number
  isZoomed: boolean
  viewStart: number
  viewEnd: number
  onStartChange: (v: number) => void
  onEndChange: (v: number) => void
  onSetStartFromCurrent: () => void
  onSetEndFromCurrent: () => void
}) {
  return (
    <>
      <div className="space-y-2">
        <RangeSlider
          startValue={startTime}
          endValue={endTime}
          onStartChange={onStartChange}
          onEndChange={onEndChange}
          min={0}
          max={duration}
          step={0.1}
          viewMin={isZoomed ? viewStart : undefined}
          viewMax={isZoomed ? viewEnd : undefined}
        />
        <div className="flex justify-between text-xs font-mono text-text-muted">
          <span>{formatTime(isZoomed ? viewStart : startTime)}</span>
          <span className="text-matrix">Duration: {formatTime(clipDuration)}</span>
          <span>{formatTime(isZoomed ? viewEnd : endTime)}</span>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={onSetStartFromCurrent} className="flex-1">
          Set Start ({formatTime(currentTime)})
        </Button>
        <Button variant="outline" size="sm" onClick={onSetEndFromCurrent} className="flex-1">
          Set End ({formatTime(currentTime)})
        </Button>
      </div>
    </>
  )
}

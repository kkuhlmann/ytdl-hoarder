"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  ScissorsIcon,
  ArrowPathIcon,
  XMarkIcon,
} from "@heroicons/react/24/solid"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import { Waveform } from "./Waveform"
import { ZoomControls } from "./ZoomControls"
import { ClipSaveDialog } from "./clip/ClipSaveDialog"
import { ClipTrimControls } from "./clip/ClipTrimControls"
import { MIN_CLIP_SECONDS, useClipEditor } from "../_hooks/useClipEditor"
import { usePeaks } from "../_hooks/usePeaks"
import { useZoom } from "../_hooks/useZoom"

interface VideoClippingControlsProps {
  mediaDetailsId: number
  duration: number
  currentTime: number
  onSeek: (time: number) => void
  videoRef: React.RefObject<HTMLVideoElement | null>
  initialClippingMode?: boolean
}

export function VideoClippingControls({
  mediaDetailsId,
  duration,
  currentTime,
  onSeek,
  videoRef,
  initialClippingMode = false,
}: VideoClippingControlsProps) {
  const [isClippingMode, setIsClippingMode] = useState(initialClippingMode)
  // Measured off the element when clipping opens, for callers whose row carries
  // no duration — `MediaDetails.duration` is nullable, and a transcript-search
  // hit reaches this surface before one is known.
  const [measuredDuration, setMeasuredDuration] = useState(0)

  const {
    peaks,
    duration: peaksDuration,
    isLoading: peaksLoading,
    error: peaksError,
    reload: reloadPeaks,
  } = usePeaks({
    mediaDetailsId,
    enabled: isClippingMode,
  })

  // Peaks carry an ffprobe-measured duration, so they backstop a row and an
  // element that both came up empty.
  const effectiveDuration =
    duration > 0 ? duration : measuredDuration > 0 ? measuredDuration : (peaksDuration ?? 0)

  const editor = useClipEditor({
    mediaDetailsId,
    duration: effectiveDuration,
    currentTime,
    mediaRef: videoRef,
    onSeek,
    onSaved: () => handleExitClippingMode(),
    initialEnd: Math.min(effectiveDuration, 30),
  })

  const {
    zoomLevel,
    viewStart,
    viewEnd,
    zoomIn,
    zoomOut,
    zoomToSelection,
    resetZoom,
    isZoomed,
  } = useZoom({
    duration: effectiveDuration,
    selectionStart: editor.startTime,
    selectionEnd: editor.endTime,
  })

  const handleEnterClippingMode = () => {
    const measured = videoRef.current?.duration ?? 0
    const known =
      duration > 0 ? duration : Number.isFinite(measured) && measured > 0 ? measured : 0
    if (known > 0) setMeasuredDuration(known)

    const start = Math.max(0, currentTime - 5)
    const end = known > 0 ? Math.min(known, currentTime + 10) : currentTime + 10

    setIsClippingMode(true)
    editor.setStartTime(start)
    editor.setEndTime(Math.max(end, start + MIN_CLIP_SECONDS))
  }

  const handleExitClippingMode = () => {
    setIsClippingMode(false)
    editor.stopLooping()
    editor.setShowSaveDialog(false)
    editor.setTitle("")
    editor.setDescription("")
  }

  if (!isClippingMode) {
    return (
      <div className="flex justify-center pt-2">
        <Button
          variant="outline"
          size="sm"
          onClick={handleEnterClippingMode}
          className="gap-2"
        >
          <ScissorsIcon className="h-4 w-4" />
          Create Clip
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-4 pt-4 border-t border-border">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="font-mono text-sm text-matrix">Clip Selection</h4>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleExitClippingMode}
          className="h-8 w-8 p-0"
        >
          <XMarkIcon className="h-4 w-4" />
        </Button>
      </div>

      {/* Zoom controls and mini waveform */}
      <div className="space-y-2">
        <ZoomControls
          zoomLevel={zoomLevel}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onZoomToSelection={zoomToSelection}
          onResetZoom={resetZoom}
          isZoomed={isZoomed}
          compact
        />
        {peaksLoading ? (
          <div className="flex items-center justify-center h-[48px] rounded-lg bg-bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-muted font-mono text-xs">
              <div className="w-3 h-3 border-2 border-matrix border-t-transparent rounded-full animate-spin" />
              Generating waveform...
            </div>
          </div>
        ) : peaksError ? (
          <div className="flex items-center justify-center gap-3 h-[48px] rounded-lg bg-bg-surface border border-border">
            <span className="text-text-muted font-mono text-xs">Failed to generate waveform</span>
            <Button variant="outline" size="sm" onClick={reloadPeaks}>
              Retry
            </Button>
          </div>
        ) : (
          <Waveform
            mediaUrl={apiUrl(mediaApi.stream(mediaDetailsId))}
            currentTime={currentTime}
            onSeek={onSeek}
            peaks={peaks ?? undefined}
            peaksDuration={peaksDuration ?? undefined}
            showRegion={true}
            regionStart={editor.startTime}
            regionEnd={editor.endTime}
            onRegionChange={editor.handleRegionChange}
            viewStart={isZoomed ? viewStart : undefined}
            viewEnd={isZoomed ? viewEnd : undefined}
            height={48}
          />
        )}
      </div>

      <ClipTrimControls
        startTime={editor.startTime}
        endTime={editor.endTime}
        clipDuration={editor.clipDuration}
        duration={effectiveDuration}
        currentTime={currentTime}
        isZoomed={isZoomed}
        viewStart={viewStart}
        viewEnd={viewEnd}
        onStartChange={editor.handleStartTimeChange}
        onEndChange={editor.handleEndTimeChange}
        onSetStartFromCurrent={editor.handleSetStartFromCurrent}
        onSetEndFromCurrent={editor.handleSetEndFromCurrent}
      />

      {/* Action buttons */}
      <div className="flex gap-2">
        <Button
          variant={editor.isLooping ? "matrix" : "outline"}
          size="sm"
          onClick={editor.toggleLoop}
          className="gap-2"
        >
          <ArrowPathIcon className={`h-4 w-4 ${editor.isLooping ? "animate-spin" : ""}`} />
          {editor.isLooping ? "Stop Loop" : "Preview Loop"}
        </Button>
        <Button
          variant="matrix"
          size="sm"
          onClick={editor.handleCreateClip}
          className="gap-2 flex-1"
        >
          <ScissorsIcon className="h-4 w-4" />
          Create Clip
        </Button>
      </div>

      {editor.showSaveDialog && (
        <ClipSaveDialog
          title={editor.title}
          setTitle={editor.setTitle}
          description={editor.description}
          setDescription={editor.setDescription}
          saving={editor.saving}
          onCancel={() => editor.setShowSaveDialog(false)}
          onSave={editor.handleSaveClip}
        />
      )}
    </div>
  )
}

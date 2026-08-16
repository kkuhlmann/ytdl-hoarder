"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Slider } from "@/components/ui/slider"
import {
  ArrowLeftIcon,
  PlayIcon,
  PauseIcon,
  ArrowPathIcon,
  ScissorsIcon,
  BackwardIcon,
  ForwardIcon,
} from "@heroicons/react/24/solid"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import { Waveform } from "./Waveform"
import { ZoomControls } from "./ZoomControls"
import { ClipSaveDialog } from "./clip/ClipSaveDialog"
import { ClipTrimControls } from "./clip/ClipTrimControls"
import { useClipEditor } from "../_hooks/useClipEditor"
import { formatTime } from "@/app/utils"
import { usePeaks } from "../_hooks/usePeaks"
import { useZoom } from "../_hooks/useZoom"

interface AudioClippingPageProps {
  mediaDetailsId: number
  title: string
  channel: string
  duration: number
  onBack: () => void
}

export function AudioClippingPage({
  mediaDetailsId,
  title,
  channel,
  duration: initialDuration,
  onBack,
}: AudioClippingPageProps) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(initialDuration || 0)

  const {
    peaks,
    duration: peaksDuration,
    isLoading: peaksLoading,
    error: peaksError,
    reload: reloadPeaks,
  } = usePeaks({ mediaDetailsId })

  const mediaSrc = apiUrl(mediaApi.stream(mediaDetailsId))

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handleTimeUpdate = () => setCurrentTime(audio.currentTime)
    // An unseekable stream reports Infinity, which would blow out every range
    // the duration feeds (clip editor, zoom, slider max).
    const handleLoadedMetadata = () =>
      setDuration(Number.isFinite(audio.duration) ? audio.duration : 0)
    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)
    const handleEnded = () => setIsPlaying(false)

    audio.addEventListener("timeupdate", handleTimeUpdate)
    audio.addEventListener("loadedmetadata", handleLoadedMetadata)
    audio.addEventListener("play", handlePlay)
    audio.addEventListener("pause", handlePause)
    audio.addEventListener("ended", handleEnded)

    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate)
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata)
      audio.removeEventListener("play", handlePlay)
      audio.removeEventListener("pause", handlePause)
      audio.removeEventListener("ended", handleEnded)
    }
  }, [])

  const togglePlay = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
    } else {
      audio.play()
    }
  }, [isPlaying])

  const handleSeek = useCallback((value: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = value
    setCurrentTime(value)
  }, [])

  const editor = useClipEditor({
    mediaDetailsId,
    duration,
    currentTime,
    mediaRef: audioRef,
    onSeek: handleSeek,
    onSaved: onBack,
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
    duration,
    selectionStart: editor.startTime,
    selectionEnd: editor.endTime,
  })

  const skip = useCallback(
    (seconds: number) => {
      const audio = audioRef.current
      if (!audio) return
      const newTime = Math.max(0, Math.min(audio.currentTime + seconds, duration))
      audio.currentTime = newTime
      setCurrentTime(newTime)
    },
    [duration]
  )

  return (
    <div className="space-y-6">
      <audio ref={audioRef} src={mediaSrc} preload="metadata" />

      <div className="flex items-center gap-4">
        <Button variant="outline" onClick={onBack} className="gap-2">
          <ArrowLeftIcon className="h-4 w-4" />
          Back
        </Button>
        <div className="flex-1">
          <h2 className="font-mono text-lg text-text-primary">{title}</h2>
          <p className="text-sm text-text-secondary">{channel}</p>
        </div>
      </div>

      <div className="space-y-2">
        <ZoomControls
          zoomLevel={zoomLevel}
          onZoomIn={zoomIn}
          onZoomOut={zoomOut}
          onZoomToSelection={zoomToSelection}
          onResetZoom={resetZoom}
          isZoomed={isZoomed}
        />
        {peaksLoading ? (
          <div className="flex items-center justify-center h-[128px] rounded-lg bg-bg-surface border border-border">
            <div className="flex items-center gap-2 text-text-muted font-mono text-sm">
              <div className="w-4 h-4 border-2 border-matrix border-t-transparent rounded-full animate-spin" />
              Generating waveform...
            </div>
          </div>
        ) : peaksError ? (
          <div className="flex flex-col items-center justify-center gap-2 h-[128px] rounded-lg bg-bg-surface border border-border">
            <p className="text-text-muted font-mono text-sm">Failed to generate waveform</p>
            <p className="text-text-secondary font-mono text-xs max-w-md truncate">{peaksError}</p>
            <Button variant="outline" size="sm" onClick={reloadPeaks}>
              Retry
            </Button>
          </div>
        ) : (
          <Waveform
            mediaUrl={mediaSrc}
            currentTime={currentTime}
            onSeek={handleSeek}
            onReady={(d) => setDuration(d)}
            peaks={peaks ?? undefined}
            peaksDuration={peaksDuration ?? undefined}
            showRegion={true}
            regionStart={editor.startTime}
            regionEnd={editor.endTime}
            onRegionChange={editor.handleRegionChange}
            viewStart={isZoomed ? viewStart : undefined}
            viewEnd={isZoomed ? viewEnd : undefined}
            height={128}
          />
        )}
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm font-mono text-text-muted">
          <span>Playback Position</span>
          <span className="text-matrix">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
        </div>
        <Slider
          value={currentTime}
          onChange={handleSeek}
          min={0}
          max={duration || 100}
          step={0.1}
        />
      </div>

      <div className="flex items-center justify-center gap-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => skip(-10)}
          className="h-10 w-10"
          title="Back 10s"
        >
          <BackwardIcon className="h-5 w-5" />
        </Button>
        <Button
          variant="matrix"
          size="icon"
          onClick={togglePlay}
          className="h-14 w-14 rounded-full"
        >
          {isPlaying ? (
            <PauseIcon className="h-7 w-7" />
          ) : (
            <PlayIcon className="h-7 w-7 ml-1" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => skip(10)}
          className="h-10 w-10"
          title="Forward 10s"
        >
          <ForwardIcon className="h-5 w-5" />
        </Button>
      </div>

      <div className="space-y-4 p-4 bg-bg-surface/50 rounded-lg border border-border">
        <h3 className="font-mono text-sm text-matrix">Clip Selection</h3>

        <ClipTrimControls
          startTime={editor.startTime}
          endTime={editor.endTime}
          clipDuration={editor.clipDuration}
          duration={duration}
          currentTime={currentTime}
          isZoomed={isZoomed}
          viewStart={viewStart}
          viewEnd={viewEnd}
          onStartChange={editor.handleStartTimeChange}
          onEndChange={editor.handleEndTimeChange}
          onSetStartFromCurrent={editor.handleSetStartFromCurrent}
          onSetEndFromCurrent={editor.handleSetEndFromCurrent}
        />

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

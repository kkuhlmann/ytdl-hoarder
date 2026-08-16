"use client"

import { useRef, useState } from "react"
import { ArrowLeftIcon } from "@heroicons/react/20/solid"

import { Button } from "@/components/ui/button"
import { AudioClippingPage } from "@/app/_components/AudioClippingPage"
import { VideoPlayer } from "@/app/_components/MediaPlayer"
import { VideoClippingControls } from "@/app/_components/VideoClippingControls"
import { useElementDuration } from "@/app/_hooks/useElementDuration"
import type { Download } from "@/app/types/DownloadsOptions"

type MediaClipEditorProps = {
  media: Download
  onBack: () => void
  /** Label for the video branch's back button. Audio brings its own header. */
  backLabel?: string
}

/**
 * The clip editor for a single media row, as a self-contained surface.
 *
 * Callers only need a row and a way back, which is what lets the playlist detail
 * view and the tag mix open clipping without owning any of the player wiring.
 * The media library keeps its own copy of the video branch (DownloadsCard),
 * because there the same view doubles as normal playback.
 */
export function MediaClipEditor({
  media,
  onBack,
  backLabel = "Back",
}: MediaClipEditorProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const { duration: videoDuration, refCallback: handleVideoRef } = useElementDuration(videoRef)

  if (media.media_type === "AUDIO") {
    return (
      <AudioClippingPage
        mediaDetailsId={media.media_details_id}
        title={media.title}
        channel={media.channel}
        duration={media.duration ?? 0}
        onBack={onBack}
      />
    )
  }

  if (media.media_type !== "VIDEO") return null

  const duration = videoDuration || media.duration || 0

  return (
    <div className="space-y-4">
      <Button variant="outline" onClick={onBack} className="gap-2">
        <ArrowLeftIcon className="h-4 w-4" />
        {backLabel}
      </Button>

      <VideoPlayer
        id={media.media_details_id}
        startTime={media.playback_position || 0}
        duration={media.duration}
        onTimeUpdate={setCurrentTime}
        videoRefCallback={handleVideoRef}
      />

      <div className="text-center space-y-1">
        <h3 className="font-mono text-lg text-text-primary">{media.title}</h3>
        <p className="text-sm text-text-secondary">{media.channel}</p>
      </div>

      <VideoClippingControls
        mediaDetailsId={media.media_details_id}
        duration={duration}
        currentTime={currentTime}
        onSeek={(time) => {
          if (videoRef.current) {
            videoRef.current.currentTime = time
          }
        }}
        videoRef={videoRef}
        initialClippingMode
      />
    </div>
  )
}

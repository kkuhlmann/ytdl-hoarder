"use client"

import { useCallback, useState, useRef } from "react"
import { Button } from "@/components/ui/button"
import { VideoPlayer } from "./MediaPlayer"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"
import {
  ArrowLeftIcon,
  BackwardIcon,
  ForwardIcon,
  ArrowPathIcon,
  ArrowsRightLeftIcon,
  PlayIcon,
  CalendarIcon,
  EyeIcon,
} from "@heroicons/react/20/solid"
import { cn } from "@/lib/utils"
import { formatDate } from "@/app/utils"
import { StarRating } from "./StarRating"

type InlinePlaylistVideoPlayerProps = {
  onReturn: () => void
}

export function InlinePlaylistVideoPlayer({ onReturn }: InlinePlaylistVideoPlayerProps) {
  const {
    mediaPlayer,
    closeVideoPlayer,
    playNext,
    playPrevious,
    toggleAutoplay,
    toggleShuffle,
    rateMedia,
    nextTrack,
  } = useMediaPlayer()

  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [autoplayBlocked, setAutoplayBlocked] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const durationListenerRef = useRef<(() => void) | null>(null)

  const timeRemaining = duration - currentTime
  const showNextUp =
    duration > 0 &&
    !!nextTrack &&
    mediaPlayer.autoplayEnabled &&
    timeRemaining <= 30 &&
    timeRemaining > 0

  const handleVideoEnded = () => {
    if (mediaPlayer.autoplayEnabled && mediaPlayer.playlistId) {
      if (nextTrack) {
        playNext()
      } else {
        handleReturn()
      }
    } else {
      setAutoplayBlocked(true)
    }
  }

  const handleTimeUpdate = (time: number) => {
    setCurrentTime(time)
  }

  // Stable: VideoPlayer re-runs its ref effect whenever this identity changes,
  // so an inline arrow would re-attach the listener on every time-update tick.
  // The removal below keeps that a non-event even if a dep is added later.
  const handleVideoRef = useCallback((ref: HTMLVideoElement | null) => {
    if (videoRef.current && durationListenerRef.current) {
      videoRef.current.removeEventListener("loadedmetadata", durationListenerRef.current)
      durationListenerRef.current = null
    }
    videoRef.current = ref
    if (!ref) return
    const update = () => setDuration(ref.duration)
    if (ref.duration) update()
    ref.addEventListener("loadedmetadata", update)
    durationListenerRef.current = update
  }, [])

  const handlePlayNextManual = () => {
    setAutoplayBlocked(false)
    playNext()
  }

  const handleReturn = () => {
    closeVideoPlayer()
    onReturn()
  }

  const canGoPrevious = mediaPlayer.currentIndex !== undefined && mediaPlayer.currentIndex > 0
  const canGoNext = mediaPlayer.playlistMedia &&
    mediaPlayer.currentIndex !== undefined &&
    mediaPlayer.currentIndex < mediaPlayer.playlistMedia.length - 1

  // Lock-screen / OS media controls: prev-next track instead of skip-seconds
  const mediaSessionQueue = mediaPlayer.playlistId
    ? {
        hasNext: !!nextTrack,
        canGoPrevious,
        onNextTrack: playNext,
        onPreviousTrack: playPrevious,
      }
    : undefined

  const positionText = mediaPlayer.playlistMedia && mediaPlayer.currentIndex !== undefined
    ? `[${mediaPlayer.currentIndex + 1}/${mediaPlayer.playlistMedia.length}]`
    : ""

  return (
    <div className="space-y-4">
      <Button
        variant="outline"
        onClick={handleReturn}
        className="gap-2"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        Return to Playlist
      </Button>

      <div className="relative">
        <VideoPlayer
          id={mediaPlayer.media_details_id}
          startTime={mediaPlayer.start_time}
          duration={mediaPlayer.duration}
          onTimeUpdate={handleTimeUpdate}
          videoRefCallback={handleVideoRef}
          onEnded={handleVideoEnded}
          queue={mediaSessionQueue}
        />

        {showNextUp && nextTrack && (
          <div className="absolute bottom-24 right-4 bg-black/80 rounded-lg p-3 max-w-xs animate-in fade-in slide-in-from-right-2">
            <p className="text-white/70 text-xs uppercase tracking-wider mb-1">Next up</p>
            <p className="text-white text-sm font-medium truncate">{nextTrack.title}</p>
            {nextTrack.channel && (
              <p className="text-white/60 text-xs truncate">{nextTrack.channel}</p>
            )}
          </div>
        )}

        {autoplayBlocked && nextTrack && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60 rounded-lg">
            <div className="text-center">
              <p className="text-white/70 text-sm mb-3">Up next: {nextTrack.title}</p>
              <Button
                variant="matrix"
                size="lg"
                onClick={handlePlayNextManual}
                className="gap-2"
              >
                <PlayIcon className="h-5 w-5" />
                Play Next
              </Button>
            </div>
          </div>
        )}
      </div>

      <div className="text-center space-y-1">
        <h3 className="font-mono text-lg text-text-primary">
          {mediaPlayer.title}
        </h3>
        <p className="text-sm text-text-secondary">
          {mediaPlayer.channel}
          {mediaPlayer.playlistName && (
            <span className="ml-2 text-matrix">
              {positionText} {mediaPlayer.playlistName}
            </span>
          )}
        </p>
        {mediaPlayer.rating !== undefined && (
          <div className="flex justify-center mt-0.5">
            <StarRating
              rating={mediaPlayer.rating}
              onRate={(r) => rateMedia(r)}
            />
          </div>
        )}
        {mediaPlayer.url && (
          <a
            href={mediaPlayer.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-text-muted hover:text-matrix transition-colors font-mono truncate block"
          >
            {mediaPlayer.url}
          </a>
        )}
        {(mediaPlayer.release_timestamp || mediaPlayer.access_count !== undefined) && (
          <div className="flex items-center justify-center gap-4 text-xs text-text-muted font-mono mt-1">
            {mediaPlayer.release_timestamp && (
              <span className="flex items-center gap-1">
                <CalendarIcon className="h-3 w-3" />
                {formatDate(mediaPlayer.release_timestamp)}
              </span>
            )}
            {mediaPlayer.access_count !== undefined && (
              <span className="flex items-center gap-1">
                <EyeIcon className="h-3 w-3" />
                {mediaPlayer.access_count} {mediaPlayer.access_count === 1 ? "play" : "plays"}
              </span>
            )}
          </div>
        )}
      </div>

      {mediaPlayer.playlistId && (
        <div className="flex items-center justify-center gap-4 py-3 border-t border-border">
          <Button
            variant="ghost"
            size="icon"
            onClick={playPrevious}
            disabled={!canGoPrevious}
            className="h-10 w-10 disabled:opacity-30"
            title="Previous track"
          >
            <BackwardIcon className="h-5 w-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={playNext}
            disabled={!canGoNext}
            className="h-10 w-10 disabled:opacity-30"
            title="Next track"
          >
            <ForwardIcon className="h-5 w-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={toggleAutoplay}
            className={cn(
              "h-10 w-10",
              mediaPlayer.autoplayEnabled ? "text-matrix" : "text-text-muted"
            )}
            title={mediaPlayer.autoplayEnabled ? "Autoplay on" : "Autoplay off"}
          >
            <ArrowPathIcon className="h-5 w-5" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={toggleShuffle}
            className={cn(
              "h-10 w-10",
              mediaPlayer.shuffleEnabled ? "text-matrix" : "text-text-muted"
            )}
            title={mediaPlayer.shuffleEnabled ? "Shuffle on" : "Shuffle off"}
          >
            <ArrowsRightLeftIcon className="h-5 w-5" />
          </Button>

          {nextTrack && (
            <div className="text-text-muted text-sm ml-4">
              Next: <span className="text-text-secondary">{nextTrack.title?.slice(0, 30)}{(nextTrack.title?.length || 0) > 30 ? '...' : ''}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

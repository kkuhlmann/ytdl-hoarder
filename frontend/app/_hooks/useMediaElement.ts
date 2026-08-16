"use client"

import { useCallback, useEffect, useRef, useState, type RefObject } from "react"
import axios from "axios"
import { apiUrl } from "@/app/lib/api"
import { mediaApi } from "@/app/lib/mediaApi"
import {
  reportMediaSessionPosition,
  useMediaSessionActionHandlers,
  type MediaSessionQueue,
} from "@/app/_hooks/useMediaSession"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"

export type UseMediaElementOptions = {
  id: number
  startTime?: number
  initialDuration?: number
  /**
   * Treat `startTime` as a timestamp the user picked rather than a resume
   * position, so the near-the-end reset below doesn't apply.
   */
  exactStart?: boolean
  isClip?: boolean
  onEnded?: () => void
  onTimeUpdate?: (time: number) => void
  queue?: MediaSessionQueue
}

/**
 * Playback lifecycle shared by every media surface: transport state, element
 * event wiring, Media Session reporting, position persistence and the transport
 * callbacks. Works for <video> and <audio> alike; anything element-specific
 * (fullscreen, PiP, the audio visualizer) stays with the caller.
 */
export function useMediaElement<T extends HTMLMediaElement>(
  mediaRef: RefObject<T | null>,
  {
    id,
    startTime = 0,
    initialDuration,
    exactStart = false,
    isClip = false,
    onEnded,
    onTimeUpdate,
    queue,
  }: UseMediaElementOptions
) {
  const { notePlaybackPosition } = useMediaPlayer()

  // Throttle marker for the position PATCH below. Nothing renders it, so a ref
  // keeps the save out of the render cycle entirely.
  const lastSavedPositionRef = useRef(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(initialDuration || 0)
  const [volume, setVolume] = useState(1)
  const [isMuted, setIsMuted] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)

  const mediaSrc = isClip ? apiUrl(mediaApi.clip(id)) : apiUrl(mediaApi.stream(id))

  // Set initial position; a resume position within 30s of the end restarts from 0.
  useEffect(() => {
    if (mediaRef.current && typeof startTime === "number") {
      const effectiveStartTime =
        !exactStart && initialDuration && startTime > initialDuration - 30 ? 0 : startTime
      mediaRef.current.currentTime = effectiveStartTime
      setCurrentTime(effectiveStartTime)
    }
  }, [startTime, id, initialDuration, exactStart, mediaRef])

  // Explicit play() for iOS playback reliability — the autoPlay attribute is
  // unreliable on iOS Safari (and doesn't work in background at all).
  useEffect(() => {
    const el = mediaRef.current
    if (!el) return

    const attemptPlay = () => {
      el.play().catch(() => {
        // iOS may block autoplay; user can tap the play button
      })
    }

    if (el.readyState >= 2) {
      attemptPlay()
    } else {
      el.addEventListener("canplay", attemptPlay, { once: true })
      return () => el.removeEventListener("canplay", attemptPlay)
    }
  }, [id, mediaRef])

  useEffect(() => {
    const el = mediaRef.current
    if (!el) return

    const handleTimeUpdateEvent = () => {
      setCurrentTime(el.currentTime)
      onTimeUpdate?.(el.currentTime)
      // Report position to Media Session API for lock screen progress bar
      reportMediaSessionPosition(el)
    }
    const handleLoadedMetadata = () => setDuration(el.duration)
    const handlePlay = () => {
      setIsPlaying(true)
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing"
    }
    const handlePause = () => {
      setIsPlaying(false)
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused"
    }
    const handleEnded = () => {
      if (!isClip) {
        setIsPlaying(false)
        onEnded?.()
      }
    }

    el.addEventListener("timeupdate", handleTimeUpdateEvent)
    el.addEventListener("loadedmetadata", handleLoadedMetadata)
    el.addEventListener("play", handlePlay)
    el.addEventListener("pause", handlePause)
    el.addEventListener("ended", handleEnded)
    return () => {
      el.removeEventListener("timeupdate", handleTimeUpdateEvent)
      el.removeEventListener("loadedmetadata", handleLoadedMetadata)
      el.removeEventListener("play", handlePlay)
      el.removeEventListener("pause", handlePause)
      el.removeEventListener("ended", handleEnded)
    }
  }, [id, onTimeUpdate, isClip, onEnded, mediaRef])

  useMediaSessionActionHandlers(mediaRef, id, queue)

  useEffect(() => {
    if (isClip) return
    if (Math.abs(currentTime - lastSavedPositionRef.current) >= 5) {
      axios
        .patch(apiUrl(mediaApi.playback(id)), {
          playback_position: currentTime,
          last_accessed: new Date().toISOString(),
        })
        .catch(() => {})
      lastSavedPositionRef.current = currentTime
      // Publish on the same beat as the save, so a list's progress bar and the
      // stored position can never disagree.
      notePlaybackPosition(id, currentTime)
    }
  }, [currentTime, id, isClip, notePlaybackPosition])

  const togglePlay = useCallback(() => {
    const el = mediaRef.current
    if (!el) return
    if (isPlaying) el.pause()
    else el.play()
  }, [isPlaying, mediaRef])

  const handleSeek = useCallback(
    (value: number) => {
      const el = mediaRef.current
      if (!el) return
      el.currentTime = value
      setCurrentTime(value)
    },
    [mediaRef]
  )

  const handleVolumeChange = useCallback(
    (value: number) => {
      const el = mediaRef.current
      if (!el) return
      el.volume = value
      setVolume(value)
      setIsMuted(value === 0)
    },
    [mediaRef]
  )

  const toggleMute = useCallback(() => {
    const el = mediaRef.current
    if (!el) return
    if (isMuted) {
      el.volume = volume || 0.5
      setIsMuted(false)
    } else {
      el.volume = 0
      setIsMuted(true)
    }
  }, [isMuted, volume, mediaRef])

  const skip = useCallback(
    (seconds: number) => {
      const el = mediaRef.current
      if (!el) return
      const newTime = Math.max(0, Math.min(el.currentTime + seconds, duration))
      el.currentTime = newTime
      setCurrentTime(newTime)
    },
    [duration, mediaRef]
  )

  const handlePlaybackRateChange = useCallback(
    (rate: string) => {
      const numRate = parseFloat(rate)
      if (mediaRef.current) mediaRef.current.playbackRate = numRate
      setPlaybackRate(numRate)
    },
    [mediaRef]
  )

  return {
    mediaSrc,
    isPlaying,
    currentTime,
    duration,
    volume,
    isMuted,
    playbackRate,
    togglePlay,
    handleSeek,
    handleVolumeChange,
    toggleMute,
    skip,
    handlePlaybackRateChange,
    setCurrentTime,
    setDuration,
  }
}

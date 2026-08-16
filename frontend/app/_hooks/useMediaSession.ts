import { RefObject, useEffect } from "react"

/**
 * Report the current playback position to the Media Session API so the
 * lock-screen / now-playing scrubber stays accurate. Works for both <audio>
 * and <video>; no-op where the API is unavailable.
 */
export function reportMediaSessionPosition(media: HTMLMediaElement) {
  if ('mediaSession' in navigator && navigator.mediaSession.setPositionState) {
    try {
      navigator.mediaSession.setPositionState({
        duration: media.duration || 0,
        playbackRate: media.playbackRate,
        position: media.currentTime,
      })
    } catch {
      // Ignore - some browsers may not support position state
    }
  }
}

/**
 * Identifies the effect that most recently claimed navigator.mediaSession.
 *
 * Switching between playback surfaces (audio footer <-> inline video) mounts the
 * new player before the old one unmounts, and the unmount can land in a later
 * commit. Without this token the departing player's cleanup nulls the handlers
 * the new one just registered, leaving the lock screen with no controls at all.
 */
let currentOwner: symbol | null = null

/**
 * Describes the queue the media element is playing within. Passing this to
 * `useMediaSessionActionHandlers` switches the lock screen from skip-seconds
 * buttons to previous/next track buttons - see the note below on why the two
 * can't coexist.
 */
export type MediaSessionQueue = {
  hasNext: boolean
  canGoPrevious: boolean
  onNextTrack: () => void
  onPreviousTrack: () => void
}

/**
 * Wire Media Session action handlers to a media element so the OS lock-screen
 * controls work for both <audio> and <video>. Handlers are registered when the
 * element is available and cleared on unmount or when the media `id` changes.
 *
 * This hook is the single owner of `setActionHandler` - MediaPlayerContext owns
 * `mediaSession.metadata` only. Splitting action registration across two places
 * means whichever effect runs last silently wins.
 *
 * `queue` toggles the two mutually exclusive control layouts:
 *   - omitted (single-track playback) -> seekbackward/seekforward (+/-10s)
 *   - provided (playlist/queue)       -> previoustrack/nexttrack
 * They are mutually exclusive because WebKit maps seekbackward/seekforward onto
 * the same left/right Now Playing slots as the track buttons and gives the seek
 * actions priority, so registering both hides track skip entirely on iOS.
 * Scrubbing survives either way via `seekto` + reportMediaSessionPosition().
 */
export function useMediaSessionActionHandlers<T extends HTMLMediaElement>(
  ref: RefObject<T | null>,
  id: number,
  queue?: MediaSessionQueue,
) {
  const hasNext = queue?.hasNext
  const canGoPrevious = queue?.canGoPrevious
  const onNextTrack = queue?.onNextTrack
  const onPreviousTrack = queue?.onPreviousTrack
  const inQueue = queue !== undefined

  useEffect(() => {
    if (typeof navigator === 'undefined' || !('mediaSession' in navigator)) return
    const media = ref.current
    if (!media) return

    // Every action is assigned on every run - a `null` entry actively clears a
    // handler a previous mode registered, rather than leaving it stale.
    const handlers: [MediaSessionAction, MediaSessionActionHandler | null][] = [
      ['play', () => { media.play().catch(() => {}) }],
      ['pause', () => media.pause()],
      ['seekbackward', inQueue ? null : (details) => {
        const offset = details.seekOffset || 10
        media.currentTime = Math.max(0, media.currentTime - offset)
      }],
      ['seekforward', inQueue ? null : (details) => {
        const offset = details.seekOffset || 10
        media.currentTime = Math.min(media.duration || media.currentTime, media.currentTime + offset)
      }],
      ['seekto', (details) => {
        if (details.seekTime != null) media.currentTime = details.seekTime
      }],
      ['nexttrack', inQueue && hasNext && onNextTrack ? () => onNextTrack() : null],
      // On the first track, previous restarts it instead of going unregistered:
      // keeping the handler live stops iOS from reshuffling the control layout
      // mid-playlist.
      ['previoustrack', inQueue
        ? (canGoPrevious && onPreviousTrack ? () => onPreviousTrack() : () => { media.currentTime = 0 })
        : null],
    ]

    const token = Symbol('mediaSessionOwner')
    currentOwner = token

    for (const [action, handler] of handlers) {
      try {
        navigator.mediaSession.setActionHandler(action, handler)
      } catch {
        // Some browsers don't support all action handlers
      }
    }

    return () => {
      // A newer player already took over - leave its handlers in place.
      if (currentOwner !== token) return
      currentOwner = null
      for (const [action] of handlers) {
        try {
          navigator.mediaSession.setActionHandler(action, null)
        } catch {
          // Ignore cleanup errors
        }
      }
    }
  }, [ref, id, inQueue, hasNext, canGoPrevious, onNextTrack, onPreviousTrack])
}

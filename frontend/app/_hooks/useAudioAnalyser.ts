"use client"

import { useEffect, useMemo, useRef, type RefObject } from "react"

/**
 * Stable handle for reading real-time frequency data off the audio element.
 * Consumers own their output buffer; `getBars` fills it with `out.length` bars
 * (0..255). `isActive` is true only when Web Audio is wired up, the visualizer
 * is enabled, and audio is playing.
 */
export interface AudioAnalyserHandle {
  getBars: (out: Uint8Array) => void
  isActive: () => boolean
  /**
   * Create/resume the Web Audio graph. MUST be called from within a user
   * gesture (e.g. the toggle click) — creating or resuming the AudioContext
   * outside a gesture leaves it suspended, so the audio element gets routed
   * into a non-running context and plays silently.
   */
  ensureStarted: () => void
}

// Frequency band the bars span. Mapping all the way to Nyquist (~22 kHz)
// leaves the top bars permanently dead — music, and especially lossy sources
// (YouTube audio low-passes ~15-20 kHz), has negligible energy above ~16 kHz.
const MIN_FREQ = 30 // Hz — skip subsonic / DC bins
const MAX_FREQ = 16000 // Hz — top of the musically-active band (raise toward 20000 for more "air")
const FREQ_CURVE = 1.6 // >1 = give lows/mids more bars (log-ish spacing)

interface AudioGraph {
  ctx: AudioContext
  source: MediaElementAudioSourceNode
  analyser: AnalyserNode
  // Pinned to ArrayBuffer (not the default ArrayBufferLike) because
  // getByteFrequencyData won't accept a possibly-shared backing buffer.
  freq: Uint8Array<ArrayBuffer>
}

// Desktop-only gate. `createMediaElementSource` reroutes the element's native
// output into the AudioContext; on iOS that lets the browser silence lock-
// screen / background audio (it suspends the context on lock and the element
// can never be un-routed back to native output). More generally, routing audio
// through Web Audio on mobile risks the same background-playback issues, and
// the visualizer is intentionally a desktop-only feature. So on any iOS or
// touch (coarse-pointer) device we never build a graph at all — the real
// <audio> element stays a plain, untouched tag and background audio is safe.
function isDesktop(): boolean {
  if (typeof navigator === "undefined") return false
  const ua = navigator.userAgent
  const iOS =
    /iP(hone|od|ad)/.test(ua) ||
    // iPadOS 13+ reports as desktop Safari on "MacIntel"; touch points reveal it.
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  if (iOS) return false
  return !window.matchMedia?.("(pointer: coarse)")?.matches
}

// `createMediaElementSource` may be called only ONCE per media element — a
// second call (e.g. React StrictMode's double-invoked effects on the same
// <audio> node) throws InvalidStateError. Cache the graph per element so
// repeat calls reuse it. Keying by the element (not a captured audio track)
// is also what lets the visualizer survive a track switch: switching tracks
// only changes the element's `src`, so the same element — and its source
// node — keeps feeding the analyser. Keyed weakly so the graph is collectable
// once the element is gone.
const graphCache = new WeakMap<HTMLMediaElement, AudioGraph>()
// Parallel strong list, used only to close contexts whose element has left the
// DOM — bounds the number of live AudioContexts over a long listening session
// (browsers cap concurrent contexts).
const liveGraphs: AudioGraph[] = []

function getOrCreateGraph(el: HTMLMediaElement): AudioGraph | null {
  const cached = graphCache.get(el)
  if (cached) return cached

  // Never route the real element through Web Audio on iOS / touch devices —
  // it would risk silencing lock-screen / background audio there.
  if (!isDesktop()) return null

  // Reap graphs whose media element is detached from the document.
  for (let i = liveGraphs.length - 1; i >= 0; i--) {
    const g = liveGraphs[i]
    if (!g.source.mediaElement.isConnected) {
      g.ctx.close().catch(() => {})
      liveGraphs.splice(i, 1)
    }
  }

  const Ctx: typeof AudioContext | undefined =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctx) return null

  try {
    const ctx = new Ctx()
    const source = ctx.createMediaElementSource(el)
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 1024
    analyser.smoothingTimeConstant = 0.8
    // source -> analyser (tap) -> destination (so audio keeps playing).
    source.connect(analyser)
    analyser.connect(ctx.destination)
    const graph: AudioGraph = {
      ctx,
      source,
      analyser,
      freq: new Uint8Array(analyser.frequencyBinCount),
    }
    graphCache.set(el, graph)
    liveGraphs.push(graph)
    return graph
  } catch {
    return null
  }
}

/**
 * Lazily routes the audio element through a Web Audio AnalyserNode so a
 * visualizer can read frequency data.
 *
 * DESKTOP-ONLY BY DESIGN: `createMediaElementSource` reroutes the element's
 * native output into the AudioContext. On iOS that lets the browser silence
 * lock-screen / background audio when the screen locks (the context is
 * suspended and the element can't be un-routed). To protect background audio
 * on phones/tablets, `getOrCreateGraph` refuses to build a graph on any iOS or
 * touch device (see `isDesktop`), leaving the visualizer inert there while the
 * real <audio> element stays untouched. We further confine risk on desktop by
 * only wiring up Web Audio once `enabled` is true, and by resuming the context
 * on return-to-foreground / next user gesture.
 */
export function useAudioAnalyser(
  audioRef: RefObject<HTMLAudioElement | null>,
  { enabled, isPlaying }: { enabled: boolean; isPlaying: boolean },
): AudioAnalyserHandle {
  const graphRef = useRef<AudioGraph | null>(null)
  const enabledRef = useRef(enabled)
  const playingRef = useRef(isPlaying)
  // Mirrored after commit rather than during render. Both are only ever read
  // from the visualizer's rAF loop (AudioVisualizer reads analyserRef.current
  // each frame), which runs after effects have flushed.
  useEffect(() => {
    enabledRef.current = enabled
    playingRef.current = isPlaying
  })

  // Lazily wire up Web Audio the first time the visualizer is enabled.
  useEffect(() => {
    if (!enabled) return
    const el = audioRef.current
    if (!el) return
    const graph = getOrCreateGraph(el)
    graphRef.current = graph
    if (graph && graph.ctx.state === "suspended") {
      graph.ctx.resume().catch(() => {})
    }
  }, [enabled, audioRef])

  // Recover the (desktop) graph after the browser auto-suspends the
  // AudioContext when the tab is backgrounded: resume it on return-to-
  // foreground and on the next user gesture. No-op on iOS/touch, where no
  // graph is ever created.
  useEffect(() => {
    if (!enabled) return
    const resume = () => {
      const g = graphRef.current
      if (g && g.ctx.state === "suspended") g.ctx.resume().catch(() => {})
    }
    const onVisibility = () => {
      if (!document.hidden) resume()
    }
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("pointerdown", resume)
    window.addEventListener("touchend", resume)
    return () => {
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("pointerdown", resume)
      window.removeEventListener("touchend", resume)
    }
  }, [enabled])

  return useMemo<AudioAnalyserHandle>(
    () => ({
      ensureStarted() {
        const el = audioRef.current
        if (!el) return
        const g = graphRef.current ?? getOrCreateGraph(el)
        graphRef.current = g
        if (g && g.ctx.state === "suspended") g.ctx.resume().catch(() => {})
      },
      getBars(out: Uint8Array) {
        const g = graphRef.current
        if (!g || !enabledRef.current) {
          out.fill(0)
          return
        }
        g.analyser.getByteFrequencyData(g.freq)
        const bins = g.freq.length
        const count = out.length
        const nyquist = g.ctx.sampleRate / 2
        // Restrict the mapped band to [MIN_FREQ, MAX_FREQ] so bars aren't
        // wasted on the near-silent top of the spectrum.
        const minBin = Math.max(1, Math.floor((MIN_FREQ / nyquist) * bins))
        const maxBin = Math.min(bins, Math.ceil((MAX_FREQ / nyquist) * bins))
        const span = Math.max(1, maxBin - minBin)
        // Down-bucket the band into `count` bars with a log-ish curve so
        // lows/mids aren't crammed into the first few bars.
        for (let i = 0; i < count; i++) {
          const start = minBin + Math.floor(Math.pow(i / count, FREQ_CURVE) * span)
          const end = Math.max(
            start + 1,
            minBin + Math.floor(Math.pow((i + 1) / count, FREQ_CURVE) * span),
          )
          let sum = 0
          let n = 0
          for (let j = start; j < end && j < maxBin; j++) {
            sum += g.freq[j]
            n++
          }
          out[i] = n > 0 ? sum / n : 0
        }
      },
      isActive() {
        return !!graphRef.current && enabledRef.current && playingRef.current
      },
    }),
    [audioRef],
  )
}

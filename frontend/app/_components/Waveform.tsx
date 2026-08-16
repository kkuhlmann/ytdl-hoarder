"use client"

import { useRef, useEffect, useState } from "react"
import WaveSurfer from "wavesurfer.js"
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.js"
import { Button } from "@/components/ui/button"
import { useThemeColors } from "@/app/_hooks/useThemeColors"

interface WaveformProps {
  mediaUrl: string
  currentTime?: number
  onSeek?: (time: number) => void
  onReady?: (duration: number) => void

  // Pre-computed peaks (skips fetching/decoding the audio file)
  peaks?: number[]
  peaksDuration?: number

  showRegion?: boolean
  regionStart?: number
  regionEnd?: number
  onRegionChange?: (start: number, end: number) => void

  // Viewport for zoom (undefined = full view)
  viewStart?: number
  viewEnd?: number

  height?: number
}

export function Waveform({
  mediaUrl,
  currentTime,
  onSeek,
  onReady,
  peaks,
  peaksDuration,
  showRegion = false,
  regionStart = 0,
  regionEnd = 30,
  onRegionChange,
  viewStart,
  viewEnd,
  height = 128,
}: WaveformProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)
  const regionsPluginRef = useRef<RegionsPlugin | null>(null)
  const regionRef = useRef<Region | null>(null)
  const [isReady, setIsReady] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)
  const [mediaDuration, setMediaDuration] = useState(0)
  const isRegionUpdatingRef = useRef(false)
  const isDestroyedRef = useRef(false)
  const isReadyRef = useRef(false)

  // Theme-aware colors (canvas needs concrete values re-read on theme change).
  // Explicit props override the theme; empty/SSR values fall back to matrix.
  const themeColors = useThemeColors({
    wave: "--matrix-dim",
    progress: "--matrix-green",
    region: "--matrix-glow",
  })
  const effWaveColor = themeColors.wave || "#00b32d"
  const effProgressColor = themeColors.progress || "#00ff41"
  const effRegionColor = themeColors.region || "rgba(0, 255, 65, 0.3)"

  // Store callbacks in refs to avoid re-creating wavesurfer on callback changes
  const onSeekRef = useRef(onSeek)
  const onReadyRef = useRef(onReady)
  const onRegionChangeRef = useRef(onRegionChange)

  useEffect(() => {
    onSeekRef.current = onSeek
  }, [onSeek])

  useEffect(() => {
    onReadyRef.current = onReady
  }, [onReady])

  useEffect(() => {
    onRegionChangeRef.current = onRegionChange
  }, [onRegionChange])

  // Store initial region props in refs for use in initialization
  const initialRegionStartRef = useRef(regionStart)
  const initialRegionEndRef = useRef(regionEnd)
  const showRegionRef = useRef(showRegion)
  const regionColorRef = useRef(effRegionColor)

  // Update refs when props change (but don't trigger re-init)
  useEffect(() => {
    showRegionRef.current = showRegion
  }, [showRegion])

  useEffect(() => {
    regionColorRef.current = effRegionColor
  }, [effRegionColor])

  useEffect(() => {
    if (!containerRef.current) return

    isDestroyedRef.current = false
    isReadyRef.current = false
    setIsReady(false)
    setLoadError(false)
    setIsLoading(true)
    const regionsPlugin = RegionsPlugin.create()
    regionsPluginRef.current = regionsPlugin

    const wavesurfer = WaveSurfer.create({
      container: containerRef.current,
      waveColor: effWaveColor,
      progressColor: effProgressColor,
      cursorColor: effProgressColor,
      cursorWidth: 2,
      height,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      backend: "WebAudio",
      // Don't play audio - we're just visualizing
      media: document.createElement("audio"),
      plugins: [regionsPlugin],
    })

    wavesurferRef.current = wavesurfer

    const onLoadFailure = (err: unknown) => {
      if (isDestroyedRef.current || isReadyRef.current) return
      console.error("Waveform load error:", err)
      setIsLoading(false)
      setLoadError(true)
    }

    wavesurfer.on("error", onLoadFailure)

    // Load the media URL - use pre-computed peaks if available to avoid
    // decoding the entire audio file in the browser (which crashes on large files)
    if (peaks && peaksDuration) {
      wavesurfer.load(mediaUrl, [peaks], peaksDuration).catch((err) => {
        if (isDestroyedRef.current && err?.name === "AbortError") return
        onLoadFailure(err)
      })
    } else {
      wavesurfer.load(mediaUrl).catch((err) => {
        if (isDestroyedRef.current && err?.name === "AbortError") return
        onLoadFailure(err)
      })
    }

    wavesurfer.on("ready", () => {
      if (isDestroyedRef.current) return
      isReadyRef.current = true
      setIsReady(true)
      setIsLoading(false)
      setLoadError(false)
      const duration = wavesurfer.getDuration()
      setMediaDuration(duration)
      onReadyRef.current?.(duration)

      if (showRegionRef.current && regionsPluginRef.current) {
        const region = regionsPluginRef.current.addRegion({
          start: initialRegionStartRef.current,
          end: Math.min(initialRegionEndRef.current, duration),
          color: regionColorRef.current,
          drag: true,
          resize: true,
        })
        regionRef.current = region
      }
    })

    wavesurfer.on("loading", (percent) => {
      if (isDestroyedRef.current) return
      if (percent < 100) {
        setIsLoading(true)
      }
    })

    // Handle click-to-seek
    wavesurfer.on("interaction", (newTime) => {
      if (isDestroyedRef.current) return
      onSeekRef.current?.(newTime)
    })

    regionsPlugin.on("region-updated", (region) => {
      if (isDestroyedRef.current) return
      if (isRegionUpdatingRef.current) return
      onRegionChangeRef.current?.(region.start, region.end)
    })

    return () => {
      isDestroyedRef.current = true
      try {
        wavesurfer.destroy()
      } catch {
        // Ignore errors during cleanup (AbortError when unmounting during load)
      }
      wavesurferRef.current = null
      regionsPluginRef.current = null
      regionRef.current = null
    }
    // Colors are applied live via setOptions below, so they're intentionally
    // excluded here to avoid tearing down/reloading WaveSurfer on theme change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaUrl, height, peaks, peaksDuration, reloadToken])

  // Apply theme color changes live without reloading the waveform
  useEffect(() => {
    wavesurferRef.current?.setOptions({
      waveColor: effWaveColor,
      progressColor: effProgressColor,
      cursorColor: effProgressColor,
    })
  }, [effWaveColor, effProgressColor])

  // Sync playback position from external source
  useEffect(() => {
    if (!wavesurferRef.current || !isReady) return
    if (currentTime === undefined) return

    const duration = wavesurferRef.current.getDuration()
    if (duration > 0) {
      const progress = currentTime / duration
      wavesurferRef.current.seekTo(Math.min(Math.max(progress, 0), 1))
    }
  }, [currentTime, isReady])

  useEffect(() => {
    if (!isReady || !showRegion || !regionRef.current) return

    isRegionUpdatingRef.current = true
    regionRef.current.setOptions({
      start: regionStart,
      end: regionEnd,
    })
    // Use setTimeout to allow the update to complete before re-enabling change detection
    setTimeout(() => {
      isRegionUpdatingRef.current = false
    }, 0)
  }, [regionStart, regionEnd, isReady, showRegion])

  useEffect(() => {
    if (!regionRef.current) return
    regionRef.current.setOptions({ color: effRegionColor })
  }, [effRegionColor])

  useEffect(() => {
    if (!wavesurferRef.current || !isReady || !containerRef.current) return
    if (mediaDuration <= 0) return

    const vStart = viewStart ?? 0
    const vEnd = viewEnd ?? mediaDuration
    const viewportDuration = vEnd - vStart

    if (viewportDuration <= 0) return

    const containerWidth = containerRef.current.clientWidth
    const pxPerSec = containerWidth / viewportDuration

    wavesurferRef.current.zoom(pxPerSec)

    // setScroll, not getWrapper().scrollLeft — getWrapper() returns the inner
    // wrapper div, while the overflow lives on its scroll-container parent, so
    // assigning scrollLeft there is silently a no-op and the view never pans.
    wavesurferRef.current.setScroll(vStart * pxPerSec)
  }, [viewStart, viewEnd, mediaDuration, isReady])

  return (
    <div className="relative rounded-lg overflow-hidden bg-bg-surface border border-border">
      <div ref={containerRef} style={{ height }} />
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-bg-surface/80">
          <div className="flex items-center gap-2 text-text-muted font-mono text-sm">
            <div className="w-4 h-4 border-2 border-matrix border-t-transparent rounded-full animate-spin" />
            Loading waveform...
          </div>
        </div>
      )}
      {!isLoading && loadError && (
        <div className="absolute inset-0 flex items-center justify-center gap-3 bg-bg-surface/80">
          <span className="text-text-muted font-mono text-xs">Failed to load waveform</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setLoadError(false)
              setIsLoading(true)
              setReloadToken((t) => t + 1)
            }}
          >
            Retry
          </Button>
        </div>
      )}
    </div>
  )
}

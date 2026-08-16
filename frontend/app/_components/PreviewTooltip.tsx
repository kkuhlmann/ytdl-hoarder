"use client"

import { useMemo } from "react"
import { useSprites } from "@/app/_hooks/useSprites"
import { formatTime } from "@/app/utils"

const TOOLTIP_WIDTH = 160
const TOOLTIP_PADDING = 4

export function PreviewTooltip({
  mediaId,
  duration,
  containerWidth,
  relativeX,
  visible,
}: {
  mediaId: number
  duration: number
  /**
   * Geometry of the hovered progress bar, measured by the parent's mouse
   * handler. Passed in rather than read off a ref here: the rect is only
   * knowable from a real pointer event, and reading it while rendering would
   * miss the first render (ref still null) and never see a resize.
   */
  containerWidth: number
  /** Cursor offset from the progress bar's left edge, same measurement. */
  relativeX: number
  visible: boolean
}) {
  const { metadata, spriteUrl, available } = useSprites({
    mediaDetailsId: mediaId,
    enabled: true,
  })

  const frame = useMemo(() => {
    if (!metadata || !containerWidth || !duration) return null

    const fraction = Math.max(0, Math.min(1, relativeX / containerWidth))
    const time = fraction * duration

    const frameIndex = Math.min(
      Math.floor(time / metadata.interval),
      metadata.total_frames - 1
    )
    const col = frameIndex % metadata.columns
    const row = Math.floor(frameIndex / metadata.columns)

    // Position tooltip centered on cursor, clamped to container edges
    const tooltipLeft = Math.max(
      TOOLTIP_PADDING,
      Math.min(relativeX - TOOLTIP_WIDTH / 2, containerWidth - TOOLTIP_WIDTH - TOOLTIP_PADDING)
    )

    return {
      backgroundPositionX: -(col * metadata.width),
      backgroundPositionY: -(row * metadata.height),
      time,
      tooltipLeft,
    }
  }, [metadata, containerWidth, relativeX, duration])

  if (!visible || !available || !metadata || !frame) return null

  return (
    <div
      className="absolute bottom-full mb-2 pointer-events-none z-50"
      style={{ left: frame.tooltipLeft }}
    >
      <div className="rounded overflow-hidden shadow-lg border border-white/20">
        <div
          style={{
            width: metadata.width,
            height: metadata.height,
            backgroundImage: `url(${spriteUrl})`,
            backgroundPosition: `${frame.backgroundPositionX}px ${frame.backgroundPositionY}px`,
            backgroundRepeat: "no-repeat",
          }}
        />
        <div className="bg-black/90 text-white text-xs text-center py-0.5 font-mono">
          {formatTime(frame.time)}
        </div>
      </div>
    </div>
  )
}

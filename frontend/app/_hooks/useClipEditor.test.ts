// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { MIN_CLIP_SECONDS, useClipEditor } from "./useClipEditor"

afterEach(cleanup)

function setup(duration: number, initialEnd = Math.min(duration, 30)) {
  return renderHook(
    ({ duration }: { duration: number }) =>
      useClipEditor({
        mediaDetailsId: 1,
        duration,
        currentTime: 0,
        mediaRef: { current: null },
        onSeek: () => {},
        onSaved: () => {},
        initialEnd,
      }),
    { initialProps: { duration } }
  )
}

describe("useClipEditor", () => {
  it("keeps end ahead of start when the duration is unknown", () => {
    // The transcript-search case: a row with no duration, entered mid-video, so
    // the end clamps against 0 while the start comes from the playhead.
    const { result } = setup(0)

    act(() => result.current.setStartTime(295))

    expect(result.current.endTime).toBeGreaterThan(result.current.startTime)
    expect(result.current.clipDuration).toBeGreaterThanOrEqual(MIN_CLIP_SECONDS)
  })

  it("never reports a negative clip length", () => {
    const { result } = setup(0)

    act(() => result.current.setEndTime(0))
    act(() => result.current.setStartTime(600))

    expect(result.current.clipDuration).toBeGreaterThanOrEqual(0)
  })

  it("seeds a usable end once the real duration lands", () => {
    const { result, rerender } = setup(0)

    expect(result.current.endTime).toBe(MIN_CLIP_SECONDS)

    rerender({ duration: 600 })

    expect(result.current.startTime).toBe(0)
    expect(result.current.endTime).toBe(30)
  })

  it("clamps the end to the duration", () => {
    const { result } = setup(600)

    act(() => result.current.setEndTime(999))

    expect(result.current.endTime).toBe(600)
  })

  it("treats a non-finite duration as unknown rather than clamping to NaN", () => {
    const { result } = setup(Number.POSITIVE_INFINITY, 30)

    expect(Number.isFinite(result.current.endTime)).toBe(true)
    expect(result.current.endTime).toBeGreaterThan(result.current.startTime)
  })
})

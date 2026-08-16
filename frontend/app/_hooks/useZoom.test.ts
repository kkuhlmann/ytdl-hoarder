// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useZoom } from "./useZoom"

afterEach(cleanup)

const selection = { selectionStart: 100, selectionEnd: 130 }

describe("useZoom", () => {
  it("keeps the viewport inert while the duration is unknown", () => {
    const { result } = renderHook(() => useZoom({ duration: 0, ...selection }))

    act(() => result.current.zoomToSelection())

    expect(result.current.viewStart).toBe(0)
    expect(result.current.viewEnd).toBe(0)
  })

  it("does not stay pinned to t=0 when the duration arrives after mount", () => {
    const { result, rerender } = renderHook(
      ({ duration }) => useZoom({ duration, ...selection }),
      { initialProps: { duration: 0 } }
    )

    rerender({ duration: 600 })
    act(() => result.current.zoomIn())

    // Centred on the media, not anchored at the start.
    expect(result.current.viewStart).toBeGreaterThan(0)
    expect(result.current.viewEnd).toBeLessThanOrEqual(600)
    expect(result.current.viewEnd - result.current.viewStart).toBeCloseTo(400, 5)
  })

  it("zooms to the selection once a duration is known", () => {
    const { result } = renderHook(() => useZoom({ duration: 600, ...selection }))

    act(() => result.current.zoomToSelection())

    expect(result.current.isZoomed).toBe(true)
    expect(result.current.viewStart).toBeLessThan(115)
    expect(result.current.viewEnd).toBeGreaterThan(115)
    expect(result.current.viewEnd - result.current.viewStart).toBeLessThan(600)
  })

  it("ignores a selection with no width instead of jumping to max zoom", () => {
    const { result } = renderHook(() =>
      useZoom({ duration: 600, selectionStart: 100, selectionEnd: 100 })
    )

    act(() => result.current.zoomToSelection())

    expect(result.current.zoomLevel).toBe(1)
  })

  it("treats a non-finite duration as unknown", () => {
    const { result } = renderHook(() =>
      useZoom({ duration: Number.POSITIVE_INFINITY, ...selection })
    )

    expect(result.current.viewStart).toBe(0)
    expect(result.current.viewEnd).toBe(0)

    act(() => result.current.zoomToSelection())
    expect(result.current.zoomLevel).toBe(1)
  })

  it("recentres on reset rather than freezing the old centre", () => {
    const { result } = renderHook(() => useZoom({ duration: 600, ...selection }))

    act(() => result.current.zoomToSelection())
    act(() => result.current.resetZoom())

    expect(result.current.zoomLevel).toBe(1)
    expect(result.current.viewStart).toBe(0)
    expect(result.current.viewEnd).toBe(600)
  })
})

// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useCountdownTick } from "./useCountdownTick"

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("useCountdownTick", () => {
  it("registers no interval when active is false", () => {
    renderHook(() => useCountdownTick(false))
    expect(vi.getTimerCount()).toBe(0)
  })

  it("registers an interval when active is true", () => {
    renderHook(() => useCountdownTick(true))
    expect(vi.getTimerCount()).toBe(1)
  })

  it("increments the tick once per intervalMs advance", () => {
    const { result } = renderHook(() => useCountdownTick(true, 1000))
    expect(result.current).toBe(0)

    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(result.current).toBe(1)

    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(result.current).toBe(3)
  })

  it("clears the interval when active flips back to false", () => {
    const { rerender } = renderHook(({ active }) => useCountdownTick(active), {
      initialProps: { active: true },
    })
    expect(vi.getTimerCount()).toBe(1)

    rerender({ active: false })
    expect(vi.getTimerCount()).toBe(0)
  })

  it("clears the interval on unmount", () => {
    const { unmount } = renderHook(() => useCountdownTick(true))
    expect(vi.getTimerCount()).toBe(1)

    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

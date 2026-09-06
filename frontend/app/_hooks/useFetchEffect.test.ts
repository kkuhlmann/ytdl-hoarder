// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useFetchEffect } from "./useFetchEffect"

/**
 * Each call to `run` hands back a promise the test settles by hand, so
 * "a fetch is in flight" is a state the assertions can sit inside.
 */
function makeRun() {
  const settles: Array<() => void> = []
  const run = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        settles.push(resolve)
      })
  )
  const settle = async (index: number) => {
    await act(async () => {
      settles[index]()
    })
  }
  return { run, settle }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe("useFetchEffect", () => {
  it("raises isLoading on mount and lowers it once the fetch settles", async () => {
    const { run, settle } = makeRun()
    const { result } = renderHook(() => useFetchEffect(run, []))

    expect(run).toHaveBeenCalledTimes(1)
    expect(result.current.isLoading).toBe(true)

    await settle(0)
    expect(result.current.isLoading).toBe(false)
  })

  it("re-runs and raises isLoading when deps change", async () => {
    const { run, settle } = makeRun()
    const { result, rerender } = renderHook(
      ({ dep }) => useFetchEffect(run, [dep]),
      { initialProps: { dep: 1 } }
    )
    await settle(0)

    rerender({ dep: 2 })

    expect(run).toHaveBeenCalledTimes(2)
    expect(result.current.isLoading).toBe(true)
  })

  it("re-runs and raises isLoading on an explicit refetch", async () => {
    const { run, settle } = makeRun()
    const { result } = renderHook(() => useFetchEffect(run, []))
    await settle(0)

    act(() => result.current.refetch())

    expect(run).toHaveBeenCalledTimes(2)
    expect(result.current.isLoading).toBe(true)
  })

  it("re-runs a poll tick without ever raising isLoading", async () => {
    const { run, settle } = makeRun()
    const { result } = renderHook(() =>
      useFetchEffect(run, [], { pollMs: 10_000 })
    )
    await settle(0)
    expect(result.current.isLoading).toBe(false)

    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })

    expect(run).toHaveBeenCalledTimes(2)
    expect(result.current.isLoading).toBe(false)

    await settle(1)
    expect(result.current.isLoading).toBe(false)
  })

  it("still raises isLoading on the run after a poll tick", async () => {
    const { run, settle } = makeRun()
    const { result, rerender } = renderHook(
      ({ dep }) => useFetchEffect(run, [dep], { pollMs: 10_000 }),
      { initialProps: { dep: 1 } }
    )
    await settle(0)

    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    await settle(1)
    expect(result.current.isLoading).toBe(false)

    rerender({ dep: 2 })

    expect(run).toHaveBeenCalledTimes(3)
    expect(result.current.isLoading).toBe(true)
  })
})

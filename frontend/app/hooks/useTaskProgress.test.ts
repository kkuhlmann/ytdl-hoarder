// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useTaskProgress } from "./useTaskProgress"
import type { ProgressEvent, StatusChangeEvent } from "./useTaskProgress"

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  constructor(
    public url: string,
    public opts?: { withCredentials?: boolean }
  ) {
    FakeEventSource.instances.push(this)
  }
  close() {
    this.closed = true
  }
}

function latestInstance(): FakeEventSource {
  return FakeEventSource.instances[FakeEventSource.instances.length - 1]
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("useTaskProgress", () => {
  it("opens exactly one connection on mount, with credentials, all_tasks=true by default", () => {
    renderHook(() => useTaskProgress())

    expect(FakeEventSource.instances).toHaveLength(1)
    const es = latestInstance()
    expect(es.url).toContain("all_tasks=true")
    expect(es.opts).toEqual({ withCredentials: true })
  })

  it("passes all_tasks=false when the allTasks option is false", () => {
    renderHook(() => useTaskProgress({ allTasks: false }))

    expect(latestInstance().url).toContain("all_tasks=false")
  })

  it("sets connected to true once the connection opens", () => {
    const { result } = renderHook(() => useTaskProgress())
    expect(result.current.connected).toBe(false)

    act(() => {
      latestInstance().onopen?.()
    })

    expect(result.current.connected).toBe(true)
  })

  it("routes a progress message to onProgressUpdate, not onStatusChange", () => {
    const onProgressUpdate = vi.fn()
    const onStatusChange = vi.fn()
    renderHook(() => useTaskProgress({ onProgressUpdate, onStatusChange }))
    const event: ProgressEvent = { event_type: "progress", task_id: "t1", percent_complete: 42 }

    act(() => {
      latestInstance().onmessage?.({ data: JSON.stringify(event) })
    })

    expect(onProgressUpdate).toHaveBeenCalledWith(event)
    expect(onStatusChange).not.toHaveBeenCalled()
  })

  it("routes a status_change message to onStatusChange, not onProgressUpdate", () => {
    const onProgressUpdate = vi.fn()
    const onStatusChange = vi.fn()
    renderHook(() => useTaskProgress({ onProgressUpdate, onStatusChange }))
    const event: StatusChangeEvent = { event_type: "status_change", task_id: "t1", status: "IN_PROGRESS" }

    act(() => {
      latestInstance().onmessage?.({ data: JSON.stringify(event) })
    })

    expect(onStatusChange).toHaveBeenCalledWith(event)
    expect(onProgressUpdate).not.toHaveBeenCalled()
  })

  it("dispatches task-completed on window only when status_change carries COMPLETE", () => {
    renderHook(() => useTaskProgress())
    const spy = vi.fn()
    window.addEventListener("task-completed", spy)

    try {
      act(() => {
        latestInstance().onmessage?.({
          data: JSON.stringify({ event_type: "status_change", task_id: "t1", status: "IN_PROGRESS" }),
        })
      })
      expect(spy).not.toHaveBeenCalled()

      act(() => {
        latestInstance().onmessage?.({
          data: JSON.stringify({ event_type: "status_change", task_id: "t1", status: "COMPLETE" }),
        })
      })
      expect(spy).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener("task-completed", spy)
    }
  })

  it("swallows malformed JSON: no throw, and neither callback fires", () => {
    const onProgressUpdate = vi.fn()
    const onStatusChange = vi.fn()
    renderHook(() => useTaskProgress({ onProgressUpdate, onStatusChange }))
    const es = latestInstance()

    expect(() => {
      act(() => {
        es.onmessage?.({ data: "{not valid json" })
      })
    }).not.toThrow()

    expect(onProgressUpdate).not.toHaveBeenCalled()
    expect(onStatusChange).not.toHaveBeenCalled()
  })

  it("onerror disconnects and closes the errored instance", () => {
    const { result } = renderHook(() => useTaskProgress())
    const es = latestInstance()
    act(() => {
      es.onopen?.()
    })
    expect(result.current.connected).toBe(true)

    act(() => {
      es.onerror?.()
    })

    expect(result.current.connected).toBe(false)
    expect(es.closed).toBe(true)
  })

  it("schedules the first reconnect at exactly 1000ms, not before", async () => {
    renderHook(() => useTaskProgress())
    act(() => {
      latestInstance().onerror?.()
    })
    expect(FakeEventSource.instances).toHaveLength(1)

    await act(async () => {
      vi.advanceTimersByTime(999)
    })
    expect(FakeEventSource.instances).toHaveLength(1)

    await act(async () => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it("doubles the reconnect delay per attempt (1000, 2000, 4000, 8000, 16000ms), boundary-exact", async () => {
    renderHook(() => useTaskProgress())
    const delays = [1000, 2000, 4000, 8000, 16000]

    for (const [index, delay] of delays.entries()) {
      const expectedBefore = index + 1
      act(() => {
        latestInstance().onerror?.()
      })

      await act(async () => {
        vi.advanceTimersByTime(delay - 1)
      })
      expect(FakeEventSource.instances).toHaveLength(expectedBefore)

      await act(async () => {
        vi.advanceTimersByTime(1)
      })
      expect(FakeEventSource.instances).toHaveLength(expectedBefore + 1)
    }
  })

  it("resets the attempt counter on open, so the next backoff starts over at 1000ms", async () => {
    renderHook(() => useTaskProgress())

    act(() => {
      latestInstance().onerror?.()
    })
    await act(async () => {
      vi.advanceTimersByTime(1000)
    })
    expect(FakeEventSource.instances).toHaveLength(2)

    act(() => {
      latestInstance().onopen?.()
    })
    act(() => {
      latestInstance().onerror?.()
    })

    // Without the reset, the ref would still read 1 here and the pending
    // delay would be 2000ms (1000 * 2**1) — this boundary would then fail,
    // since no new instance appears until 2000ms have elapsed.
    await act(async () => {
      vi.advanceTimersByTime(999)
    })
    expect(FakeEventSource.instances).toHaveLength(2)

    await act(async () => {
      vi.advanceTimersByTime(1)
    })
    expect(FakeEventSource.instances).toHaveLength(3)
  })

  it("stops reconnecting after 5 attempts: a 6th error spawns no new instance ever", async () => {
    renderHook(() => useTaskProgress())

    for (let attempt = 0; attempt < 5; attempt++) {
      act(() => {
        latestInstance().onerror?.()
      })
      await act(async () => {
        vi.advanceTimersByTime(1000 * 2 ** attempt)
      })
    }
    expect(FakeEventSource.instances).toHaveLength(6)

    act(() => {
      latestInstance().onerror?.()
    })
    await act(async () => {
      vi.advanceTimersByTime(1_000_000)
    })
    expect(FakeEventSource.instances).toHaveLength(6)
  })

  it("closes the current instance on unmount when no reconnect is pending", () => {
    const { unmount } = renderHook(() => useTaskProgress())
    const es = latestInstance()
    expect(es.closed).toBe(false)

    unmount()

    expect(es.closed).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
  })

  it("clears a pending reconnect timer on unmount", () => {
    const { unmount } = renderHook(() => useTaskProgress())
    act(() => {
      latestInstance().onerror?.()
    })
    expect(vi.getTimerCount()).toBe(1)

    unmount()

    expect(vi.getTimerCount()).toBe(0)
  })
})

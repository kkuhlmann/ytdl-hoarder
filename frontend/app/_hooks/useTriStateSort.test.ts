// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, renderHook } from "@testing-library/react"
import { useTriStateSort } from "./useTriStateSort"

afterEach(cleanup)

describe("useTriStateSort", () => {
  it("cycles same-column clicks desc -> asc -> off -> desc", () => {
    const { result } = renderHook(() => useTriStateSort())

    act(() => result.current.handleSort("name"))
    expect(result.current.sortBy).toBe("name")
    expect(result.current.sortDirection).toBe("desc")

    act(() => result.current.handleSort("name"))
    expect(result.current.sortBy).toBe("name")
    expect(result.current.sortDirection).toBe("asc")

    act(() => result.current.handleSort("name"))
    expect(result.current.sortBy).toBeNull()
    expect(result.current.sortDirection).toBeNull()

    act(() => result.current.handleSort("name"))
    expect(result.current.sortBy).toBe("name")
    expect(result.current.sortDirection).toBe("desc")
  })

  it("resets straight to desc on a different column", () => {
    const { result } = renderHook(() => useTriStateSort())

    act(() => result.current.handleSort("name"))
    act(() => result.current.handleSort("name"))
    expect(result.current.sortDirection).toBe("asc")

    act(() => result.current.handleSort("date"))
    expect(result.current.sortBy).toBe("date")
    expect(result.current.sortDirection).toBe("desc")
  })
})

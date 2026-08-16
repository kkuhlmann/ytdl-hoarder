import { describe, expect, it } from "vitest"
import { errorMessage } from "./api"

function axiosError(detail: unknown): unknown {
  return Object.assign(new Error("Request failed"), {
    isAxiosError: true,
    response: { data: { detail } },
  })
}

describe("errorMessage", () => {
  it("returns the fallback for a non-axios error", () => {
    expect(errorMessage(new Error("boom"))).toBe("An error occurred")
  })

  it("honors a custom fallback argument", () => {
    expect(errorMessage(new Error("boom"), "Custom fallback")).toBe("Custom fallback")
  })

  it("returns a string detail verbatim", () => {
    expect(errorMessage(axiosError("Something failed"))).toBe("Something failed")
  })

  it("falls back for an empty-string detail", () => {
    expect(errorMessage(axiosError(""))).toBe("An error occurred")
  })

  it("reads message off an object detail", () => {
    expect(errorMessage(axiosError({ message: "Structured failure" }))).toBe("Structured failure")
  })

  it("falls back for a FastAPI-422-style array detail", () => {
    const detail = [{ loc: ["body", "url"], msg: "field required", type: "value_error.missing" }]
    expect(errorMessage(axiosError(detail))).toBe("An error occurred")
  })
})

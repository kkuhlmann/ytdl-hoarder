// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { apiUrl, errorMessage } from "./api"

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

describe("apiUrl", () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it("derives the dev API origin from the browser's own address", () => {
    // Stubbed rather than left unset: a developer's shell or container may carry
    // a real NEXT_PUBLIC_BACKEND_API, and vitest reads the actual process.env.
    vi.stubEnv("NEXT_PUBLIC_BACKEND_API", "")

    // jsdom serves the page from http://localhost:3000, standing in for whatever
    // address a developer actually browsed to.
    expect(apiUrl("/health")).toBe("http://localhost:8000/health")
  })

  it("uses NEXT_PUBLIC_BACKEND_API verbatim when one is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_API", "/api")

    expect(apiUrl("/health")).toBe("/api/health")
  })

  it("honors an absolute override, for a reverse proxy or TLS in front", () => {
    vi.stubEnv("NEXT_PUBLIC_BACKEND_API", "https://media.example.com/api")

    expect(apiUrl("/health")).toBe("https://media.example.com/api/health")
  })
})

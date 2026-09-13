import { describe, it, expect } from "vitest"
import { classifyMediaPath, classifyRequest } from "./offlineRoutes"

describe("classifyMediaPath", () => {
  it("matches the production /api-prefixed stream path", () => {
    expect(classifyMediaPath("/api/media/42")).toEqual({ kind: "stream", mediaId: 42 })
  })

  it("matches the dev path, which carries no prefix", () => {
    expect(classifyMediaPath("/media/42")).toEqual({ kind: "stream", mediaId: 42 })
  })

  it("maps every cached asset suffix", () => {
    expect(classifyMediaPath("/api/media/7/thumbnail")).toEqual({
      kind: "asset",
      mediaId: 7,
      asset: "thumbnail",
    })
    expect(classifyMediaPath("/api/media/7/sprites")).toEqual({
      kind: "asset",
      mediaId: 7,
      asset: "sprites",
    })
    expect(classifyMediaPath("/api/media/7/sprites/metadata")).toEqual({
      kind: "asset",
      mediaId: 7,
      asset: "spriteMetadata",
    })
    expect(classifyMediaPath("/api/media/7/peaks")).toEqual({
      kind: "asset",
      mediaId: 7,
      asset: "peaks",
    })
  })

  it("never claims a clip, whose id segment is not numeric", () => {
    expect(classifyMediaPath("/api/media/clip/9")).toBeNull()
    expect(classifyMediaPath("/api/media/clip/9/download")).toBeNull()
  })

  it("ignores unknown suffixes so they reach the network", () => {
    expect(classifyMediaPath("/api/media/7/sprites/generate")).toBeNull()
    expect(classifyMediaPath("/api/media/7/transcripts")).toBeNull()
  })

  it("ignores unrelated API paths", () => {
    expect(classifyMediaPath("/api/media-details/7")).toBeNull()
    expect(classifyMediaPath("/api/sse/progress")).toBeNull()
    expect(classifyMediaPath("/")).toBeNull()
  })

  it("rejects id segments the backend's int parser would also reject", () => {
    expect(classifyMediaPath("/api/media/1.0")).toBeNull()
    expect(classifyMediaPath("/api/media/-1")).toBeNull()
    expect(classifyMediaPath("/api/media/abc")).toBeNull()
  })

  it("resolves a zero-padded id the way FastAPI would", () => {
    expect(classifyMediaPath("/api/media/01")).toEqual({ kind: "stream", mediaId: 1 })
  })
})

describe("classifyRequest", () => {
  const request = (overrides: Partial<Parameters<typeof classifyRequest>[0]> = {}) =>
    classifyRequest({
      pathname: "/",
      method: "GET",
      sameOrigin: true,
      isNavigation: false,
      ...overrides,
    })

  it("serves the cached shell for a navigation", () => {
    expect(request({ isNavigation: true })).toEqual({ kind: "shell" })
  })

  it("serves content-hashed build assets cache-first", () => {
    expect(request({ pathname: "/_next/static/chunks/abc.js" })).toEqual({ kind: "static" })
  })

  it("claims media paths", () => {
    expect(request({ pathname: "/api/media/5" })).toEqual({
      kind: "media",
      media: { kind: "stream", mediaId: 5 },
    })
  })

  it("never intercepts the SSE stream", () => {
    // Buffering this would leave useTaskProgress waiting forever.
    expect(request({ pathname: "/api/sse/progress" })).toEqual({ kind: "passthrough" })
    expect(request({ pathname: "/sse/progress" })).toEqual({ kind: "passthrough" })
  })

  it("passes through live API data", () => {
    expect(request({ pathname: "/api/media-details" })).toEqual({ kind: "passthrough" })
    expect(request({ pathname: "/api" })).toEqual({ kind: "passthrough" })
  })

  it("never falls back to the shell for an API navigation", () => {
    // The decisive rule: a shell fallback here would answer an unknown endpoint
    // with 200 and a page of HTML.
    expect(request({ pathname: "/api/nope", isNavigation: true })).toEqual({
      kind: "passthrough",
    })
  })

  it("ignores non-GET requests", () => {
    expect(request({ pathname: "/api/media/5", method: "POST" })).toEqual({
      kind: "passthrough",
    })
    expect(request({ isNavigation: true, method: "POST" })).toEqual({ kind: "passthrough" })
  })

  it("ignores cross-origin requests", () => {
    expect(request({ pathname: "/api/media/5", sameOrigin: false })).toEqual({
      kind: "passthrough",
    })
  })

  it("passes through anything else it does not recognise", () => {
    expect(request({ pathname: "/favicon.ico" })).toEqual({ kind: "passthrough" })
    expect(request({ pathname: "/manifest.webmanifest" })).toEqual({ kind: "passthrough" })
  })
})

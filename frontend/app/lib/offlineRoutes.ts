/**
 * Classification of media URLs for the service worker.
 *
 * Kept apart from mediaApi.ts because that builds paths and this takes them apart:
 * the worker sees only a pathname and has to decide, without app state, whether it
 * is something local storage could answer.
 */

import type { OfflineAssetKind } from "./offlineDb"

export type MediaRoute =
  | { kind: "stream"; mediaId: number }
  | { kind: "asset"; mediaId: number; asset: OfflineAssetKind }

const ASSET_SUFFIXES: Record<string, OfflineAssetKind> = {
  thumbnail: "thumbnail",
  sprites: "sprites",
  "sprites/metadata": "spriteMetadata",
  peaks: "peaks",
}

/**
 * Recognise a streamable media path, or null for anything else.
 *
 * The `/api` prefix is optional so the same matcher describes dev (no prefix) and
 * production (Dockerfile.prod bakes NEXT_PUBLIC_BACKEND_API=/api). Clips are
 * deliberately unmatched: `/media/clip/{id}` fails the numeric id test, and a clip
 * is a derived artefact that is never downloaded for offline use.
 */
export function classifyMediaPath(pathname: string): MediaRoute | null {
  const match = /^(?:\/api)?\/media\/([^/]+)(?:\/(.*))?$/.exec(pathname)
  if (!match) return null

  const [, rawId, suffix] = match
  // Digits only, matching what FastAPI's `id: int` will accept -- so "01" resolves
  // to the same record here as at the origin, while "clip" and "1.0" do not.
  if (!/^\d+$/.test(rawId)) return null
  const mediaId = Number(rawId)
  if (!Number.isSafeInteger(mediaId)) return null

  if (suffix === undefined || suffix === "") return { kind: "stream", mediaId }

  const asset = ASSET_SUFFIXES[suffix.replace(/\/$/, "")]
  return asset ? { kind: "asset", mediaId, asset } : null
}

/** What the service worker should do with one request. */
export type WorkerRoute =
  | { kind: "passthrough" }
  | { kind: "media"; media: MediaRoute }
  | { kind: "shell" }
  | { kind: "static" }

export type WorkerRequest = {
  pathname: string
  method: string
  sameOrigin: boolean
  isNavigation: boolean
}

const PASSTHROUGH: WorkerRoute = { kind: "passthrough" }

/**
 * The worker's whole routing decision, as a pure function.
 *
 * Split out from the fetch handler because the rules that matter most here are
 * the ones about what NOT to claim, and those are invisible in an integration
 * test that only checks the happy path.
 */
export function classifyRequest({
  pathname,
  method,
  sameOrigin,
  isNavigation,
}: WorkerRequest): WorkerRoute {
  if (method !== "GET" || !sameOrigin) return PASSTHROUGH

  // EventSource: intercepting it buffers the stream and useTaskProgress never
  // sees an event.
  if (pathname.endsWith("/sse/progress")) return PASSTHROUGH

  const media = classifyMediaPath(pathname)
  if (media) return { kind: "media", media }

  // Everything else under the API is live data — and crucially never gets the
  // navigation fallback below. The backend's SPA catch-all used to answer an
  // unknown path with index.html, so a fallback here would turn a typo'd endpoint
  // into a 200 page of HTML.
  if (pathname === "/api" || pathname.startsWith("/api/")) return PASSTHROUGH

  if (isNavigation) return { kind: "shell" }
  if (pathname.startsWith("/_next/static/")) return { kind: "static" }

  return PASSTHROUGH
}

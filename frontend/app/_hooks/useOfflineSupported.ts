"use client"

import { useSyncExternalStore } from "react"

const noopSubscribe = () => () => {}

/**
 * Whether offline support can work here at all.
 *
 * Three conditions, and every one of them is a case where the controls would
 * otherwise be offered and then fail at the only moment that matters — downloads
 * would fill IndexedDB and simply never play back:
 *
 * - Service workers exist in this browser at all.
 * - The origin is a secure context. Browsers refuse to register a worker over
 *   plain http://, so a LAN or bare Tailscale address cannot support any of this.
 * - This is a production build. ServiceWorkerRegistrar deliberately skips `next
 *   dev` (a worker in front of the dev server breaks HMR), and dev is served on a
 *   different origin from the API besides. Without this clause the controls appear
 *   on http://localhost:3000, where nothing behind them works.
 *
 * Its own module because both the offline hooks and OfflineProvider need it, and
 * the provider must not depend on the downloader to answer it.
 */
export function useOfflineSupported(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () =>
      process.env.NODE_ENV === "production" &&
      "serviceWorker" in navigator &&
      window.isSecureContext,
    () => false
  )
}

"use client"

import { useEffect } from "react"
import toast from "react-hot-toast"

/**
 * Registers the offline service worker.
 *
 * Production only, and only in a secure context: service workers are refused over
 * plain http:// (a LAN IP or a bare Tailscale name without `tailscale serve`), and
 * a worker in front of `next dev` caches the dev server's output and breaks HMR.
 * Both guards fail silently by design -- offline support is an enhancement, and an
 * install reached over http:// should still work in every other respect.
 */
export function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return

    let cancelled = false

    // A waiting worker takes over only when the user accepts, so a new deploy can
    // never swap the shell out from under someone mid-playback.
    const promptUpdate = (waiting: ServiceWorker) => {
      toast(
        (t) => (
          <span className="flex items-center gap-3">
            A new version is ready.
            <button
              type="button"
              className="underline"
              onClick={() => {
                toast.dismiss(t.id)
                waiting.postMessage("skip-waiting")
              }}
            >
              Reload
            </button>
          </span>
        ),
        { duration: Infinity, id: "sw-update" }
      )
    }

    navigator.serviceWorker
      .register("/sw.js")
      .then((registration) => {
        if (cancelled) return
        if (registration.waiting) promptUpdate(registration.waiting)

        registration.addEventListener("updatefound", () => {
          const installing = registration.installing
          if (!installing) return
          installing.addEventListener("statechange", () => {
            // No existing controller means this is the first install, which needs
            // no prompt -- there is nothing to replace.
            if (installing.state === "installed" && navigator.serviceWorker.controller) {
              promptUpdate(installing)
            }
          })
        })
      })
      .catch(() => {
        // Registration is best-effort; the app is fully usable without it.
      })

    let reloading = false
    const onControllerChange = () => {
      if (reloading) return
      reloading = true
      window.location.reload()
    }
    navigator.serviceWorker.addEventListener("controllerchange", onControllerChange)

    return () => {
      cancelled = true
      navigator.serviceWorker.removeEventListener("controllerchange", onControllerChange)
    }
  }, [])

  return null
}

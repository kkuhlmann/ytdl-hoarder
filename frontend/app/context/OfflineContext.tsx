"use client"

import { createContext, useCallback, useContext, useEffect, type ReactNode } from "react"

import { useStoredValue, writeStored } from "@/app/_hooks/useStoredValue"
import { useOfflineSupported } from "@/app/_hooks/useOfflineSupported"
import { OFFLINE_MODE_STORAGE_KEY, readOfflineMode } from "@/app/lib/offlineMode"
import { hydrateDownloads } from "@/app/lib/offlineDownloader"
import { flushPlaybackOutbox } from "@/app/lib/playbackSync"
import { syncMarkedCollections } from "@/app/lib/offlineSync"

type OfflineContextType = {
  /** True when the user has switched the app to its downloaded library. */
  offlineMode: boolean
  setOfflineMode: (enabled: boolean) => void
}

const OfflineContext = createContext<OfflineContextType | null>(null)

/**
 * Offline mode is an explicit switch, never inferred from `navigator.onLine`.
 *
 * A phone reports itself online while attached to a captive portal or a bar of
 * signal that resolves nothing, so auto-detection would flip the library out from
 * under someone mid-scroll. Being deliberate also makes the mode testable from a
 * desk with a working connection.
 */
export function OfflineProvider({ children }: { children: ReactNode }) {
  const supported = useOfflineSupported()
  const stored = useStoredValue(readOfflineMode, false)
  // An origin that cannot register a service worker is never offline, whatever is
  // stored. Otherwise an install that loses its HTTPS front strands the app in
  // offline mode with an empty library and the toggle hidden — no way back.
  const offlineMode = stored && supported

  const setOfflineMode = useCallback((enabled: boolean) => {
    writeStored(OFFLINE_MODE_STORAGE_KEY, enabled ? "on" : "off")
  }, [])

  // What is already downloaded has to be known before any row can render its
  // state, and leaving offline mode is the moment parked playback positions can
  // finally be sent and marked collections can be brought up to date.
  useEffect(() => {
    void hydrateDownloads()
    if (offlineMode) return
    void flushPlaybackOutbox()
    void syncMarkedCollections()
  }, [offlineMode])

  return (
    <OfflineContext.Provider value={{ offlineMode, setOfflineMode }}>
      {children}
    </OfflineContext.Provider>
  )
}

export function useOffline() {
  const context = useContext(OfflineContext)
  if (!context) {
    throw new Error("useOffline must be used within an OfflineProvider")
  }
  return context
}

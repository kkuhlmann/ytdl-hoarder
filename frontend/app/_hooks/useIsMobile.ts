"use client"

import { useEffect, useState } from "react"

// Matches Tailwind's `sm` breakpoint (640px). Returns false during SSR/first
// paint, then updates after mount. Safe because StatsCard is client-rendered
// and shows a loading state until data arrives, so users never see a flash of
// the desktop layout with real content.
export function useIsMobile(query = "(max-width: 640px)"): boolean {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia(query)
    const update = () => setIsMobile(mql.matches)
    update()
    mql.addEventListener("change", update)
    return () => mql.removeEventListener("change", update)
  }, [query])

  return isMobile
}

"use client"

import { useEffect, useState } from "react"

/**
 * Re-renders the caller on an interval so rendered countdowns advance on their own.
 *
 * The value is only a change signal — read the actual deadline from your own data.
 * Pass `active: false` (no countdown on screen) and no timer is registered at all,
 * which is what keeps a table of finished tasks from re-rendering once a second.
 */
export function useCountdownTick(active: boolean, intervalMs = 1000): number {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!active) return
    const intervalId = setInterval(() => setTick((n) => n + 1), intervalMs)
    return () => clearInterval(intervalId)
  }, [active, intervalMs])

  return tick
}

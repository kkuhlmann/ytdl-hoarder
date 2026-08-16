"use client"

import { useEffect, useState } from "react"

/**
 * True once `active` has been continuously true for `delayMs`.
 *
 * Used to hold a loading spinner back so a fast refetch doesn't flash one.
 *
 * The effect body only ever *schedules* the rising edge; the fall back to false
 * happens in the cleanup, which is what runs when `active` goes false. That
 * keeps the whole thing out of `react-hooks/set-state-in-effect`, which only
 * looks at synchronous setState in the effect body.
 */
export function useDelayedFlag(active: boolean, delayMs = 500): boolean {
  const [elapsed, setElapsed] = useState(false)

  useEffect(() => {
    if (!active) return
    const timeoutId = setTimeout(() => setElapsed(true), delayMs)
    return () => {
      clearTimeout(timeoutId)
      setElapsed(false)
    }
  }, [active, delayMs])

  return elapsed
}

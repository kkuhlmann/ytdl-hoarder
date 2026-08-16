"use client"

import { useEffect, useState } from "react"

function readVars<T extends Record<string, string>>(vars: T): Record<keyof T, string> {
  const out = {} as Record<keyof T, string>
  if (typeof window === "undefined") return out
  const cs = getComputedStyle(document.documentElement)
  for (const k in vars) {
    out[k] = cs.getPropertyValue(vars[k]).trim()
  }
  return out
}

// Resolve theme CSS custom properties to concrete color strings, re-resolving
// whenever the active theme (data-theme on <html>) changes. For canvas/SVG
// consumers that can't rely on the CSS cascade (WaveSurfer, Recharts). Regular
// DOM elements should use CSS vars in inline styles / Tailwind classes instead.
export function useThemeColors<T extends Record<string, string>>(vars: T): Record<keyof T, string> {
  // Callers pass an object literal, so `vars` is a fresh identity every render.
  // Keying the effect on its serialized contents keeps the subscription stable
  // without stashing the object in a ref and reading it back during render.
  // Depending on `vars` directly would resubscribe and setColors every render —
  // an infinite loop; this is self-defending against that.
  const varsKey = JSON.stringify(vars)

  const [colors, setColors] = useState<Record<keyof T, string>>(() => readVars(vars))

  useEffect(() => {
    const names = JSON.parse(varsKey) as T
    const update = () => setColors(readVars(names))
    update()
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    })
    return () => observer.disconnect()
  }, [varsKey])

  return colors
}

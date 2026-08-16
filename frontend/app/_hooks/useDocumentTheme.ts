"use client"

import { useCallback, useSyncExternalStore } from "react"

/**
 * An attribute on `<html>`, kept live by a MutationObserver.
 *
 * useSyncExternalStore rather than useState-plus-effect: the attribute is the
 * source of truth and isn't readable during the static prerender, and this form
 * has no first render with a wrong value that an effect then has to correct.
 */
export function useDocumentAttribute<T extends string>(name: string, fallback: T): T {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const observer = new MutationObserver(onChange)
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: [name],
      })
      return () => observer.disconnect()
    },
    [name]
  )

  return useSyncExternalStore(
    subscribe,
    () => (document.documentElement.getAttribute(name) as T | null) || fallback,
    () => fallback
  )
}

/** The theme currently applied to `<html data-theme>`. */
export function useDocumentTheme(): string {
  return useDocumentAttribute("data-theme", "matrix")
}

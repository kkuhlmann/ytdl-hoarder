import { useCallback, useRef, useState, type RefObject } from "react"

/**
 * A media element's own duration, for surfaces whose stored row duration can be
 * missing. A zero duration leaves the clip range and zoom unusable, so the
 * element's value wins as soon as metadata lands.
 *
 * Returns a ref callback to hand to the player instead of a plain ref
 * assignment; it keeps `elementRef` populated too.
 */
export function useElementDuration(elementRef: RefObject<HTMLVideoElement | null>) {
  const listenerRef = useRef<(() => void) | null>(null)
  const [duration, setDuration] = useState(0)

  // Stable: players re-run their ref effect whenever this identity changes, so
  // an inline arrow would re-attach the listener on every time-update tick.
  // The removal below keeps that a non-event even if a dep is added later.
  const refCallback = useCallback(
    (el: HTMLVideoElement | null) => {
      if (elementRef.current && listenerRef.current) {
        elementRef.current.removeEventListener("loadedmetadata", listenerRef.current)
        listenerRef.current = null
      }
      elementRef.current = el
      if (!el) {
        setDuration(0)
        return
      }
      // An unseekable stream reports Infinity, which would blow out every
      // range the duration feeds.
      const update = () => setDuration(Number.isFinite(el.duration) ? el.duration : 0)
      if (el.duration) update()
      el.addEventListener("loadedmetadata", update)
      listenerRef.current = update
    },
    [elementRef]
  )

  return { duration, refCallback }
}

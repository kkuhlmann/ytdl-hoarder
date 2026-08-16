"use client"

import React from "react"
import {
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core"
import type { MouseSensorOptions, TouchSensorOptions } from "@dnd-kit/core"
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable"

/**
 * Whether a gesture starting on this element may lift the row.
 *
 * dnd-kit's stock mouse and touch activators don't look at what was pressed —
 * only KeyboardSensor filters interactive elements — so without this a drag
 * across a star rating would set a rating *and* reorder the playlist.
 */
function mayStartDrag(target: EventTarget | null): boolean {
  let el = target instanceof HTMLElement ? target : null
  while (el) {
    if (el.dataset.noDnd === "true") return false
    el = el.parentElement
  }
  return true
}

/**
 * Left button only, and not on a no-dnd subtree.
 *
 * Mirrors the stock activator otherwise, including the `onActivation` callback;
 * stock rejects only the right button, which would leave a middle click able to
 * start a drag.
 */
// Not annotated as Activators<T>: the base class declares `eventName` as a
// single literal, and that wider type doesn't satisfy the static side.
const mouseActivators = [
  {
    eventName: "onMouseDown" as const,
    handler: (
      { nativeEvent: event }: React.MouseEvent,
      { onActivation }: MouseSensorOptions,
    ) => {
      if (event.button !== 0 || !mayStartDrag(event.target)) return false
      onActivation?.({ event })
      return true
    },
  },
]

/** Single finger only, and not on a no-dnd subtree. Mirrors the stock activator. */
const touchActivators = [
  {
    eventName: "onTouchStart" as const,
    handler: (
      { nativeEvent: event }: React.TouchEvent,
      { onActivation }: TouchSensorOptions,
    ) => {
      if (event.touches.length > 1 || !mayStartDrag(event.target)) return false
      onActivation?.({ event })
      return true
    },
  },
]

export class RowMouseSensor extends MouseSensor {
  static activators = mouseActivators
}

export class RowTouchSensor extends TouchSensor {
  static activators = touchActivators
}

/**
 * Sensors for dragging a row in a list that also scrolls and whose rows are
 * clickable.
 *
 * Mouse and touch are deliberately separate sensors rather than one
 * PointerSensor: `pointerdown` fires for touch too, so a single
 * distance-constrained PointerSensor would seize a vertical scroll the instant
 * the finger moved 8px and the long-press delay would never get to run — the
 * list would stop scrolling.
 *
 *   mouse — 8px of travel, so a plain click still reaches the row's onClick
 *   touch — 220ms hold, so a swipe scrolls and only a deliberate press lifts
 */
export function useRowDragSensors() {
  return useSensors(
    useSensor(RowMouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(RowTouchSensor, {
      activationConstraint: { delay: 220, tolerance: 6 },
    }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )
}

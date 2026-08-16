"use client"

import { useEffect, useRef, useState, useCallback } from "react"
import { TaskStatus } from "@/app/types/TasksOptions"
import { apiUrl } from "@/app/lib/api"

export type ProgressEvent = {
  event_type: "progress"
  task_id: string
  percent_complete?: number
  eta_seconds?: number
  download_phase?: "VIDEO" | "AUDIO" | null
  status_message?: string
}

export type StatusChangeEvent = {
  event_type: "status_change"
  task_id: string
  status: TaskStatus
  status_message?: string
  /** Present only on the event that starts a rate-limit sleep. */
  sleep_until?: string | null
}

export type SSEEvent = ProgressEvent | StatusChangeEvent

type UseTaskProgressOptions = {
  onProgressUpdate?: (event: ProgressEvent) => void
  onStatusChange?: (event: StatusChangeEvent) => void
  /** Whether to stream all tasks (default: true) */
  allTasks?: boolean
  /** Whether to enable the SSE connection (default: true) */
  enabled?: boolean
}

type UseTaskProgressReturn = {
  connected: boolean
}

const MAX_RECONNECT_ATTEMPTS = 5
const BASE_RECONNECT_DELAY = 1000 // 1 second

/**
 * React hook for receiving real-time task progress updates via SSE.
 *
 * Uses the native EventSource API with automatic reconnection on failure.
 * Provides callbacks for progress updates and status changes.
 *
 * @example
 * ```tsx
 * const { connected } = useTaskProgress({
 *   onProgressUpdate: (event) => {
 *     setTasks(prev => prev.map(t =>
 *       t.task_id === event.task_id
 *         ? { ...t, percent_complete: event.percent_complete ?? t.percent_complete }
 *         : t
 *     ))
 *   },
 *   onStatusChange: (event) => {
 *     // Trigger full refresh for terminal states
 *     if (['COMPLETE', 'FAILED', 'CANCELLED'].includes(event.status)) {
 *       refreshTasks()
 *     }
 *   }
 * })
 * ```
 */
export function useTaskProgress({
  onProgressUpdate,
  onStatusChange,
  allTasks = true,
  enabled = true,
}: UseTaskProgressOptions = {}): UseTaskProgressReturn {
  const [connected, setConnected] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)

  // Store callbacks in refs to avoid recreating EventSource on callback changes
  const onProgressUpdateRef = useRef(onProgressUpdate)
  const onStatusChangeRef = useRef(onStatusChange)

  useEffect(() => {
    onProgressUpdateRef.current = onProgressUpdate
    onStatusChangeRef.current = onStatusChange
  }, [onProgressUpdate, onStatusChange])

  const buildUrl = useCallback(() => {
    const params = new URLSearchParams()
    params.set("all_tasks", String(allTasks))
    return apiUrl(`/sse/progress?${params.toString()}`)
  }, [allTasks])

  // Named, rather than an arrow, so the reconnect timer below can call it
  // without naming the `connect` binding it is still in the middle of defining.
  const connect = useCallback(function openConnection() {
    if (!enabled) return

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    const url = buildUrl()
    const eventSource = new EventSource(url, { withCredentials: true })
    eventSourceRef.current = eventSource

    eventSource.onopen = () => {
      setConnected(true)
      reconnectAttemptRef.current = 0
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SSEEvent

        if (data.event_type === "progress") {
          onProgressUpdateRef.current?.(data)
        } else if (data.event_type === "status_change") {
          onStatusChangeRef.current?.(data)
          // Dispatch custom event for components like NavigationBar storage indicator
          if (data.status === "COMPLETE") {
            window.dispatchEvent(new CustomEvent("task-completed"))
          }
        }
      } catch (e) {
        // Silently ignore parse errors (e.g., keepalive comments)
      }
    }

    eventSource.onerror = () => {
      setConnected(false)
      eventSource.close()

      if (reconnectAttemptRef.current < MAX_RECONNECT_ATTEMPTS) {
        const delay = BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptRef.current)
        reconnectAttemptRef.current++

        reconnectTimeoutRef.current = setTimeout(() => {
          openConnection()
        }, delay)
      }
    }
  }, [enabled, buildUrl])

  useEffect(() => {
    connect()

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
    }
  }, [connect])

  return { connected }
}

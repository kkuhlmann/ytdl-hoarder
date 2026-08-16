/**
 * Which task statuses accept which action. One home, because the tasks table,
 * its bulk bar and the card that owns them all have to agree on the answer.
 */

import { formatTimeUntil, getFullTimestamp } from "@/app/utils"
import type { TaskRecord } from "@/app/types/TasksOptions"

export const CANCELLABLE_TASK_STATUSES = [
  "RESOLVING",
  "QUEUED",
  "IN_PROGRESS",
  "POSTPROCESSING",
  "RETRY",
  "NOT_READY",
] as const

export const RETRYABLE_TASK_STATUSES = ["FAILED", "CANCELLED"] as const

export const canCancel = (status: string) =>
  (CANCELLABLE_TASK_STATUSES as readonly string[]).includes(status)

export const isRetryable = (status: string) =>
  (RETRYABLE_TASK_STATUSES as readonly string[]).includes(status)

/** "3 of 20", or just "3" for a task type with no attempt ceiling. */
export const retryAttemptsLabel = (task: TaskRecord) =>
  task.max_retries ? `${task.retry_count} of ${task.max_retries}` : `${task.retry_count}`

/** "in 4m (14:32:05)" — the countdown plus the wall-clock time it lands on. */
export function retryNextTryLabel(task: TaskRecord): string {
  if (!task.next_retry_at) return "N/A"
  const remaining = formatTimeUntil(task.next_retry_at)
  return `${remaining ? `in ${remaining}` : "now"} (${getFullTimestamp(task.next_retry_at)})`
}

/**
 * Time left in the pre-download rate-limit sleep, or null when the row isn't sleeping.
 *
 * One helper answers both "is it sleeping?" and "for how much longer?", so the badge and
 * the Message cell can't disagree. formatTimeUntil returns null once the deadline passes,
 * which is what ends the state on its own — the backend publishes no wake-up event.
 */
export const sleepRemaining = (task: TaskRecord): string | null =>
  task.status === "IN_PROGRESS" && task.task_type === "DOWNLOAD"
    ? formatTimeUntil(task.sleep_until)
    : null

/**
 * The Message cell for a retrying task: what failed and when it tries again,
 * instead of the exception text (which stays on the row's title and in the dialog).
 * Returns null for any row that can't answer both — the caller falls back to the
 * normal status_message rendering rather than showing half a sentence.
 */
export function retryRowMessage(task: TaskRecord): string | null {
  if (task.status !== "RETRY" || !task.next_retry_at) return null

  const attempts = task.max_retries
    ? `${task.retry_count}/${task.max_retries}`
    : `${task.retry_count}`
  const remaining = formatTimeUntil(task.next_retry_at)

  if (!task.error_code) {
    return remaining ? `Retry ${attempts} in ${remaining}` : `Retry ${attempts} now`
  }
  return remaining
    ? `${task.error_code} (${attempts}): Retries in ${remaining}`
    : `${task.error_code} (${attempts}): Retrying now`
}

/**
 * The Message cell text for a row whose live countdown says more than its status_message
 * does, or null to fall back to that message. Both render paths of the Message column go
 * through here so the desktop and mobile cells can't drift apart.
 */
export function taskRowMessage(task: TaskRecord): string | null {
  const sleeping = sleepRemaining(task)
  if (sleeping) return `Starts in ${sleeping}`
  return retryRowMessage(task)
}

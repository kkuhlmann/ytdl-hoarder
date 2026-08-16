import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  canCancel,
  isRetryable,
  retryAttemptsLabel,
  retryNextTryLabel,
  retryRowMessage,
  sleepRemaining,
  taskRowMessage,
} from "./taskStatus"
import type { TaskRecord } from "@/app/types/TasksOptions"

const SECOND = 1000
const MINUTE = 60 * SECOND

const NOW_ISO = "2026-08-08T12:00:00Z"
const NOW_MS = Date.parse(NOW_ISO)

function isoAfter(ms: number): string {
  return new Date(NOW_MS + ms).toISOString()
}

function isoBefore(ms: number): string {
  return new Date(NOW_MS - ms).toISOString()
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(NOW_ISO))
})

afterEach(() => {
  vi.useRealTimers()
})

describe("canCancel", () => {
  it("allows a cancellable status", () => {
    expect(canCancel("QUEUED")).toBe(true)
  })

  it("rejects a non-cancellable status", () => {
    expect(canCancel("COMPLETE")).toBe(false)
  })
})

describe("isRetryable", () => {
  it("allows a retryable status", () => {
    expect(isRetryable("FAILED")).toBe(true)
  })

  it("rejects a non-retryable status", () => {
    expect(isRetryable("QUEUED")).toBe(false)
  })
})

describe("retryAttemptsLabel", () => {
  it("renders \"N of M\" when the task type has an attempt ceiling", () => {
    const task = { retry_count: 3, max_retries: 20 } as TaskRecord
    expect(retryAttemptsLabel(task)).toBe("3 of 20")
  })

  it("renders just the count when the task type has no ceiling", () => {
    const task = { retry_count: 3, max_retries: null } as TaskRecord
    expect(retryAttemptsLabel(task)).toBe("3")
  })
})

describe("retryNextTryLabel", () => {
  it("returns \"N/A\" when there is no next_retry_at", () => {
    const task = { next_retry_at: null } as TaskRecord
    expect(retryNextTryLabel(task)).toBe("N/A")
  })

  it("renders the countdown plus wall-clock time for a future retry", () => {
    const task = { next_retry_at: isoAfter(4 * MINUTE) } as TaskRecord
    expect(retryNextTryLabel(task)).toMatch(/^in .+ \(.+\)$/)
  })

  it("renders \"now\" plus wall-clock time once the retry is due", () => {
    const task = { next_retry_at: isoBefore(SECOND) } as TaskRecord
    expect(retryNextTryLabel(task)).toMatch(/^now \(.+\)$/)
  })
})

describe("retryRowMessage", () => {
  it("returns null for a non-RETRY status", () => {
    const task = {
      status: "QUEUED",
      next_retry_at: isoAfter(4 * MINUTE),
      error_code: null,
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBeNull()
  })

  it("returns null for a RETRY status without a next_retry_at", () => {
    const task = {
      status: "RETRY",
      next_retry_at: null,
      error_code: null,
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBeNull()
  })

  it("renders \"Retry N/M in Xm\" with no error_code and time remaining", () => {
    const task = {
      status: "RETRY",
      next_retry_at: isoAfter(4 * MINUTE),
      error_code: null,
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBe("Retry 3/20 in 4m")
  })

  it("renders \"Retry N/M now\" with no error_code once the retry is due", () => {
    const task = {
      status: "RETRY",
      next_retry_at: isoBefore(SECOND),
      error_code: null,
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBe("Retry 3/20 now")
  })

  it("prefixes the error code and reads \"Retries in Xm\" with time remaining", () => {
    const task = {
      status: "RETRY",
      next_retry_at: isoAfter(4 * MINUTE),
      error_code: "HTTP_403",
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBe("HTTP_403 (3/20): Retries in 4m")
  })

  it("prefixes the error code and reads \"Retrying now\" once the retry is due", () => {
    const task = {
      status: "RETRY",
      next_retry_at: isoBefore(SECOND),
      error_code: "HTTP_403",
      retry_count: 3,
      max_retries: 20,
    } as TaskRecord
    expect(retryRowMessage(task)).toBe("HTTP_403 (3/20): Retrying now")
  })

  it("renders attempts as just the count when the task type has no ceiling", () => {
    const task = {
      status: "RETRY",
      next_retry_at: isoAfter(4 * MINUTE),
      error_code: null,
      retry_count: 3,
      max_retries: null,
    } as TaskRecord
    expect(retryRowMessage(task)).toBe("Retry 3 in 4m")
  })
})

function sleepingTask(overrides: Partial<TaskRecord> = {}): TaskRecord {
  return {
    status: "IN_PROGRESS",
    task_type: "DOWNLOAD",
    sleep_until: isoAfter(2 * MINUTE),
    ...overrides,
  } as TaskRecord
}

describe("sleepRemaining", () => {
  it("returns the time left for an in-progress download still sleeping", () => {
    expect(sleepRemaining(sleepingTask())).toBe("2m")
  })

  it("returns null once the wake time has passed", () => {
    expect(sleepRemaining(sleepingTask({ sleep_until: isoBefore(SECOND) }))).toBeNull()
  })

  it("returns null when the task carries no sleep_until", () => {
    expect(sleepRemaining(sleepingTask({ sleep_until: null }))).toBeNull()
  })

  it("returns null for a download that is not IN_PROGRESS", () => {
    expect(sleepRemaining(sleepingTask({ status: "QUEUED" }))).toBeNull()
  })

  it("returns null for a non-download task type", () => {
    expect(sleepRemaining(sleepingTask({ task_type: "TRANSCRIPT_GENERATION" }))).toBeNull()
  })
})

describe("taskRowMessage", () => {
  it("leads with the sleep countdown for a sleeping download", () => {
    expect(taskRowMessage(sleepingTask())).toBe("Starts in 2m")
  })

  it("falls through to the retry message for a retrying task", () => {
    const task = {
      status: "RETRY",
      task_type: "DOWNLOAD",
      next_retry_at: isoAfter(4 * MINUTE),
      error_code: "HTTP_403",
      retry_count: 3,
      max_retries: 20,
      sleep_until: null,
    } as TaskRecord
    expect(taskRowMessage(task)).toBe("HTTP_403 (3/20): Retries in 4m")
  })

  it("returns null when the row has no countdown, so the caller shows status_message", () => {
    const task = {
      status: "IN_PROGRESS",
      task_type: "DOWNLOAD",
      next_retry_at: null,
      sleep_until: null,
    } as TaskRecord
    expect(taskRowMessage(task)).toBeNull()
  })
})

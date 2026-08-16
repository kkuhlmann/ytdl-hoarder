// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render } from "@testing-library/react"
import { TasksCard } from "./TasksCard"
import type { StatusChangeEvent } from "@/app/hooks/useTaskProgress"
import type { TaskRecord, TaskStats, TaskStatus } from "@/app/types/TasksOptions"

vi.mock("@/app/_components/TasksTable", () => ({ TasksTable: () => <div>tasks-table</div> }))
vi.mock("@/app/_components/TaskStatsBar", () => ({ TaskStatsBar: () => <div>stats-bar</div> }))
vi.mock("@/app/_components/BulkActionsBar", () => ({ BulkActionsBar: () => <div>bulk-bar</div> }))
vi.mock("@/app/_components/TablePagination", () => ({ TablePagination: () => <div>pages</div> }))
vi.mock("@/app/_components/ConfirmDialog", () => ({ ConfirmDialog: () => null }))

class FakeEventSource {
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  constructor(
    public url: string,
    public opts?: { withCredentials?: boolean }
  ) {
    FakeEventSource.instances.push(this)
  }
  close() {}
}

const EMPTY_STATS: TaskStats = {
  queued_total: 0,
  queued_downloads: 0,
  queued_transcripts: 0,
  processing: 0,
  failed: 0,
  retry: 0,
  not_ready: 0,
  completed_24h: 0,
}

function row(status: TaskStatus, title: string): TaskRecord {
  return { id: 1, task_id: "t1", task_type: "DOWNLOAD", status, title } as TaskRecord
}

function statusChange(status: TaskStatus): string {
  const event: StatusChangeEvent = { event_type: "status_change", task_id: "t1", status }
  return JSON.stringify(event)
}

beforeEach(() => {
  vi.useFakeTimers()
  FakeEventSource.instances = []
  vi.stubGlobal("EventSource", FakeEventSource)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

/** Mounts the card with the first page already fetched and committed to state. */
async function mountWith(initial: TaskRecord) {
  const fetchTasks = vi
    .fn()
    .mockResolvedValueOnce({ pageCount: 1, tableRows: [initial] })
    .mockResolvedValue({ pageCount: 1, tableRows: [row("QUEUED", "Real Video Title")] })

  await act(async () => {
    render(<TasksCard fetchTasks={fetchTasks} fetchStats={vi.fn().mockResolvedValue(EMPTY_STATS)} />)
    await vi.advanceTimersByTimeAsync(0)
  })

  // The connection has to be open before the card stops polling, and the rows have to be
  // committed before knownTaskStatusRef knows what status they are transitioning away from.
  await act(async () => {
    FakeEventSource.instances[0].onopen?.()
    await vi.advanceTimersByTimeAsync(0)
  })

  expect(fetchTasks).toHaveBeenCalledTimes(1)
  return fetchTasks
}

async function emit(data: string, advanceMs: number) {
  await act(async () => {
    FakeEventSource.instances[0].onmessage?.({ data })
    await vi.advanceTimersByTimeAsync(advanceMs)
  })
}

describe("TasksCard live row refresh", () => {
  it("refetches when a row leaves RESOLVING, since the event carries no title", async () => {
    const fetchTasks = await mountWith(row("RESOLVING", "https://youtu.be/abc123"))

    await emit(statusChange("QUEUED"), 500)

    expect(fetchTasks).toHaveBeenCalledTimes(2)
  })

  it("does not refetch on a status change that starts anywhere but RESOLVING", async () => {
    const fetchTasks = await mountWith(row("QUEUED", "Real Video Title"))

    await emit(statusChange("IN_PROGRESS"), 5000)

    expect(fetchTasks).toHaveBeenCalledTimes(1)
  })
})

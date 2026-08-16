"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { useTriStateSort } from "@/app/_hooks/useTriStateSort"
import { useBulkSelection } from "@/app/_hooks/useBulkSelection"
import { canCancel, isRetryable } from "@/app/lib/taskStatus"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { MagnifyingGlassIcon } from "@heroicons/react/20/solid"
import { TasksTable } from "@/app/_components/TasksTable"
import { TablePagination } from "@/app/_components/TablePagination"
import { BulkActionsBar } from "@/app/_components/BulkActionsBar"
import { ConfirmDialog } from "@/app/_components/ConfirmDialog"
import { ArrowPathIcon, TrashIcon } from "@heroicons/react/24/outline"
import { TaskStatsBar } from "@/app/_components/TaskStatsBar"
import {
  TaskRecord,
  TaskFilterState,
  TaskStatus,
  SortDirection,
  TaskStats,
  StatCategory,
} from "@/app/types/TasksOptions"
import { useTaskProgress, ProgressEvent, StatusChangeEvent } from "@/app/hooks/useTaskProgress"
import axios from "axios"
import toast from "react-hot-toast"
import { cn } from "@/lib/utils"
import { apiUrl, errorMessage } from "@/app/lib/api"
import { motion } from "framer-motion"

// Hoisted so useBulkSelection's selectAll keeps one identity across renders.
const taskId = (task: TaskRecord) => task.id

type FilterBadgeProps = {
  label: string
  checked: boolean
  onChange: () => void
  variant: "success" | "queued" | "info" | "warning" | "error" | "secondary"
}

function FilterBadge({ label, checked, onChange, variant }: FilterBadgeProps) {
  return (
    <label
      className={cn(
        "flex items-center gap-2 px-2 py-1 md:px-3 md:py-1.5 rounded-md text-xs md:text-sm font-mono transition-all cursor-pointer",
        checked
          ? "bg-bg-surface border border-border"
          : "bg-transparent border border-transparent opacity-60 hover:opacity-100"
      )}
    >
      <Checkbox checked={checked} onCheckedChange={onChange} />
      <Badge variant={variant} className="pointer-events-none">
        {label}
      </Badge>
    </label>
  )
}

type TasksCardProps = {
  fetchTasks: (
    search: string | null,
    statuses: string | null,
    sinceHours: number,
    pageNumber: number,
    sortBy?: string | null,
    sortDirection?: SortDirection
  ) => Promise<{ pageCount: number; tableRows: TaskRecord[] }>
  fetchStats: () => Promise<TaskStats>
}

export function TasksCard({ fetchTasks, fetchStats }: TasksCardProps) {
  const [tableRows, setTableRows] = useState<TaskRecord[]>([])
  const [pageCount, setPageCount] = useState(0)
  // Tagged with the filter/search combination it was paged within — combined
  // just below `filters`, where both are in scope.
  const [page, setPage] = useState<{ key: string; n: number }>({ key: "", n: 1 })
  const { sortBy, sortDirection, handleSort } = useTriStateSort()
  const [stats, setStats] = useState<TaskStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [search, setSearch] = useState("")

  const [showBulkRetry, setShowBulkRetry] = useState(false)
  const [showBulkDelete, setShowBulkDelete] = useState(false)
  const [bulkRetryDownstream, setBulkRetryDownstream] = useState(true)
  const [bulkOverwrite, setBulkOverwrite] = useState(false)
  const [bulkActionLoading, setBulkActionLoading] = useState<"cancel" | "delete" | "retry" | null>(null)

  const [filters, setFilters] = useState<TaskFilterState>({
    showInProgress: true,
    showQueued: true,
    showNotReleased: true,
    showRecentlyCompleted: true,
    showCancelled: false,
    showFailed: false,
    showRetry: false,
  })

  // Changing a filter or the search is a different result set, so the page
  // number doesn't carry over. Derived rather than reset from an effect — there
  // are nine call sites that change one of these.
  const pageKey = JSON.stringify([filters, search])
  const pageNumber = page.key === pageKey ? page.n : 1
  const setPageNumber = useCallback((n: number) => setPage({ key: pageKey, n }), [pageKey])

  const [activeStatFilter, setActiveStatFilter] = useState<StatCategory | null>(null)

  const {
    selectedIds,
    setSelectedIds,
    selectedItems: selectedTasks,
    allSelected,
    clear: clearSelection,
    selectAll,
  } = useBulkSelection(tableRows, taskId)

  const bulkRetryableTasks = selectedTasks.filter((t) => isRetryable(t.status))
  const bulkRetryableCount = bulkRetryableTasks.length
  const bulkHasDownstream = bulkRetryableTasks.some((t) => t.has_downstream_tasks)
  const bulkHasDownloadTasks = bulkRetryableTasks.some((t) => t.task_type === "DOWNLOAD")

  const loadTasksRef = useRef<() => void>(() => {})
  const loadStatsRef = useRef<() => void>(() => {})
  const statsDebounceTimerRef = useRef<NodeJS.Timeout | null>(null)
  const reloadDebounceRef = useRef<NodeJS.Timeout | null>(null)
  // Status, not just membership: handleStatusChange keys off the status a row held
  // *before* the event, which the incoming event can't tell it.
  const knownTaskStatusRef = useRef<Map<string, TaskStatus>>(new Map())

  const loadStats = useCallback((immediate = false) => {
    if (statsDebounceTimerRef.current) {
      clearTimeout(statsDebounceTimerRef.current)
      statsDebounceTimerRef.current = null
    }

    const executeLoad = () => {
      // Only show loading on initial load - use functional update to check current state
      setStats((currentStats) => {
        if (currentStats === null) {
          setStatsLoading(true)
        }
        return currentStats
      })
      fetchStats()
        .then((data) => {
          setStats(data)
          setStatsLoading(false)
        })
        .catch(() => setStatsLoading(false))
    }

    if (immediate) {
      executeLoad()
    } else {
      statsDebounceTimerRef.current = setTimeout(executeLoad, 300)
    }
  }, [fetchStats])

  const scheduleReload = useCallback((delayMs: number) => {
    if (reloadDebounceRef.current) clearTimeout(reloadDebounceRef.current)
    reloadDebounceRef.current = setTimeout(() => {
      reloadDebounceRef.current = null
      loadTasksRef.current()
      loadStatsRef.current()
    }, delayMs)
  }, [])

  const handleProgressUpdate = useCallback((event: ProgressEvent) => {
    setTableRows((prev) =>
      prev.map((task) =>
        task.task_id === event.task_id
          ? {
              ...task,
              percent_complete: event.percent_complete ?? task.percent_complete,
              eta_seconds: event.eta_seconds ?? task.eta_seconds,
              download_phase: event.download_phase !== undefined ? event.download_phase : task.download_phase,
              status_message: event.status_message ?? task.status_message,
            }
          : task
      )
    )
  }, [])

  const handleStatusChange = useCallback((event: StatusChangeEvent) => {
    const priorStatus = knownTaskStatusRef.current.get(event.task_id)

    if (priorStatus === undefined) {
      // New task detected — debounced refresh to batch rapid creates
      scheduleReload(800)
    } else {
      setTableRows((prev) =>
        prev.map((task) =>
          task.task_id === event.task_id
            ? {
                ...task,
                status: event.status,
                status_message: event.status_message ?? task.status_message,
                sleep_until:
                  event.sleep_until !== undefined ? event.sleep_until : task.sleep_until,
              }
            : task
        )
      )
    }

    // Refresh stats on any status change (debounced to handle rapid successive changes)
    loadStatsRef.current()

    // Terminal statuses: refresh to get any new tasks or cleanup. The other two triggers
    // are here because the status_change event carries only status + status_message:
    // RETRY's retry_count, next_retry_at and error_code arrive by refetch, and leaving
    // RESOLVING rewrites the row's title, channel and release_timestamp server-side plus
    // assigns its queue position — so the row would otherwise keep showing the raw URL.
    const reloadStatuses = ["COMPLETE", "FAILED", "CANCELLED", "RETRY"]
    if (reloadStatuses.includes(event.status) || priorStatus === "RESOLVING") {
      // Debounce the refresh slightly to batch multiple completions
      scheduleReload(500)
    }
  }, [scheduleReload])

  const { connected: sseConnected } = useTaskProgress({
    onProgressUpdate: handleProgressUpdate,
    onStatusChange: handleStatusChange,
  })

  const buildStatusFilter = useCallback((): string | null => {
    const statuses: string[] = []
    if (filters.showInProgress) statuses.push("IN_PROGRESS", "POSTPROCESSING")
    if (filters.showQueued) statuses.push("QUEUED", "RESOLVING")
    if (filters.showNotReleased) statuses.push("NOT_READY")
    if (filters.showRecentlyCompleted) statuses.push("COMPLETE")
    if (filters.showCancelled) statuses.push("CANCELLED")
    if (filters.showFailed) statuses.push("FAILED")
    if (filters.showRetry) statuses.push("RETRY")
    return statuses.length > 0 ? statuses.join(",") : null
  }, [filters])

  const loadTasks = useCallback(() => {
    const statusFilter = buildStatusFilter()
    const searchParam = search.length > 2 ? search : null
    return fetchTasks(searchParam, statusFilter, 24, pageNumber, sortBy, sortDirection)
      .then(({ pageCount, tableRows }) => {
        setPageCount(pageCount)
        setTableRows(tableRows)
      })
      .catch(() => {})
  }, [fetchTasks, buildStatusFilter, pageNumber, sortBy, sortDirection, search])

  // Loads on mount and on filter/pagination/sort changes. Polling only kicks in
  // when SSE is down; while it is connected, SSE drives the refreshes.
  const { isLoading: loading, refetch: reloadTasks } = useFetchEffect(
    loadTasks,
    [loadTasks],
    { pollMs: sseConnected ? null : 10_000 }
  )

  const handleBulkCancel = async () => {
    const cancellableTasks = selectedTasks.filter((t) => canCancel(t.status))

    if (cancellableTasks.length === 0) {
      toast.error("No cancellable tasks selected")
      return
    }

    setBulkActionLoading("cancel")
    try {
      const response = await axios.post(
        apiUrl('/tasks/bulk/cancel'),
        { task_ids: cancellableTasks.map((t) => t.task_id) }
      )

      if (response.status === 200) {
        const { cancelled_count, downstream_cancelled } = response.data
        let message = `Cancelled ${cancelled_count} task(s)`
        if (downstream_cancelled > 0) {
          message += ` and ${downstream_cancelled} downstream task(s)`
        }
        toast.success(message)
        clearSelection()
        reloadTasks()
      }
    } catch (error) {
      toast.error(
        `Failed to cancel tasks: ${errorMessage(error, "Unknown error")}`
      )
    } finally {
      setBulkActionLoading(null)
    }
  }

  const handleBulkDelete = async () => {
    if (selectedTasks.length === 0) {
      toast.error("No tasks selected")
      return
    }

    setBulkActionLoading("delete")
    try {
      const response = await axios.delete(
        apiUrl('/tasks/bulk'),
        { data: { record_ids: selectedTasks.map((t) => t.id) } }
      )

      if (response.status === 200) {
        toast.success(`Deleted ${response.data.deleted_count} task(s)`)
        clearSelection()
        setShowBulkDelete(false)
        reloadTasks()
      }
    } catch (error) {
      toast.error(
        `Failed to delete tasks: ${errorMessage(error, "Unknown error")}`
      )
    } finally {
      setBulkActionLoading(null)
    }
  }

  const handleBulkRetry = async (retryDownstream: boolean, overwrite: boolean) => {
    const retryableTasks = selectedTasks.filter((t) => isRetryable(t.status))

    if (retryableTasks.length === 0) {
      toast.error("No retryable tasks selected")
      return
    }

    setBulkActionLoading("retry")
    try {
      const response = await axios.post(
        apiUrl('/tasks/bulk/retry'),
        {
          record_ids: retryableTasks.map((t) => t.id),
          retry_downstream: retryDownstream,
          overwrite: overwrite,
        }
      )

      if (response.status === 200) {
        const retryType = overwrite ? "hard retried" : "retried"
        toast.success(`${retryType.charAt(0).toUpperCase() + retryType.slice(1)} ${response.data.retried_count} task(s)`)
        clearSelection()
        setShowBulkRetry(false)
        reloadTasks()
      }
    } catch (error) {
      toast.error(
        `Failed to retry tasks: ${errorMessage(error, "Unknown error")}`
      )
    } finally {
      setBulkActionLoading(null)
    }
  }

  const handleStatClick = useCallback((category: StatCategory) => {
    if (activeStatFilter === category) {
      setActiveStatFilter(null)
      setFilters({
        showInProgress: true,
        showQueued: true,
        showNotReleased: true,
        showRecentlyCompleted: true,
        showCancelled: false,
        showFailed: false,
        showRetry: false,
      })
    } else {
      setActiveStatFilter(category)
      setFilters({
        showInProgress: category === 'processing',
        showQueued: category === 'queued',
        showNotReleased: category === 'not_ready',
        showRecentlyCompleted: category === 'completed',
        showCancelled: false,
        showFailed: category === 'failed',
        showRetry: category === 'retry',
      })
    }
  }, [activeStatFilter])

  useEffect(() => {
    loadTasksRef.current = reloadTasks
  }, [reloadTasks])

  useEffect(() => {
    loadStatsRef.current = loadStats
  }, [loadStats])

  // Keep known task statuses in sync with table rows so handleStatusChange can detect
  // new tasks and see what status each row is transitioning away from
  useEffect(() => {
    knownTaskStatusRef.current = new Map(tableRows.map((t) => [t.task_id, t.status]))
  }, [tableRows])

  useEffect(() => {
    return () => {
      if (statsDebounceTimerRef.current) {
        clearTimeout(statsDebounceTimerRef.current)
      }
      if (reloadDebounceRef.current) {
        clearTimeout(reloadDebounceRef.current)
      }
    }
  }, [])

  // Stats are refreshed via SSE status changes and polling, not on filter changes
  useEffect(() => {
    loadStats(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Stats poll alongside the tasks poll above, on the same SSE-down condition.
  useEffect(() => {
    if (sseConnected) return
    const interval = setInterval(() => loadStats(), 10000)
    return () => clearInterval(interval)
  }, [loadStats, sseConnected])

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <Card className="mt-4">
        <CardHeader className="pb-3">
          <CardTitle className="text-lg">Task Queue</CardTitle>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Stats bar */}
          <TaskStatsBar
            stats={stats}
            loading={statsLoading}
            onStatClick={handleStatClick}
            activeCategory={activeStatFilter}
          />

          {/* Filter toggles */}
          <div className="grid grid-cols-2 md:grid-cols-3 lg:flex lg:flex-wrap gap-2">
            <FilterBadge
              label="In Progress"
              checked={filters.showInProgress}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showInProgress: !f.showInProgress }))
              }}
              variant="info"
            />
            <FilterBadge
              label="Queued"
              checked={filters.showQueued}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showQueued: !f.showQueued }))
              }}
              variant="queued"
            />
            <FilterBadge
              label="Not Released"
              checked={filters.showNotReleased}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showNotReleased: !f.showNotReleased }))
              }}
              variant="warning"
            />
            <FilterBadge
              label="Done (24h)"
              checked={filters.showRecentlyCompleted}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showRecentlyCompleted: !f.showRecentlyCompleted }))
              }}
              variant="success"
            />
            <FilterBadge
              label="Cancelled"
              checked={filters.showCancelled}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showCancelled: !f.showCancelled }))
              }}
              variant="secondary"
            />
            <FilterBadge
              label="Failed"
              checked={filters.showFailed}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showFailed: !f.showFailed }))
              }}
              variant="error"
            />
            <FilterBadge
              label="Retry"
              checked={filters.showRetry}
              onChange={() => {
                setActiveStatFilter(null)
                setFilters((f) => ({ ...f, showRetry: !f.showRetry }))
              }}
              variant="warning"
            />
          </div>

          {/* Search input */}
          <div className="relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <Input
              placeholder="Search tasks by title or channel..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>

          {/* Bulk actions bar */}
          <BulkActionsBar
            selectedTasks={selectedTasks}
            onCancel={handleBulkCancel}
            onDelete={() => setShowBulkDelete(true)}
            onRetry={() => setShowBulkRetry(true)}
            onClearSelection={clearSelection}
            loadingAction={bulkActionLoading}
          />

          {/* Table */}
          <div className="md:rounded-lg md:border md:border-border overflow-hidden">
            <TasksTable
              tableRows={tableRows}
              loading={loading}
              refreshTasks={loadTasks}
              sortBy={sortBy}
              sortDirection={sortDirection}
              onSort={handleSort}
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              allSelected={allSelected}
              onSelectAll={selectAll}
            />
          </div>

          <TablePagination
            pageNumber={pageNumber}
            pageCount={pageCount}
            setPageNumber={setPageNumber}
          />
        </CardContent>

        {/* Bulk retry dialog */}
        <ConfirmDialog
          open={showBulkRetry}
          onOpenChange={setShowBulkRetry}
          icon={<ArrowPathIcon className="h-5 w-5 text-matrix" />}
          title={`Retry ${bulkRetryableCount} Task${bulkRetryableCount !== 1 ? "s" : ""}?`}
          description="This will create new tasks to retry the selected failed/cancelled operations."
          descriptionClassName="text-matrix/80"
          contentClassName="max-w-[calc(100%-2rem)] sm:max-w-xl overflow-hidden"
          confirmLabel={`Retry ${bulkRetryableCount} Task${bulkRetryableCount !== 1 ? "s" : ""}`}
          loadingLabel="Retrying..."
          confirmVariant="matrix"
          confirmDisabled={bulkRetryableCount === 0}
          isLoading={bulkActionLoading === "retry"}
          onConfirm={() => {
            handleBulkRetry(bulkRetryDownstream, bulkOverwrite)
            setBulkRetryDownstream(true)
            setBulkOverwrite(false)
          }}
          onCancel={() => {
            setShowBulkRetry(false)
            setBulkRetryDownstream(true)
            setBulkOverwrite(false)
          }}
        >
          <div className="space-y-4 py-4">
            {bulkRetryableCount < selectedTasks.length && (
              <p className="text-sm text-status-warning bg-status-warning/10 border border-status-warning/20 rounded-md p-3">
                Note: {selectedTasks.length - bulkRetryableCount} task(s) cannot be retried
                because they are not in a failed or cancelled state.
              </p>
            )}

            <div className="overflow-hidden">
              <p className="font-mono text-sm text-text-secondary mb-2">Tasks to retry:</p>
              <ul className="space-y-1.5 max-h-32 sm:max-h-40 overflow-y-auto overflow-x-hidden pr-2">
                {bulkRetryableTasks.slice(0, 5).map((task) => (
                  <li
                    key={task.id}
                    className="text-sm text-text-muted font-mono grid grid-cols-[auto_1fr_auto] items-center gap-2"
                  >
                    <span className="w-1.5 h-1.5 rounded-full bg-matrix/50" />
                    <span className="truncate">
                      {task.title || task.task_type}
                    </span>
                    <span className="text-status-error text-xs whitespace-nowrap">({task.status})</span>
                  </li>
                ))}
                {bulkRetryableTasks.length > 5 && (
                  <li className="text-sm text-text-muted">
                    ...and {bulkRetryableTasks.length - 5} more
                  </li>
                )}
              </ul>
            </div>

            <div className="space-y-3 pt-2">
              {bulkHasDownstream && (
                <div className="flex items-start gap-3">
                  <Checkbox
                    id="bulk-retry-downstream"
                    checked={bulkRetryDownstream}
                    onCheckedChange={(checked) => setBulkRetryDownstream(checked === true)}
                    className="mt-0.5"
                  />
                  <label
                    htmlFor="bulk-retry-downstream"
                    className="text-sm text-text-secondary cursor-pointer leading-tight"
                  >
                    Also retry downstream tasks that failed due to these tasks
                  </label>
                </div>
              )}

              {bulkHasDownloadTasks && (
                <div className="flex items-start gap-3">
                  <Checkbox
                    id="bulk-overwrite"
                    checked={bulkOverwrite}
                    onCheckedChange={(checked) => setBulkOverwrite(checked === true)}
                    className="mt-0.5"
                  />
                  <label
                    htmlFor="bulk-overwrite"
                    className="text-sm text-status-warning cursor-pointer leading-tight"
                  >
                    Hard retry: Force overwrite for download tasks (start from beginning)
                  </label>
                </div>
              )}
            </div>
          </div>
        </ConfirmDialog>
        {/* Bulk delete dialog */}
        <ConfirmDialog
          open={showBulkDelete}
          onOpenChange={setShowBulkDelete}
          icon={<TrashIcon className="h-5 w-5 text-status-error" />}
          title={`Delete ${selectedTasks.length} Task${selectedTasks.length !== 1 ? "s" : ""}?`}
          description="This removes the selected task records, cancelling any that are still running. This action cannot be undone."
          descriptionClassName="text-status-error/80"
          confirmLabel="Delete"
          loadingLabel="Deleting..."
          confirmDisabled={selectedTasks.length === 0}
          isLoading={bulkActionLoading === "delete"}
          onConfirm={handleBulkDelete}
          onCancel={() => setShowBulkDelete(false)}
        />
      </Card>
    </motion.div>
  )
}

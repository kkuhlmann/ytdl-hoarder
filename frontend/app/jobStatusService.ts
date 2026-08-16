// Polling on purpose: add-subscription jobs are untracked (no TaskRecord), so
// they never appear on the SSE stream — GET /tasks/{id} is their only status
// source (see get_task_status in backend routers/task_records.py).

import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl } from "@/app/lib/api"

const intervalMap = new Map<string, NodeJS.Timeout>()

export const startJobPolling = (
  taskType: string,
  taskId: string | null,
  onSuccess: () => void,
  onFailure: () => void,
  onLoading?: (toastId: string) => void
) => {
  if (!taskId) return
  if (intervalMap.has(taskId)) return

  const toastId = toast.loading(`Getting ${taskType} information...`)
  if (onLoading) onLoading(toastId)

  const intervalId = setInterval(async () => {
    try {
      const response = await axios.get(apiUrl(`/tasks/${taskId}`))
      const data = response.data

      if (data.status === "SUCCESS") {
        toast.remove(toastId)
        clearJobPolling(taskId)
        onSuccess()
      } else if (data.status === "FAILURE") {
        clearJobPolling(taskId)
        onFailure()
      }
    } catch (err) {
      toast.error("Error checking job status")
      clearJobPolling(taskId)
      onFailure()
    }
  }, 1000)

  intervalMap.set(taskId, intervalId)
}

export const clearJobPolling = (taskId: string | null) => {
  if (!taskId) return
  const intervalId = intervalMap.get(taskId)
  if (intervalId) {
    clearInterval(intervalId)
    intervalMap.delete(taskId)
  }
}

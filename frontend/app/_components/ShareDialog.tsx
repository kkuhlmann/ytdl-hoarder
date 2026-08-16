"use client"

import { useState, useEffect } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { MagnifyingGlassIcon, CheckIcon } from "@heroicons/react/20/solid"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl } from "@/app/lib/api"
import { useAuth } from "@/app/context/AuthContext"
import { useAdmin } from "@/app/context/AdminContext"

type ShareDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  entityIds: number[]
  entityType: "subscriptions" | "playlists" | "media-details"
  entityTitle: string
  bulkMode?: boolean
}

type ShareableUser = {
  id: number
  username: string
}

export function ShareDialog({
  open,
  onOpenChange,
  entityIds,
  entityType,
  entityTitle,
  bulkMode = false,
}: ShareDialogProps) {
  const { user } = useAuth()
  const { adminParam } = useAdmin()
  const [users, setUsers] = useState<ShareableUser[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [search, setSearch] = useState("")
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set())
  const [initialSharedIds, setInitialSharedIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    if (!open) return
    let cancelled = false

    async function doFetch() {
      setLoading(true)
      try {
        if (bulkMode) {
          const usersResp = await axios.get(apiUrl("/auth/users/shareable"))
          if (cancelled) return
          setUsers(usersResp.data)
          setInitialSharedIds(new Set())
          setSelectedUserIds(new Set())
        } else {
          const [usersResp, sharedResp] = await Promise.all([
            axios.get(apiUrl("/auth/users/shareable")),
            axios.get(apiUrl(`/${entityType}/${entityIds[0]}/shared-users`), { params: adminParam }),
          ])
          if (cancelled) return

          setUsers(usersResp.data)
          const sharedIds = new Set<number>(sharedResp.data.shared_user_ids || [])
          setInitialSharedIds(sharedIds)
          setSelectedUserIds(new Set(sharedIds))
        }
      } catch (error) {
        if (cancelled) return
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          toast.error("Only the owner can manage sharing")
        } else {
          toast.error("Failed to load sharing data")
        }
        onOpenChange(false)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    doFetch()

    // Clearing the search on teardown rather than on open is equivalent — the
    // box is only visible while the dialog is up — and keeps the reset out of
    // the effect body.
    return () => {
      cancelled = true
      setSearch("")
    }
    // onOpenChange intentionally excluded — it's a callback prop,
    // not a value we need to react to. Including it causes refetch loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, entityType, entityIds, bulkMode])

  const filteredUsers = users
    .filter((u) => u.id !== user?.id)
    .filter((u) => u.username.toLowerCase().includes(search.toLowerCase()))

  const toggleUser = (userId: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev)
      if (next.has(userId)) {
        next.delete(userId)
      } else {
        next.add(userId)
      }
      return next
    })
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      if (bulkMode) {
        const userIds = Array.from(selectedUserIds)
        const res = await axios.post(
          apiUrl(`/${entityType}/share/bulk`),
          { entity_ids: entityIds, user_ids: userIds },
          { params: adminParam }
        )
        const skipped = res.data.errors?.length ?? 0
        if (skipped === 0) {
          toast.success(`Shared ${entityIds.length} items with ${userIds.length} user(s)`)
        } else {
          toast.success(`Shared ${res.data.shared_count} grants (${skipped} items skipped)`)
        }
      } else {
        const toAdd = Array.from(selectedUserIds).filter((id) => !initialSharedIds.has(id))
        const toRemove = Array.from(initialSharedIds).filter((id) => !selectedUserIds.has(id))

        await Promise.all([
          ...toAdd.map((uid) =>
            axios.post(apiUrl(`/${entityType}/${entityIds[0]}/share`), { user_id: uid }, { params: adminParam })
          ),
          ...toRemove.map((uid) =>
            axios.delete(apiUrl(`/${entityType}/${entityIds[0]}/share/${uid}`), { params: adminParam })
          ),
        ])

        const changes = toAdd.length + toRemove.length
        if (changes > 0) {
          toast.success(`Sharing updated (${toAdd.length} added, ${toRemove.length} removed)`)
        } else {
          toast.success("No changes")
        }
      }
      onOpenChange(false)
    } catch {
      toast.error("Failed to update sharing")
    } finally {
      setSaving(false)
    }
  }

  const hasChanges = bulkMode
    ? selectedUserIds.size > 0
    : Array.from(selectedUserIds).some((id) => !initialSharedIds.has(id)) ||
      Array.from(initialSharedIds).some((id) => !selectedUserIds.has(id))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-mono">Share</DialogTitle>
          <p className="text-sm text-text-muted truncate mt-1" title={bulkMode ? undefined : entityTitle}>
            {bulkMode
              ? `${entityIds.length} items`
              : entityTitle.length > 50
                ? entityTitle.slice(0, 50) + "..."
                : entityTitle}
          </p>
        </DialogHeader>

        <div className="space-y-4">
          {/* Search */}
          <div className="relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search users..."
              className="pl-9 font-mono"
            />
          </div>

          {/* User list */}
          <div className="max-h-[300px] overflow-y-auto border border-border rounded-lg">
            {loading ? (
              <div className="p-4 text-center text-text-muted font-mono">
                Loading...
              </div>
            ) : filteredUsers.length === 0 ? (
              <div className="p-4 text-center text-text-muted font-mono">
                {search ? "No matching users" : "No other users available"}
              </div>
            ) : (
              <div className="divide-y divide-border/50">
                {filteredUsers.map((u) => (
                  <button
                    key={u.id}
                    onClick={() => toggleUser(u.id)}
                    className={cn(
                      "w-full px-4 py-3 text-left transition-colors hover:bg-bg-surface/50",
                      selectedUserIds.has(u.id) && "bg-matrix/10"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-sm text-text-primary font-mono">
                        {u.username}
                      </p>
                      {selectedUserIds.has(u.id) && (
                        <CheckIcon className="h-5 w-5 text-matrix" />
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving || !hasChanges}
            >
              {saving ? "Saving..." : "Save"}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  )
}

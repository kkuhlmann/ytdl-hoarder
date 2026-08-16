"use client"

import { useState, useCallback } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
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
import { Playlist } from "@/app/types/PlaylistOptions"
import { useMediaPlayer } from "@/app/context/MediaPlayerContext"
import { MagnifyingGlassIcon, PlusIcon, CheckIcon } from "@heroicons/react/20/solid"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl } from "@/app/lib/api"

type AddToPlaylistDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  mediaDetailsIds: number[]
  mediaTitle: string
}

export function AddToPlaylistDialog({ open, onOpenChange, ...form }: AddToPlaylistDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts DialogContent on close, so every field below is seeded
          from useState on each open, with no effect needed to reset it. */}
      <DialogContent className="sm:max-w-md">
        <AddToPlaylistForm onOpenChange={onOpenChange} {...form} />
      </DialogContent>
    </Dialog>
  )
}

function AddToPlaylistForm({
  onOpenChange,
  mediaDetailsIds,
  mediaTitle,
}: Omit<AddToPlaylistDialogProps, "open">) {
  const bulkMode = mediaDetailsIds.length > 1
  const { syncPlaylistQueue } = useMediaPlayer()
  const [playlists, setPlaylists] = useState<Playlist[]>([])
  const [search, setSearch] = useState("")
  const [selectedPlaylistId, setSelectedPlaylistId] = useState<number | null>(null)
  const [adding, setAdding] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newPlaylistName, setNewPlaylistName] = useState("")
  const [memberOf, setMemberOf] = useState<Set<number>>(new Set())

  // Keyed on the ids' *contents*: callers build this array inline, so depending
  // on its identity would refetch on every render of the parent.
  const idsKey = mediaDetailsIds.join(",")

  const fetchPlaylists = useCallback(
    async (signal: AbortSignal) => {
      const ids = idsKey ? idsKey.split(",").map(Number) : []
      try {
        if (ids.length > 1) {
          const playlistsRes = await axios.get(apiUrl('/playlists'), {
            params: { page_size: 100 },
            signal,
          })
          setPlaylists(playlistsRes.data.records)
          setMemberOf(new Set())
        } else {
          const [playlistsRes, membershipRes] = await Promise.all([
            axios.get(apiUrl('/playlists'), { params: { page_size: 100 }, signal }),
            axios.get(apiUrl(`/playlists/containing/${ids[0]}`), { signal }),
          ])
          setPlaylists(playlistsRes.data.records)
          setMemberOf(new Set(membershipRes.data.playlist_ids as number[]))
        }
      } catch (error) {
        if (axios.isCancel(error)) return
        toast.error("Failed to load playlists")
      }
    },
    [idsKey]
  )

  const { isLoading: loading } = useFetchEffect(fetchPlaylists, [fetchPlaylists], {
    initialLoading: true,
  })

  const filteredPlaylists = playlists
    .filter((p) => p.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => {
      const aIsMember = memberOf.has(a.id) ? 1 : 0
      const bIsMember = memberOf.has(b.id) ? 1 : 0
      return aIsMember - bIsMember
    })

  const handleAddToPlaylist = async () => {
    if (!selectedPlaylistId) return

    setAdding(true)
    try {
      if (bulkMode) {
        const res = await axios.post(
          apiUrl(`/playlists/${selectedPlaylistId}/media/bulk`),
          { media_details_ids: mediaDetailsIds }
        )
        const { added, already_present: alreadyPresent, invalid } = res.data
        const parts = [`Added ${added}`]
        if (alreadyPresent) parts.push(`${alreadyPresent} already in playlist`)
        if (invalid) parts.push(`${invalid} skipped`)
        toast.success(parts.join(", "))
      } else {
        await axios.post(
          apiUrl(`/playlists/${selectedPlaylistId}/media`),
          { media_details_id: mediaDetailsIds[0] }
        )
        toast.success("Added to playlist")
      }
      // Deliberately absent from handleCreateAndAdd: a playlist created in that
      // same handler can never be the one already playing.
      syncPlaylistQueue(selectedPlaylistId)
      onOpenChange(false)
    } catch (error: unknown) {
      if (axios.isAxiosError(error) && error.response?.status === 400) {
        toast.error("Already in playlist")
      } else {
        toast.error("Failed to add to playlist")
      }
    } finally {
      setAdding(false)
    }
  }

  const handleCreateAndAdd = async () => {
    if (!newPlaylistName.trim()) {
      toast.error("Please enter a playlist name")
      return
    }

    setAdding(true)
    try {
      const createResponse = await axios.post(
        apiUrl('/playlists'),
        { name: newPlaylistName.trim() }
      )
      const newPlaylist = createResponse.data

      if (bulkMode) {
        const res = await axios.post(
          apiUrl(`/playlists/${newPlaylist.id}/media/bulk`),
          { media_details_ids: mediaDetailsIds }
        )
        toast.success(`Created "${newPlaylistName}" and added ${res.data.added} items`)
      } else {
        await axios.post(
          apiUrl(`/playlists/${newPlaylist.id}/media`),
          { media_details_id: mediaDetailsIds[0] }
        )
        toast.success(`Created "${newPlaylistName}" and added media`)
      }
      onOpenChange(false)
    } catch {
      toast.error("Failed to create playlist")
    } finally {
      setAdding(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-mono">Add to Playlist</DialogTitle>
        <p className="text-sm text-text-muted truncate mt-1" title={bulkMode ? undefined : mediaTitle}>
          {bulkMode
            ? `${mediaDetailsIds.length} items`
            : mediaTitle.length > 50
              ? mediaTitle.slice(0, 50) + "..."
              : mediaTitle}
        </p>
      </DialogHeader>

      {showCreateForm ? (
        <div className="space-y-4">
          <Input
            value={newPlaylistName}
            onChange={(e) => setNewPlaylistName(e.target.value)}
            placeholder="New playlist name"
            className="font-mono"
            autoFocus
          />
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => setShowCreateForm(false)}
              disabled={adding}
            >
              Back
            </Button>
            <Button
              onClick={handleCreateAndAdd}
              disabled={adding || !newPlaylistName.trim()}
            >
              {adding ? "Creating..." : "Create & Add"}
            </Button>
          </DialogFooter>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-text-muted" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search playlists..."
              className="pl-9 font-mono"
            />
          </div>

          <div className="max-h-[300px] overflow-y-auto border border-border rounded-lg">
            {loading ? (
              <div className="p-4 text-center text-text-muted font-mono">
                Loading...
              </div>
            ) : filteredPlaylists.length === 0 ? (
              <div className="p-4 text-center text-text-muted font-mono">
                {search ? "No matching playlists" : "No playlists yet"}
              </div>
            ) : (
              <div className="divide-y divide-border/50">
                {filteredPlaylists.map((playlist) => {
                  const alreadyAdded = memberOf.has(playlist.id)
                  return (
                    <button
                      key={playlist.id}
                      onClick={() => {
                        if (!alreadyAdded) setSelectedPlaylistId(playlist.id)
                      }}
                      className={cn(
                        "w-full px-4 py-3 text-left transition-colors",
                        alreadyAdded
                          ? "opacity-50 cursor-default"
                          : "hover:bg-bg-surface/50",
                        !alreadyAdded && selectedPlaylistId === playlist.id && "bg-matrix/10"
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <p className={cn(
                            "text-sm font-mono",
                            alreadyAdded ? "text-text-muted" : "text-text-primary"
                          )}>
                            {playlist.name}
                          </p>
                          <p className="text-xs text-text-muted">
                            {playlist.media_count} items
                          </p>
                        </div>
                        {alreadyAdded ? (
                          <span className="flex items-center gap-1 text-xs text-matrix">
                            <CheckIcon className="h-4 w-4" />
                            Added
                          </span>
                        ) : selectedPlaylistId === playlist.id ? (
                          <CheckIcon className="h-5 w-5 text-matrix" />
                        ) : null}
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          <Button
            type="button"
            variant="outline"
            className="w-full gap-2"
            onClick={() => setShowCreateForm(true)}
          >
            <PlusIcon className="h-4 w-4" />
            Create New Playlist
          </Button>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={adding}
            >
              Cancel
            </Button>
            <Button
              onClick={handleAddToPlaylist}
              disabled={adding || !selectedPlaylistId || memberOf.has(selectedPlaylistId!)}
            >
              {adding ? "Adding..." : "Add to Playlist"}
            </Button>
          </DialogFooter>
        </div>
      )}
    </>
  )
}

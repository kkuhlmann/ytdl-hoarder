"use client"

import { useState } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl } from "@/app/lib/api"

type CreatePlaylistDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onPlaylistCreated: () => void
  /** Dialog copy, for surfaces that create a playlist from existing media. */
  title?: string
  submitLabel?: string
  /** Prefills the name each time the dialog opens. */
  defaultName?: string
  /**
   * Runs after the playlist exists, with the new row, so a caller can populate
   * it before anything reports success. Throwing leaves the dialog open with an
   * error rather than claiming success for a playlist that ended up empty; the
   * caller owns the success message in that case.
   */
  onCreated?: (playlist: { id: number; name: string }) => Promise<void>
}

export function CreatePlaylistDialog({ open, onOpenChange, ...form }: CreatePlaylistDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts DialogContent on close, so the form below is seeded from
          `defaultName` on every open with no effect to reset it. */}
      <DialogContent className="sm:max-w-md">
        <CreatePlaylistForm onOpenChange={onOpenChange} {...form} />
      </DialogContent>
    </Dialog>
  )
}

function CreatePlaylistForm({
  onOpenChange,
  onPlaylistCreated,
  title = "Create Playlist",
  submitLabel = "Create",
  defaultName,
  onCreated,
}: Omit<CreatePlaylistDialogProps, "open">) {
  const [name, setName] = useState(defaultName ?? "")
  const [description, setDescription] = useState("")
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!name.trim()) {
      toast.error("Please enter a playlist name")
      return
    }

    setLoading(true)
    try {
      const response = await axios.post(apiUrl('/playlists'), {
        name: name.trim(),
        description: description.trim() || null,
      })
      if (onCreated) {
        await onCreated(response.data)
      } else {
        toast.success("Playlist created")
      }
      setName("")
      setDescription("")
      onOpenChange(false)
      onPlaylistCreated()
    } catch {
      toast.error(
        onCreated ? "Failed to save playlist" : "Failed to create playlist",
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-mono">{title}</DialogTitle>
      </DialogHeader>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name" className="font-mono text-sm">
            Name
          </Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="My Playlist"
            className="font-mono"
            autoFocus
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description" className="font-mono text-sm">
            Description (optional)
          </Label>
          <Input
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="A collection of..."
            className="font-mono"
          />
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={loading || !name.trim()}>
            {loading ? "Saving..." : submitLabel}
          </Button>
        </DialogFooter>
      </form>
    </>
  )
}

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
import { TagInput } from "./TagInput"
import { TagInfo } from "@/app/types/DownloadsOptions"

const EMPTY_TAGS: TagInfo[] = []

type TagsDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  mediaTitle: string
  tags: TagInfo[]
  allTags: TagInfo[]
  onSave: (tagNames: string[]) => void
  bulkMode?: boolean
  bulkCount?: number
}

export function TagsDialog({ open, onOpenChange, ...body }: TagsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Radix unmounts DialogContent on close, so the draft inside TagsDialogBody
          is seeded fresh from `tags` on every open with no effect to reset it. */}
      <DialogContent className="sm:max-w-md">
        <TagsDialogBody onOpenChange={onOpenChange} {...body} />
      </DialogContent>
    </Dialog>
  )
}

function TagsDialogBody({
  onOpenChange,
  mediaTitle,
  tags,
  allTags,
  onSave,
  bulkMode = false,
  bulkCount = 0,
}: Omit<TagsDialogProps, "open">) {
  const [localTags, setLocalTags] = useState<string[]>(bulkMode ? [] : tags.map((t) => t.name))

  const handleSave = () => {
    onSave(localTags)
    if (!bulkMode) {
      onOpenChange(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle className="font-mono">
          {bulkMode ? `Add Tags to ${bulkCount} Items` : "Tags"}
        </DialogTitle>
        {!bulkMode && (
          <p className="text-sm text-text-muted truncate mt-1" title={mediaTitle}>
            {mediaTitle.length > 50 ? mediaTitle.slice(0, 50) + "..." : mediaTitle}
          </p>
        )}
      </DialogHeader>
      <div className="space-y-4">
        <TagInput
          tags={bulkMode ? EMPTY_TAGS : tags}
          allTags={allTags}
          autoEdit
          onSave={() => {}}
          onChange={setLocalTags}
        />
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave}>Save</Button>
        </DialogFooter>
      </div>
    </>
  )
}

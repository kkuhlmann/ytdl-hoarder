"use client"

import { useState, useRef, useEffect } from "react"
import { XMarkIcon } from "@heroicons/react/20/solid"
import { TagInfo } from "@/app/types/DownloadsOptions"

type TagInputProps = {
  tags: TagInfo[]
  allTags: TagInfo[]
  onSave: (tagNames: string[]) => void
  onChange?: (tagNames: string[]) => void
  autoEdit?: boolean
}

export function TagInput({ tags, allTags, onSave, onChange, autoEdit = false }: TagInputProps) {
  const [editing, setEditing] = useState(autoEdit)
  const [inputValue, setInputValue] = useState("")
  const [localTags, setLocalTags] = useState<string[]>(tags.map((t) => t.name))
  const [showSuggestions, setShowSuggestions] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // No effect syncing localTags from `tags`: the only call site is TagsDialogBody,
  // a child of DialogContent, which Radix unmounts on close — so the draft above
  // is already seeded fresh on every open, and Escape below reverts it. Syncing
  // here actively clobbered unsaved edits, because MediaActionDialogs passes
  // `focusItem.tags || []` and `tags` is optional, minting a fresh array on every
  // parent render for an untagged item.

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
    }
  }, [editing])

  // Close on outside click — only auto-save for inline usage, not dialog usage
  useEffect(() => {
    if (!editing || autoEdit) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setEditing(false)
        setShowSuggestions(false)
        setInputValue("")
        onSave(localTags)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [editing, autoEdit, localTags, onSave])

  const addTag = (name: string) => {
    const normalized = name.trim().toLowerCase()
    if (normalized && !localTags.includes(normalized)) {
      const updated = [...localTags, normalized]
      setLocalTags(updated)
      onChange?.(updated)
    }
    setInputValue("")
  }

  const removeTag = (name: string) => {
    const updated = localTags.filter((t) => t !== name)
    setLocalTags(updated)
    onChange?.(updated)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault()
      if (inputValue.trim()) {
        addTag(inputValue)
      }
    } else if (e.key === "Backspace" && !inputValue && localTags.length > 0) {
      removeTag(localTags[localTags.length - 1])
    } else if (e.key === "Escape") {
      setEditing(false)
      setLocalTags(tags.map((t) => t.name))
      setInputValue("")
    }
  }

  const suggestions = allTags
    .filter(
      (t) =>
        !localTags.includes(t.name) &&
        t.name.includes(inputValue.toLowerCase())
    )
    .slice(0, 8)

  if (!editing) {
    return (
      <div
        className="inline-flex items-center gap-1 flex-wrap cursor-pointer min-h-[20px]"
        onClick={(e) => {
          e.stopPropagation()
          setEditing(true)
        }}
        title="Click to edit tags"
      >
        {tags.length === 0 ? (
          <span className="text-xs text-text-muted/40 font-mono">
            +tag
          </span>
        ) : (
          tags.map((tag) => (
            <span
              key={tag.id}
              className="inline-flex items-center px-1.5 py-0.5 text-xs rounded-full bg-matrix/15 text-matrix font-mono border border-matrix/20"
            >
              {tag.name}
            </span>
          ))
        )}
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-1 flex-wrap p-1 rounded border border-matrix/40 bg-bg-base min-w-[160px]">
        {localTags.map((name) => (
          <span
            key={name}
            className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-matrix/15 text-matrix text-xs font-mono border border-matrix/20"
          >
            {name}
            <button
              onClick={() => removeTag(name)}
              className="hover:text-status-error transition-colors"
            >
              <XMarkIcon className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value)
            setShowSuggestions(true)
          }}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={handleKeyDown}
          placeholder={localTags.length === 0 ? "Add tag..." : ""}
          className="flex-1 min-w-[60px] bg-transparent text-xs font-mono text-text-primary outline-hidden placeholder:text-text-muted/40"
        />
      </div>

      {showSuggestions && inputValue.length > 0 && suggestions.length > 0 && (
        <div className="absolute z-50 mt-1 w-full rounded border border-border bg-bg-terminal shadow-lg max-h-32 overflow-y-auto">
          {suggestions.map((tag) => (
            <button
              key={tag.id}
              onClick={() => {
                addTag(tag.name)
                setShowSuggestions(false)
              }}
              className="w-full text-left px-2 py-1 text-xs font-mono text-text-primary hover:bg-bg-surface transition-colors"
            >
              {tag.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

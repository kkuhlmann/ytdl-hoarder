"use client"

import { useState, useRef, useEffect, useMemo } from "react"
import { useFetchEffect } from "@/app/_hooks/useFetchEffect"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { apiUrl } from "@/app/lib/api"
import axios from "axios"
import { useAdmin } from "@/app/context/AdminContext"
import type { StatsFilter, StatsFilterOptions } from "@/app/types/StatsOptions"

interface StatsFilterComboboxProps {
  value: StatsFilter
  onChange: (filter: StatsFilter) => void
}

export function StatsFilterCombobox({ value, onChange }: StatsFilterComboboxProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)
  const { adminParam } = useAdmin()

  // The cache is keyed on the admin scope's contents, so toggling admin view
  // invalidates it and nothing else does.
  const scope = JSON.stringify(adminParam)
  const [cache, setCache] = useState<{ scope: string; options: StatsFilterOptions } | null>(null)
  const options = cache?.scope === scope ? cache.options : null

  // Fetch options lazily on first open, and again after the admin scope changes.
  // `enabled` is what stops it refetching: once the cache matches the scope,
  // `options` is non-null. That replaces a fetchingScope ref which was also
  // masking this effect from react-hooks/set-state-in-effect.
  const { isLoading: loading } = useFetchEffect(
    (signal) =>
      axios
        .get(apiUrl("/stats/filter-options"), { params: adminParam, signal })
        .then((res) => setCache({ scope, options: res.data }))
        .catch((err) => {
          if (axios.isCancel(err)) return
          console.error("Failed to fetch filter options:", err)
        }),
    [scope, adminParam],
    { enabled: open && options === null }
  )

  // Focus the input after the popover renders. The search reset lives in the
  // open handler below — it belongs to the act of opening.
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  const handleOpenChange = (next: boolean) => {
    if (next) setSearch("")
    setOpen(next)
  }

  const filtered = useMemo(() => {
    if (!options) return { channels: [], playlists: [] }
    const q = search.toLowerCase()
    return {
      channels: options.channels.filter((c) => c.name.toLowerCase().includes(q)),
      playlists: options.playlists.filter((p) => p.name.toLowerCase().includes(q)),
    }
  }, [options, search])

  const hasResults = filtered.channels.length > 0 || filtered.playlists.length > 0

  const triggerLabel = value
    ? value.type === "channel"
      ? value.channel
      : value.playlist_name
    : null

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <div className="flex items-center gap-2">
        <PopoverTrigger asChild>
          <button
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border text-sm font-mono transition-colors ${
              value
                ? "border-matrix/50 bg-matrix/10 text-matrix hover:bg-matrix/20"
                : "border-border bg-bg-surface text-text-muted hover:text-text-secondary hover:bg-bg-elevated"
            }`}
          >
            {value ? (
              <>
                <span className="text-text-muted text-xs">
                  {value.type === "channel" ? "CH" : "PL"}
                </span>
                <span className="max-w-[200px] truncate">{triggerLabel}</span>
              </>
            ) : (
              <>
                <svg
                  className="w-3.5 h-3.5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"
                  />
                </svg>
                Filter
              </>
            )}
          </button>
        </PopoverTrigger>

        {/* Clear button — outside the trigger so it doesn't toggle the popover */}
        {value && (
          <button
            onClick={() => onChange(null)}
            className="inline-flex items-center justify-center w-6 h-6 rounded-md text-text-muted hover:text-matrix hover:bg-matrix/10 transition-colors"
            title="Clear filter"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <PopoverContent align="start" className="w-72 p-0">
        {/* Search input */}
        <div className="p-2 border-b border-border">
          <input
            ref={inputRef}
            type="text"
            placeholder="Search channels or playlists..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full px-2 py-1.5 bg-bg-surface border border-border rounded text-sm font-mono text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-matrix/50"
          />
        </div>

        {/* Options list */}
        <div className="max-h-[300px] overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-6">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-matrix border-t-transparent" />
              <span className="ml-2 text-xs font-mono text-text-muted">Loading...</span>
            </div>
          )}

          {!loading && !hasResults && (
            <div className="py-6 text-center text-xs font-mono text-text-muted">
              {search ? "No matches found" : "No channels or playlists"}
            </div>
          )}

          {!loading && filtered.channels.length > 0 && (
            <div>
              <div className="sticky top-0 z-10 px-3 py-1.5 text-xs font-mono font-semibold text-text-muted bg-bg-terminal border-b border-border/50">
                Channels
              </div>
              {filtered.channels.map((ch) => {
                const isActive = value?.type === "channel" && value.channel === ch.name
                return (
                  <button
                    key={`ch-${ch.name}`}
                    onClick={() => {
                      onChange({ type: "channel", channel: ch.name })
                      setOpen(false)
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm font-mono transition-colors ${
                      isActive
                        ? "bg-matrix/10 text-matrix"
                        : "text-text-primary hover:bg-bg-elevated"
                    }`}
                  >
                    <span className="truncate mr-2">{ch.name}</span>
                    <span className="text-xs text-text-muted shrink-0">{ch.media_count}</span>
                  </button>
                )
              })}
            </div>
          )}

          {!loading && filtered.playlists.length > 0 && (
            <div>
              <div className="sticky top-0 z-10 px-3 py-1.5 text-xs font-mono font-semibold text-text-muted bg-bg-terminal border-b border-border/50">
                Playlists
              </div>
              {filtered.playlists.map((pl) => {
                const isActive = value?.type === "playlist" && value.playlist_id === pl.id
                return (
                  <button
                    key={`pl-${pl.id}`}
                    onClick={() => {
                      onChange({ type: "playlist", playlist_id: pl.id, playlist_name: pl.name })
                      setOpen(false)
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-sm font-mono transition-colors ${
                      isActive
                        ? "bg-matrix/10 text-matrix"
                        : "text-text-primary hover:bg-bg-elevated"
                    }`}
                  >
                    <span className="truncate mr-2">{pl.name}</span>
                    <span className="text-xs text-text-muted shrink-0">{pl.media_count}</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

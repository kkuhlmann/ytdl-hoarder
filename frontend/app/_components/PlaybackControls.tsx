"use client"

import { useState } from "react"
import { PlayIcon, ArrowsRightLeftIcon, EllipsisVerticalIcon } from "@heroicons/react/20/solid"
import { Button } from "@/components/ui/button"
import { Switch } from "@/components/ui/switch"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"
import { cn } from "@/lib/utils"

export type QueueMode = "off" | "ordered" | "shuffled"

type PlaybackControlsProps = {
  onPlayAll: () => void
  onShuffle: () => void
  resume: {
    checked: boolean
    disabled?: boolean
    onChange: (checked: boolean) => void
  }
  /**
   * Only the library owns a queue it can detach, so only it has an on/off state to
   * reflect. Where it's absent the two buttons are plain actions, which is what the
   * playlist and tag-mix surfaces need.
   */
  queueMode?: QueueMode
  disabled?: boolean
  playAllTitle?: string
  shuffleTitle?: string
  className?: string
}

export function PlaybackControls({
  onPlayAll,
  onShuffle,
  resume,
  queueMode,
  disabled = false,
  playAllTitle,
  shuffleTitle,
  className,
}: PlaybackControlsProps) {
  const [optionsOpen, setOptionsOpen] = useState(false)
  const ordered = queueMode === "ordered"
  const shuffled = queueMode === "shuffled"

  return (
    <div className={cn("flex items-center gap-1.5 sm:gap-2", className)}>
      <Button
        variant={queueMode === undefined || ordered ? "matrix" : "outline"}
        size="sm"
        onClick={onPlayAll}
        disabled={disabled}
        {...(queueMode !== undefined && { "aria-pressed": ordered })}
        className="gap-2"
        title={
          playAllTitle ??
          (ordered
            ? "Stop after this track"
            : shuffled
              ? "Play the current queue in order"
              : "Play everything matching the current filter")
        }
      >
        <PlayIcon className="h-4 w-4" />
        <span className="hidden sm:inline">Play All</span>
      </Button>
      <Button
        variant={shuffled ? "matrix" : "outline"}
        size="sm"
        onClick={onShuffle}
        disabled={disabled}
        {...(queueMode !== undefined && { "aria-pressed": shuffled })}
        className="gap-2"
        title={
          shuffleTitle ??
          (shuffled
            ? "Stop after this track"
            : ordered
              ? "Shuffle the current queue"
              : "Shuffle everything matching the current filter")
        }
      >
        <ArrowsRightLeftIcon className="h-4 w-4" />
        <span className="hidden sm:inline">Shuffle</span>
      </Button>
      <Popover open={optionsOpen} onOpenChange={setOptionsOpen}>
        <PopoverTrigger asChild>
          <button
            className="inline-flex items-center px-1 py-1 rounded-md text-xs font-mono transition-colors bg-bg-surface text-text-muted hover:text-text-secondary border border-border"
            title="Playback options"
            aria-label="Playback options"
          >
            <EllipsisVerticalIcon className="h-3.5 w-3.5" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto p-2">
          <label
            className={cn(
              "flex items-center gap-2 select-none whitespace-nowrap",
              resume.disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
            )}
            title={
              resume.disabled
                ? "Play All and Shuffle always start each track from the beginning"
                : "Resume each track from where you left off, and show how far through each one you are"
            }
          >
            <Switch
              checked={resume.checked}
              onCheckedChange={resume.onChange}
              disabled={resume.disabled}
            />
            <span className="font-mono text-xs text-text-secondary">Resume</span>
          </label>
        </PopoverContent>
      </Popover>
    </div>
  )
}

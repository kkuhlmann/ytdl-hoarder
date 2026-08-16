"use client"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { SettingMeta, OptionMeta } from "@/app/types/Settings"
import { ArrowPathIcon, ChevronUpIcon, ChevronDownIcon } from "@heroicons/react/24/outline"
import { cn } from "@/lib/utils"

type SettingFieldProps = {
  meta: SettingMeta
  value: number | string[] | boolean
  onChange: (value: number | string[] | boolean) => void
  onReset: () => void
  isModified: boolean
  isResetting: boolean
}

export function SettingField({
  meta,
  value,
  onChange,
  onReset,
  isModified,
  isResetting,
}: SettingFieldProps) {
  if (meta.type === "number") {
    return (
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 py-3 border-b border-border/50 last:border-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{meta.label}</span>
            {isModified && (
              <Badge variant="warning" className="text-xs">
                Modified
              </Badge>
            )}
          </div>
          <p className="text-xs text-text-muted mt-1">{meta.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            value={value as number}
            onChange={(e) => onChange(parseInt(e.target.value) || 0)}
            min={meta.min}
            max={meta.max}
            className="w-24 font-mono text-right"
          />
          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            disabled={isResetting}
            className="shrink-0"
            title="Reset to default"
          >
            <ArrowPathIcon className={cn("h-4 w-4", isResetting && "animate-spin")} />
          </Button>
        </div>
      </div>
    )
  }

  if (meta.type === "boolean") {
    return (
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 py-3 border-b border-border/50 last:border-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium">{meta.label}</span>
            {isModified && (
              <Badge variant="warning" className="text-xs">
                Modified
              </Badge>
            )}
          </div>
          <p className="text-xs text-text-muted mt-1">{meta.description}</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <Checkbox
              checked={value as boolean}
              onCheckedChange={(checked) => onChange(checked === true)}
            />
            <span className="text-sm font-mono">{value ? "On" : "Off"}</span>
          </label>
          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            disabled={isResetting}
            className="shrink-0"
            title="Reset to default"
          >
            <ArrowPathIcon className={cn("h-4 w-4", isResetting && "animate-spin")} />
          </Button>
        </div>
      </div>
    )
  }

  // List type (player_client)
  const selectedValues = value as string[]
  const options: OptionMeta[] = meta.options || []

  const optionMap = new Map(options.map((opt) => [opt.value, opt]))

  const toggleOption = (optionValue: string) => {
    if (selectedValues.includes(optionValue)) {
      // Remove option (but keep at least one)
      if (selectedValues.length > 1) {
        onChange(selectedValues.filter((v) => v !== optionValue))
      }
    } else {
      onChange([...selectedValues, optionValue])
    }
  }

  const moveUp = (index: number) => {
    if (index <= 0) return
    const newOrder = [...selectedValues]
    ;[newOrder[index - 1], newOrder[index]] = [newOrder[index], newOrder[index - 1]]
    onChange(newOrder)
  }

  const moveDown = (index: number) => {
    if (index >= selectedValues.length - 1) return
    const newOrder = [...selectedValues]
    ;[newOrder[index], newOrder[index + 1]] = [newOrder[index + 1], newOrder[index]]
    onChange(newOrder)
  }

  return (
    <div className="flex flex-col gap-2 py-3 border-b border-border/50 last:border-0">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm font-medium">{meta.label}</span>
          {isModified && (
            <Badge variant="warning" className="text-xs">
              Modified
            </Badge>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onReset}
          disabled={isResetting}
          title="Reset to default"
        >
          <ArrowPathIcon className={cn("h-4 w-4", isResetting && "animate-spin")} />
        </Button>
      </div>
      <p className="text-xs text-text-muted">{meta.description}</p>
      <div className="flex flex-wrap gap-2 mt-1">
        {options.map((option) => (
          <label
            key={option.value}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-mono transition-all cursor-pointer",
              selectedValues.includes(option.value)
                ? "bg-matrix/10 border border-matrix/30 text-matrix"
                : "bg-bg-surface border border-border text-text-secondary hover:border-border-hover"
            )}
            title={option.description}
          >
            <Checkbox
              checked={selectedValues.includes(option.value)}
              onCheckedChange={() => toggleOption(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
      {selectedValues.length > 1 && (
        <div className="mt-3 pt-3 border-t border-border/30">
          <span className="text-xs text-text-muted mb-2 block">
            Priority order (first = highest priority)
          </span>
          <div className="flex flex-col gap-1">
            {selectedValues.map((optionValue, index) => {
              const optMeta = optionMap.get(optionValue)
              return (
                <div
                  key={optionValue}
                  className="flex items-center gap-2 px-2 py-1 bg-bg-surface rounded border border-border/50"
                >
                  <div className="flex-1 min-w-0">
                    <span className="text-sm font-mono">
                      {index + 1}. {optMeta?.label || optionValue}
                    </span>
                    {optMeta?.description && (
                      <span className="text-xs text-text-muted ml-2">
                        — {optMeta.description}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => moveUp(index)}
                    disabled={index === 0}
                    className={cn(
                      "p-1 rounded hover:bg-bg-hover transition-colors",
                      index === 0 && "opacity-30 cursor-not-allowed"
                    )}
                    title="Move up"
                  >
                    <ChevronUpIcon className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => moveDown(index)}
                    disabled={index === selectedValues.length - 1}
                    className={cn(
                      "p-1 rounded hover:bg-bg-hover transition-colors",
                      index === selectedValues.length - 1 && "opacity-30 cursor-not-allowed"
                    )}
                    title="Move down"
                  >
                    <ChevronDownIcon className="h-4 w-4" />
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

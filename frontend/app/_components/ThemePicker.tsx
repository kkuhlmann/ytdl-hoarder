"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl, errorMessage } from "@/app/lib/api"
import { useAuth } from "@/app/context/AuthContext"

const COLOR_STORAGE_KEY = "geo-theme-colors"

const DEFAULTS = {
  primary: "#ff1493",
  secondary: "#ffff00",
  accent: "#00bfff",
}

type ThemeColors = typeof DEFAULTS

// --- CSS preset backgrounds (all use --geo-primary/secondary/accent) ---

const GEO_BACKGROUNDS: Record<
  string,
  { label: string; pattern: string; size: string }
> = {
  polkadots: {
    label: "Polka",
    pattern:
      "radial-gradient(circle at 10px 10px, var(--geo-primary) 3px, transparent 3.5px), radial-gradient(circle at 30px 30px, var(--geo-accent) 3px, transparent 3.5px), radial-gradient(circle at 20px 20px, var(--geo-secondary) 2px, transparent 2.5px)",
    size: "40px 40px",
  },
  starfield: {
    label: "Stars",
    pattern:
      "radial-gradient(1px 1px at 5px 5px, var(--geo-accent), transparent), radial-gradient(1px 1px at 25px 18px, var(--geo-secondary), transparent), radial-gradient(2px 2px at 40px 8px, var(--geo-primary), transparent), radial-gradient(1px 1px at 12px 32px, var(--geo-accent), transparent), radial-gradient(1px 1px at 35px 38px, var(--geo-secondary), transparent), radial-gradient(2px 2px at 48px 28px, var(--geo-primary), transparent)",
    size: "50px 50px",
  },
  stripes: {
    label: "Stripes",
    pattern:
      "repeating-linear-gradient(45deg, transparent, transparent 10px, color-mix(in srgb, var(--geo-primary) 25%, transparent) 10px, color-mix(in srgb, var(--geo-primary) 25%, transparent) 12px, transparent 12px, transparent 22px, color-mix(in srgb, var(--geo-accent) 20%, transparent) 22px, color-mix(in srgb, var(--geo-accent) 20%, transparent) 24px)",
    size: "auto",
  },
  checkerboard: {
    label: "Check",
    pattern:
      "conic-gradient(color-mix(in srgb, var(--geo-primary) 18%, transparent) 90deg, transparent 90deg 180deg, color-mix(in srgb, var(--geo-primary) 18%, transparent) 180deg 270deg, transparent 270deg)",
    size: "40px 40px",
  },
}

function applyColors(colors: ThemeColors) {
  const root = document.documentElement
  root.style.setProperty("--geo-primary", colors.primary)
  root.style.setProperty("--geo-secondary", colors.secondary)
  root.style.setProperty("--geo-accent", colors.accent)
}

function loadColors(): ThemeColors {
  if (typeof window === "undefined") return DEFAULTS
  try {
    const stored = localStorage.getItem(COLOR_STORAGE_KEY)
    if (stored) return { ...DEFAULTS, ...JSON.parse(stored) }
  } catch {
    // ignore
  }
  return DEFAULTS
}

function saveColors(colors: ThemeColors) {
  localStorage.setItem(COLOR_STORAGE_KEY, JSON.stringify(colors))
}

function applyPresetBackground(presetKey: string) {
  const preset = GEO_BACKGROUNDS[presetKey]
  if (!preset) return
  const root = document.documentElement
  root.style.setProperty("--bg-pattern", preset.pattern)
  root.style.setProperty("--bg-pattern-size", preset.size)
}

// One endpoint serves whatever the current upload is, so a fresh upload would
// otherwise come back from cache. The buster is minted here rather than in
// render — an impure call during render is a new URL, and a new fetch, on every
// re-render — and the same URL is then shared by the page background and the
// panel's preview thumbnail.
function customBackgroundUrl() {
  return `${apiUrl("/auth/me/geo-background")}?t=${Date.now()}`
}

function applyCustomBackground(url: string) {
  const root = document.documentElement
  root.style.setProperty("--bg-pattern", `url(${url})`)
  root.style.setProperty("--bg-pattern-size", "auto")
}

function clearBackgroundOverride() {
  const root = document.documentElement
  root.style.removeProperty("--bg-pattern")
  root.style.removeProperty("--bg-pattern-size")
}

export function ThemePicker() {
  const { user, refreshAuth } = useAuth()
  const [colors, setColors] = useState<ThemeColors>(DEFAULTS)
  const [open, setOpen] = useState(false)
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const [hasCustom, setHasCustom] = useState(false)
  const [customBgUrl, setCustomBgUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const saved = loadColors()
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seeds colours from localStorage plus background state the three async handlers write optimistically; each leaves refreshAuth() un-awaited, so deriving from `user` would stall the upload UI
    setColors(saved)
    applyColors(saved)

    const preset = user?.geo_background_preset ?? null
    setActivePreset(preset)
    setHasCustom(user?.has_geo_background ?? false)

    if (preset === "custom" && user?.has_geo_background) {
      const url = customBackgroundUrl()
      setCustomBgUrl(url)
      applyCustomBackground(url)
    } else if (preset && preset !== "custom" && GEO_BACKGROUNDS[preset]) {
      applyPresetBackground(preset)
    }
    // null = default polka dots from CSS, no override needed

    return () => clearBackgroundOverride()
  }, [user?.geo_background_preset, user?.has_geo_background])

  const handleColorChange = useCallback(
    (key: keyof ThemeColors, value: string) => {
      const next = { ...colors, [key]: value }
      setColors(next)
      applyColors(next)
      saveColors(next)
    },
    [colors]
  )

  const handleColorReset = useCallback(() => {
    setColors(DEFAULTS)
    applyColors(DEFAULTS)
    saveColors(DEFAULTS)
  }, [])

  const handlePresetSelect = useCallback(
    async (presetKey: string) => {
      // If selecting the default (polkadots), clear the override
      const presetValue = presetKey === "polkadots" ? null : presetKey
      try {
        await axios.put(apiUrl("/auth/me/geo-background-preset"), {
          preset: presetValue,
        })
        setActivePreset(presetValue)
        if (presetValue && GEO_BACKGROUNDS[presetKey]) {
          applyPresetBackground(presetKey)
        } else {
          clearBackgroundOverride()
        }
        refreshAuth()
      } catch (err) {
        toast.error(errorMessage(err, "Failed to set preset"))
      }
    },
    [refreshAuth]
  )

  const handleCustomUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      setUploading(true)
      try {
        const formData = new FormData()
        formData.append("file", file)
        await axios.post(apiUrl("/auth/me/geo-background"), formData, {
          headers: { "Content-Type": "multipart/form-data" },
        })
        setActivePreset("custom")
        setHasCustom(true)
        const url = customBackgroundUrl()
        setCustomBgUrl(url)
        applyCustomBackground(url)
        refreshAuth()
        toast.success("Background uploaded!")
      } catch (err) {
        toast.error(errorMessage(err, "Failed to upload background"))
      } finally {
        setUploading(false)
        if (fileInputRef.current) fileInputRef.current.value = ""
      }
    },
    [refreshAuth]
  )

  const handleRemoveCustom = useCallback(async () => {
    try {
      await axios.delete(apiUrl("/auth/me/geo-background"))
      setActivePreset(null)
      setHasCustom(false)
      setCustomBgUrl(null)
      clearBackgroundOverride()
      refreshAuth()
      toast.success("Background removed")
    } catch (err) {
      toast.error(errorMessage(err, "Failed to remove background"))
    }
  }, [refreshAuth])

  // Resolve which key is "active" for highlighting
  const effectivePreset = activePreset ?? "polkadots"

  const btnBase =
    "px-1.5 py-1 text-[10px] font-sans font-bold border-2 [border-style:outset] border-[#C0C0C0] bg-[#C0C0C0] text-black active:[border-style:inset]"
  const btnActive =
    "px-1.5 py-1 text-[10px] font-sans font-bold border-2 [border-style:inset] border-(--geo-primary) bg-(--geo-primary) text-white"

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-sans font-bold border-2 [border-style:outset] border-[#C0C0C0] bg-[#C0C0C0] text-black active:[border-style:inset] hover:bg-(--geo-secondary)"
        title="Customize theme colors"
      >
        <span
          className="inline-block w-3 h-3 border border-black"
          style={{ background: colors.primary }}
        />
        <span
          className="inline-block w-3 h-3 border border-black"
          style={{ background: colors.secondary }}
        />
        <span
          className="inline-block w-3 h-3 border border-black"
          style={{ background: colors.accent }}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 z-50 bg-white border-[3px] border-(--geo-primary) shadow-[6px_6px_0_#000000] p-4 min-w-[220px]">
          <p className="font-sans font-bold text-sm text-(--geo-primary) mb-3 [text-shadow:1px_1px_0_var(--geo-accent)]">
            ★ Theme Colors ★
          </p>

          <div className="space-y-3">
            <label className="flex items-center gap-2 text-xs font-sans font-bold text-black">
              Primary:
              <input
                type="color"
                value={colors.primary}
                onChange={(e) => handleColorChange("primary", e.target.value)}
                className="w-8 h-8 border-2 border-black cursor-pointer p-0"
              />
              <span className="font-mono text-[10px] text-[#808080]">
                {colors.primary}
              </span>
            </label>

            <label className="flex items-center gap-2 text-xs font-sans font-bold text-black">
              Secondary:
              <input
                type="color"
                value={colors.secondary}
                onChange={(e) =>
                  handleColorChange("secondary", e.target.value)
                }
                className="w-8 h-8 border-2 border-black cursor-pointer p-0"
              />
              <span className="font-mono text-[10px] text-[#808080]">
                {colors.secondary}
              </span>
            </label>

            <label className="flex items-center gap-2 text-xs font-sans font-bold text-black">
              Accent:
              <input
                type="color"
                value={colors.accent}
                onChange={(e) => handleColorChange("accent", e.target.value)}
                className="w-8 h-8 border-2 border-black cursor-pointer p-0"
              />
              <span className="font-mono text-[10px] text-[#808080]">
                {colors.accent}
              </span>
            </label>
          </div>

          <div className="mt-3 pt-2 border-t-2 border-dashed border-(--geo-primary)">
            <button
              onClick={handleColorReset}
              className="w-full px-2 py-1 text-xs font-sans font-bold border-2 [border-style:outset] border-[#C0C0C0] bg-[#C0C0C0] text-black active:[border-style:inset]"
            >
              Reset Colors
            </button>
          </div>

          {/* Background section */}
          <div className="mt-3 pt-2 border-t-2 border-dashed border-(--geo-primary)">
            <p className="font-sans font-bold text-sm text-(--geo-primary) mb-2 [text-shadow:1px_1px_0_var(--geo-accent)]">
              ★ Background ★
            </p>

            {/* Preset swatches */}
            <div className="flex flex-wrap gap-1.5 mb-2">
              {Object.entries(GEO_BACKGROUNDS).map(([key, bg]) => (
                <button
                  key={key}
                  onClick={() => handlePresetSelect(key)}
                  className={
                    effectivePreset === key && activePreset !== "custom"
                      ? btnActive
                      : btnBase
                  }
                  title={bg.label}
                >
                  <div className="flex items-center gap-1">
                    <div
                      className="w-4 h-4 border border-black"
                      style={{
                        backgroundImage: bg.pattern,
                        backgroundSize: bg.size,
                        backgroundColor: "#ffffcc",
                      }}
                    />
                    <span>{bg.label}</span>
                  </div>
                </button>
              ))}
            </div>

            {/* Custom upload */}
            <div className="flex gap-1.5">
              <label
                className={`cursor-pointer ${activePreset === "custom" ? btnActive : btnBase} ${uploading ? "opacity-50 pointer-events-none" : ""}`}
              >
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/png,image/gif,image/jpeg,image/webp"
                  onChange={handleCustomUpload}
                  className="sr-only"
                />
                {uploading ? "..." : "Custom \u2191"}
              </label>
              {(activePreset === "custom" || activePreset) && (
                <button onClick={handleRemoveCustom} className={btnBase}>
                  Reset
                </button>
              )}
            </div>

            {activePreset === "custom" && hasCustom && customBgUrl && (
              <div className="mt-2">
                <div
                  className="w-full h-10 border-2 border-black"
                  style={{
                    backgroundImage: `url(${customBgUrl})`,
                    backgroundSize: "auto",
                    backgroundRepeat: "repeat",
                  }}
                />
              </div>
            )}
          </div>

          {/* Close button */}
          <div className="mt-3 pt-2 border-t-2 border-dashed border-(--geo-primary)">
            <button
              onClick={() => setOpen(false)}
              className="w-full px-2 py-1 text-xs font-sans font-bold text-white border-2 [border-style:outset] border-(--geo-primary) bg-(--geo-primary) active:[border-style:inset]"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

"use client"

import { useState, useEffect, useRef, useMemo } from "react"
import { cn } from "@/lib/utils"
import { useDocumentAttribute } from "@/app/_hooks/useDocumentTheme"
import { useStoredValue, writeStored } from "@/app/_hooks/useStoredValue"

type Theme = { id: string; label: string }

const CATEGORIES: { name: string; themes: Theme[] }[] = [
  {
    name: "Terminal",
    themes: [
      { id: "matrix", label: "Matrix" },
      { id: "amber", label: "Amber CRT" },
      { id: "apple2", label: "Apple II" },
      { id: "ibm3270", label: "IBM 3270" },
      { id: "pipboy", label: "Pip-Boy" },
      { id: "tron", label: "Tron" },
    ],
  },
  {
    name: "Windows",
    themes: [
      { id: "win31", label: "Windows 3.1" },
      { id: "win98", label: "Win98" },
      { id: "win2k", label: "Windows 2000" },
      { id: "winme", label: "Windows ME" },
      { id: "xp", label: "XP Luna" },
      { id: "vista", label: "Vista" },
      { id: "win7", label: "Windows 7" },
      { id: "win10", label: "Windows 10" },
      { id: "win11", label: "Windows 11" },
      { id: "mspaint", label: "MS Paint" },
    ],
  },
  {
    name: "Mac",
    themes: [
      { id: "macclassic", label: "Mac Classic" },
      { id: "macos9", label: "Mac OS 9" },
      { id: "aqua", label: "Aqua (OS X)" },
      { id: "tiger", label: "OS X Tiger" },
      { id: "leopard", label: "OS X Leopard" },
      { id: "yosemite", label: "Yosemite" },
      { id: "macosdark", label: "macOS Dark" },
      { id: "macoslight", label: "macOS Light" },
    ],
  },
  {
    name: "Unix / Other OS",
    themes: [
      { id: "nextstep", label: "NeXTSTEP" },
      { id: "beos", label: "BeOS" },
      { id: "cde", label: "CDE/Solaris" },
      { id: "irix", label: "SGI IRIX" },
      { id: "plan9", label: "Plan 9" },
      { id: "ubuntu", label: "Ubuntu" },
    ],
  },
  {
    name: "Code Editors",
    themes: [
      { id: "dracula", label: "Dracula" },
      { id: "gruvbox", label: "Gruvbox" },
      { id: "nord", label: "Nord" },
      { id: "monokai", label: "Monokai" },
      { id: "catppuccin", label: "Catppuccin" },
      { id: "onedark", label: "One Dark" },
      { id: "solarized-dark", label: "Solarized Dark" },
      { id: "solarized-light", label: "Solarized Light" },
      { id: "nightowl", label: "Night Owl" },
      { id: "borland", label: "Borland Turbo" },
      { id: "bios", label: "DOS BIOS" },
    ],
  },
  {
    name: "Early Web",
    themes: [
      { id: "geocities", label: "GeoCities" },
      { id: "angelfire", label: "Angelfire" },
      { id: "aol", label: "AOL" },
      { id: "neopets", label: "Neopets" },
      { id: "craigslist", label: "Craigslist" },
      { id: "newgrounds", label: "Newgrounds" },
      { id: "construction", label: "Under Construction" },
      { id: "flash", label: "Flash Intro" },
      { id: "hotdog", label: "Hot Dog Stand" },
      { id: "livejournal", label: "LiveJournal" },
      { id: "web2", label: "Web 2.0" },
      { id: "aero", label: "Frutiger Aero" },
      { id: "y2k", label: "Y2K" },
      { id: "google", label: "Early Google" },
      { id: "wikipedia", label: "Wikipedia" },
      { id: "reddit", label: "Old Reddit" },
      { id: "hackernews", label: "Hacker News" },
    ],
  },
  {
    name: "Apps & Chat",
    themes: [
      { id: "winamp", label: "Winamp" },
      { id: "aim", label: "AIM" },
      { id: "irc", label: "IRC/mIRC" },
      { id: "napster", label: "Napster" },
      { id: "limewire", label: "Limewire" },
      { id: "kazaa", label: "Kazaa" },
      { id: "spotify", label: "Spotify" },
      { id: "discord", label: "Discord" },
      { id: "bonzi", label: "Bonzi Buddy" },
      { id: "myspace", label: "Myspace" },
    ],
  },
  {
    name: "Gaming",
    themes: [
      { id: "gameboy", label: "Game Boy" },
      { id: "virtualboy", label: "Virtual Boy" },
      { id: "atari", label: "Atari 2600" },
      { id: "spectrum", label: "ZX Spectrum" },
      { id: "cyberpunk", label: "Cyberpunk" },
      { id: "doom", label: "Doom" },
      { id: "minecraft", label: "Minecraft" },
      { id: "oregon", label: "Oregon Trail" },
    ],
  },
  {
    name: "Aesthetic",
    themes: [
      { id: "vaporwave", label: "Vaporwave" },
      { id: "synthwave", label: "Synthwave" },
      { id: "outrun", label: "Outrun" },
      { id: "miami", label: "Miami Vice" },
      { id: "rave", label: "Acid Rave" },
      { id: "barbie", label: "Barbie" },
      { id: "lisafrank", label: "Lisa Frank" },
      { id: "teletext", label: "Teletext" },
    ],
  },
  {
    name: "Reading",
    themes: [
      { id: "sepia", label: "Sepia" },
      { id: "newspaper", label: "Newspaper" },
      { id: "blueprint", label: "Blueprint" },
      { id: "highcontrast", label: "High Contrast" },
      { id: "sunset", label: "Sunset" },
      { id: "ocean", label: "Ocean" },
      { id: "forest", label: "Forest" },
      { id: "lavender", label: "Lavender" },
    ],
  },
]

const ALL_THEMES = CATEGORIES.flatMap((c) => c.themes)

type ThemeId = string

function getStoredTheme(): ThemeId {
  if (typeof window === "undefined") return "matrix"
  return localStorage.getItem("theme") || "matrix"
}

function applyTheme(theme: ThemeId) {
  document.documentElement.setAttribute("data-theme", theme)
  localStorage.setItem("theme", theme)
}

type ThumbMode = "off" | "tint" | "wire"

const THUMB_MODES: { id: ThumbMode; label: string }[] = [
  { id: "off", label: "Off" },
  { id: "tint", label: "Tint" },
  { id: "wire", label: "Wire" },
]

function getStoredThumbMode(): ThumbMode {
  if (typeof window === "undefined") return "off"
  const v = localStorage.getItem("thumbnailTint")
  if (v === "tint" || v === "wire") return v
  if (v === "on") return "tint" // handle deprecated boolean value format
  return "off"
}

function applyThumbMode(mode: ThumbMode) {
  document.documentElement.setAttribute("data-thumbnail-tint", mode)
  localStorage.setItem("thumbnailTint", mode)
}

const MAX_FAVORITES = 5
const VALID_IDS = new Set(ALL_THEMES.map((t) => t.id))

// Snapshot and parse are split so useStoredValue compares a primitive: returning
// a fresh array from a useSyncExternalStore snapshot re-renders forever.
function readStoredFavorites(): string {
  return localStorage.getItem("favoriteThemes") || "[]"
}

function parseFavorites(raw: string): ThemeId[] {
  try {
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // keep order, drop unknown/removed theme ids, cap at MAX_FAVORITES
    return parsed
      .filter((id) => typeof id === "string" && VALID_IDS.has(id))
      .slice(0, MAX_FAVORITES)
  } catch {
    return []
  }
}

function saveFavorites(ids: ThemeId[]) {
  writeStored("favoriteThemes", JSON.stringify(ids))
}

export function ThemeSwitcher() {
  // applyTheme/applyThumbMode write the <html> attribute as well as localStorage,
  // so the attribute is the live source of truth for both — read it rather than
  // mirroring it into state. The raw favourites string is read the same way and
  // parsed here, so the snapshot stays a primitive and the array identity is
  // stable across renders.
  const current = useDocumentAttribute<ThemeId>("data-theme", "matrix")
  const thumbMode = useDocumentAttribute<ThumbMode>("data-thumbnail-tint", "off")
  const favoritesRaw = useStoredValue(readStoredFavorites, "[]")
  const favorites = useMemo(() => parseFavorites(favoritesRaw), [favoritesRaw])

  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const [rawActiveIndex, setActiveIndex] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const itemRefs = useRef<(HTMLDivElement | null)[]>([])

  // Apply the stored preferences on mount. Pure DOM writes — the values above
  // come back through the observers.
  useEffect(() => {
    applyTheme(getStoredTheme())
    applyThumbMode(getStoredThumbMode())
  }, [])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  // Focus the input once the dropdown has rendered. The search reset lives in
  // openDropdown — it belongs to the act of opening, not to a render pass.
  useEffect(() => {
    if (open) {
      setTimeout(() => searchRef.current?.focus(), 0)
    }
  }, [open])

  const previewTheme = (theme: ThemeId) => {
    applyTheme(theme)
  }

  const handleSelect = (theme: ThemeId, flatIndex: number) => {
    previewTheme(theme)
    setActiveIndex(flatIndex)
    // Keep the search input focused so arrow keys keep navigating themes.
    searchRef.current?.focus()
  }

  const handleSelectThumbMode = (mode: ThumbMode) => {
    applyThumbMode(mode)
  }

  const toggleFavorite = (id: ThemeId) => {
    if (favorites.includes(id)) {
      saveFavorites(favorites.filter((f) => f !== id))
    } else if (favorites.length < MAX_FAVORITES) {
      saveFavorites([...favorites, id])
    }
    // else: at cap — block until one is freed
  }

  const filtered = useMemo(() => {
    if (!search.trim()) return CATEGORIES
    const q = search.toLowerCase()
    return CATEGORIES.map((cat) => ({
      ...cat,
      themes: cat.themes.filter(
        (t) =>
          t.label.toLowerCase().includes(q) ||
          t.id.toLowerCase().includes(q) ||
          cat.name.toLowerCase().includes(q)
      ),
    })).filter((cat) => cat.themes.length > 0)
  }, [search])

  // Favorites group (pinned) + the regular categories, all honoring the search filter.
  const displayCategories = useMemo(() => {
    const q = search.trim().toLowerCase()
    const favThemes = favorites
      .map((id) => ALL_THEMES.find((t) => t.id === id))
      .filter((t): t is Theme => Boolean(t))
    const favFiltered = q
      ? favThemes.filter(
          (t) =>
            t.label.toLowerCase().includes(q) ||
            t.id.toLowerCase().includes(q) ||
            "favorites".includes(q)
        )
      : favThemes

    const cats: { name: string; themes: Theme[] }[] = []
    if (favFiltered.length > 0) cats.push({ name: "Favorites", themes: favFiltered })
    cats.push(...filtered)
    return cats
  }, [favorites, search, filtered])

  // Flattened, in-render-order list of theme ids that drives arrow-key navigation.
  const flatThemes = useMemo(
    () => displayCategories.flatMap((cat) => cat.themes.map((t) => t.id)),
    [displayCategories]
  )

  // Keep the keyboard cursor in range when the list shrinks (e.g. while filtering).
  // Clamped at read so a shrinking list doesn't need an effect to correct it.
  const activeIndex = Math.min(rawActiveIndex, Math.max(0, flatThemes.length - 1))

  // Starting flat index of each category, so each rendered row can derive its flat index.
  const catOffsets = useMemo(() => {
    const offs: number[] = []
    let acc = 0
    for (const cat of displayCategories) {
      offs.push(acc)
      acc += cat.themes.length
    }
    return offs
  }, [displayCategories])

  useEffect(() => {
    if (!open) return
    itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" })
  }, [activeIndex, open])

  const openDropdown = () => {
    setSearch("")
    // Position the cursor on the current theme within the unfiltered display list
    // (Favorites first, then every theme in category order).
    const favIdx = favorites.indexOf(current)
    if (favIdx >= 0) {
      setActiveIndex(favIdx)
    } else {
      const allIdx = ALL_THEMES.findIndex((t) => t.id === current)
      setActiveIndex(allIdx >= 0 ? favorites.length + allIdx : 0)
    }
    setOpen(true)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const n = flatThemes.length
    if (n === 0) return
    if (e.key === "ArrowDown") {
      e.preventDefault()
      const i = Math.min(activeIndex + 1, n - 1)
      setActiveIndex(i)
      previewTheme(flatThemes[i])
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      const i = Math.max(activeIndex - 1, 0)
      setActiveIndex(i)
      previewTheme(flatThemes[i])
    } else if (e.key === "Home") {
      e.preventDefault()
      setActiveIndex(0)
      previewTheme(flatThemes[0])
    } else if (e.key === "End") {
      e.preventDefault()
      setActiveIndex(n - 1)
      previewTheme(flatThemes[n - 1])
    } else if (e.key === "Enter") {
      e.preventDefault()
      previewTheme(flatThemes[activeIndex])
      setOpen(false)
    } else if (e.key === "Escape") {
      e.preventDefault()
      setOpen(false)
    }
  }

  const currentTheme = ALL_THEMES.find((t) => t.id === current)
  const atCap = favorites.length >= MAX_FAVORITES

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => (open ? setOpen(false) : openDropdown())}
        className={cn(
          "flex items-center gap-1.5 px-2 py-1 text-xs font-sans rounded transition-colors",
          "text-text-muted hover:text-text-secondary border border-transparent hover:border-border"
        )}
        title={`Theme: ${currentTheme?.label ?? current}`}
      >
        <span className="hidden lg:inline">{currentTheme?.label ?? current}</span>
        <svg className="w-3 h-3" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M3 5l3 3 3-3" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 w-[220px] max-h-[420px] flex flex-col rounded-md border border-border bg-bg-terminal shadow-lg">
          <div className="p-1.5 border-b border-border">
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setActiveIndex(0)
              }}
              onKeyDown={handleKeyDown}
              placeholder="Search themes..."
              className="w-full px-2 py-1 text-xs font-sans bg-bg-surface text-text-primary border border-border rounded placeholder:text-text-muted focus:outline-hidden focus:border-matrix"
            />
          </div>
          <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-border text-xs font-sans text-text-secondary">
            <span>Thumbnails</span>
            <div className="inline-flex items-center rounded border border-border overflow-hidden">
              {THUMB_MODES.map((mode) => (
                <button
                  key={mode.id}
                  onClick={() => handleSelectThumbMode(mode.id)}
                  aria-pressed={thumbMode === mode.id}
                  className={cn(
                    "px-2 py-0.5 text-[11px] font-sans transition-colors",
                    thumbMode === mode.id
                      ? "text-matrix bg-matrix/10 font-bold"
                      : "text-text-muted hover:text-text-secondary hover:bg-bg-surface"
                  )}
                >
                  {mode.label}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-y-auto flex-1 py-1">
            {displayCategories.length === 0 && (
              <div className="px-3 py-2 text-xs text-text-muted">No themes found</div>
            )}
            {displayCategories.map((cat, ci) => (
              <div key={cat.name}>
                <div className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-text-muted select-none">
                  {cat.name === "Favorites"
                    ? `Favorites · ${favorites.length}/${MAX_FAVORITES}`
                    : cat.name}
                </div>
                {cat.themes.map((theme, i) => {
                  const flatIndex = catOffsets[ci] + i
                  const isFav = favorites.includes(theme.id)
                  const starDisabled = !isFav && atCap
                  return (
                    <div
                      key={theme.id}
                      ref={(el) => {
                        itemRefs.current[flatIndex] = el
                      }}
                      className={cn(
                        "flex items-center",
                        flatIndex === activeIndex && "ring-1 ring-inset ring-matrix"
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => handleSelect(theme.id, flatIndex)}
                        className={cn(
                          "flex-1 flex items-center px-3 py-1 text-xs font-sans transition-colors text-left",
                          current === theme.id
                            ? "text-matrix bg-matrix/10 font-bold"
                            : "text-text-secondary hover:text-text-primary hover:bg-bg-surface"
                        )}
                      >
                        {theme.label}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          toggleFavorite(theme.id)
                          searchRef.current?.focus()
                        }}
                        disabled={starDisabled}
                        aria-pressed={isFav}
                        title={
                          isFav
                            ? "Unfavorite"
                            : starDisabled
                              ? `${MAX_FAVORITES} favorites max — unfavorite one first`
                              : "Favorite"
                        }
                        className={cn(
                          "shrink-0 px-2 py-1 transition-colors",
                          isFav
                            ? "text-matrix"
                            : starDisabled
                              ? "text-text-muted opacity-40 cursor-not-allowed"
                              : "text-text-muted hover:text-text-secondary"
                        )}
                      >
                        <svg
                          className="w-3 h-3"
                          viewBox="0 0 24 24"
                          fill={isFav ? "currentColor" : "none"}
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinejoin="round"
                        >
                          <path d="M12 2l2.9 6.2 6.8.6-5.1 4.5 1.5 6.7L12 17l-6 3.5 1.5-6.7L2.4 8.8l6.8-.6z" />
                        </svg>
                      </button>
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
          <div className="px-2 py-1 border-t border-border text-[10px] text-text-muted text-center">
            {ALL_THEMES.length} themes
          </div>
        </div>
      )}
    </div>
  )
}

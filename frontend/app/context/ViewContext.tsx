"use client"
import { createContext, useState, useContext, ReactNode } from "react"

type ViewType = "downloads" | "subscriptions" | "clips" | "playlists" | "tasks" | "stats" | "settings"

const ViewContext = createContext<{
  view: ViewType
  setView: (view: ViewType) => void
} | null>(null)

export function ViewProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<ViewType>("downloads")
  return (
    <ViewContext.Provider value={{ view, setView }}>
      {children}
    </ViewContext.Provider>
  )
}

export function useView() {
  const context = useContext(ViewContext)
  if (!context) {
    throw new Error("useView must be used within a ViewProvider")
  }
  return context
}

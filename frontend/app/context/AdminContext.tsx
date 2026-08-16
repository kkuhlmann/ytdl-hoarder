"use client"

import { createContext, useContext, useState, useCallback, useMemo, ReactNode } from "react"
import { useAuth } from "./AuthContext"

type AdminContextType = {
  adminMode: boolean
  setAdminMode: (mode: boolean) => void
  adminParam: Record<string, string>
}

const AdminContext = createContext<AdminContextType | null>(null)

export function AdminProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [adminMode, setAdminModeState] = useState(false)

  const setAdminMode = useCallback(
    (mode: boolean) => {
      if (user?.is_admin) {
        setAdminModeState(mode)
      }
    },
    [user],
  )

  // Convenience object to spread into axios params when admin mode is active.
  // Memoised because consumers put it in effect dep arrays: as a fresh literal
  // it changed identity on every render of this provider, which re-ran those
  // effects (refetching folders in useDownloadGrouping, dropping the cached
  // filter options in StatsFilterCombobox) on renders that had nothing to do
  // with admin mode.
  const adminParam = useMemo((): Record<string, string> => {
    if (adminMode && user?.is_admin) return { admin_view: "true" }
    return {}
  }, [adminMode, user?.is_admin])

  return (
    <AdminContext.Provider value={{ adminMode: adminMode && !!user?.is_admin, setAdminMode, adminParam }}>
      {children}
    </AdminContext.Provider>
  )
}

export function useAdmin() {
  const context = useContext(AdminContext)
  if (!context) {
    throw new Error("useAdmin must be used within an AdminProvider")
  }
  return context
}

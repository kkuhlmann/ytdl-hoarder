"use client"

import { ReactNode } from "react"
import { useAuth } from "@/app/context/AuthContext"
import { SetupPage } from "./SetupPage"
import { LoginPage } from "./LoginPage"
import { PendingApproval } from "./PendingApproval"
import { ForcePasswordChange } from "./ForcePasswordChange"

export function AuthGuard({ children }: { children: ReactNode }) {
  const { user, isLoading, needsSetup } = useAuth()

  if (isLoading) {
    return (
      <div className="min-h-screen bg-bg-void bg-grid flex items-center justify-center">
        <div className="text-matrix font-mono text-sm animate-pulse">Loading...</div>
      </div>
    )
  }

  if (needsSetup) {
    return <SetupPage />
  }

  if (!user) {
    return <LoginPage />
  }

  if (!user.is_approved) {
    return <PendingApproval />
  }

  // Mirrors the server-side gate in dependencies.py: a user holding an admin-issued
  // temporary password is authenticated but locked out of every data endpoint.
  if (user.must_change_password) {
    return <ForcePasswordChange />
  }

  return <>{children}</>
}

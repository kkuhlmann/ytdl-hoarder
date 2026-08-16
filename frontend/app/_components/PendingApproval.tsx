"use client"

import { useAuth } from "@/app/context/AuthContext"
import { AuthCard } from "./auth/AuthCard"

export function PendingApproval() {
  const { logout } = useAuth()

  return (
    <AuthCard centered>
      <div className="text-text-secondary font-mono text-sm space-y-3">
        <p>Your account is pending approval.</p>
        <p>An admin needs to approve your account before you can access the app.</p>
      </div>
      <div className="flex justify-center mt-6">
        <button
          onClick={logout}
          className="px-4 py-2 bg-bg-void border border-border rounded font-mono text-sm text-text-muted hover:text-text-primary transition-colors"
        >
          Sign Out
        </button>
      </div>
    </AuthCard>
  )
}

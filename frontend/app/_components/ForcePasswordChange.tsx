"use client"

import { useState } from "react"
import { useAuth } from "@/app/context/AuthContext"
import { submitPasswordChange } from "./auth/changePassword"
import { AuthCard } from "./auth/AuthCard"
import { authInputClass, authSubmitClass } from "./auth/styles"

export function ForcePasswordChange() {
  const { logout, refreshAuth, pendingTempPassword, clearPendingTempPassword } = useAuth()
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Carried over from the sign-in that landed here, so the temp password isn't asked for
  // twice in a row. Absent after a reload, in which case we ask for it.
  const knownTempPassword = pendingTempPassword !== null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)

    const result = await submitPasswordChange(
      pendingTempPassword ?? currentPassword,
      newPassword,
      confirmPassword
    )
    setIsSubmitting(false)

    if (!result.ok) {
      // The carried-over password was rejected. Drop it so the field reappears and the
      // user can type it, rather than stranding them on an unfixable error.
      if (knownTempPassword && result.status === 401) {
        clearPendingTempPassword()
      }
      setError(result.error)
      return
    }
    clearPendingTempPassword()
    await refreshAuth()
  }

  return (
    <AuthCard subtitle="Choose a New Password">
      <p className="text-text-muted font-mono text-xs text-center mb-6">
        {knownTempPassword
          ? "You signed in with a temporary password from your admin. Choose your own to continue."
          : "Your admin issued you a temporary password. Enter it, then choose your own to continue."}
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {!knownTempPassword && (
          <div>
            <label className="block text-sm font-mono text-text-secondary mb-1">
              Temporary password
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className={authInputClass}
              autoComplete="current-password"
              autoFocus
              required
            />
          </div>
        )}

        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">
            New password
          </label>
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className={authInputClass}
            autoComplete="new-password"
            autoFocus={knownTempPassword}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">
            Confirm new password
          </label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={authInputClass}
            autoComplete="new-password"
            required
          />
        </div>

        {error && <p className="text-sm font-mono text-status-error">{error}</p>}

        <button
          type="submit"
          disabled={isSubmitting}
          className={authSubmitClass}
        >
          {isSubmitting ? "Saving..." : "Set Password"}
        </button>
      </form>

      <div className="flex justify-center mt-6">
        <button
          onClick={logout}
          className="text-sm font-mono text-text-muted hover:text-text-primary transition-colors"
        >
          Sign Out
        </button>
      </div>
    </AuthCard>
  )
}

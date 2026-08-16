"use client"

import { useState } from "react"
import { useAuth } from "@/app/context/AuthContext"
import { errorMessage } from "@/app/lib/api"
import { AuthCard } from "./auth/AuthCard"
import { authInputClass, authSubmitClass } from "./auth/styles"
import { validateRegistration } from "./auth/validation"

export function SetupPage() {
  const { register } = useAuth()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    const invalid = validateRegistration(username, password, confirmPassword)
    if (invalid) {
      setError(invalid)
      return
    }

    setIsSubmitting(true)
    try {
      await register(username, password)
    } catch (err) {
      setError(errorMessage(err, "Registration failed"))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AuthCard
      subtitle="Create Admin Account"
      note="This is the first user and will have admin privileges."
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={authInputClass}
            placeholder="admin"
            autoFocus
            required
          />
        </div>

        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">Password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={authInputClass}
            placeholder="Min 6 characters"
            required
          />
        </div>

        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">
            Confirm Password
          </label>
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={authInputClass}
            placeholder="Confirm password"
            required
          />
        </div>

        {error && (
          <p className="text-sm font-mono text-status-error">{error}</p>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className={authSubmitClass}
        >
          {isSubmitting ? "Creating..." : "Create Admin Account"}
        </button>
      </form>
    </AuthCard>
  )
}

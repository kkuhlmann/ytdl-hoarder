"use client"

import { useState } from "react"
import axios from "axios"
import { apiUrl } from "@/app/lib/api"
import { authInputClass, authSubmitClass } from "./styles"

export function ForgotPasswordPanel({ onBack }: { onBack: () => void }) {
  const [username, setUsername] = useState("")
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)
    try {
      await axios.post(apiUrl("/auth/forgot-password"), { username })
      setSubmitted(true)
    } catch {
      setError("Could not reach the server. Try again.")
    } finally {
      setIsSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="text-center">
        <div className="text-text-secondary font-mono text-sm space-y-3">
          <p>If that account exists, your admin has been notified.</p>
          <p className="text-text-muted text-xs">
            They&apos;ll give you a temporary password to sign in with. There&apos;s no email
            involved, so reach out to them however you normally would.
          </p>
        </div>
        <button
          onClick={onBack}
          className="mt-6 text-sm font-mono text-text-muted hover:text-matrix transition-colors"
        >
          Back to sign in
        </button>
      </div>
    )
  }

  return (
    <>
      <p className="text-text-muted font-mono text-xs mb-4">
        Your admin resets passwords from the app. Enter your username to let them know.
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={authInputClass}
            autoFocus
            required
          />
        </div>

        {error && <p className="text-sm font-mono text-status-error">{error}</p>}

        <button
          type="submit"
          disabled={isSubmitting}
          className={authSubmitClass}
        >
          {isSubmitting ? "Sending..." : "Request Reset"}
        </button>
      </form>

      <div className="mt-6 text-center">
        <button
          onClick={onBack}
          className="text-sm font-mono text-text-muted hover:text-matrix transition-colors"
        >
          Back to sign in
        </button>
      </div>
    </>
  )
}

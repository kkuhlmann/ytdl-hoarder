"use client"

import { useState } from "react"
import { useAuth } from "@/app/context/AuthContext"
import { ForgotPasswordPanel } from "./auth/ForgotPasswordPanel"
import { AdminRecoveryPanel } from "./auth/AdminRecoveryPanel"
import { AuthCard } from "./auth/AuthCard"
import { authInputClass as inputClass, authSubmitClass } from "./auth/styles"
import { validateRegistration } from "./auth/validation"
import { errorMessage } from "@/app/lib/api"

type Mode = "auth" | "forgot" | "adminRecovery"

export function LoginPage() {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<Mode>("auth")
  const [isRegistering, setIsRegistering] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [error, setError] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [pendingApproval, setPendingApproval] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")
    setIsSubmitting(true)

    try {
      await login(username, password)
    } catch (err) {
      setError(errorMessage(err, "Login failed"))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    const invalid = validateRegistration(username, password, confirmPassword)
    if (invalid) {
      setError(invalid)
      return
    }

    setIsSubmitting(true)
    try {
      const result = await register(username, password)
      if (!result.is_approved) {
        setPendingApproval(true)
      }
    } catch (err) {
      setError(errorMessage(err, "Registration failed"))
    } finally {
      setIsSubmitting(false)
    }
  }

  if (pendingApproval) {
    return <PendingApprovalMessage />
  }

  const backToSignIn = () => {
    setMode("auth")
    setError("")
  }

  if (mode === "forgot") {
    return (
      <AuthCard subtitle="Forgot Password">
        <ForgotPasswordPanel onBack={backToSignIn} />
      </AuthCard>
    )
  }

  if (mode === "adminRecovery") {
    return (
      <AuthCard subtitle="Admin Account Recovery">
        <AdminRecoveryPanel onBack={backToSignIn} />
      </AuthCard>
    )
  }

  return (
    <AuthCard subtitle={isRegistering ? "Create Account" : "Sign In"}>
      <form onSubmit={isRegistering ? handleRegister : handleLogin} className="space-y-4">
        <div>
          <label className="block text-sm font-mono text-text-secondary mb-1">Username</label>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputClass}
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
            className={inputClass}
            required
          />
        </div>

        {isRegistering && (
          <div>
            <label className="block text-sm font-mono text-text-secondary mb-1">
              Confirm Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className={inputClass}
              required
            />
          </div>
        )}

        {error && <p className="text-sm font-mono text-status-error">{error}</p>}

        <button
          type="submit"
          disabled={isSubmitting}
          className={authSubmitClass}
        >
          {isSubmitting
            ? isRegistering ? "Creating..." : "Signing in..."
            : isRegistering ? "Create Account" : "Sign In"}
        </button>
      </form>

      <div className="mt-6 text-center space-y-2">
        <div>
          <button
            onClick={() => {
              setIsRegistering(!isRegistering)
              setError("")
              setConfirmPassword("")
            }}
            className="text-sm font-mono text-text-muted hover:text-matrix transition-colors"
          >
            {isRegistering
              ? "Already have an account? Sign in"
              : "Need an account? Register"}
          </button>
        </div>

        {!isRegistering && (
          <>
            <div>
              <button
                onClick={() => setMode("forgot")}
                className="text-sm font-mono text-text-muted hover:text-matrix transition-colors"
              >
                Forgot your password?
              </button>
            </div>
            <div>
              <button
                onClick={() => setMode("adminRecovery")}
                className="text-xs font-mono text-text-muted/60 hover:text-matrix transition-colors"
              >
                Admin account recovery
              </button>
            </div>
          </>
        )}
      </div>
    </AuthCard>
  )
}

function PendingApprovalMessage() {
  return (
    <AuthCard centered>
      <div className="text-text-secondary font-mono text-sm space-y-3">
        <p>Your account has been created.</p>
        <p>An admin needs to approve your account before you can sign in.</p>
      </div>
      <button
        onClick={() => window.location.reload()}
        className="mt-6 px-4 py-2 bg-matrix/20 border border-matrix/50 rounded font-mono text-sm text-matrix hover:bg-matrix/30 transition-colors"
      >
        Refresh
      </button>
    </AuthCard>
  )
}

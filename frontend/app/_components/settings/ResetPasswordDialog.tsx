"use client"

import { useState } from "react"
import axios from "axios"
import toast from "react-hot-toast"
import { apiUrl, errorMessage } from "@/app/lib/api"
import { copyToClipboard } from "@/app/lib/clipboard"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { ClipboardDocumentIcon } from "@heroicons/react/24/outline"
import { LoadingSpinner } from "../LoadingSpinner"

type ResetPasswordDialogProps = {
  /** The user to reset; null closes the dialog. */
  user: { id: number; username: string } | null
  onOpenChange: (open: boolean) => void
  onReset: () => void
}

export function ResetPasswordDialog({ user, onOpenChange, onReset }: ResetPasswordDialogProps) {
  const [tempPassword, setTempPassword] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)

  const close = () => {
    onOpenChange(false)
    setTempPassword("")
  }

  const handleReset = async () => {
    if (!user) return
    setIsSubmitting(true)
    try {
      const resp = await axios.post(apiUrl(`/auth/users/${user.id}/reset-password`))
      setTempPassword(resp.data.temporary_password)
      onReset()
    } catch (error) {
      toast.error(errorMessage(error, "Failed to reset password"))
    } finally {
      setIsSubmitting(false)
    }
  }

  const copyPassword = async () => {
    if (await copyToClipboard(tempPassword)) {
      toast.success("Copied to clipboard")
    } else {
      toast.error("Could not copy — click the password to select it, then copy manually")
    }
  }

  return (
    <Dialog
      open={user !== null}
      onOpenChange={(next) => {
        if (isSubmitting) return
        if (!next) close()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {tempPassword ? "Temporary password" : `Reset password for ${user?.username}`}
          </DialogTitle>
          <DialogDescription>
            {tempPassword
              ? "Shown once. Send it to them however you normally would."
              : `Generates a temporary password for ${user?.username} and signs them out everywhere. There is no email integration, so you'll relay it to them yourself.`}
          </DialogDescription>
        </DialogHeader>

        {tempPassword && (
          <div className="py-4 space-y-3">
            <div className="flex items-center gap-2">
              <code className="flex-1 px-3 py-2 bg-bg-void border border-matrix/40 rounded font-mono text-base text-matrix tracking-wide break-all select-all">
                {tempPassword}
              </code>
              <Button variant="outline" size="icon" onClick={copyPassword} title="Copy">
                <ClipboardDocumentIcon className="h-4 w-4" />
              </Button>
            </div>
            <p className="text-xs text-text-muted">
              {user?.username} must choose their own password the first time they sign in with
              this — it won&apos;t work for anything else.
            </p>
          </div>
        )}

        <DialogFooter>
          {tempPassword ? (
            <Button variant="matrix" onClick={close}>
              Done
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={close} disabled={isSubmitting}>
                Cancel
              </Button>
              <Button variant="matrix" onClick={handleReset} disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <LoadingSpinner />
                    Resetting...
                  </>
                ) : (
                  "Reset Password"
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

import axios from "axios"
import { apiUrl, errorMessage } from "@/app/lib/api"

export const MIN_PASSWORD_LENGTH = 6

type ChangePasswordResult =
  | { ok: true }
  | { ok: false; error: string; /** HTTP status, absent for client-side validation failures. */ status?: number }

/** Shared by the nav dialog and the forced-change screen, which differ only in chrome. */
export async function submitPasswordChange(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string
): Promise<ChangePasswordResult> {
  if (newPassword.length < MIN_PASSWORD_LENGTH) {
    return { ok: false, error: `Password must be at least ${MIN_PASSWORD_LENGTH} characters` }
  }
  if (newPassword !== confirmPassword) {
    return { ok: false, error: "Passwords do not match" }
  }

  try {
    await axios.post(apiUrl("/auth/me/change-password"), {
      current_password: currentPassword,
      new_password: newPassword,
    })
    return { ok: true }
  } catch (err) {
    return {
      ok: false,
      error: errorMessage(err, "Failed to change password"),
      status: axios.isAxiosError(err) ? err.response?.status : undefined,
    }
  }
}

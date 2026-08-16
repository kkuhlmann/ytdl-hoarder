import { MIN_PASSWORD_LENGTH } from "./changePassword"

/** Returns the first failure, or null when the form is good to submit. */
export function validateRegistration(
  username: string,
  password: string,
  confirmPassword: string
): string | null {
  if (username.length < 3) return "Username must be at least 3 characters"
  if (password.length < MIN_PASSWORD_LENGTH)
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
  if (password !== confirmPassword) return "Passwords do not match"
  return null
}

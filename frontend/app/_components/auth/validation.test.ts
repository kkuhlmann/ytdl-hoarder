import { describe, expect, it } from "vitest"
import { validateRegistration } from "./validation"
import { MIN_PASSWORD_LENGTH } from "./changePassword"

const validPassword = "a".repeat(MIN_PASSWORD_LENGTH)
const shortPassword = "a".repeat(MIN_PASSWORD_LENGTH - 1)

describe("validateRegistration", () => {
  it("rejects a short username first, even when the password is also invalid", () => {
    expect(validateRegistration("ab", shortPassword, "mismatch")).toBe(
      "Username must be at least 3 characters",
    )
  })

  it(`rejects a password under ${MIN_PASSWORD_LENGTH} characters once the username passes`, () => {
    expect(validateRegistration("abc", shortPassword, "mismatch")).toBe(
      `Password must be at least ${MIN_PASSWORD_LENGTH} characters`,
    )
  })

  it("rejects a mismatched confirmation once username and password both pass", () => {
    expect(validateRegistration("abc", validPassword, validPassword + "x")).toBe(
      "Passwords do not match",
    )
  })

  it("returns null when all three rules pass", () => {
    expect(validateRegistration("abc", validPassword, validPassword)).toBeNull()
  })
})

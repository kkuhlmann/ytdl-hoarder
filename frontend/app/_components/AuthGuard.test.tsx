// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import { AuthGuard } from "./AuthGuard"
import { useAuth } from "@/app/context/AuthContext"

vi.mock("@/app/context/AuthContext", () => ({ useAuth: vi.fn() }))
vi.mock("@/app/_components/SetupPage", () => ({
  SetupPage: () => <div>setup-page</div>,
}))
vi.mock("@/app/_components/LoginPage", () => ({
  LoginPage: () => <div>login-page</div>,
}))
vi.mock("@/app/_components/PendingApproval", () => ({
  PendingApproval: () => <div>pending-approval</div>,
}))
vi.mock("@/app/_components/ForcePasswordChange", () => ({
  ForcePasswordChange: () => <div>force-password-change</div>,
}))

afterEach(cleanup)

type MockUser = {
  is_approved: boolean
  must_change_password: boolean
}

type MockAuthState = {
  user: MockUser | null
  isLoading: boolean
  needsSetup: boolean
}

// Most rungs' fixtures also satisfy every rung below them, so a passing
// assertion proves that rung wins on precedence rather than merely being
// reachable in isolation (e.g. the needsSetup case also has user: null).
// Rung 1 is the exception: its non-null user (needed to also cover rungs 4
// and 5) can't simultaneously satisfy rung 3's user: null, but isLoading's
// precedence over !user is still closed transitively via rung 2's fixture.
function mockAuth(state: MockAuthState) {
  vi.mocked(useAuth).mockReturnValue(state as ReturnType<typeof useAuth>)
}

describe("AuthGuard", () => {
  it("rung 1: isLoading wins over every other rung, rendering inline Loading text", () => {
    mockAuth({
      isLoading: true,
      needsSetup: true,
      user: { is_approved: false, must_change_password: true },
    })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("Loading...")).toBeTruthy()
    expect(screen.queryByText("setup-page")).toBeNull()
  })

  it("rung 2: needsSetup wins over !user, rendering SetupPage", () => {
    mockAuth({ isLoading: false, needsSetup: true, user: null })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("setup-page")).toBeTruthy()
    expect(screen.queryByText("login-page")).toBeNull()
  })

  it("rung 3: !user wins over !is_approved, rendering LoginPage", () => {
    mockAuth({ isLoading: false, needsSetup: false, user: null })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("login-page")).toBeTruthy()
    expect(screen.queryByText("pending-approval")).toBeNull()
  })

  it("rung 4: !is_approved wins over must_change_password, rendering PendingApproval", () => {
    mockAuth({
      isLoading: false,
      needsSetup: false,
      user: { is_approved: false, must_change_password: true },
    })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("pending-approval")).toBeTruthy()
    expect(screen.queryByText("force-password-change")).toBeNull()
  })

  it("rung 5: must_change_password wins over rendering children, rendering ForcePasswordChange", () => {
    mockAuth({
      isLoading: false,
      needsSetup: false,
      user: { is_approved: true, must_change_password: true },
    })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("force-password-change")).toBeTruthy()
    expect(screen.queryByText("protected")).toBeNull()
  })

  it("rung 6: with every gate clear, renders children", () => {
    mockAuth({
      isLoading: false,
      needsSetup: false,
      user: { is_approved: true, must_change_password: false },
    })

    render(
      <AuthGuard>
        <div>protected</div>
      </AuthGuard>,
    )

    expect(screen.getByText("protected")).toBeTruthy()
  })
})

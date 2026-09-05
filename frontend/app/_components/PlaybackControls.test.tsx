// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { PlaybackControls, type QueueMode } from "./PlaybackControls"

afterEach(cleanup)

function renderControls(overrides: Partial<React.ComponentProps<typeof PlaybackControls>> = {}) {
  const props = {
    onPlayAll: vi.fn(),
    onShuffle: vi.fn(),
    resume: { checked: false, onChange: vi.fn() },
    ...overrides,
  }
  render(<PlaybackControls {...props} />)
  return props
}

const playAll = () => screen.getByText("Play All").closest("button")!
const shuffle = () => screen.getByText("Shuffle").closest("button")!
const options = () => screen.getByLabelText("Playback options")

describe("PlaybackControls", () => {
  it.each<[QueueMode, string | null, string | null]>([
    ["off", "false", "false"],
    ["ordered", "true", "false"],
    ["shuffled", "false", "true"],
  ])("reflects queueMode %s as pressed state", (queueMode, pressedPlay, pressedShuffle) => {
    renderControls({ queueMode })

    expect(playAll().getAttribute("aria-pressed")).toBe(pressedPlay)
    expect(shuffle().getAttribute("aria-pressed")).toBe(pressedShuffle)
  })

  it("is a pair of plain actions on surfaces with no queue state", () => {
    renderControls()

    expect(playAll().getAttribute("aria-pressed")).toBeNull()
    expect(shuffle().getAttribute("aria-pressed")).toBeNull()
  })

  it("keeps Resume behind the options menu", () => {
    renderControls()
    expect(screen.queryByText("Resume")).toBeNull()

    fireEvent.click(options())
    expect(screen.getByText("Resume")).toBeTruthy()
  })

  it("disables Resume while a queue is playing, without dropping the preference", () => {
    const props = renderControls({
      queueMode: "ordered",
      resume: { checked: true, disabled: true, onChange: vi.fn() },
    })
    fireEvent.click(options())

    const toggle = screen.getByRole("switch")
    expect(toggle.hasAttribute("disabled")).toBe(true)
    expect(toggle.getAttribute("aria-checked")).toBe("true")

    fireEvent.click(toggle)
    expect(props.resume.onChange).not.toHaveBeenCalled()
  })

  it("fires the playback callbacks", () => {
    const props = renderControls()

    fireEvent.click(playAll())
    fireEvent.click(shuffle())

    expect(props.onPlayAll).toHaveBeenCalledOnce()
    expect(props.onShuffle).toHaveBeenCalledOnce()
  })

  it("disables both actions when the surface has nothing to play", () => {
    renderControls({ disabled: true })

    expect(playAll().hasAttribute("disabled")).toBe(true)
    expect(shuffle().hasAttribute("disabled")).toBe(true)
  })
})

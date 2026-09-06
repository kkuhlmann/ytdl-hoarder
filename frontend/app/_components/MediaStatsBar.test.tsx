// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { MediaStatsBar } from "./MediaStatsBar"

afterEach(cleanup)

const STATS = {
  total_downloads: 128,
  downloads_with_transcripts: 94,
  total_transcript_blocks: 12340,
}

const chip = () => screen.getByLabelText(/128 downloads/)
const breakdown = () => screen.queryByText("with transcripts")

describe("MediaStatsBar", () => {
  it("carries all three counts in one chip, abbreviating the large one", () => {
    render(<MediaStatsBar stats={STATS} />)

    expect(chip().textContent).toMatch(/^128.*94.*12\.3k$/)
  })

  it("labels the chip for assistive tech, which can't read the colours", () => {
    render(<MediaStatsBar stats={STATS} />)

    expect(chip().getAttribute("aria-label")).toMatch(/downloads.*with transcripts.*transcript blocks/)
  })

  it("spells the counts out on hover", () => {
    render(<MediaStatsBar stats={STATS} />)
    expect(breakdown()).toBeNull()

    fireEvent.pointerEnter(chip(), { pointerType: "mouse" })
    expect(breakdown()).not.toBeNull()

    fireEvent.pointerLeave(chip(), { pointerType: "mouse" })
    expect(breakdown()).toBeNull()
  })

  it("leaves the breakdown to the tap on a touch device", () => {
    render(<MediaStatsBar stats={STATS} />)

    fireEvent.pointerEnter(chip(), { pointerType: "touch" })
    expect(breakdown()).toBeNull()

    fireEvent.click(chip())
    expect(breakdown()).not.toBeNull()
  })

  it("shows a placeholder until the first fetch lands", () => {
    const { rerender } = render(<MediaStatsBar stats={null} loading />)
    expect(screen.getByText("Loading...")).toBeTruthy()

    rerender(<MediaStatsBar stats={null} />)
    expect(screen.getByText("Loading...")).toBeTruthy()
  })
})

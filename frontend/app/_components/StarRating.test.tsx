// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"

import { StarRating } from "./StarRating"

// RTL's automatic cleanup never registers with globals off — see .claude/rules/frontend.md.
afterEach(cleanup)

describe("StarRating", () => {
  it("rates on click and clears when the current star is clicked again", () => {
    const onRate = vi.fn()
    render(<StarRating rating={3} onRate={onRate} />)

    fireEvent.click(screen.getByTitle("Rate 4 stars"))
    expect(onRate).toHaveBeenCalledWith(4)

    fireEvent.click(screen.getByTitle("Clear rating"))
    expect(onRate).toHaveBeenCalledWith(null)
  })

  it("is read-only without a handler: no buttons, the rating still shown", () => {
    // Offline mode keeps ratings visible (the list sorts on them) but a click
    // would be a server write, so the stars must not be interactive.
    const { container } = render(<StarRating rating={2} />)

    expect(screen.queryAllByRole("button")).toHaveLength(0)
    expect(screen.getByTitle("Rated 2 stars")).toBeDefined()
    expect(container.querySelectorAll("svg")).toHaveLength(5)
  })
})

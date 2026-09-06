// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { FiltersPopover } from "./FiltersPopover"
import type { TagInfo } from "@/app/types/DownloadsOptions"

afterEach(cleanup)

const TAGS: TagInfo[] = [
  { id: 1, name: "lofi" },
  { id: 2, name: "talks" },
] as TagInfo[]

function renderFilters(overrides: Partial<React.ComponentProps<typeof FiltersPopover>> = {}) {
  const props = {
    allTags: TAGS,
    selectedTagIds: [] as number[],
    onTagsChange: vi.fn(),
    minRating: null as number | null,
    onRatingChange: vi.fn(),
    ...overrides,
  }
  render(<FiltersPopover {...props} />)
  return props
}

const trigger = () => screen.getByTitle(/filter/i)

describe("FiltersPopover", () => {
  it("counts tags and rating as one active filter each", () => {
    const { unmount } = render(
      <FiltersPopover
        allTags={TAGS}
        selectedTagIds={[]}
        onTagsChange={() => {}}
        minRating={null}
        onRatingChange={() => {}}
      />
    )
    expect(trigger().textContent).toBe("Filters")
    unmount()

    renderFilters({ selectedTagIds: [1, 2] })
    expect(trigger().textContent).toBe("Filters1")
    cleanup()

    renderFilters({ minRating: 3 })
    expect(trigger().textContent).toBe("Filters1")
    cleanup()

    renderFilters({ selectedTagIds: [1], minRating: 3 })
    expect(trigger().textContent).toBe("Filters2")
  })

  it("offers Clear all only while something is filtered, and clears both", () => {
    const { unmount } = render(
      <FiltersPopover
        allTags={TAGS}
        selectedTagIds={[]}
        onTagsChange={() => {}}
        minRating={null}
        onRatingChange={() => {}}
      />
    )
    fireEvent.click(trigger())
    expect(screen.queryByText("Clear all")).toBeNull()
    unmount()

    const props = renderFilters({ selectedTagIds: [1], minRating: 3 })
    fireEvent.click(trigger())
    fireEvent.click(screen.getByText("Clear all"))

    expect(props.onTagsChange).toHaveBeenCalledWith([])
    expect(props.onRatingChange).toHaveBeenCalledWith(null)
  })

  it("selects a minimum rating from the star row", () => {
    const props = renderFilters()
    fireEvent.click(trigger())
    fireEvent.click(screen.getByTitle("4+ stars"))

    expect(props.onRatingChange).toHaveBeenCalledWith(4)
  })

  it("clears the rating when the selected star is clicked again", () => {
    const props = renderFilters({ minRating: 4 })
    fireEvent.click(trigger())
    fireEvent.click(screen.getByTitle("Clear filter"))

    expect(props.onRatingChange).toHaveBeenCalledWith(null)
  })

  it("toggles a tag through the embedded tag list", () => {
    const props = renderFilters()
    fireEvent.click(trigger())
    fireEvent.click(screen.getByText("talks"))

    expect(props.onTagsChange).toHaveBeenCalledWith([2])
  })

  it("says so rather than rendering an empty tag list", () => {
    renderFilters({ allTags: [] })
    fireEvent.click(trigger())

    expect(screen.getByText("No tags yet")).toBeTruthy()
    expect(screen.queryByPlaceholderText("Search tags...")).toBeNull()
  })
})

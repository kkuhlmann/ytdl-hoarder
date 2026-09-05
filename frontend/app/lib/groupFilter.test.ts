import { describe, it, expect } from "vitest"
import { groupFilterParams } from "./groupFilter"

describe("groupFilterParams", () => {
  it("sends nothing when no folder is open", () => {
    expect(groupFilterParams(null)).toEqual({})
    expect(groupFilterParams(undefined)).toEqual({})
    expect(groupFilterParams({})).toEqual({})
  })

  it("maps a channel folder", () => {
    expect(groupFilterParams({ channel: "NASA" })).toEqual({ channel: "NASA" })
  })

  it("keeps an empty channel name, which is a real bucket key", () => {
    expect(groupFilterParams({ channel: "" })).toEqual({ channel: "" })
  })

  it("maps the untagged bucket", () => {
    expect(groupFilterParams({ untagged: true })).toEqual({ untagged: true })
  })

  it("omits the month when only a year is open, so the backend reads the whole year", () => {
    expect(groupFilterParams({ dateField: "released", year: 2024 })).toEqual({
      date_field: "released",
      date_year: 2024,
    })
  })

  it("maps a year and month", () => {
    expect(groupFilterParams({ dateField: "downloaded", year: 2024, month: 3 })).toEqual({
      date_field: "downloaded",
      date_year: 2024,
      date_month: 3,
    })
  })

  it("sends no date params for a month without its year", () => {
    expect(groupFilterParams({ dateField: "released", month: 3 })).toEqual({})
  })
})

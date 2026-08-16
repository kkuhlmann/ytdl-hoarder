import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import {
  formatBytes,
  formatDate,
  formatDuration,
  formatDurationCompact,
  formatRelativeTime,
  formatTime,
  formatTimeUntil,
  getFullTimestamp,
  isValidSubscriptionUrl,
  isValidURL,
} from "./utils"

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

const NOW_ISO = "2026-08-08T12:00:00Z"
const NOW_MS = Date.parse(NOW_ISO)

function isoBefore(ms: number, withTrailingZ = true): string {
  const iso = new Date(NOW_MS - ms).toISOString()
  return withTrailingZ ? iso : iso.slice(0, -1)
}

function isoAfter(ms: number): string {
  return new Date(NOW_MS + ms).toISOString()
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(NOW_ISO))
})

afterEach(() => {
  vi.useRealTimers()
})

describe("formatRelativeTime", () => {
  it.each([
    ["30s ago", "now", 30 * SECOND],
    ["59s ago", "now", 59 * SECOND],
    ["exactly 60s ago (1m boundary)", "1m ago", 60 * SECOND],
    ["5m ago", "5m ago", 5 * MINUTE],
    ["exactly 60m ago (1h boundary)", "1h ago", 60 * MINUTE],
    ["3h ago", "3h ago", 3 * HOUR],
    ["exactly 24h ago (1d boundary)", "1d ago", 24 * HOUR],
    ["2d ago", "2d ago", 2 * DAY],
    ["exactly 7d ago (1w boundary)", "1w ago", 7 * DAY],
    ["10d ago", "1w ago", 10 * DAY],
    ["exactly 30d ago (1mo boundary)", "1mo ago", 30 * DAY],
    ["60d ago", "2mo ago", 60 * DAY],
    ["exactly 365d ago (1y boundary)", "1y ago", 365 * DAY],
    ["400d ago", "1y ago", 400 * DAY],
  ])("%s -> %s", (_label, expected, ms) => {
    expect(formatRelativeTime(isoBefore(ms))).toBe(expected)
  })

  it("treats a timestamp without a trailing Z as UTC, same as one with it", () => {
    expect(formatRelativeTime(isoBefore(5 * MINUTE, false))).toBe(
      formatRelativeTime(isoBefore(5 * MINUTE, true)),
    )
  })

  it("returns an empty string for undefined", () => {
    expect(formatRelativeTime(undefined)).toBe("")
  })

  it("returns an empty string for an empty string", () => {
    expect(formatRelativeTime("")).toBe("")
  })
})

describe("formatTimeUntil", () => {
  it("renders a minutes-out timestamp as \"4m\"", () => {
    expect(formatTimeUntil(isoAfter(4 * MINUTE))).toBe("4m")
  })

  it("renders an hours-and-minutes-out timestamp as \"2h 5m\"", () => {
    expect(formatTimeUntil(isoAfter(2 * HOUR + 5 * MINUTE))).toBe("2h 5m")
  })

  it("drops the minutes component when it is zero", () => {
    expect(formatTimeUntil(isoAfter(HOUR))).toBe("1h")
  })

  it("renders a sub-minute timestamp in seconds", () => {
    expect(formatTimeUntil(isoAfter(30 * SECOND))).toBe("30s")
  })

  it("returns null for a timestamp that has already passed", () => {
    expect(formatTimeUntil(isoBefore(SECOND))).toBeNull()
  })

  it("returns null exactly at now", () => {
    expect(formatTimeUntil(NOW_ISO)).toBeNull()
  })

  it("returns null for null input", () => {
    expect(formatTimeUntil(null)).toBeNull()
  })

  it("returns null for undefined input", () => {
    expect(formatTimeUntil(undefined)).toBeNull()
  })
})

describe("formatBytes", () => {
  it.each([
    [0, "0 B"],
    [-5, "0 B"],
    [null, "0 B"],
    [undefined, "0 B"],
    [500, "500 B"],
    [1536, "1.5 KB"],
    [150 * 1024, "150 KB"],
    [5 * 1024 * 1024, "5.0 MB"],
    [2 * 1024 * 1024 * 1024, "2.0 GB"],
    [3 * 1024 * 1024 * 1024 * 1024, "3.0 TB"],
  ])("formatBytes(%o) -> %s", (input, expected) => {
    expect(formatBytes(input)).toBe(expected)
  })
})

describe("formatDuration", () => {
  it.each([
    [undefined, "-"],
    [null, "-"],
    [0, "0:00"],
    [45, "0:45"],
    [65, "1:05"],
    [3599, "59:59"],
    [3600, "1:00:00"],
    [3661, "1:01:01"],
  ])("formatDuration(%o) -> %s", (input, expected) => {
    expect(formatDuration(input)).toBe(expected)
  })

  it("has no non-finite guard: NaN falls through to NaN:NaN", () => {
    expect(formatDuration(NaN)).toBe("NaN:NaN")
  })

  it("has no non-finite guard: Infinity falls through to Infinity:NaN:NaN", () => {
    expect(formatDuration(Infinity)).toBe("Infinity:NaN:NaN")
  })
})

describe("formatDurationCompact", () => {
  it.each([
    [0, "0m"],
    [-5, "0m"],
    [null, "0m"],
    [undefined, "0m"],
    [30, "30s"],
    [90, "1m"],
    [3600, "1h"],
    [3661, "1h 1m"],
  ])("formatDurationCompact(%o) -> %s", (input, expected) => {
    expect(formatDurationCompact(input)).toBe(expected)
  })

  it("treats NaN as falsy, same as 0", () => {
    expect(formatDurationCompact(NaN)).toBe("0m")
  })

  it("has no non-finite guard: Infinity falls through to Infinityh", () => {
    expect(formatDurationCompact(Infinity)).toBe("Infinityh")
  })
})

describe("formatTime", () => {
  it.each([
    [NaN, "0:00"],
    [Infinity, "0:00"],
    [-Infinity, "0:00"],
    [0, "0:00"],
    [45, "0:45"],
    [65, "1:05"],
    [3599, "59:59"],
    [3600, "1:00:00"],
    [3661, "1:01:01"],
  ])("formatTime(%o) -> %s", (input, expected) => {
    expect(formatTime(input)).toBe(expected)
  })
})

describe("isValidURL", () => {
  it.each([
    "https://example.com",
    "http://example.com",
    "https://www.example.co.uk/path?q=1",
    "https://sub.example.com/a/b?x=1&y=2#frag",
  ])("%s is valid", (url) => {
    expect(isValidURL(url)).toBe(true)
  })

  it.each(["not a url", "example.com", "ftp://example.com", ""])("%s is invalid", (url) => {
    expect(isValidURL(url)).toBe(false)
  })
})

describe("isValidSubscriptionUrl", () => {
  it.each([
    "https://www.youtube.com/channel/UCabc123",
    "https://youtube.com/@somechannel",
    "https://www.youtube.com/playlist?list=PLabc123",
    "https://rumble.com/c/SomeChannel",
    "https://odysee.com/@SomeChannel:1",
    "https://www.bitchute.com/channel/somechannel",
    "https://example.com/some-generic-page",
  ])("%s is a valid subscription URL", (url) => {
    expect(isValidSubscriptionUrl(url)).toBe(true)
  })

  it("falls back to isValidURL and rejects a non-URL", () => {
    expect(isValidSubscriptionUrl("not a url")).toBe(false)
  })
})

describe("getFullTimestamp", () => {
  it("returns an empty string for undefined", () => {
    expect(getFullTimestamp(undefined)).toBe("")
  })

  it("returns a non-empty timestamp string containing the year", () => {
    expect(getFullTimestamp("2026-08-08T12:00:00Z")).toMatch(/2026/)
  })

  it("treats a timestamp without a trailing Z as UTC, same as one with it", () => {
    expect(getFullTimestamp("2026-08-08T12:00:00")).toBe(
      getFullTimestamp("2026-08-08T12:00:00Z"),
    )
  })
})

describe("formatDate", () => {
  it("returns an empty string for undefined", () => {
    expect(formatDate(undefined)).toBe("")
  })

  it("returns an empty string for an empty string", () => {
    expect(formatDate("")).toBe("")
  })

  it("returns a non-empty date string containing the year", () => {
    expect(formatDate("2026-08-08T12:00:00Z")).toMatch(/2026/)
  })
})

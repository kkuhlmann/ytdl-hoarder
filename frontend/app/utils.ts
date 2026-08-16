export function isValidURL(url: string): boolean {
  const pattern =
    /^(https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*))$/
  return !!url.match(pattern)
}

export function formatDate(dateString: string | undefined) {
  if (!dateString) return ""
  const date = new Date(dateString)
  return date.toLocaleDateString()
}

export function formatRelativeTime(dateString: string | undefined): string {
  if (!dateString) return ""

  // Ensure UTC timestamps are parsed correctly
  const utcDateString = dateString.endsWith("Z") ? dateString : dateString + "Z"
  const date = new Date(utcDateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffSeconds = Math.floor(diffMs / 1000)
  const diffMinutes = Math.floor(diffSeconds / 60)
  const diffHours = Math.floor(diffMinutes / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffSeconds < 60) {
    return "now"
  }

  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`
  }

  if (diffHours < 24) {
    return `${diffHours}h ago`
  }

  if (diffDays < 7) {
    return `${diffDays}d ago`
  }

  if (diffDays < 30) {
    const weeks = Math.floor(diffDays / 7)
    return `${weeks}w ago`
  }

  if (diffDays < 365) {
    const months = Math.floor(diffDays / 30)
    return `${months}mo ago`
  }

  const years = Math.floor(diffDays / 365)
  return `${years}y ago`
}

/**
 * Compact time remaining until a future timestamp ("2h 5m", "5m", "30s"), or null
 * once it has passed. Callers need that null distinguishable — formatDurationCompact
 * answers "0m" for a non-positive duration, which reads as a live countdown.
 */
export function formatTimeUntil(dateString: string | null | undefined): string | null {
  if (!dateString) return null

  const utcDateString = dateString.endsWith("Z") ? dateString : dateString + "Z"
  const diffSeconds = Math.floor((new Date(utcDateString).getTime() - Date.now()) / 1000)
  if (!isFinite(diffSeconds) || diffSeconds <= 0) return null

  return formatDurationCompact(diffSeconds)
}

export function getFullTimestamp(dateString: string | undefined): string {
  if (!dateString) return ""
  const utcDateString = dateString.endsWith("Z") ? dateString : dateString + "Z"
  const date = new Date(utcDateString)
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  })
}

export function formatDuration(seconds: number | undefined | null): string {
  if (seconds === undefined || seconds === null) return "-"
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
  }
  return `${minutes}:${secs.toString().padStart(2, "0")}`
}

// Player-clock variant of formatDuration: renders "0:00" rather than "-" while a
// media element's duration is still NaN/Infinity.
export function formatTime(seconds: number): string {
  if (!isFinite(seconds) || isNaN(seconds)) return "0:00"
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

export function formatBytes(bytes: number | undefined | null): string {
  if (!bytes || bytes < 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let i = 0
  let val = bytes
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024
    i++
  }
  // Whole numbers for bytes and large values; one decimal otherwise
  const display = i === 0 || val >= 100 ? Math.round(val) : val.toFixed(1)
  return `${display} ${units[i]}`
}

export function formatDurationCompact(seconds: number | undefined | null): string {
  if (!seconds || seconds <= 0) return "0m"
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`
  if (minutes > 0) return `${minutes}m`
  return `${Math.floor(seconds)}s`
}

export function isValidSubscriptionUrl(url: string) {
  // Known platform channel/playlist patterns for instant client-side feedback
  const knownPatterns = [
    // YouTube channels and playlists
    /^https?:\/\/(www\.)?youtube\.com\/(channel\/|c\/|user\/|@)[\w@.-]+/,
    /^https?:\/\/(www\.)?youtube\.com\/playlist\?list=[a-zA-Z0-9_-]+/,
    // Rumble channels
    /^https?:\/\/(www\.)?rumble\.com\/(c|user)\/[\w.-]+/,
    // Odysee channels
    /^https?:\/\/(www\.)?odysee\.com\/@[\w:.-]+/,
    // Bitchute channels
    /^https?:\/\/(www\.)?bitchute\.com\/channel\/[\w-]+/,
  ]

  for (const pattern of knownPatterns) {
    if (pattern.test(url)) return true
  }

  // Fall back to generic URL validation - let the backend validate via yt-dlp
  return isValidURL(url)
}




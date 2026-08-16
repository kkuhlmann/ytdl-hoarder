/**
 * Copy text to the clipboard, falling back to the legacy path in non-secure contexts.
 *
 * `navigator.clipboard` is exposed only in a secure context — HTTPS, or localhost. This app
 * is routinely reached over plain HTTP on a LAN or Tailscale hostname (see
 * NEXT_PUBLIC_BACKEND_API), where the property is `undefined` outright rather than
 * permission-denied. So the fallback below is the *normal* path for those users, not an
 * edge case, and `navigator.clipboard.writeText(...)` must never be called unguarded.
 *
 * Returns whether the text actually made it to the clipboard.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Denied or transient — the legacy path below may still succeed.
    }
  }
  return legacyCopy(text)
}

function legacyCopy(text: string): boolean {
  // Parent the scratch textarea to the open dialog rather than <body>: both callers render
  // inside a Radix dialog, whose focus trap pulls focus back synchronously on focusin and
  // clears the selection before execCommand can read it.
  const host = document.querySelector('[role="dialog"]') ?? document.body

  const textarea = document.createElement("textarea")
  textarea.value = text
  textarea.readOnly = true
  textarea.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;"
  host.appendChild(textarea)

  try {
    textarea.select()
    textarea.setSelectionRange(0, text.length)
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    textarea.remove()
  }
}

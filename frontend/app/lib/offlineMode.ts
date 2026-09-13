/**
 * The offline-mode switch, as a storage key and a synchronous reader.
 *
 * Deliberately dependency-free: api.ts's 401 interceptor and AuthContext both need
 * to know the mode, and routing that through a provider would mean an import cycle
 * or a module-level mirror that can fall out of step with the stored value.
 */

export const OFFLINE_MODE_STORAGE_KEY = "offline:mode"

export function readOfflineMode(): boolean {
  try {
    return localStorage.getItem(OFFLINE_MODE_STORAGE_KEY) === "on"
  } catch {
    // Private mode, or storage disabled entirely.
    return false
  }
}

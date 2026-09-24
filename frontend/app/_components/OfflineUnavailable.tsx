"use client"

import { SignalSlashIcon } from "@heroicons/react/24/outline"

import { useOffline } from "@/app/context/OfflineContext"

/**
 * Placeholder for the views that need the server.
 *
 * Subscriptions, clips, tasks, stats and settings are all live server state with
 * nothing cached behind them. Shown instead of letting them mount and hang on a
 * request that cannot complete: a spinner that never resolves reads as a broken
 * app, and an error toast reads as a bug rather than a mode the user chose.
 */
export function OfflineUnavailable({ label }: { label: string }) {
  const { setOfflineMode } = useOffline()

  return (
    <div className="flex flex-col items-center justify-center gap-3 py-20 text-center">
      <SignalSlashIcon className="h-10 w-10 text-status-warning" />
      <p className="font-mono text-sm text-text-secondary">
        {label} isn&apos;t available in offline mode.
      </p>
      <p className="font-mono text-xs text-text-muted">
        Your downloaded media is still on the Downloads tab.
      </p>
      <button
        type="button"
        onClick={() => setOfflineMode(false)}
        className="mt-1 px-3 py-1 text-xs font-mono rounded text-matrix hover:bg-matrix/10 transition-colors"
      >
        Go back online
      </button>
    </div>
  )
}

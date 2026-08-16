/** Shared by the full-page auth screens, which use raw inputs rather than the ui/input primitive. */
export const authInputClass =
  "w-full px-3 py-2 bg-bg-void border border-border rounded font-mono text-sm text-text-primary focus:border-matrix focus:outline-hidden"

/** Likewise for their submit buttons, which are raw <button>s rather than ui/button. */
export const authSubmitClass =
  "w-full py-2 bg-matrix/20 border border-matrix/50 rounded font-mono text-sm text-matrix hover:bg-matrix/30 transition-colors disabled:opacity-50"

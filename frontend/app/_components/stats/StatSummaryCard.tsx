export function StatSummaryCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-bg-elevated border border-border rounded-lg p-4 text-center">
      <p className="text-2xl font-mono font-bold text-matrix">{value}</p>
      <p className="text-sm text-text-secondary mt-1">{label}</p>
      {sub && <p className="text-xs text-text-muted mt-0.5">{sub}</p>}
    </div>
  )
}

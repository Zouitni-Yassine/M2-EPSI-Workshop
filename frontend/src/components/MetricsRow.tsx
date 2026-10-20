import type { Metrics } from '../types'

export function MetricsRow({ metrics }: { metrics: Metrics }) {
  const items = [
    { label: 'Requêtes / s', value: metrics.rps.toLocaleString('fr-FR') },
    { label: 'Taux d’erreur', value: `${(metrics.errRate * 100).toFixed(1)} %` },
    { label: 'Latence p95', value: `${metrics.p95.toLocaleString('fr-FR')} ms` },
    { label: 'Blocages WAF', value: metrics.wafBlocks.toLocaleString('fr-FR') },
  ]

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {items.map((m) => (
        <div key={m.label} className="rounded-panel border border-edge bg-card px-5 py-4 shadow-panel">
          <div className="text-xs text-text-2">{m.label}</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">{m.value}</div>
        </div>
      ))}
    </div>
  )
}

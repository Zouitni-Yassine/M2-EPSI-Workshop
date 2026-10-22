import type { Metrics, WafState } from '../types'

const ND = 'n/d'

function hhmm(ms: number): string {
  return new Date(ms).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

export function MetricsRow({ metrics, waf }: { metrics: Metrics; waf?: WafState }) {
  // En mode démo (mock), pas de WAF réel : on garde la valeur du scénario.
  const blocks = waf ? waf.blocks15m : metrics.wafBlocks
  const banned = waf?.banned
  const source =
    metrics.source === 'victoriametrics'
      ? 'VictoriaMetrics · toutes les requêtes de payment-api, 2 min'
      : metrics.source === 'api'
        ? 'payment-api (/api/status, 10 s) · VictoriaMetrics injoignable'
        : undefined

  const items = [
    { label: 'Requêtes / s', value: metrics.rps.toLocaleString('fr-FR') },
    { label: 'Taux d’erreur', value: `${(metrics.errRate * 100).toFixed(1)} %` },
    { label: 'Latence p95', value: `${metrics.p95.toLocaleString('fr-FR')} ms` },
  ]

  return (
    <div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {items.map((m) => (
          <div key={m.label} className="rounded-panel border border-edge bg-card px-5 py-4 shadow-panel">
            <div className="text-xs text-text-2">{m.label}</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight">{m.value}</div>
          </div>
        ))}
        <div
          className={`rounded-panel border px-5 py-4 shadow-panel ${
            banned && banned.length > 0 ? 'border-bad/30 bg-bad/5' : 'border-edge bg-card'
          }`}
        >
          <div className="text-xs text-text-2">{waf ? 'Blocages WAF · 15 min' : 'Blocages WAF'}</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">{blocks === null ? ND : blocks.toLocaleString('fr-FR')}</div>
          {waf ? (
            <div className="mt-1 text-xs text-text-2">
              {banned == null ? (
                'IP bannies : n/d'
              ) : banned.length === 0 ? (
                'Aucune IP bannie'
              ) : (
                <ul className="space-y-0.5">
                  {banned.slice(0, 3).map((b) => (
                    <li key={b.ip} className="truncate text-bad" title={b.reason}>
                      {b.ip} bannie → {hhmm(b.until)}
                    </li>
                  ))}
                  {banned.length > 3 ? <li>+ {banned.length - 3} autre(s)</li> : null}
                </ul>
              )}
            </div>
          ) : null}
        </div>
      </div>
      {source || waf ? (
        <p className="mt-2 px-1 text-xs text-text-2">
          {source}
          {source && waf ? ' — ' : ''}
          {waf ? 'WAF : journaux de waf01 dans Loki' : ''}
        </p>
      ) : null}
    </div>
  )
}

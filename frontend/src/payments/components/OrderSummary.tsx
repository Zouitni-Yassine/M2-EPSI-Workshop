import { euros } from '../domain/money'
import type { Cents } from '../domain/types'

const LINES = [
  { label: 'Abonnement Résilience — Entreprise', detail: 'Facturation mensuelle', qty: 1, unit: 19_900 },
  { label: 'Sièges supplémentaires', detail: '12 utilisateurs', qty: 12, unit: 1_500 },
  { label: 'Support prioritaire 24/7', detail: 'Engagement de réponse 15 min', qty: 1, unit: 4_900 },
]

export const SUBTOTAL: Cents = LINES.reduce((s, l) => s + l.qty * l.unit, 0)
export const VAT: Cents = Math.round(SUBTOTAL * 0.2)
export const TOTAL: Cents = SUBTOTAL + VAT

export function OrderSummary() {
  return (
    <div className="rounded-panel border border-edge bg-card shadow-panel">
      <div className="px-6 pt-6">
        <p className="text-sm text-text-2">Montant à régler</p>
        <p className="mt-1 text-4xl font-semibold tracking-tight">{euros(TOTAL)}</p>
      </div>

      <ul className="mt-6 divide-y divide-edge border-t border-edge">
        {LINES.map((l) => (
          <li key={l.label} className="flex items-start justify-between gap-6 px-6 py-4">
            <div className="min-w-0">
              <p className="text-sm font-medium">{l.label}</p>
              <p className="mt-0.5 text-xs text-text-2">{l.detail}</p>
            </div>
            <p className="shrink-0 text-sm font-medium">{euros(l.qty * l.unit)}</p>
          </li>
        ))}
      </ul>

      <dl className="space-y-2 border-t border-edge px-6 py-4 text-sm">
        <div className="flex justify-between">
          <dt className="text-text-2">Sous-total</dt>
          <dd>{euros(SUBTOTAL)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-2">TVA 20 %</dt>
          <dd>{euros(VAT)}</dd>
        </div>
        <div className="flex justify-between border-t border-edge pt-3 text-base font-semibold">
          <dt>Total</dt>
          <dd>{euros(TOTAL)}</dd>
        </div>
      </dl>
    </div>
  )
}

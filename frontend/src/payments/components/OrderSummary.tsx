import { euros } from '../domain/money'
import type { Cents } from '../domain/types'

export interface SummaryLine {
  label: string
  detail: string
  qty: number
  unit: Cents
}

/** Commande de démonstration : l'onglet Paiement des opérateurs l'utilise tel quel. */
export const DEMO_LINES: SummaryLine[] = [
  { label: 'Abonnement Résilience — Entreprise', detail: 'Facturation mensuelle', qty: 1, unit: 19_900 },
  { label: 'Sièges supplémentaires', detail: '12 utilisateurs', qty: 12, unit: 1_500 },
  { label: 'Support prioritaire 24/7', detail: 'Engagement de réponse 15 min', qty: 1, unit: 4_900 },
]

export interface Totals {
  subtotal: Cents
  vat: Cents
  total: Cents
}

export function summarize(lines: SummaryLine[]): Totals {
  const subtotal = lines.reduce((s, l) => s + l.qty * l.unit, 0)
  const vat = Math.round(subtotal * 0.2)
  return { subtotal, vat, total: subtotal + vat }
}

export const TOTAL: Cents = summarize(DEMO_LINES).total

export function OrderSummary({ lines = DEMO_LINES }: { lines?: SummaryLine[] }) {
  const { subtotal, vat, total } = summarize(lines)
  return (
    <div className="rounded-panel border border-edge bg-card shadow-panel">
      <div className="px-6 pt-6">
        <p className="text-sm text-text-2">Montant à régler</p>
        <p className="mt-1 text-4xl font-semibold tracking-tight">{euros(total)}</p>
      </div>

      <ul className="mt-6 divide-y divide-edge border-t border-edge">
        {lines.map((l) => (
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
          <dd>{euros(subtotal)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-text-2">TVA 20 %</dt>
          <dd>{euros(vat)}</dd>
        </div>
        <div className="flex justify-between border-t border-edge pt-3 text-base font-semibold">
          <dt>Total</dt>
          <dd>{euros(total)}</dd>
        </div>
      </dl>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { euros } from './domain/money'
import type { Balance, IntentStatus, PaymentIntent } from './domain/types'
import { usePaymentEngine } from './engine'
import { BrandLogo } from './components/BrandLogo'

const STATUS_LABEL: Record<IntentStatus, string> = {
  requires_confirmation: 'À confirmer',
  requires_action: 'Authentification',
  processing: 'En cours',
  succeeded: 'Acceptée',
  canceled: 'Refusée',
}

const STATUS_CHIP: Record<IntentStatus, string> = {
  requires_confirmation: 'bg-well text-text-2',
  requires_action: 'bg-accent/10 text-accent',
  processing: 'bg-accent/10 text-accent',
  succeeded: 'bg-good/10 text-good',
  canceled: 'bg-bad/10 text-bad',
}

export function LedgerPage({ version }: { version: number }) {
  const choice = usePaymentEngine()
  const [rows, setRows] = useState<PaymentIntent[]>([])
  const [balance, setBalance] = useState<Balance | null>(null)
  const [open, setOpen] = useState<PaymentIntent | null>(null)

  useEffect(() => {
    if (!choice) return
    void choice.engine.list().then(setRows)
    void choice.engine.balance().then(setBalance)
  }, [choice, version])

  const accepted = rows.filter((r) => r.status === 'succeeded')
  const volume = accepted.reduce((s, r) => s + r.amount, 0)

  return (
    <main className="mx-auto max-w-[1120px] px-6 py-10">
      <div className="flex items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Transactions</h1>
          <p className="mt-1 text-sm text-text-2">Activité du compte marchand</p>
        </div>
      </div>

      <div className="mt-8 grid gap-4 sm:grid-cols-3">
        <Tile label="Solde disponible" value={balance ? euros(balance.available) : '—'} />
        <Tile label="Encaissé aujourd’hui" value={euros(volume)} note={`${accepted.length} paiement${accepted.length > 1 ? 's' : ''}`} />
        <Tile
          label="Prochain versement"
          value={
            balance
              ? new Date(balance.nextPayoutAt).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })
              : '—'
          }
          note="Vers FR76 •••• 0189"
        />
      </div>

      <section className="mt-8 overflow-hidden rounded-panel border border-edge bg-card shadow-panel">
        {rows.length === 0 ? (
          <div className="px-6 py-16 text-center">
            <p className="text-sm font-medium">Aucune transaction</p>
            <p className="mt-1 text-sm text-text-2">Les paiements apparaîtront ici dès le premier encaissement.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge bg-well/60 text-left text-xs font-medium text-text-2">
                <th className="px-6 py-3">Montant</th>
                <th className="px-6 py-3">État</th>
                <th className="px-6 py-3">Carte</th>
                <th className="px-6 py-3">Référence</th>
                <th className="px-6 py-3 text-right">Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-edge">
              {rows.map((r) => (
                <tr
                  key={r.id}
                  tabIndex={0}
                  onClick={() => setOpen(r)}
                  onKeyDown={(e) => e.key === 'Enter' && setOpen(r)}
                  className="cursor-pointer transition-colors hover:bg-well/60"
                >
                  <td className="px-6 py-3.5 font-medium">{euros(r.amount)}</td>
                  <td className="px-6 py-3.5">
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_CHIP[r.status]}`}>
                      {STATUS_LABEL[r.status]}
                    </span>
                    {r.error ? <span className="ml-2 text-xs text-text-2">{r.error.code}</span> : null}
                  </td>
                  <td className="px-6 py-3.5">
                    <span className="inline-flex items-center gap-2">
                      <span className="h-4 w-7 text-[#1a1f71]">
                        <BrandLogo brand={r.card.brand} className="h-full w-full" />
                      </span>
                      <span className="text-text-2">•••• {r.card.last4}</span>
                    </span>
                  </td>
                  <td className="px-6 py-3.5 text-text-2">{r.reference}</td>
                  <td className="px-6 py-3.5 text-right text-text-2">
                    {new Date(r.createdAt).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {open ? <Drawer intent={open} onClose={() => setOpen(null)} /> : null}
    </main>
  )
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-panel border border-edge bg-card px-5 py-4 shadow-panel">
      <p className="text-sm text-text-2">{label}</p>
      <p className="mt-1 text-2xl font-semibold tracking-tight">{value}</p>
      {note ? <p className="mt-1 text-xs text-text-2">{note}</p> : null}
    </div>
  )
}

function Drawer({ intent, onClose }: { intent: PaymentIntent; onClose: () => void }) {
  return (
    <div className="fade fixed inset-0 z-50 flex justify-end bg-text/40 backdrop-blur-sm" onClick={onClose}>
      <aside
        role="dialog"
        aria-label={`Transaction ${intent.reference}`}
        onClick={(e) => e.stopPropagation()}
        className="rise h-full w-full max-w-md overflow-y-auto bg-card shadow-float"
      >
        <div className="flex items-start justify-between gap-4 border-b border-edge px-6 py-5">
          <div>
            <p className="text-sm text-text-2">{intent.reference}</p>
            <p className="mt-1 text-3xl font-semibold tracking-tight">{euros(intent.amount)}</p>
            <span className={`mt-2 inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_CHIP[intent.status]}`}>
              {STATUS_LABEL[intent.status]}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Fermer"
            className="grid size-9 place-items-center rounded-lg text-text-2 transition-colors hover:bg-well hover:text-text"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
              <path d="M2 2l10 10M12 2L2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <dl className="divide-y divide-edge border-b border-edge text-sm">
          {[
            ['Carte', `${intent.card.brand} •••• ${intent.card.last4}`],
            ['Titulaire', intent.card.holder],
            ['Identifiant', intent.id],
            ['Clé d’idempotence', intent.idempotencyKey],
            ...(intent.error ? [['Motif du refus', intent.error.code]] : []),
          ].map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-6 px-6 py-3">
              <dt className="text-text-2">{k}</dt>
              <dd className="truncate text-right font-medium">{v}</dd>
            </div>
          ))}
        </dl>

        <div className="px-6 py-5">
          <h3 className="text-sm font-semibold">Historique</h3>
          <ol className="mt-4 space-y-4">
            {intent.history.map((h, i) => (
              <li key={i} className="flex gap-3">
                <span className="relative mt-1.5 flex size-2 shrink-0">
                  <span
                    className={`size-2 rounded-full ${
                      h.status === 'succeeded' ? 'bg-good' : h.status === 'canceled' ? 'bg-bad' : 'bg-accent'
                    }`}
                  />
                </span>
                <div className="min-w-0">
                  <p className="text-sm">{h.note}</p>
                  <p className="mt-0.5 text-xs text-text-2">
                    {h.at} · {h.status}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </div>
  )
}

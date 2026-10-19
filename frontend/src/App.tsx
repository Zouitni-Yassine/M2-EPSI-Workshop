import { useState } from 'react'
import { LedgerPage } from './payments/LedgerPage'
import { PayPage } from './payments/PayPage'
import { OpsPage } from './ops/OpsPage'

type View = 'pay' | 'ledger' | 'ops'

const TABS: { id: View; label: string }[] = [
  { id: 'pay', label: 'Paiement' },
  { id: 'ledger', label: 'Transactions' },
  { id: 'ops', label: 'Supervision' },
]

export default function App() {
  const [view, setView] = useState<View>('pay')
  // Incrémenté à chaque paiement abouti pour que le journal se recharge.
  const [version, setVersion] = useState(0)

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-edge bg-card/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-6 px-6 py-3">
          <div className="flex items-center gap-3">
            <Wordmark />
            <span className="rounded-md bg-note/10 px-2 py-0.5 text-[11px] font-semibold text-note">
              Mode test
            </span>
          </div>
          <nav className="flex rounded-lg bg-well p-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setView(t.id)}
                aria-current={view === t.id ? 'page' : undefined}
                className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${
                  view === t.id ? 'bg-card text-text shadow-panel' : 'text-text-2 hover:text-text'
                }`}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {view === 'pay' ? (
        <PayPage onPaid={() => setVersion((v) => v + 1)} />
      ) : view === 'ledger' ? (
        <LedgerPage version={version} />
      ) : (
        <OpsPage />
      )}
    </div>
  )
}

function Wordmark() {
  return (
    <span className="flex items-center gap-2">
      <span className="grid size-7 place-items-center rounded-md bg-accent text-white">
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
          <path d="M2 7h10M7 2v10" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Resilience Pay</span>
    </span>
  )
}

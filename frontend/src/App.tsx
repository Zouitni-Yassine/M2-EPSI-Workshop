import { useState } from 'react'
import { LoginPage } from './auth/LoginPage'
import { logout, useAuth, type SessionUser } from './auth/session'
import { Wordmark } from './components/Wordmark'
import { LedgerPage } from './payments/LedgerPage'
import { PayPage } from './payments/PayPage'
import { OpsPage } from './ops/OpsPage'

type View = 'pay' | 'ledger' | 'ops'

const TABS: { id: View; label: string; operatorOnly?: boolean }[] = [
  { id: 'pay', label: 'Paiement' },
  { id: 'ledger', label: 'Transactions' },
  { id: 'ops', label: 'Supervision', operatorOnly: true },
]

const ROLE_LABEL: Record<SessionUser['role'], string> = { client: 'Client', operator: 'Opérateur' }

export default function App() {
  const { session, notice } = useAuth()
  if (!session) return <LoginPage notice={notice} />
  // La clé remonte l'espace de travail à chaque changement de compte : onglet et journal repartent de zéro.
  return <Workspace key={session.user.username} user={session.user} />
}

function Workspace({ user }: { user: SessionUser }) {
  const [view, setView] = useState<View>('pay')
  // Incrémenté à chaque paiement abouti pour que le journal se recharge.
  const [version, setVersion] = useState(0)

  const operator = user.role === 'operator'
  // Masquer l'onglet ne protège rien : c'est l'API qui refuse. Ici, on évite juste un écran vide.
  const tabs = TABS.filter((t) => operator || !t.operatorOnly)

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-40 border-b border-edge bg-card/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-x-6 gap-y-3 px-6 py-3">
          <div className="flex items-center gap-3">
            <Wordmark />
            <span className="rounded-md bg-note/10 px-2 py-0.5 text-[11px] font-semibold text-note">
              Mode test
            </span>
          </div>
          <div className="flex items-center gap-4">
            <nav className="flex rounded-lg bg-well p-1">
              {tabs.map((t) => (
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
            <div className="flex items-center gap-3 border-l border-edge pl-4">
              <span className="hidden text-right leading-tight sm:block">
                <span className="block text-sm font-medium">{user.username}</span>
                <span className="block text-[11px] text-text-2">{ROLE_LABEL[user.role]}</span>
              </span>
              <button
                type="button"
                onClick={logout}
                className="rounded-md px-2.5 py-1.5 text-sm font-medium text-text-2 transition-colors hover:bg-well hover:text-text"
              >
                Déconnexion
              </button>
            </div>
          </div>
        </div>
      </header>

      {view === 'ops' && operator ? (
        <OpsPage />
      ) : view === 'ledger' ? (
        <LedgerPage version={version} operator={operator} />
      ) : (
        <PayPage onPaid={() => setVersion((v) => v + 1)} />
      )}
    </div>
  )
}

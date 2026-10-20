import { useEffect, useRef, useState } from 'react'
import { LoginPage } from './auth/LoginPage'
import { useAuth } from './auth/session'
import { LedgerPage } from './payments/LedgerPage'
import { PayPage } from './payments/PayPage'
import { OpsPage } from './ops/OpsPage'
import { ShopHeader, type AdminView } from './shop/ShopHeader'
import { ShopPage } from './shop/ShopPage'

type View = 'shop' | 'login' | AdminView

// Lien du mail de réinitialisation : /?reset=<jeton>. Lu une seule fois, au chargement.
const RESET_TOKEN = new URLSearchParams(window.location.search).get('reset') ?? undefined

export default function App() {
  const { session, notice } = useAuth()
  const [view, setView] = useState<View>(RESET_TOKEN ? 'login' : 'shop')
  // Incrémenté à chaque paiement abouti pour que le journal se recharge.
  const [version, setVersion] = useState(0)

  const user = session?.user ?? null
  const operator = user?.role === 'operator'

  // Connexion réussie ou session terminée : on revient à la boutique. Uniquement quand la
  // session change vraiment : au montage (même doublé par StrictMode), on ne touche à rien,
  // pour qu'un lien de réinitialisation affiche d'abord son formulaire.
  const prevSession = useRef(session)
  useEffect(() => {
    if (prevSession.current !== session) {
      prevSession.current = session
      setView('shop')
    }
  }, [session])

  if (view === 'login' && !user) {
    return <LoginPage notice={notice} onBack={() => setView('shop')} resetToken={RESET_TOKEN} />
  }

  const adminView: AdminView | null = operator && (view === 'pay' || view === 'ledger' || view === 'ops') ? view : null

  return (
    <div className="min-h-full">
      <ShopHeader
        user={user}
        adminView={adminView}
        onShop={() => setView('shop')}
        onAdmin={(v) => setView(v)}
        onLogin={() => setView('login')}
      />

      {adminView === 'ops' ? (
        <OpsPage />
      ) : adminView === 'ledger' ? (
        <LedgerPage version={version} operator />
      ) : adminView === 'pay' ? (
        <PayPage onPaid={() => setVersion((v) => v + 1)} />
      ) : (
        <ShopPage
          key={user?.username ?? 'invite'}
          user={user}
          onPaid={() => setVersion((v) => v + 1)}
          onRequireLogin={() => setView('login')}
        />
      )}
    </div>
  )
}

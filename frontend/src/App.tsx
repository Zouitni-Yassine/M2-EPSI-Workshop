import { useEffect, useRef, useState } from 'react'
import { LoginPage } from './auth/LoginPage'
import { useAuth } from './auth/session'
import { LedgerPage } from './payments/LedgerPage'
import { OpsPage } from './ops/OpsPage'
import { ShopHeader, type AdminView } from './shop/ShopHeader'
import { ShopPage } from './shop/ShopPage'

type View = 'shop' | 'login' | 'orders' | AdminView

// Lien du mail de réinitialisation : /?reset=<jeton>. Lu au chargement, puis l'URL est
// nettoyée tout de suite : un rechargement ou un retour au login ne rejoue pas le formulaire.
const INITIAL_RESET = (() => {
  const token = new URLSearchParams(window.location.search).get('reset') ?? undefined
  if (token) window.history.replaceState(null, '', window.location.pathname)
  return token
})()

export default function App() {
  const { session, notice } = useAuth()
  const [view, setView] = useState<View>(INITIAL_RESET ? 'login' : 'shop')
  const [resetToken, setResetToken] = useState(INITIAL_RESET)
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
      setResetToken(undefined)
      setView('shop')
    }
  }, [session])

  if (view === 'login' && !user) {
    return <LoginPage notice={notice} onBack={() => setView('shop')} resetToken={resetToken} onClearReset={() => setResetToken(undefined)} />
  }

  const adminView: AdminView | null = operator && (view === 'ledger' || view === 'ops') ? view : null

  return (
    <div className="min-h-full">
      <ShopHeader
        user={user}
        adminView={adminView}
        onShop={() => setView('shop')}
        onAdmin={(v) => setView(v)}
        onLogin={() => setView('login')}
        onOrders={() => setView('orders')}
      />

      {adminView === 'ops' ? (
        <OpsPage />
      ) : adminView === 'ledger' ? (
        <LedgerPage version={version} operator />
      ) : view === 'orders' && user ? (
        <LedgerPage version={version} operator={false} />
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

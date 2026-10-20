import { useEffect, useState } from 'react'
import { LoginPage } from './auth/LoginPage'
import { useAuth } from './auth/session'
import { LedgerPage } from './payments/LedgerPage'
import { PayPage } from './payments/PayPage'
import { OpsPage } from './ops/OpsPage'
import { ShopHeader, type AdminView } from './shop/ShopHeader'
import { ShopPage } from './shop/ShopPage'

type View = 'shop' | 'login' | AdminView

export default function App() {
  const { session, checking, notice } = useAuth()
  const [view, setView] = useState<View>('shop')
  // Incrémenté à chaque paiement abouti pour que le journal se recharge.
  const [version, setVersion] = useState(0)

  const user = session?.user ?? null
  const operator = user?.role === 'operator'

  // Connexion réussie ou session terminée : on revient à la boutique.
  useEffect(() => {
    setView('shop')
  }, [session])

  // Le temps de demander au serveur si le cookie ouvre encore une session : pas de boutique
  // affichée « déconnectée » une fraction de seconde à un client qui l'est.
  if (checking) return null

  if (view === 'login' && !user) {
    return <LoginPage notice={notice} onBack={() => setView('shop')} />
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

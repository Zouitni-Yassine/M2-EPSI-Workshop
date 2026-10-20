import { logout, type SessionUser } from '../auth/session'
import { useCart } from './cart'
import { CATEGORIES } from './catalog'
import { openCart, setCategory, setQuery, useShopUI } from './ui'

export type AdminView = 'pay' | 'ledger' | 'ops'

const ADMIN_TABS: { id: AdminView; label: string }[] = [
  { id: 'pay', label: 'Paiement' },
  { id: 'ledger', label: 'Transactions' },
  { id: 'ops', label: 'Supervision' },
]

interface Props {
  user: SessionUser | null
  adminView: AdminView | null
  onShop: () => void
  onAdmin: (view: AdminView) => void
  onLogin: () => void
}

export function ShopHeader({ user, adminView, onShop, onAdmin, onLogin }: Props) {
  const { count } = useCart()
  const { query, category } = useShopUI()
  const operator = user?.role === 'operator'

  function goCategory(id: Parameters<typeof setCategory>[0]) {
    setCategory(id)
    onShop()
  }

  return (
    <header className="sticky top-0 z-40 bg-card shadow-[0_1px_0_var(--color-edge)]">
      {/* Bandeau annonce */}
      <div className="bg-inkwarm px-6 py-1.5 text-center text-[12.5px] font-medium text-paper">
        Livraison offerte dès 150 € — boutique de démonstration, paiements en mode test
      </div>

      {/* Logo · recherche · compte · panier */}
      <div className="mx-auto flex max-w-[1360px] items-center gap-6 px-6 py-3.5">
        <button type="button" onClick={() => goCategory('tout')} aria-label="Accueil YAZNOW" className="shrink-0">
          <span className="font-head text-[26px] font-extrabold tracking-tight">YAZNOW</span>
        </button>

        <div className="relative mx-auto w-full max-w-[640px]">
          <svg aria-hidden="true" viewBox="0 0 20 20" className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-text-2">
            <circle cx="9" cy="9" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
            <path d="m14 14 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
          <input
            id="shop-search"
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              onShop()
            }}
            placeholder="Que cherchez-vous ?"
            aria-label="Rechercher un produit"
            className="h-11 w-full rounded-full border border-edge bg-card pl-11 pr-5 text-[15px] outline-none transition-colors placeholder:text-text-2 focus:border-inkwarm"
          />
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {user ? (
            <div className="flex items-center gap-2">
              <span className="hidden text-right leading-tight lg:block">
                <span className="block text-sm font-semibold">{user.username}</span>
                <span className="block text-[11px] text-text-2">{user.role === 'operator' ? 'Opérateur' : 'Client'}</span>
              </span>
              <button
                type="button"
                onClick={logout}
                className="rounded-full px-3 py-2 text-sm font-medium text-text-2 transition-colors hover:bg-well hover:text-text"
              >
                Déconnexion
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={onLogin}
              className="flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold transition-colors hover:bg-well"
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6">
                <circle cx="12" cy="8.2" r="3.7" fill="none" stroke="currentColor" strokeWidth="1.7" />
                <path d="M4.8 19.5a7.6 7.6 0 0 1 14.4 0" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              </svg>
              Se connecter
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              onShop()
              openCart()
            }}
            aria-label={`Panier, ${count} article${count > 1 ? 's' : ''}`}
            className="relative rounded-full p-2.5 transition-colors hover:bg-well"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6">
              <path d="M4 7h16l-1.3 12.2a1.8 1.8 0 0 1-1.8 1.6H7.1a1.8 1.8 0 0 1-1.8-1.6Z" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
              <path d="M8.6 9.5V6.4a3.4 3.4 0 0 1 6.8 0v3.1" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
            {count > 0 ? (
              <span className="absolute -right-0.5 -top-0.5 grid size-5 place-items-center rounded-full bg-inkwarm text-[11px] font-bold text-paper">
                {count}
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {/* Navigation catégories + sections opérateur */}
      <nav aria-label="Navigation principale" className="border-t border-edge">
        <div className="mx-auto flex max-w-[1360px] items-center justify-between gap-4 overflow-x-auto px-6">
          <div className="flex items-center gap-1">
            {[{ id: 'tout' as const, label: 'Tout' }, ...CATEGORIES.map(({ id, label }) => ({ id, label }))].map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => goCategory(c.id)}
                aria-current={adminView === null && category === c.id ? 'page' : undefined}
                className={`whitespace-nowrap border-b-2 px-3.5 py-3 text-sm font-medium transition-colors ${
                  adminView === null && category === c.id
                    ? 'border-inkwarm text-text'
                    : 'border-transparent text-text-2 hover:text-text'
                }`}
              >
                {c.label}
              </button>
            ))}
          </div>
          {operator ? (
            <div className="flex items-center gap-1">
              {ADMIN_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => onAdmin(t.id)}
                  aria-current={adminView === t.id ? 'page' : undefined}
                  className={`whitespace-nowrap border-b-2 px-3.5 py-3 text-sm font-medium transition-colors ${
                    adminView === t.id ? 'border-accent text-accent' : 'border-transparent text-text-2 hover:text-text'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </nav>
    </header>
  )
}

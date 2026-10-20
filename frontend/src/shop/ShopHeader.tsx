import { useEffect, useState } from 'react'
import { logout, type SessionUser } from '../auth/session'
import { useCart } from './cart'
import { SECTIONS } from './catalog'
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
  // Comme les grandes boutiques : header complet en haut de page, condensé dès qu'on descend.
  const [condensed, setCondensed] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)

  useEffect(() => {
    const onScroll = () => {
      // Hystérésis : on condense après 140 px, on rouvre sous 40 px, sans clignoter entre les deux.
      setCondensed((c) => (c ? window.scrollY > 40 : window.scrollY > 140))
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (!condensed) setMenuOpen(false)
  }, [condensed])

  function goCategory(id: Parameters<typeof setCategory>[0]) {
    setMenuOpen(false)
    setCategory(id)
    onShop()
  }

  return (
    <header className="sticky top-0 z-40 bg-card shadow-[0_1px_0_var(--color-edge)]">
      {/* Bandeau annonce — replié une fois qu'on descend */}
      <div
        className={`overflow-hidden bg-inkwarm text-center text-[12.5px] font-medium text-paper transition-all duration-300 ${
          condensed ? 'max-h-0' : 'max-h-10 px-6 py-1.5'
        }`}
      >
        Livraison offerte dès 150 € — boutique de démonstration, paiements en mode test
      </div>

      {/* Logo · recherche · compte · panier */}
      <div className="flex items-center gap-4 px-6 py-3.5 sm:gap-6 lg:px-9">
        <button
          type="button"
          onClick={() => setMenuOpen((o) => !o)}
          aria-label={menuOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
          aria-expanded={menuOpen}
          className={`grid shrink-0 place-items-center overflow-hidden rounded-full transition-all duration-300 hover:bg-well ${
            condensed ? 'size-10 opacity-100' : 'w-0 opacity-0'
          }`}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6">
            {menuOpen ? (
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            ) : (
              <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            )}
          </svg>
        </button>
        <button type="button" onClick={() => goCategory('tout')} aria-label="Accueil YAZNOW" className="shrink-0">
          <span className="font-logo text-[26px] font-bold tracking-tight text-logo">YAZNOW</span>
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
            <div className="relative">
              <button
                type="button"
                onClick={() => setAccountOpen((o) => !o)}
                aria-expanded={accountOpen}
                className="flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold transition-colors hover:bg-well"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" className="size-6">
                  <circle cx="12" cy="8.2" r="3.7" fill="none" stroke="currentColor" strokeWidth="1.7" />
                  <path d="M4.8 19.5a7.6 7.6 0 0 1 14.4 0" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
                <span className="hidden sm:block">{user.firstName || user.username}</span>
              </button>
              {accountOpen ? (
                <div className="rise absolute right-0 top-full mt-2 w-44 overflow-hidden rounded-lg border border-edge bg-card py-1 shadow-float">
                  <button
                    type="button"
                    onClick={() => {
                      setAccountOpen(false)
                      logout()
                    }}
                    className="block w-full px-4 py-2.5 text-left text-sm font-medium transition-colors hover:bg-well"
                  >
                    Déconnexion
                  </button>
                </div>
              ) : null}
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

      {/* Navigation catégories + sections opérateur — repliée une fois qu'on descend */}
      <nav
        aria-label="Navigation principale"
        className={`overflow-hidden border-t border-edge transition-all duration-300 ${
          condensed && !menuOpen ? 'max-h-0 border-transparent' : 'max-h-14'
        }`}
      >
        <div className="flex items-center justify-center gap-1 overflow-x-auto px-6">
          {SECTIONS.map((c) => {
            const current = adminView === null && category === c.id
            let tone = 'border-transparent text-text-2 hover:text-text'
            if (current) tone = 'border-inkwarm text-text'
            if (c.accent) tone = current ? 'border-bad text-bad' : 'border-transparent text-bad hover:opacity-75'
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => goCategory(c.id)}
                aria-current={current ? 'page' : undefined}
                className={`whitespace-nowrap border-b-2 px-3.5 py-3 text-[15px] font-medium transition-colors ${tone}`}
              >
                {c.label}
              </button>
            )
          })}
          {operator ? (
            <>
              <span aria-hidden="true" className="mx-2 h-5 w-px shrink-0 bg-edge" />
              {ADMIN_TABS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => onAdmin(t.id)}
                  aria-current={adminView === t.id ? 'page' : undefined}
                  className={`whitespace-nowrap border-b-2 px-3.5 py-3 text-[15px] font-medium transition-colors ${
                    adminView === t.id ? 'border-accent text-accent' : 'border-transparent text-text-2 hover:text-text'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </>
          ) : null}
        </div>
      </nav>

    </header>
  )
}

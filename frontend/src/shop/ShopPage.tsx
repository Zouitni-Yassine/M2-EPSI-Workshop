import { useState } from 'react'
import { euros } from '../payments/domain/money'
import type { SummaryLine } from '../payments/components/OrderSummary'
import { PayPage } from '../payments/PayPage'
import { ProductArt } from './art'
import { clearCart, addToCart, useCart } from './cart'
import { CATEGORIES, PRODUCTS, type Category, type Product } from './catalog'
import { CartDrawer } from './CartDrawer'
import { ProductSheet } from './ProductSheet'

type Stage = 'browse' | 'checkout'

export function ShopPage({ onPaid }: { onPaid: () => void }) {
  const [stage, setStage] = useState<Stage>('browse')
  const [filter, setFilter] = useState<Category | 'tout'>('tout')
  const [open, setOpen] = useState<Product | null>(null)
  const [cartOpen, setCartOpen] = useState(false)
  // Figée à l'entrée du paiement : le reçu reste juste même une fois le panier vidé.
  const [order, setOrder] = useState<SummaryLine[]>([])
  const { lines, count } = useCart()

  function toCheckout() {
    setOrder(
      lines.map(({ product, qty }) => ({
        label: product.name,
        detail: product.detail,
        qty,
        unit: product.price,
      })),
    )
    setCartOpen(false)
    setStage('checkout')
  }

  if (stage === 'checkout') {
    return (
      <div>
        <div className="mx-auto max-w-[1120px] px-6 pt-6">
          <button
            type="button"
            onClick={() => setStage('browse')}
            className="text-sm font-medium text-text-2 transition-colors hover:text-text"
          >
            ← Revenir à la boutique
          </button>
        </div>
        <PayPage
          order={order.length > 0 ? order : undefined}
          onPaid={() => {
            clearCart()
            onPaid()
          }}
        />
      </div>
    )
  }

  const visible = filter === 'tout' ? PRODUCTS : PRODUCTS.filter((p) => p.category === filter)

  return (
    <div className="bg-paper">
      {/* ---- Héros ---- */}
      <section className="mx-auto grid max-w-[1200px] items-center gap-10 px-6 pb-14 pt-12 lg:grid-cols-[7fr_5fr]">
        <div>
          <p className="text-sm font-medium text-walnut">Mobilier &amp; objets choisis</p>
          <h1 className="mt-3 max-w-[16ch] font-display text-5xl leading-[1.05] text-inkwarm sm:text-6xl">
            Des pièces qui font la maison.
          </h1>
          <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-text-2">
            Bois massif, lin lavé, grès émaillé main. Chaque pièce YAZNOW est choisie pour durer —
            et livrée chez vous en quelques jours.
          </p>
          <div className="mt-7 flex items-center gap-4">
            <a
              href="#collection"
              className="rounded-lg bg-inkwarm px-6 py-3 text-sm font-semibold text-paper transition-colors hover:bg-walnut"
            >
              Découvrir la collection
            </a>
            <span className="text-xs text-text-2">Livraison offerte dès 150 €</span>
          </div>
        </div>
        <div className="hidden grid-cols-2 gap-4 lg:grid" aria-hidden="true">
          <span className="grid place-items-center rounded-panel p-6" style={{ background: '#E3E0D5' }}>
            <ProductArt id="fauteuil-ryo" className="w-full max-w-[180px]" />
          </span>
          <span className="mt-10 grid place-items-center rounded-panel p-6" style={{ background: '#E8E0CC' }}>
            <ProductArt id="lampadaire-orne" className="w-full max-w-[180px]" />
          </span>
          <span className="-mt-10 grid place-items-center rounded-panel p-6" style={{ background: '#EBDFD2' }}>
            <ProductArt id="vase-terra" className="w-full max-w-[150px]" />
          </span>
          <span className="grid place-items-center rounded-panel p-6" style={{ background: '#EADFCE' }}>
            <ProductArt id="table-noma" className="w-full max-w-[180px]" />
          </span>
        </div>
      </section>

      {/* ---- Filtres + panier ---- */}
      <div className="sticky top-[57px] z-30 border-y border-edge bg-paper/95 backdrop-blur" id="collection">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6 py-3">
          <nav className="flex flex-wrap gap-2" aria-label="Catégories">
            {[{ id: 'tout' as const, label: 'Tout' }, ...CATEGORIES].map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setFilter(c.id)}
                aria-pressed={filter === c.id}
                className={`rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                  filter === c.id ? 'bg-inkwarm text-paper' : 'text-text-2 hover:bg-paper-2 hover:text-text'
                }`}
              >
                {c.label}
              </button>
            ))}
          </nav>
          <button
            type="button"
            onClick={() => setCartOpen(true)}
            className="flex items-center gap-2 rounded-lg border border-edge bg-card px-4 py-2 text-sm font-semibold transition-colors hover:border-walnut"
          >
            Panier
            <span
              className={`grid size-5 place-items-center rounded-full text-[11px] font-bold ${
                count > 0 ? 'bg-walnut text-paper' : 'bg-well text-text-2'
              }`}
              aria-label={`${count} article${count > 1 ? 's' : ''} dans le panier`}
            >
              {count}
            </span>
          </button>
        </div>
      </div>

      {/* ---- Grille produits ---- */}
      <section className="mx-auto grid max-w-[1200px] gap-6 px-6 py-10 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((p) => (
          <article key={p.id} className="group overflow-hidden rounded-panel border border-edge bg-card">
            <button
              type="button"
              onClick={() => setOpen(p)}
              className="block w-full cursor-pointer"
              aria-label={`Voir ${p.name}`}
            >
              <span className="grid aspect-[11/9] place-items-center p-8 transition-transform duration-300 group-hover:scale-[1.03]" style={{ background: p.plinth }}>
                <ProductArt id={p.id} className="w-full max-w-[200px]" />
              </span>
            </button>
            <div className="flex items-start justify-between gap-4 px-5 py-4">
              <div className="min-w-0">
                <h3 className="truncate font-display text-lg text-inkwarm">{p.name}</h3>
                <p className="mt-0.5 truncate text-xs text-text-2">{p.detail}</p>
              </div>
              <p className="shrink-0 pt-0.5 text-sm font-semibold">{euros(p.price)}</p>
            </div>
            <div className="px-5 pb-5">
              <button
                type="button"
                onClick={() => addToCart(p.id)}
                className="w-full rounded-lg border border-inkwarm/20 px-4 py-2 text-sm font-semibold text-inkwarm transition-colors hover:bg-inkwarm hover:text-paper"
              >
                Ajouter au panier
              </button>
            </div>
          </article>
        ))}
      </section>

      <footer className="border-t border-edge">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-3 px-6 py-8 text-xs text-text-2">
          <span className="font-display text-base text-inkwarm">YAZNOW</span>
          <span>Boutique de démonstration — aucun produit réel, paiements en mode test.</span>
        </div>
      </footer>

      {open ? <ProductSheet product={open} onClose={() => setOpen(null)} /> : null}
      {cartOpen ? (
        <CartDrawer onClose={() => setCartOpen(false)} onCheckout={toCheckout} />
      ) : null}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { SessionUser } from '../auth/session'
import { euros } from '../payments/domain/money'
import type { SummaryLine } from '../payments/components/OrderSummary'
import { PayPage } from '../payments/PayPage'
import { addToCart, clearCart, useCart } from './cart'
import { CATEGORIES, PRODUCTS, type Product } from './catalog'
import { CartDrawer } from './CartDrawer'
import { ProductSheet } from './ProductSheet'
import { closeCart, setCategory, useShopUI } from './ui'

const SLIDES = [
  {
    image: '/img/hero-1.jpg',
    eyebrow: 'Collection automne',
    title: 'L’art d’habiter',
    text: 'Des pièces choisies pour durer, livrées chez vous en quelques jours.',
    cta: 'Découvrir la collection',
    category: 'tout' as const,
  },
  {
    image: '/img/hero-2.jpg',
    eyebrow: 'Couleur assumée',
    title: 'Osez la pièce forte',
    text: 'Un canapé qui porte la pièce entière, et tout le reste qui s’accorde.',
    cta: 'Voir le salon',
    category: 'salon' as const,
  },
  {
    image: '/img/hero-3.jpg',
    eyebrow: 'Lumière douce',
    title: 'Façonnez l’ambiance',
    text: 'Laiton, arcs et abat-jour : la lumière comme un meuble à part entière.',
    cta: 'Voir les luminaires',
    category: 'luminaires' as const,
  },
]

interface Props {
  user: SessionUser | null
  onPaid: () => void
  onRequireLogin: () => void
}

export function ShopPage({ user, onPaid, onRequireLogin }: Props) {
  const [checkout, setCheckout] = useState(false)
  const [open, setOpen] = useState<Product | null>(null)
  // Figée à l'entrée du paiement : le reçu reste juste même une fois le panier vidé.
  const [order, setOrder] = useState<SummaryLine[]>([])
  const { lines } = useCart()
  const { cartOpen, query, category } = useShopUI()

  function toCheckout() {
    closeCart()
    if (!user) {
      onRequireLogin()
      return
    }
    setOrder(
      lines.map(({ product, qty }) => ({
        label: product.name,
        detail: product.detail,
        qty,
        unit: product.price,
      })),
    )
    setCheckout(true)
  }

  if (checkout) {
    return (
      <div>
        <div className="mx-auto max-w-[1120px] px-6 pt-6">
          <button
            type="button"
            onClick={() => setCheckout(false)}
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
        {cartOpen ? <CartDrawer onCheckout={toCheckout} /> : null}
      </div>
    )
  }

  const q = query.trim().toLowerCase()
  const visible = PRODUCTS.filter(
    (p) =>
      (category === 'tout' || p.category === category) &&
      (q === '' || `${p.name} ${p.maker} ${p.detail} ${p.category}`.toLowerCase().includes(q)),
  )
  const searching = q !== ''

  return (
    <div className="bg-card">
      {!searching && category === 'tout' ? <Hero /> : null}

      {!searching && category === 'tout' ? <Departments /> : null}

      {/* ---- Produits ---- */}
      <section className="mx-auto max-w-[1360px] px-6 py-12" id="produits">
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="font-head text-2xl font-bold tracking-tight sm:text-3xl">
            {searching
              ? `Résultats pour « ${query.trim()} »`
              : category === 'tout'
                ? 'Nouveautés'
                : CATEGORIES.find((c) => c.id === category)?.label}
          </h2>
          <p className="text-sm text-text-2">{visible.length} article{visible.length > 1 ? 's' : ''}</p>
        </div>

        {visible.length === 0 ? (
          <div className="mt-10 rounded-panel border border-edge bg-well px-6 py-14 text-center">
            <p className="font-head text-lg font-semibold">Aucun article ne correspond.</p>
            <p className="mt-1 text-sm text-text-2">Essayez un autre mot, ou parcourez une catégorie.</p>
          </div>
        ) : (
          <div className="mt-8 grid grid-cols-2 gap-x-5 gap-y-10 md:grid-cols-3 xl:grid-cols-4">
            {visible.map((p) => (
              <ProductCard key={p.id} product={p} onOpen={() => setOpen(p)} />
            ))}
          </div>
        )}
      </section>

      {!searching && category === 'tout' ? <Editorial /> : null}

      <footer className="border-t border-edge bg-well">
        <div className="mx-auto grid max-w-[1360px] gap-8 px-6 py-12 sm:grid-cols-[2fr_1fr_1fr]">
          <div>
            <p className="font-head text-xl font-extrabold tracking-tight">YAZNOW</p>
            <p className="mt-2 max-w-[40ch] text-sm text-text-2">
              Mobilier et objets choisis pour durer. Boutique de démonstration : aucun produit réel,
              paiements en mode test.
            </p>
          </div>
          <div>
            <p className="text-sm font-semibold">Boutique</p>
            <ul className="mt-3 space-y-2 text-sm text-text-2">
              {CATEGORIES.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setCategory(c.id)} className="transition-colors hover:text-text">
                    {c.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-sm font-semibold">Aide</p>
            <ul className="mt-3 space-y-2 text-sm text-text-2">
              <li>Livraison offerte dès 150 €</li>
              <li>Retours sous 30 jours</li>
              <li>Paiement sécurisé — Stripe &amp; PayPal</li>
            </ul>
          </div>
        </div>
        <div className="border-t border-edge px-6 py-4 text-center text-xs text-text-2">
          Workshop M2 EPSI 2026 · Project RESILIENCE-ALPHA
        </div>
      </footer>

      {open ? <ProductSheet product={open} onClose={() => setOpen(null)} /> : null}
      {cartOpen ? <CartDrawer onCheckout={toCheckout} /> : null}
    </div>
  )
}

/* ---- Héros : carrousel de photos pleine largeur ---- */

function Hero() {
  const [index, setIndex] = useState(0)
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    timer.current = setInterval(() => setIndex((i) => (i + 1) % SLIDES.length), 5500)
    return () => clearInterval(timer.current)
  }, [])

  function go(i: number) {
    clearInterval(timer.current)
    setIndex((i + SLIDES.length) % SLIDES.length)
  }

  return (
    <section aria-label="À la une" className="relative overflow-hidden">
      <div
        className="flex transition-transform duration-700 ease-[cubic-bezier(0.25,0.8,0.25,1)]"
        style={{ transform: `translateX(-${index * 100}%)` }}
      >
        {SLIDES.map((s) => (
          <div key={s.image} className="relative aspect-[21/10] min-h-[380px] w-full shrink-0 max-h-[560px]">
            <img src={s.image} alt="" className="absolute inset-0 size-full object-cover" />
            <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/10 to-transparent" />
            <div className="absolute inset-x-0 bottom-0 mx-auto max-w-[1360px] px-[72px] pb-10 sm:pb-14">
              <p className="text-[13px] font-semibold uppercase tracking-[0.14em] text-white/85">{s.eyebrow}</p>
              <h1 className="mt-2 max-w-[14ch] font-head text-4xl font-extrabold leading-[1.04] text-white sm:text-6xl">
                {s.title}
              </h1>
              <p className="mt-3 hidden max-w-[44ch] text-[15px] text-white/85 sm:block">{s.text}</p>
              <button
                type="button"
                onClick={() => setCategory(s.category)}
                className="mt-5 inline-block border-b-2 border-white pb-0.5 text-[15px] font-semibold text-white transition-opacity hover:opacity-80"
              >
                {s.cta}
              </button>
            </div>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() => go(index - 1)}
        aria-label="Image précédente"
        className="absolute left-4 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-text shadow-panel transition-colors hover:bg-white"
      >
        ←
      </button>
      <button
        type="button"
        onClick={() => go(index + 1)}
        aria-label="Image suivante"
        className="absolute right-4 top-1/2 grid size-11 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-text shadow-panel transition-colors hover:bg-white"
      >
        →
      </button>

      <div className="absolute inset-x-0 bottom-3 flex justify-center gap-2">
        {SLIDES.map((s, i) => (
          <button
            key={s.image}
            type="button"
            onClick={() => go(i)}
            aria-label={`Aller à l’image ${i + 1}`}
            aria-current={i === index}
            className={`size-2 rounded-full transition-colors ${i === index ? 'bg-white' : 'bg-white/45'}`}
          />
        ))}
      </div>
    </section>
  )
}

/* ---- Départements ---- */

function Departments() {
  return (
    <section className="mx-auto max-w-[1360px] px-6 pt-12" aria-label="Catégories">
      <h2 className="text-center font-head text-2xl font-bold tracking-tight sm:text-3xl">Parcourir par univers</h2>
      <div className="mt-8 grid gap-5 sm:grid-cols-3">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => setCategory(c.id)}
            className="group relative overflow-hidden rounded-panel"
          >
            <img
              src={c.image}
              alt=""
              className="aspect-[4/3] w-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
            <span className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent" />
            <span className="absolute inset-x-0 bottom-4 text-center font-head text-xl font-bold text-white">
              {c.label}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

/* ---- Carte produit ---- */

const BADGE_STYLE: Record<NonNullable<Product['badge']>, string> = {
  Nouveau: 'bg-accent text-white',
  Tendance: 'bg-inkwarm text-paper',
  Promo: 'bg-bad text-white',
}

function ProductCard({ product: p, onOpen }: { product: Product; onOpen: () => void }) {
  const [added, setAdded] = useState(false)

  function add() {
    addToCart(p.id)
    setAdded(true)
    window.setTimeout(() => setAdded(false), 900)
  }

  return (
    <article className="group">
      <div className="relative overflow-hidden rounded-panel bg-well">
        <button type="button" onClick={onOpen} aria-label={`Voir ${p.name}`} className="block w-full">
          <img
            src={p.image}
            alt={p.name}
            loading="lazy"
            style={p.pos ? { objectPosition: p.pos } : undefined}
            className="aspect-[4/5] w-full object-cover transition-transform duration-500 group-hover:scale-[1.04]"
          />
        </button>
        {p.badge ? (
          <span className={`absolute left-3 top-3 rounded-full px-3 py-1 text-[11.5px] font-semibold ${BADGE_STYLE[p.badge]}`}>
            {p.badge}
          </span>
        ) : null}
        <button
          type="button"
          onClick={add}
          className={`absolute inset-x-3 bottom-3 rounded-lg py-2.5 text-sm font-semibold shadow-panel transition-all ${
            added
              ? 'bg-good text-white'
              : 'bg-white/95 text-text opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-inkwarm hover:text-paper'
          }`}
        >
          {added ? 'Ajouté au panier ✓' : 'Ajouter au panier'}
        </button>
      </div>
      <div className="mt-3">
        <p className="text-[11.5px] font-semibold uppercase tracking-[0.1em] text-text-2">{p.maker}</p>
        <button type="button" onClick={onOpen} className="mt-0.5 block text-left text-[15px] font-medium hover:underline">
          {p.name}
        </button>
        <p className="mt-1 text-[15px]">
          {p.compareAt ? (
            <>
              <span className="text-text-2 line-through">{euros(p.compareAt)}</span>{' '}
              <span className="font-semibold text-bad">{euros(p.price)}</span>
            </>
          ) : (
            <span className="font-semibold">{euros(p.price)}</span>
          )}
        </p>
      </div>
    </article>
  )
}

/* ---- Tuiles éditoriales ---- */

const TILES = [
  { image: '/img/ed-1.jpg', title: 'Un salon pensé pour durer', cta: 'Explorer le salon', category: 'salon' as const, big: true },
  { image: '/img/ed-2.jpg', title: 'Lignes épurées', cta: 'Voir la sélection', category: 'tout' as const, big: false },
  { image: '/img/ed-3.jpg', title: 'Pièces de caractère', cta: 'Voir le salon', category: 'salon' as const, big: false },
]

function Editorial() {
  return (
    <section className="mx-auto max-w-[1360px] px-6 pb-14" aria-label="Collections">
      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        {TILES.map((t) => (
          <button
            key={t.image}
            type="button"
            onClick={() => setCategory(t.category)}
            className={`group relative overflow-hidden rounded-panel text-left ${t.big ? 'aspect-[4/3] lg:row-span-2 lg:aspect-auto' : 'aspect-[21/9]'}`}
          >
            <img
              src={t.image}
              alt=""
              className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-105"
            />
            <span className="absolute inset-0 bg-gradient-to-t from-black/55 to-transparent" />
            <span className="absolute inset-x-0 bottom-0 p-6">
              <span className="block font-head text-2xl font-bold text-white">{t.title}</span>
              <span className="mt-1 inline-block border-b border-white pb-0.5 text-sm font-semibold text-white">{t.cta}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

import { useEffect } from 'react'
import { euros } from '../payments/domain/money'
import { setQty, useCart } from './cart'
import { closeCart } from './ui'

export function CartDrawer({ onCheckout }: { onCheckout: () => void }) {
  const { lines, subtotal } = useCart()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeCart()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Panier">
      <button
        type="button"
        aria-label="Fermer le panier"
        onClick={closeCart}
        className="absolute inset-0 cursor-default bg-black/40 backdrop-blur-[2px]"
      />
      <aside className="drawer-in absolute inset-y-0 right-0 flex w-full max-w-[440px] flex-col bg-card shadow-float">
        <header className="flex items-center justify-between border-b border-edge px-6 py-4">
          <h2 className="font-head text-lg font-bold">Votre panier</h2>
          <button
            type="button"
            onClick={closeCart}
            aria-label="Fermer"
            className="grid size-8 place-items-center rounded-full text-text-2 transition-colors hover:bg-well hover:text-text"
          >
            ✕
          </button>
        </header>

        {lines.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
            <p className="font-head text-lg font-semibold">Il est encore vide.</p>
            <p className="text-sm text-text-2">Parcourez la boutique et ajoutez une première pièce.</p>
          </div>
        ) : (
          <>
            <ul className="flex-1 divide-y divide-edge overflow-y-auto px-6">
              {lines.map(({ product, qty }) => (
                <li key={product.id} className="flex items-center gap-4 py-4">
                  <img
                    src={product.image}
                    alt=""
                    className="size-[72px] shrink-0 rounded-lg object-cover"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{product.name}</span>
                    <span className="mt-0.5 block text-xs text-text-2">{euros(product.price)} l’unité</span>
                    <span className="mt-2 inline-flex items-center rounded-md border border-edge">
                      <button
                        type="button"
                        onClick={() => setQty(product.id, qty - 1)}
                        className="px-2 py-1 text-sm text-text-2 transition-colors hover:text-text"
                        aria-label={`Diminuer la quantité de ${product.name}`}
                      >
                        −
                      </button>
                      <span className="w-7 text-center text-xs font-semibold">{qty}</span>
                      <button
                        type="button"
                        onClick={() => setQty(product.id, qty + 1)}
                        className="px-2 py-1 text-sm text-text-2 transition-colors hover:text-text"
                        aria-label={`Augmenter la quantité de ${product.name}`}
                      >
                        +
                      </button>
                    </span>
                  </span>
                  <span className="shrink-0 text-sm font-semibold">{euros(product.price * qty)}</span>
                </li>
              ))}
            </ul>

            <footer className="border-t border-edge px-6 py-5">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-text-2">Sous-total</span>
                <span className="font-head text-2xl font-bold">{euros(subtotal)}</span>
              </div>
              <p className="mt-1 text-xs text-text-2">TVA calculée à l’étape de paiement.</p>
              <button
                type="button"
                onClick={onCheckout}
                className="mt-4 w-full rounded-lg bg-inkwarm px-5 py-3 text-sm font-semibold text-paper transition-colors hover:bg-walnut"
              >
                Passer au paiement
              </button>
            </footer>
          </>
        )}
      </aside>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { euros } from '../payments/domain/money'
import { ProductArt } from './art'
import { addToCart } from './cart'
import type { Product } from './catalog'

export function ProductSheet({ product, onClose }: { product: Product; onClose: () => void }) {
  const [qty, setQty] = useState(1)
  const [added, setAdded] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function add() {
    addToCart(product.id, qty)
    setAdded(true)
    window.setTimeout(onClose, 650)
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" role="dialog" aria-modal="true" aria-label={product.name}>
      <button
        type="button"
        aria-label="Fermer la fiche produit"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-inkwarm/40 backdrop-blur-[2px]"
      />
      <div className="rise relative w-full max-w-[760px] overflow-hidden rounded-panel bg-card shadow-float">
        <div className="grid sm:grid-cols-[320px_1fr]">
          <div className="grid place-items-center p-8" style={{ background: product.plinth }}>
            <ProductArt id={product.id} className="w-full max-w-[260px]" />
          </div>
          <div className="flex flex-col gap-4 p-8">
            <div>
              <h2 className="font-display text-3xl text-inkwarm">{product.name}</h2>
              <p className="mt-1 text-sm text-text-2">{product.detail}</p>
            </div>
            <p className="text-[15px] leading-relaxed text-text">{product.story}</p>
            <p className="font-display text-2xl text-inkwarm">{euros(product.price)}</p>

            <div className="mt-auto flex items-center gap-3 pt-2">
              <div className="flex items-center rounded-lg border border-edge">
                <button
                  type="button"
                  onClick={() => setQty((q) => Math.max(1, q - 1))}
                  className="px-3 py-2 text-text-2 transition-colors hover:text-text"
                  aria-label="Diminuer la quantité"
                >
                  −
                </button>
                <span className="w-8 text-center text-sm font-semibold" aria-live="polite">{qty}</span>
                <button
                  type="button"
                  onClick={() => setQty((q) => Math.min(9, q + 1))}
                  className="px-3 py-2 text-text-2 transition-colors hover:text-text"
                  aria-label="Augmenter la quantité"
                >
                  +
                </button>
              </div>
              <button
                type="button"
                onClick={add}
                disabled={added}
                className="flex-1 rounded-lg bg-inkwarm px-5 py-2.5 text-sm font-semibold text-paper transition-colors hover:bg-walnut disabled:opacity-80"
              >
                {added ? 'Ajouté ✓' : 'Ajouter au panier'}
              </button>
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer"
          className="absolute right-4 top-4 grid size-8 place-items-center rounded-full bg-card/80 text-text-2 transition-colors hover:text-text"
        >
          ✕
        </button>
      </div>
    </div>
  )
}

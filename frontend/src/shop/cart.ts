import { useSyncExternalStore } from 'react'
import type { Cents } from '../payments/domain/types'
import { PRODUCTS, productById, type Product } from './catalog'

export interface CartLine {
  product: Product
  qty: number
}

/** Même mécanique que la session : un petit store, et les composants s'abonnent. */
type Entries = Record<string, number>

const KEY = 'yaznow.cart'
let entries: Entries = restore()
const listeners = new Set<() => void>()

function restore(): Entries {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Entries
    // On ne garde que des produits du catalogue, avec des quantités saines.
    const clean: Entries = {}
    for (const [id, qty] of Object.entries(parsed)) {
      if (productById(id) && Number.isInteger(qty) && qty > 0) clean[id] = Math.min(qty, 9)
    }
    return clean
  } catch {
    return {}
  }
}

function emit(): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(entries))
  } catch {
    // Stockage indisponible : le panier vit en mémoire, c'est suffisant.
  }
  listeners.forEach((l) => l())
}

export function addToCart(id: string, qty = 1): void {
  if (!productById(id)) return
  entries = { ...entries, [id]: Math.min((entries[id] ?? 0) + qty, 9) }
  emit()
}

export function setQty(id: string, qty: number): void {
  if (qty <= 0) {
    const { [id]: _, ...rest } = entries
    entries = rest
  } else {
    entries = { ...entries, [id]: Math.min(qty, 9) }
  }
  emit()
}

export function clearCart(): void {
  entries = {}
  emit()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useCart(): { lines: CartLine[]; count: number; subtotal: Cents } {
  const snapshot = useSyncExternalStore(subscribe, () => entries)
  const lines: CartLine[] = PRODUCTS.filter((p) => snapshot[p.id]).map((p) => ({
    product: p,
    qty: snapshot[p.id],
  }))
  return {
    lines,
    count: lines.reduce((s, l) => s + l.qty, 0),
    subtotal: lines.reduce((s, l) => s + l.qty * l.product.price, 0),
  }
}

import { useSyncExternalStore } from 'react'
import type { SectionId } from './catalog'

/** État d'interface partagé entre le header et la boutique : panier ouvert, recherche, catégorie. */
interface ShopUI {
  cartOpen: boolean
  query: string
  category: SectionId
}

let state: ShopUI = { cartOpen: false, query: '', category: 'tout' }
const listeners = new Set<() => void>()

function set(next: Partial<ShopUI>): void {
  state = { ...state, ...next }
  listeners.forEach((l) => l())
}

export const openCart = () => set({ cartOpen: true })
export const closeCart = () => set({ cartOpen: false })
export const setQuery = (query: string) => set({ query })
export const setCategory = (category: ShopUI['category']) => set({ category, query: '' })

export function useShopUI(): ShopUI {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => state,
  )
}

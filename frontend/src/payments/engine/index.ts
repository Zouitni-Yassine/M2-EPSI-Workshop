import { useEffect, useState } from 'react'
import type { PaymentEngine, Provider } from '../domain/types'
import { createLocalEngine } from './localEngine'
import { createPayPalCheckout, type PayPalCheckout } from './paypalCheckout'
import { createStripeEngine } from './stripeEngine'

export interface EngineChoice {
  engine: PaymentEngine
  provider: Provider
  /** Renseigné quand le backend a des identifiants PayPal sandbox et le .env un client ID. */
  paypal?: PayPalCheckout
  /** Renseigné quand on a dû se rabattre sur la simulation : affiché à l'écran, jamais caché. */
  notice?: string
}

let pending: Promise<EngineChoice> | null = null

/** Un seul choix par session, pour que le journal et le solde restent cohérents. */
export function resolvePaymentEngine(): Promise<EngineChoice> {
  pending ??= choose()
  return pending
}

async function choose(): Promise<EngineChoice> {
  const pk = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY
  const paypalClientId = import.meta.env.VITE_PAYPAL_CLIENT_ID
  const api = import.meta.env.VITE_API_URL

  if (!api) {
    return {
      engine: createLocalEngine(),
      provider: 'local',
      notice: 'URL d’API absente du .env — simulation locale.',
    }
  }

  let health: { ok?: boolean; stripe?: boolean; paypal?: boolean }
  try {
    const res = await fetch(`${api}/health`, { signal: AbortSignal.timeout(3000) })
    health = (await res.json()) as typeof health
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err)
    return {
      engine: createLocalEngine(),
      provider: 'local',
      notice: `Backend injoignable (${why}) — simulation locale hors ligne.`,
    }
  }

  // PayPal s'ajoute au paiement par carte, que celui-ci passe par Stripe ou par la simulation.
  const paypal = health.paypal && paypalClientId ? createPayPalCheckout(api, paypalClientId) : undefined

  if (pk && health.stripe) {
    return { engine: createStripeEngine(api), provider: 'stripe', paypal }
  }
  return {
    engine: createLocalEngine(),
    provider: 'local',
    paypal,
    notice: pk
      ? 'Clé Stripe absente côté serveur — paiement par carte simulé localement.'
      : 'Clé Stripe absente du .env — paiement par carte simulé localement.',
  }
}

export function usePaymentEngine(): EngineChoice | null {
  const [choice, setChoice] = useState<EngineChoice | null>(null)
  useEffect(() => {
    void resolvePaymentEngine().then(setChoice)
  }, [])
  return choice
}

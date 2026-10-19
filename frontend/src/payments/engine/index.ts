import { useEffect, useState } from 'react'
import type { PaymentEngine, Provider } from '../domain/types'
import { createLocalEngine } from './localEngine'
import { createStripeEngine } from './stripeEngine'

export interface EngineChoice {
  engine: PaymentEngine
  provider: Provider
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
  const api = import.meta.env.VITE_API_URL

  if (!pk || !api) {
    return {
      engine: createLocalEngine(),
      provider: 'local',
      notice: 'Clé Stripe ou URL d’API absente du .env — simulation locale.',
    }
  }

  try {
    const res = await fetch(`${api}/health`, { signal: AbortSignal.timeout(3000) })
    const body = (await res.json()) as { ok?: boolean; stripe?: boolean }
    if (!res.ok || !body.stripe) throw new Error('clé Stripe absente côté serveur')
    return { engine: createStripeEngine(api), provider: 'stripe' }
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err)
    return {
      engine: createLocalEngine(),
      provider: 'local',
      notice: `Backend injoignable (${why}) — simulation locale hors ligne.`,
    }
  }
}

export function usePaymentEngine(): EngineChoice | null {
  const [choice, setChoice] = useState<EngineChoice | null>(null)
  useEffect(() => {
    void resolvePaymentEngine().then(setChoice)
  }, [])
  return choice
}

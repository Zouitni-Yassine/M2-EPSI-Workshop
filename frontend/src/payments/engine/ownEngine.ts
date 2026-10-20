import { loadStripe, type Stripe } from '@stripe/stripe-js'
import { authHeaders, checkSession } from '../../auth/session'
import type { PaymentEngine, PaymentIntent } from '../domain/types'

/**
 * Stripe en mode test, avec nos propres champs de carte.
 *
 * Le numéro saisi va à notre backend, qui le remplace par le jeton de test
 * Stripe correspondant (`pm_card_visa`, …) : aucun numéro n'est transmis à
 * Stripe, et la carte à l'écran se remplit au fil de la saisie. Le 3-D Secure
 * reste celui de Stripe, ouvert ici avec `handleNextAction`.
 *
 * Par construction, seules les cartes de test fonctionnent. En production,
 * la voie est Stripe Elements (`stripeEngine`).
 */
export function createOwnEngine(baseUrl: string, publishableKey: string): PaymentEngine {
  const stripePromise: Promise<Stripe | null> = loadStripe(publishableKey)
  const store = new Map<string, PaymentIntent>()

  const call = async <T>(path: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
    })
    if (!res.ok) {
      checkSession(res)
      const body = (await res.json().catch(() => ({}))) as { detail?: string }
      throw new Error(body.detail ?? `${res.status} sur ${path}`)
    }
    return (await res.json()) as T
  }

  return {
    provider: 'stripe',
    entry: 'own',

    async createIntent(amount, card) {
      const intent = await call<PaymentIntent>('/payment_intents', {
        method: 'POST',
        body: JSON.stringify({ amount, holder: card.holder }),
      })
      store.set(intent.id, intent)
      return intent
    },

    async confirm(intentId, source, onStep) {
      if (source.kind !== 'raw') throw new Error('Ce moteur attend les chiffres de la carte.')
      const intent = store.get(intentId)
      if (!intent) throw new Error(`Intention inconnue : ${intentId}`)

      onStep?.({ ...intent, status: 'processing', rail: { ...intent.rail, authorization: 'active' } })

      let fresh = await call<PaymentIntent>(`/payment_intents/${intentId}/confirm`, {
        method: 'POST',
        body: JSON.stringify({ number: source.card.number, holder: source.card.holder }),
      })
      onStep?.(fresh)

      if (fresh.status === 'requires_action' && fresh.clientSecret) {
        // L'émetteur exige une authentification forte : Stripe ouvre sa fenêtre.
        const stripe = await stripePromise
        if (!stripe) throw new Error('Stripe.js n’a pas pu se charger.')
        await stripe.handleNextAction({ clientSecret: fresh.clientSecret })
        fresh = await call<PaymentIntent>(`/payment_intents/${intentId}`)
      }

      store.set(intentId, fresh)
      onStep?.(fresh)
      return fresh
    },

    async authenticate() {
      throw new Error('Stripe gère lui-même l’authentification 3-D Secure.')
    },

    list: () => call<PaymentIntent[]>('/payment_intents'),
    balance: () => call('/balance'),
  }
}

import type { StripeError } from '@stripe/stripe-js'
import { authHeaders, checkSession } from '../../auth/session'
import type { DeclineCode, PaymentEngine, PaymentIntent } from '../domain/types'

const KNOWN: DeclineCode[] = [
  'insufficient_funds',
  'card_declined',
  'expired_card',
  'incorrect_cvc',
  'processing_error',
  'fraudulent',
  'authentication_failed',
]

function codeOf(err: StripeError): DeclineCode {
  if (err.code === 'payment_intent_authentication_failure') return 'authentication_failed'
  const candidate = (err.decline_code ?? err.code ?? '') as DeclineCode
  return KNOWN.includes(candidate) ? candidate : 'card_declined'
}

/**
 * Moteur Stripe en mode test. Le backend crée l'intention et porte la clé
 * secrète ; le navigateur confirme avec Stripe.js, qui ouvre lui-même la
 * fenêtre 3-D Secure quand l'émetteur l'exige.
 */
export function createStripeEngine(baseUrl: string): PaymentEngine {
  // Garde le clientSecret entre la création et la confirmation.
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
    entry: 'elements',

    async createIntent(amount, card) {
      const intent = await call<PaymentIntent>('/payment_intents', {
        method: 'POST',
        body: JSON.stringify({ amount, holder: card.holder }),
      })
      store.set(intent.id, intent)
      return intent
    },

    async confirm(intentId, source, onStep) {
      if (source.kind !== 'stripe') {
        throw new Error('Le moteur Stripe attend un élément de carte Stripe.')
      }
      const intent = store.get(intentId)
      if (!intent?.clientSecret) throw new Error(`Intention inconnue : ${intentId}`)

      onStep?.({ ...intent, status: 'processing', rail: { ...intent.rail, authorization: 'active' } })

      const result = await source.stripe.confirmCardPayment(intent.clientSecret, {
        payment_method: {
          card: source.element,
          billing_details: { name: source.holder },
        },
      })

      // Dans tous les cas on relit l'intention côté serveur : c'est lui qui
      // connaît le réseau, les 4 derniers chiffres, le 3-D Secure et le refus.
      let fresh = await call<PaymentIntent>(`/payment_intents/${intentId}`)

      if (result.error && fresh.status !== 'canceled') {
        // Erreur côté client (saisie incomplète, réseau) avant tout verdict Stripe.
        const code = codeOf(result.error)
        fresh = {
          ...fresh,
          status: 'canceled',
          error: { code, message: result.error.message ?? 'Le paiement n’a pas pu être confirmé.' },
          rail: {
            ...fresh.rail,
            [code === 'authentication_failed' ? 'authentication' : 'authorization']: 'failed',
          },
        }
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

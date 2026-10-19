import type { Balance, PaymentEngine, PaymentIntent } from '../domain/types'

/**
 * Même contrat, servi par l'API métier. Les composants ne changent pas.
 * Le backend expose la machine à états ; l'interface se contente de l'afficher.
 */
export function createApiEngine(baseUrl: string): PaymentEngine {
  const call = async <T>(path: string, body?: unknown): Promise<T> => {
    const res = await fetch(`${baseUrl}${path}`, {
      method: body ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(`${res.status} sur ${path}`)
    return (await res.json()) as T
  }

  return {
    createIntent: (amount, card) => call<PaymentIntent>('/payment_intents', { amount, card }),
    confirm: (intentId, card, onStep) =>
      call<PaymentIntent>(`/payment_intents/${intentId}/confirm`, { card }).then((i) => {
        onStep?.(i)
        return i
      }),
    authenticate: (intentId, code, onStep) =>
      call<PaymentIntent>(`/payment_intents/${intentId}/authenticate`, { code }).then((i) => {
        onStep?.(i)
        return i
      }),
    list: () => call<PaymentIntent[]>('/payment_intents'),
    balance: () => call<Balance>('/balance'),
  }
}

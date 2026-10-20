import { authHeaders, checkSession } from '../../auth/session'
import type { Cents, PaymentIntent } from '../domain/types'

/**
 * PayPal en sandbox. Le backend porte le secret, crée la commande et la capture ;
 * le SDK JS v6 ouvre la fenêtre où le payeur se connecte avec un compte acheteur
 * sandbox. Les réponses ont la même forme `PaymentIntent` que Stripe.
 */
export interface PayPalCheckout {
  readonly clientId: string
  createOrder(amount: Cents): Promise<PaymentIntent>
  capture(orderId: string): Promise<PaymentIntent>
  list(): Promise<PaymentIntent[]>
}

export function createPayPalCheckout(baseUrl: string, clientId: string): PayPalCheckout {
  const call = async <T>(path: string, init?: RequestInit): Promise<T> => {
    const res = await fetch(`${baseUrl}/paypal${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...authHeaders(), ...init?.headers },
    })
    if (!res.ok) {
      checkSession(res)
      const body = (await res.json().catch(() => ({}))) as { detail?: string }
      throw new Error(body.detail ?? `${res.status} sur /paypal${path}`)
    }
    return (await res.json()) as T
  }

  return {
    clientId,
    createOrder: (amount) => call('/orders', { method: 'POST', body: JSON.stringify({ amount }) }),
    capture: (orderId) => call(`/orders/${encodeURIComponent(orderId)}/capture`, { method: 'POST' }),
    list: () => call('/orders'),
  }
}

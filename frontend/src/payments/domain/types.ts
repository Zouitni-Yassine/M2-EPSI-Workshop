import type { Stripe, StripeCardNumberElement } from '@stripe/stripe-js'

/** Montants en centimes, comme Stripe. Jamais de flottant pour de l'argent. */
export type Cents = number

export type Brand = 'visa' | 'mastercard' | 'amex' | 'unknown'

export type Provider = 'local' | 'stripe'

/** Absent = carte. PayPal se branche à côté du moteur carte, quel qu'il soit. */
export type PaymentMethod = 'card' | 'paypal'

/**
 * Machine à états reprise de Stripe. Le moteur local et le backend
 * produisent exactement les mêmes transitions.
 */
export type IntentStatus =
  | 'requires_confirmation'
  | 'requires_action'
  | 'processing'
  | 'succeeded'
  | 'canceled'

/** Codes de refus de Stripe, repris tels quels pour rester crédible. */
export type DeclineCode =
  | 'insufficient_funds'
  | 'card_declined'
  | 'expired_card'
  | 'incorrect_cvc'
  | 'processing_error'
  | 'fraudulent'
  | 'authentication_failed'

export interface PaymentError {
  code: DeclineCode
  message: string
}

export interface CardSummary {
  brand: Brand
  last4: string
  holder: string
}

/** Les quatre étapes que traverse réellement un paiement par carte. */
export type RailStage = 'authorization' | 'authentication' | 'capture' | 'settlement'

export type StageState = 'pending' | 'active' | 'done' | 'failed' | 'skipped'

export type Rail = Record<RailStage, StageState>

export interface IntentEvent {
  at: string
  status: IntentStatus
  note: string
}

export interface PaymentIntent {
  id: string
  idempotencyKey: string
  amount: Cents
  currency: 'EUR'
  status: IntentStatus
  method?: PaymentMethod
  /** Pour PayPal : pas de carte, seul `holder` (le nom du payeur) est renseigné. */
  card: CardSummary
  createdAt: string
  reference: string
  error?: PaymentError
  rail: Rail
  history: IntentEvent[]
  /** Fourni par Stripe à la création ; sert à confirmer depuis le navigateur. */
  clientSecret?: string
}

export interface Balance {
  available: Cents
  pending: Cents
  nextPayoutAt: string
}

export interface CardInput {
  number: string
  expiry: string
  cvc: string
  holder: string
}

/**
 * D'où vient la carte au moment de confirmer. En local on a les chiffres ;
 * avec Stripe on n'a qu'un élément iframe — le numéro ne touche jamais notre code.
 */
export type CardSource =
  | { kind: 'raw'; card: CardInput }
  | { kind: 'stripe'; stripe: Stripe; element: StripeCardNumberElement; holder: string }

/** Appelé à chaque transition, pour que le stepper avance sous les yeux du payeur. */
export type OnStep = (intent: PaymentIntent) => void

/**
 * Contrat du moteur de paiement. `local` le simule hors ligne,
 * `stripe` le délègue au backend et à Stripe. L'interface ne change pas.
 */
export interface PaymentEngine {
  readonly provider: Provider
  createIntent(amount: Cents, card: CardSummary): Promise<PaymentIntent>
  confirm(intentId: string, source: CardSource, onStep?: OnStep): Promise<PaymentIntent>
  /** Réponse au défi 3-D Secure. Stripe gère le sien ; seul le moteur local l'utilise. */
  authenticate(intentId: string, code: string, onStep?: OnStep): Promise<PaymentIntent>
  list(): Promise<PaymentIntent[]>
  balance(): Promise<Balance>
}

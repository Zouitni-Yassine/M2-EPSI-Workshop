/** Montants en centimes, comme Stripe. Jamais de flottant pour de l'argent. */
export type Cents = number

export type Brand = 'visa' | 'mastercard' | 'amex' | 'unknown'

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
  card: CardSummary
  createdAt: string
  reference: string
  error?: PaymentError
  rail: Rail
  history: IntentEvent[]
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

/** Appelé à chaque transition, pour que le rail avance sous les yeux du payeur. */
export type OnStep = (intent: PaymentIntent) => void

/**
 * Contrat du moteur de paiement. `local` le simule hors ligne,
 * `api` le délègue au backend. L'interface ne change pas.
 */
export interface PaymentEngine {
  createIntent(amount: Cents, card: CardSummary): Promise<PaymentIntent>
  confirm(intentId: string, card: CardInput, onStep?: OnStep): Promise<PaymentIntent>
  /** Réponse au défi 3-D Secure. */
  authenticate(intentId: string, code: string, onStep?: OnStep): Promise<PaymentIntent>
  list(): Promise<PaymentIntent[]>
  balance(): Promise<Balance>
}

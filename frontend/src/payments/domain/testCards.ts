import type { DeclineCode } from './types'

export type Outcome =
  | { kind: 'succeed' }
  | { kind: 'challenge' }
  | { kind: 'decline'; code: DeclineCode }

export interface TestCard {
  number: string
  label: string
  outcome: Outcome
}

/**
 * Catalogue repris des cartes de test Stripe. Aucune donnée bancaire réelle :
 * ces numéros n'existent sur aucun réseau de paiement.
 */
export const TEST_CARDS: TestCard[] = [
  { number: '4242424242424242', label: 'Visa — paiement accepté', outcome: { kind: 'succeed' } },
  { number: '5555555555554444', label: 'Mastercard — paiement accepté', outcome: { kind: 'succeed' } },
  { number: '378282246310005', label: 'American Express — accepté', outcome: { kind: 'succeed' } },
  { number: '4000002500003155', label: 'Authentification 3-D Secure requise', outcome: { kind: 'challenge' } },
  { number: '4000000000009995', label: 'Provision insuffisante', outcome: { kind: 'decline', code: 'insufficient_funds' } },
  { number: '4000000000000002', label: 'Refus de l’émetteur', outcome: { kind: 'decline', code: 'card_declined' } },
  { number: '4000000000000069', label: 'Carte expirée', outcome: { kind: 'decline', code: 'expired_card' } },
  { number: '4000000000000127', label: 'Cryptogramme incorrect', outcome: { kind: 'decline', code: 'incorrect_cvc' } },
  { number: '4000000000000119', label: 'Erreur de traitement', outcome: { kind: 'decline', code: 'processing_error' } },
  { number: '4100000000000019', label: 'Transaction jugée frauduleuse', outcome: { kind: 'decline', code: 'fraudulent' } },
]

export const DECLINE_MESSAGE: Record<DeclineCode, string> = {
  insufficient_funds: 'La provision du compte est insuffisante. Utilisez un autre moyen de paiement.',
  card_declined: 'L’émetteur a refusé la transaction. Contactez votre banque ou changez de carte.',
  expired_card: 'Cette carte a expiré. Vérifiez la date inscrite au recto.',
  incorrect_cvc: 'Le cryptogramme ne correspond pas à la carte. Il figure au dos, à trois chiffres.',
  processing_error: 'Le réseau d’autorisation n’a pas répondu. Réessayez dans un instant.',
  fraudulent: 'La transaction a été bloquée par le contrôle de fraude.',
  authentication_failed: 'L’authentification a échoué. Le code saisi ne correspond pas.',
}

export function outcomeFor(number: string): Outcome {
  const d = number.replace(/\D/g, '')
  return TEST_CARDS.find((c) => c.number === d)?.outcome ?? { kind: 'decline', code: 'card_declined' }
}

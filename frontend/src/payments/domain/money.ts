import type { Cents } from './types'

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })

export function euros(cents: Cents): string {
  return EUR.format(cents / 100)
}

export function timeNow(): string {
  return new Date().toLocaleTimeString('fr-FR', { hour12: false })
}

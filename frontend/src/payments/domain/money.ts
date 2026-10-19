import type { Cents } from './types'

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })

export function euros(cents: Cents): string {
  return EUR.format(cents / 100)
}

export function timeNow(): string {
  return new Date().toISOString()
}

/** Heure locale lisible à partir d'un horodatage ISO ; laisse passer tel quel ce qui n'en est pas un. */
export function localTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('fr-FR', { hour12: false })
}

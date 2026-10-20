import type { Cents } from './types'

const EUR = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' })

export function euros(cents: Cents): string {
  return EUR.format(cents / 100)
}

export function timeNow(): string {
  return new Date().toISOString()
}

function dayStart(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** Jours calendaires écoulés depuis un horodatage ISO : 0 aujourd'hui, 1 hier. */
function daysAgo(d: Date): number {
  // Arrondi : un passage à l'heure d'été ne fait pas tomber un jour à 0,96.
  return Math.round((dayStart(new Date()) - dayStart(d)) / 86_400_000)
}

export function isToday(iso: string): boolean {
  const d = new Date(iso)
  return !Number.isNaN(d.getTime()) && daysAgo(d) === 0
}

/** Pour le journal : l'heure seule aujourd'hui, « Hier, 15:07 », puis « 18 oct., 15:07 ». */
export function ledgerDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const time = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  const days = daysAgo(d)
  if (days === 0) return time
  if (days === 1) return `Hier, ${time}`
  const sameYear = d.getFullYear() === new Date().getFullYear()
  const date = d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: sameYear ? undefined : 'numeric' })
  return `${date}, ${time}`
}

/** Heure locale lisible à partir d'un horodatage ISO ; laisse passer tel quel ce qui n'en est pas un. */
export function localTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('fr-FR', { hour12: false })
}

import type { Brand } from './types'

const RULES: { brand: Brand; re: RegExp; len: number[]; cvc: number; groups: number[] }[] = [
  { brand: 'amex', re: /^3[47]/, len: [15], cvc: 4, groups: [4, 6, 5] },
  { brand: 'visa', re: /^4/, len: [16], cvc: 3, groups: [4, 4, 4, 4] },
  { brand: 'mastercard', re: /^(5[1-5]|2[2-7])/, len: [16], cvc: 3, groups: [4, 4, 4, 4] },
]

export function digitsOf(v: string): string {
  return v.replace(/\D/g, '')
}

export function brandOf(number: string): Brand {
  const d = digitsOf(number)
  return RULES.find((r) => r.re.test(d))?.brand ?? 'unknown'
}

export function cvcLength(brand: Brand): number {
  return RULES.find((r) => r.brand === brand)?.cvc ?? 3
}

export function maxDigits(brand: Brand): number {
  return RULES.find((r) => r.brand === brand)?.len[0] ?? 19
}

/** Regroupe à la volée : 4-4-4-4, et 4-6-5 pour American Express. */
export function formatNumber(value: string): string {
  const brand = brandOf(value)
  const groups = RULES.find((r) => r.brand === brand)?.groups ?? [4, 4, 4, 4, 3]
  const d = digitsOf(value).slice(0, maxDigits(brand))
  const out: string[] = []
  let i = 0
  for (const g of groups) {
    if (i >= d.length) break
    out.push(d.slice(i, i + g))
    i += g
  }
  return out.join(' ')
}

/** Algorithme de Luhn. Première barrière, côté client, avant tout appel réseau. */
export function luhnValid(number: string): boolean {
  const d = digitsOf(number)
  if (d.length < 12) return false
  let sum = 0
  let double = false
  for (let i = d.length - 1; i >= 0; i--) {
    let n = d.charCodeAt(i) - 48
    if (double) {
      n *= 2
      if (n > 9) n -= 9
    }
    sum += n
    double = !double
  }
  return sum % 10 === 0
}

export function formatExpiry(value: string): string {
  const d = digitsOf(value).slice(0, 4)
  if (d.length <= 2) return d
  return `${d.slice(0, 2)}/${d.slice(2)}`
}

export function expiryValid(value: string, now = new Date()): boolean {
  const d = digitsOf(value)
  if (d.length !== 4) return false
  const month = Number(d.slice(0, 2))
  const year = 2000 + Number(d.slice(2))
  if (month < 1 || month > 12) return false
  const end = new Date(year, month, 1)
  return end > now
}

export function last4(number: string): string {
  return digitsOf(number).slice(-4)
}

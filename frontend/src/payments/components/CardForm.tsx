import { useState } from 'react'
import {
  brandOf,
  cvcLength,
  digitsOf,
  expiryValid,
  formatExpiry,
  formatNumber,
  luhnValid,
} from '../domain/card'
import type { Brand, CardInput } from '../domain/types'
import { BrandLogo } from './BrandLogo'
import { Field } from './Field'

export type CardField = keyof CardInput

interface Props {
  value: CardInput
  onChange: (v: CardInput) => void
  onFocusField: (f: CardField | null) => void
  disabled: boolean
  showErrors: boolean
}

const NETWORKS: Brand[] = ['visa', 'mastercard', 'amex']

export function CardForm({ value, onChange, onFocusField, disabled, showErrors }: Props) {
  const [touched, setTouched] = useState<Partial<Record<CardField, boolean>>>({})
  const brand = brandOf(value.number)
  const cvcLen = cvcLength(brand)

  const show = (f: CardField) => showErrors || touched[f]
  const set = (patch: Partial<CardInput>) => onChange({ ...value, ...patch })
  const blur = (f: CardField) => () => {
    setTouched((t) => ({ ...t, [f]: true }))
    onFocusField(null)
  }

  const numberError = show('number')
    ? !value.number
      ? 'Saisissez le numéro de votre carte.'
      : !luhnValid(value.number)
        ? 'Ce numéro de carte n’est pas valide.'
        : undefined
    : undefined

  const expiryError = show('expiry')
    ? !value.expiry
      ? 'Date d’expiration requise.'
      : !expiryValid(value.expiry)
        ? 'Date invalide ou carte expirée.'
        : undefined
    : undefined

  const cvcError = show('cvc')
    ? digitsOf(value.cvc).length !== cvcLen
      ? `Le cryptogramme comporte ${cvcLen} chiffres.`
      : undefined
    : undefined

  const holderError = show('holder') && value.holder.trim().length < 2 ? 'Indiquez le nom du titulaire.' : undefined

  return (
    <div className="grid gap-5">
      <Field
        label="Numéro de carte"
        inputMode="numeric"
        autoComplete="cc-number"
        placeholder="1234 1234 1234 1234"
        value={formatNumber(value.number)}
        onChange={(e) => set({ number: digitsOf(e.target.value) })}
        onFocus={() => onFocusField('number')}
        onBlur={blur('number')}
        disabled={disabled}
        error={numberError}
        className="tracking-[0.06em]"
        trailing={
          <span className="flex shrink-0 items-center gap-1.5" aria-hidden="true">
            {NETWORKS.map((n) => {
              const lit = brand === 'unknown' || brand === n
              return (
                <span
                  key={n}
                  className={`h-5 w-8 text-[#1a1f71] transition-[opacity,transform] duration-200 ${
                    lit ? 'opacity-100' : 'scale-90 opacity-20'
                  }`}
                >
                  <BrandLogo brand={n} className="h-full w-full" />
                </span>
              )
            })}
          </span>
        }
      />

      <div className="grid grid-cols-2 gap-4">
        <Field
          label="Expiration"
          inputMode="numeric"
          autoComplete="cc-exp"
          placeholder="MM / AA"
          value={formatExpiry(value.expiry)}
          onChange={(e) => set({ expiry: digitsOf(e.target.value) })}
          onFocus={() => onFocusField('expiry')}
          onBlur={blur('expiry')}
          disabled={disabled}
          error={expiryError}
        />
        <Field
          label="Cryptogramme"
          inputMode="numeric"
          autoComplete="cc-csc"
          placeholder={'•'.repeat(cvcLen)}
          value={digitsOf(value.cvc).slice(0, cvcLen)}
          onChange={(e) => set({ cvc: digitsOf(e.target.value) })}
          onFocus={() => onFocusField('cvc')}
          onBlur={blur('cvc')}
          disabled={disabled}
          error={cvcError}
          trailing={<CvcHint />}
        />
      </div>

      <Field
        label="Nom du titulaire"
        autoComplete="cc-name"
        placeholder="Tel qu’inscrit sur la carte"
        value={value.holder}
        onChange={(e) => set({ holder: e.target.value })}
        onFocus={() => onFocusField('holder')}
        onBlur={blur('holder')}
        disabled={disabled}
        error={holderError}
      />
    </div>
  )
}

function CvcHint() {
  return (
    <svg width="28" height="20" viewBox="0 0 28 20" aria-hidden="true" className="shrink-0 text-text-2/70">
      <rect x="1" y="1" width="26" height="18" rx="3" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <rect x="1" y="5" width="26" height="3.5" fill="currentColor" />
      <rect x="15" y="11.5" width="9" height="3.5" rx="1" fill="currentColor" opacity="0.6" />
    </svg>
  )
}

export function cardComplete(v: CardInput): boolean {
  return (
    luhnValid(v.number) &&
    expiryValid(v.expiry) &&
    digitsOf(v.cvc).length === cvcLength(brandOf(v.number)) &&
    v.holder.trim().length > 1
  )
}

import { useEffect, useState, type MutableRefObject } from 'react'
import {
  CardCvcElement,
  CardExpiryElement,
  CardNumberElement,
  useElements,
  useStripe,
} from '@stripe/react-stripe-js'
import type { StripeCardNumberElementChangeEvent, StripeElementChangeEvent } from '@stripe/stripe-js'
import type { Brand, CardSource } from '../domain/types'
import { BrandLogo } from './BrandLogo'
import { Field } from './Field'
import { FieldShell } from './FieldShell'
import type { CardField } from './CardForm'

const NETWORKS: Brand[] = ['visa', 'mastercard', 'amex']

/** Même rendu que nos champs : l'iframe Stripe adopte Inter et nos couleurs. */
const STYLE = {
  base: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
    fontSize: '15px',
    fontWeight: '400',
    color: '#0b0f19',
    '::placeholder': { color: 'rgba(102, 112, 133, 0.55)' },
  },
  invalid: { color: '#dc2626' },
}

interface Props {
  holder: string
  onHolderChange: (v: string) => void
  onBrandChange: (b: Brand) => void
  onCompleteChange: (complete: boolean) => void
  onFocusField: (f: CardField | null) => void
  /** Le parent y lit la carte au moment de payer, sans jamais voir le numéro. */
  sourceRef: MutableRefObject<() => CardSource | null>
  disabled: boolean
  showErrors: boolean
}

type Part = 'number' | 'expiry' | 'cvc'

interface PartState {
  complete: boolean
  empty: boolean
  error?: string
}

const MESSAGES: Record<Part, { empty: string; invalid: string }> = {
  number: { empty: 'Saisissez le numéro de votre carte.', invalid: 'Ce numéro de carte n’est pas valide.' },
  expiry: { empty: 'Date d’expiration requise.', invalid: 'Date invalide ou carte expirée.' },
  cvc: { empty: 'Cryptogramme requis.', invalid: 'Cryptogramme incomplet.' },
}

function asBrand(b: string): Brand {
  return b === 'visa' || b === 'mastercard' || b === 'amex' ? b : 'unknown'
}

/**
 * Le formulaire carte branché sur Stripe Elements. Les trois champs sont des
 * iframes Stripe : le numéro ne transite jamais par notre code.
 */
export function StripeCardForm({
  holder,
  onHolderChange,
  onBrandChange,
  onCompleteChange,
  onFocusField,
  sourceRef,
  disabled,
  showErrors,
}: Props) {
  const stripe = useStripe()
  const elements = useElements()

  const [brand, setBrand] = useState<Brand>('unknown')
  const [focused, setFocused] = useState<Part | null>(null)
  const [touched, setTouched] = useState<Partial<Record<Part, boolean>>>({})
  const [parts, setParts] = useState<Record<Part, PartState>>({
    number: { complete: false, empty: true },
    expiry: { complete: false, empty: true },
    cvc: { complete: false, empty: true },
  })

  useEffect(() => {
    sourceRef.current = () => {
      const element = elements?.getElement(CardNumberElement)
      return stripe && element ? { kind: 'stripe', stripe, element, holder } : null
    }
  }, [stripe, elements, holder, sourceRef])

  useEffect(() => {
    onCompleteChange(
      parts.number.complete && parts.expiry.complete && parts.cvc.complete && holder.trim().length > 1,
    )
  }, [parts, holder, onCompleteChange])

  const onChange = (part: Part) => (ev: StripeElementChangeEvent | StripeCardNumberElementChangeEvent) => {
    setParts((p) => ({ ...p, [part]: { complete: ev.complete, empty: ev.empty, error: ev.error?.message } }))
    if ('brand' in ev) {
      const b = asBrand(ev.brand)
      setBrand(b)
      onBrandChange(b)
    }
  }

  const focus = (part: Part) => () => {
    setFocused(part)
    onFocusField(part)
  }
  const blur = (part: Part) => () => {
    setFocused(null)
    setTouched((t) => ({ ...t, [part]: true }))
    onFocusField(null)
  }

  const errorFor = (part: Part): string | undefined => {
    if (!showErrors && !touched[part]) return undefined
    const s = parts[part]
    if (s.empty) return MESSAGES[part].empty
    if (s.error || !s.complete) return MESSAGES[part].invalid
    return undefined
  }

  const holderError = (showErrors || touched.cvc) && holder.trim().length < 2 ? 'Indiquez le nom du titulaire.' : undefined

  return (
    <div className="grid gap-5">
      <FieldShell
        label="Numéro de carte"
        focused={focused === 'number'}
        error={errorFor('number')}
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
      >
        <CardNumberElement
          options={{ style: STYLE, showIcon: false, disableLink: true, placeholder: '1234 1234 1234 1234', disabled }}
          onChange={onChange('number')}
          onFocus={focus('number')}
          onBlur={blur('number')}
        />
      </FieldShell>

      <div className="grid grid-cols-2 gap-4">
        <FieldShell label="Expiration" focused={focused === 'expiry'} error={errorFor('expiry')}>
          <CardExpiryElement
            options={{ style: STYLE, placeholder: 'MM / AA', disabled }}
            onChange={onChange('expiry')}
            onFocus={focus('expiry')}
            onBlur={blur('expiry')}
          />
        </FieldShell>
        <FieldShell label="Cryptogramme" focused={focused === 'cvc'} error={errorFor('cvc')}>
          <CardCvcElement
            options={{ style: STYLE, placeholder: brand === 'amex' ? '••••' : '•••', disabled }}
            onChange={onChange('cvc')}
            onFocus={focus('cvc')}
            onBlur={blur('cvc')}
          />
        </FieldShell>
      </div>

      <Field
        label="Nom du titulaire"
        autoComplete="cc-name"
        placeholder="Tel qu’inscrit sur la carte"
        value={holder}
        onChange={(e) => onHolderChange(e.target.value)}
        onFocus={() => onFocusField('holder')}
        onBlur={() => onFocusField(null)}
        disabled={disabled}
        error={holderError}
      />
    </div>
  )
}

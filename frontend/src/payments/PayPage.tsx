import { useMemo, useState } from 'react'
import { brandOf, last4 } from './domain/card'
import { euros } from './domain/money'
import type { CardInput, PaymentIntent, Rail } from './domain/types'
import { paymentEngine } from './engine'
import { CardForm, cardComplete, type CardField } from './components/CardForm'
import { CardPreview } from './components/CardPreview'
import { OrderSummary, TOTAL } from './components/OrderSummary'
import { Outcome } from './components/Outcome'
import { Stepper } from './components/Stepper'
import { ThreeDSChallenge } from './components/ThreeDSChallenge'

const EMPTY_CARD: CardInput = { number: '', expiry: '', cvc: '', holder: '' }

const IDLE_RAIL: Rail = {
  authorization: 'pending',
  authentication: 'pending',
  capture: 'pending',
  settlement: 'pending',
}

export function PayPage({ onPaid }: { onPaid: () => void }) {
  const engine = useMemo(() => paymentEngine(), [])

  const [card, setCard] = useState<CardInput>(EMPTY_CARD)
  const [focused, setFocused] = useState<CardField | null>(null)
  const [intent, setIntent] = useState<PaymentIntent | null>(null)
  const [busy, setBusy] = useState(false)
  const [showErrors, setShowErrors] = useState(false)
  const [authError, setAuthError] = useState<string | undefined>()

  const brand = brandOf(card.number)
  const rail = intent?.rail ?? IDLE_RAIL
  const settled = intent?.status === 'succeeded' || intent?.status === 'canceled'
  const challenging = intent?.status === 'requires_action'

  async function pay() {
    if (!cardComplete(card)) {
      setShowErrors(true)
      return
    }
    setBusy(true)
    setAuthError(undefined)
    try {
      const created = await engine.createIntent(TOTAL, {
        brand,
        last4: last4(card.number),
        holder: card.holder.trim(),
      })
      setIntent(created)
      const final = await engine.confirm(created.id, card, setIntent)
      setIntent(final)
      if (final.status === 'succeeded') onPaid()
    } finally {
      setBusy(false)
    }
  }

  async function authenticate(code: string) {
    if (!intent) return
    setBusy(true)
    setAuthError(undefined)
    try {
      const final = await engine.authenticate(intent.id, code, setIntent)
      setIntent(final)
      if (final.status === 'canceled') setAuthError(final.error?.message)
      if (final.status === 'succeeded') onPaid()
    } finally {
      setBusy(false)
    }
  }

  function restart() {
    setIntent(null)
    setCard(EMPTY_CARD)
    setShowErrors(false)
    setAuthError(undefined)
  }

  return (
    <main className="mx-auto grid max-w-[1120px] gap-10 px-6 py-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14">
      <section className="flex flex-col gap-8">
        <CardPreview
          number={card.number}
          holder={card.holder}
          expiry={card.expiry}
          cvc={card.cvc}
          brand={brand}
          flipped={focused === 'cvc'}
        />
        <OrderSummary />
      </section>

      <section className="flex flex-col gap-6">
        <div className="px-2">
          <Stepper rail={rail} />
        </div>

        {settled && intent ? (
          <Outcome intent={intent} onRestart={restart} />
        ) : (
          <form
            className="rounded-panel border border-edge bg-card shadow-panel"
            onSubmit={(e) => {
              e.preventDefault()
              void pay()
            }}
            noValidate
          >
            <div className="border-b border-edge px-6 py-4">
              <h2 className="text-base font-semibold">Payer par carte</h2>
              <p className="mt-0.5 text-sm text-text-2">Visa, Mastercard et American Express acceptées.</p>
            </div>

            <div className="px-6 py-6">
              <CardForm
                value={card}
                onChange={setCard}
                onFocusField={setFocused}
                disabled={busy}
                showErrors={showErrors}
              />
            </div>

            <div className="border-t border-edge px-6 py-5">
              <button
                type="submit"
                disabled={busy}
                className="relative h-12 w-full overflow-hidden rounded-lg bg-accent text-[15px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-wait"
              >
                {busy ? (
                  <>
                    <span className="sweep absolute inset-y-0 left-0 w-1/4 bg-white/15" aria-hidden="true" />
                    <span className="relative inline-flex items-center gap-2">
                      <Spinner />
                      Traitement du paiement
                    </span>
                  </>
                ) : (
                  `Payer ${euros(TOTAL)}`
                )}
              </button>
              <p className="mt-3 flex items-center justify-center gap-1.5 text-xs text-text-2">
                <Lock />
                Paiement chiffré. Vos données de carte ne sont jamais stockées.
              </p>
            </div>
          </form>
        )}
      </section>

      {challenging && intent ? (
        <ThreeDSChallenge
          amount={intent.amount}
          last4={intent.card.last4}
          busy={busy}
          error={authError}
          onSubmit={authenticate}
          onCancel={restart}
        />
      ) : null}
    </main>
  )
}

function Spinner() {
  return (
    <svg className="spin size-4" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.3" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

function Lock() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

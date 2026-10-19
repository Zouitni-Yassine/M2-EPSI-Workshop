import { useCallback, useRef, useState } from 'react'
import { Elements } from '@stripe/react-stripe-js'
import { loadStripe } from '@stripe/stripe-js'
import { brandOf, last4 } from './domain/card'
import { euros } from './domain/money'
import type { Brand, CardInput, CardSource, PaymentIntent, Rail } from './domain/types'
import { usePaymentEngine, type EngineChoice } from './engine'
import { CardForm, cardComplete, type CardField } from './components/CardForm'
import { CardPreview } from './components/CardPreview'
import { OrderSummary, TOTAL } from './components/OrderSummary'
import { Outcome } from './components/Outcome'
import { Stepper } from './components/Stepper'
import { StripeCardForm } from './components/StripeCardForm'
import { ThreeDSChallenge } from './components/ThreeDSChallenge'

const EMPTY_CARD: CardInput = { number: '', expiry: '', cvc: '', holder: '' }

const IDLE_RAIL: Rail = {
  authorization: 'pending',
  authentication: 'pending',
  capture: 'pending',
  settlement: 'pending',
}

const PK = import.meta.env.VITE_STRIPE_PUBLISHABLE_KEY
const stripePromise = PK ? loadStripe(PK) : null

const INTER_CSS = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'

export function PayPage({ onPaid }: { onPaid: () => void }) {
  const choice = usePaymentEngine()

  if (!choice) {
    return (
      <main className="mx-auto max-w-[1120px] px-6 py-24 text-center text-sm text-text-2">
        Connexion à la plateforme de paiement…
      </main>
    )
  }

  if (choice.provider === 'stripe' && stripePromise) {
    return (
      <Elements stripe={stripePromise} options={{ fonts: [{ cssSrc: INTER_CSS }], locale: 'fr' }}>
        <Checkout choice={choice} onPaid={onPaid} />
      </Elements>
    )
  }

  return <Checkout choice={choice} onPaid={onPaid} />
}

function Checkout({ choice, onPaid }: { choice: EngineChoice; onPaid: () => void }) {
  const { engine, provider } = choice
  const elements = engine.entry === 'elements'

  const [card, setCard] = useState<CardInput>(EMPTY_CARD)
  const [stripeBrand, setStripeBrand] = useState<Brand>('unknown')
  const [stripeComplete, setStripeComplete] = useState(false)
  const sourceRef = useRef<() => CardSource | null>(() => null)

  const [focused, setFocused] = useState<CardField | null>(null)
  const [intent, setIntent] = useState<PaymentIntent | null>(null)
  const [busy, setBusy] = useState(false)
  const [showErrors, setShowErrors] = useState(false)
  const [authError, setAuthError] = useState<string | undefined>()
  const [failure, setFailure] = useState<string | undefined>()

  const brand = elements ? stripeBrand : brandOf(card.number)
  const rail = intent?.rail ?? IDLE_RAIL
  const settled = intent?.status === 'succeeded' || intent?.status === 'canceled'
  const challenging = provider === 'local' && intent?.status === 'requires_action'

  const onHolderChange = useCallback((holder: string) => setCard((c) => ({ ...c, holder })), [])

  async function pay() {
    const ready = elements ? stripeComplete : cardComplete(card)
    if (!ready) {
      setShowErrors(true)
      return
    }
    const source: CardSource | null = elements ? sourceRef.current() : { kind: 'raw', card }
    if (!source) {
      setFailure('Le formulaire Stripe n’est pas encore prêt. Réessayez dans un instant.')
      return
    }

    setBusy(true)
    setFailure(undefined)
    setAuthError(undefined)
    try {
      const created = await engine.createIntent(TOTAL, {
        brand,
        last4: elements ? '' : last4(card.number),
        holder: card.holder.trim(),
      })
      setIntent(created)
      const final = await engine.confirm(created.id, source, setIntent)
      setIntent(final)
      if (final.status === 'succeeded') onPaid()
    } catch (err) {
      // Une panne réseau ou backend ne doit jamais laisser l'écran muet.
      setIntent(null)
      setFailure(err instanceof Error ? err.message : 'Le paiement n’a pas pu être envoyé.')
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
    setFailure(undefined)
  }

  return (
    <main className="mx-auto max-w-[1120px] px-6 py-10">
      {choice.notice ? (
        <div className="rise mb-8 flex items-start gap-3 rounded-lg border border-note/30 bg-note/10 px-4 py-3 text-sm text-note">
          <span className="mt-0.5 size-2 shrink-0 rounded-full bg-note" />
          <p>
            <strong className="font-semibold">Mode hors ligne.</strong> {choice.notice}
          </p>
        </div>
      ) : null}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14">
        <section className="flex flex-col gap-8">
          <CardPreview
            number={elements ? '' : card.number}
            holder={card.holder}
            expiry={elements ? '' : card.expiry}
            cvc={elements ? '' : card.cvc}
            brand={brand}
            flipped={focused === 'cvc'}
          />
          {provider === 'stripe' ? (
            <p className="-mt-4 flex items-start gap-2 text-xs leading-relaxed text-text-2">
              <Shield />
              <span>
                {elements
                  ? 'Le numéro et la date sont saisis dans un cadre sécurisé Stripe : ils n’apparaissent jamais ici ni dans notre code.'
                  : 'Cartes de test uniquement : le serveur remplace le numéro par le jeton de test Stripe correspondant. Aucun numéro n’est transmis à Stripe.'}
              </span>
            </p>
          ) : null}
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
              <div className="flex items-start justify-between gap-4 border-b border-edge px-6 py-4">
                <div>
                  <h2 className="text-base font-semibold">Payer par carte</h2>
                  <p className="mt-0.5 text-sm text-text-2">
                    Visa, Mastercard et American Express acceptées.
                  </p>
                </div>
                {provider === 'stripe' ? (
                  <span className="shrink-0 rounded-md bg-well px-2 py-1 text-[11px] font-semibold text-text-2">
                    Stripe · test
                  </span>
                ) : null}
              </div>

              <div className="px-6 py-6">
                {elements ? (
                  <StripeCardForm
                    holder={card.holder}
                    onHolderChange={onHolderChange}
                    onBrandChange={setStripeBrand}
                    onCompleteChange={setStripeComplete}
                    onFocusField={setFocused}
                    sourceRef={sourceRef}
                    disabled={busy}
                    showErrors={showErrors}
                  />
                ) : (
                  <CardForm
                    value={card}
                    onChange={setCard}
                    onFocusField={setFocused}
                    disabled={busy}
                    showErrors={showErrors}
                  />
                )}
              </div>

              <div className="border-t border-edge px-6 py-5">
                {failure ? (
                  <p className="rise mb-3 rounded-lg border border-bad/30 bg-bad/5 px-3.5 py-2.5 text-sm text-bad">
                    {failure}
                  </p>
                ) : null}
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
      </div>

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

function Shield() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true" className="mt-0.5 shrink-0 text-good">
      <path d="M8 1.5l5.5 2v4c0 3.2-2.3 5.6-5.5 7-3.2-1.4-5.5-3.8-5.5-7v-4l5.5-2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M5.5 8l1.8 1.8L10.5 6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
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

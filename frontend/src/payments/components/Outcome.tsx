import { euros } from '../domain/money'
import type { PaymentIntent } from '../domain/types'
import { BrandLogo, PayPalMark } from './BrandLogo'

interface Props {
  intent: PaymentIntent
  onRestart: () => void
}

export function Outcome({ intent, onRestart }: Props) {
  const failed = intent.status === 'canceled'
  const viaPayPal = intent.method === 'paypal'

  const rows: [string, string][] = [
    ['Référence', intent.reference],
    ['Date', new Date(intent.createdAt).toLocaleString('fr-FR', { dateStyle: 'long', timeStyle: 'short' })],
    ['Identifiant', intent.id],
    ['Clé d’idempotence', intent.idempotencyKey],
    ...(intent.error ? ([['Motif', intent.error.code]] as [string, string][]) : []),
  ]

  return (
    <div className="rise rounded-panel border border-edge bg-card shadow-panel">
      <div className="flex flex-col items-center px-8 pt-10 pb-8 text-center">
        {failed ? <CrossMark /> : <CheckMark />}
        <h2 className="mt-5 text-2xl font-semibold tracking-tight">
          {failed ? 'Paiement refusé' : 'Paiement effectué'}
        </h2>
        <p className="mt-1 text-4xl font-semibold tracking-tight">{euros(intent.amount)}</p>
        <p className="mt-3 max-w-[38ch] text-sm leading-relaxed text-text-2">
          {failed
            ? intent.error?.message
            : 'Un reçu a été envoyé à votre adresse e-mail. Le montant apparaîtra sur votre relevé sous le libellé RESILIENCE PAY.'}
        </p>
      </div>

      <div className="mx-6 flex items-center gap-3 rounded-lg bg-well px-4 py-3">
        {viaPayPal ? (
          <span className="h-5 w-16">
            <PayPalMark className="h-full w-full" />
          </span>
        ) : (
          <>
            <span className="h-6 w-9 text-[#1a1f71]">
              <BrandLogo brand={intent.card.brand} className="h-full w-full" />
            </span>
            <span className="text-sm font-medium">•••• {intent.card.last4}</span>
          </>
        )}
        <span className="ml-auto truncate text-sm text-text-2">{intent.card.holder}</span>
      </div>

      <dl className="mt-6 divide-y divide-edge border-t border-edge text-sm">
        {rows.map(([k, v], i) => (
          <div
            key={k}
            className="rise flex items-baseline justify-between gap-6 px-6 py-3"
            style={{ animationDelay: `${120 + i * 60}ms` }}
          >
            <dt className="text-text-2">{k}</dt>
            <dd className="truncate text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="border-t border-edge px-6 py-5">
        <button
          type="button"
          onClick={onRestart}
          className={`h-11 w-full rounded-lg text-sm font-semibold transition-colors ${
            failed
              ? 'bg-accent text-white hover:bg-accent-strong'
              : 'border border-edge bg-card text-text hover:bg-well'
          }`}
        >
          {failed ? (viaPayPal ? 'Réessayer le paiement' : 'Réessayer avec une autre carte') : 'Nouveau paiement'}
        </button>
      </div>
    </div>
  )
}

function CheckMark() {
  return (
    <svg width="64" height="64" viewBox="0 0 56 56" fill="none" aria-hidden="true">
      <circle className="draw-circle" cx="28" cy="28" r="26" stroke="var(--color-good)" strokeWidth="2.5" />
      <path
        className="draw-check"
        d="M17 28.5l7.5 7.5L39.5 20"
        stroke="var(--color-good)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function CrossMark() {
  return (
    <svg width="64" height="64" viewBox="0 0 56 56" fill="none" aria-hidden="true">
      <circle className="draw-circle" cx="28" cy="28" r="26" stroke="var(--color-bad)" strokeWidth="2.5" />
      <path
        className="draw-check"
        d="M19 19l18 18M37 19L19 37"
        stroke="var(--color-bad)"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

import type { SystemState } from '../types'

const HEADLINE: Record<SystemState, string> = {
  nominal: 'Paiements opérationnels',
  degraded: 'Service de paiement interrompu',
  remediating: 'Remédiation en cours',
}

const DETAIL: Record<SystemState, string> = {
  nominal: 'Les transactions de contrôle passent',
  degraded: 'Les transactions de contrôle échouent',
  remediating: 'La plateforme applique le plan de reprise',
}

interface Props {
  state: SystemState
  headline?: string
  reason?: string
  elapsed: number
  humanActions: number
}

/** Le bandeau d'état : lisible à cinq mètres, avant le moindre chiffre. */
export function StatusBand({ state, headline, reason, elapsed, humanActions }: Props) {
  const mmss = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`

  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-panel bg-[var(--state)] text-white shadow-panel transition-colors duration-500 ${
        state === 'remediating' ? 'band-working' : ''
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-10 gap-y-3 px-6 py-5">
        <div className="flex items-center gap-4">
          <StateIcon state={state} />
          <div>
            <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{headline ?? HEADLINE[state]}</h1>
            <p className="mt-0.5 text-sm text-white/80">{reason ?? DETAIL[state]}</p>
          </div>
        </div>

        <dl className="flex items-center gap-8">
          <div className="text-right">
            <dt className="text-xs font-medium text-white/75">Interventions humaines</dt>
            <dd className="text-2xl font-semibold leading-tight">{humanActions}</dd>
          </div>
          <div className="text-right">
            <dt className="text-xs font-medium text-white/75">Écoulé</dt>
            <dd className="text-2xl font-semibold leading-tight">{mmss}</dd>
          </div>
        </dl>
      </div>
    </div>
  )
}

function StateIcon({ state }: { state: SystemState }) {
  const box = 'grid size-11 shrink-0 place-items-center rounded-full bg-white/15'
  if (state === 'nominal') {
    return (
      <span className={box}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M5 12.5l4.5 4.5L19 7.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    )
  }
  if (state === 'degraded') {
    return (
      <span className={box}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 8v5M12 16.5v.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          <path d="M10.3 3.8L2.6 17.2A2 2 0 0 0 4.3 20.2h15.4a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        </svg>
      </span>
    )
  }
  return (
    <span className={box}>
      <svg className="spin" width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.35" strokeWidth="2.4" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      </svg>
    </span>
  )
}

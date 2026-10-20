import type { Rail, RailStage, StageState } from '../domain/types'

const STAGES: { key: RailStage; label: string }[] = [
  { key: 'authorization', label: 'Autorisation' },
  { key: 'authentication', label: '3-D Secure' },
  { key: 'capture', label: 'Capture' },
  { key: 'settlement', label: 'Compensation' },
]

/**
 * Le trajet réel d'un paiement par carte, étape par étape. La piste se
 * remplit à mesure que le réseau répond ; une étape refusée vire au rouge.
 */
export function Stepper({ rail }: { rail: Rail }) {
  const states = STAGES.map((s) => rail[s.key])
  const failed = states.includes('failed')
  const reached = states.reduce((last, st, i) => (st === 'pending' ? last : i), -1)
  const fill = Math.max(0, reached) / (STAGES.length - 1)

  return (
    <div className="relative">
      {/* Piste de fond, entre le centre du premier et du dernier nœud. */}
      <div className="absolute left-[12.5%] right-[12.5%] top-3 h-0.5 bg-edge" aria-hidden="true">
        <div
          className={`h-full transition-[width] duration-500 ease-out ${failed ? 'bg-bad' : 'bg-good'}`}
          style={{ width: `${fill * 100}%` }}
        />
      </div>

      <ol className="relative grid grid-cols-4">
        {STAGES.map((s) => {
          const st = rail[s.key]
          return (
            <li key={s.key} className="flex flex-col items-center gap-2">
              <Node state={st} />
              <span
                className={`text-[12px] font-medium transition-colors ${
                  st === 'pending' || st === 'skipped' ? 'text-text-2' : 'text-text'
                }`}
              >
                {s.label}
              </span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Node({ state }: { state: StageState }) {
  const base = 'grid size-6 place-items-center rounded-full border-2 transition-[background-color,border-color] duration-300'
  if (state === 'done') {
    return (
      <span className={`${base} border-good bg-good text-white`}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M2.5 6.5l2.3 2.3L9.5 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    )
  }
  if (state === 'failed') {
    return (
      <span className={`${base} border-bad bg-bad text-white`}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M3.5 3.5l5 5M8.5 3.5l-5 5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </span>
    )
  }
  if (state === 'active') {
    return (
      <span className={`${base} ring border-accent bg-accent`}>
        <span className="size-2 rounded-full bg-white" />
      </span>
    )
  }
  if (state === 'skipped') {
    return <span className={`${base} border-dashed border-edge bg-card`} />
  }
  return <span className={`${base} border-edge bg-card`} />
}

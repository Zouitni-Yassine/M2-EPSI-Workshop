import type { CanaryTick } from '../types'
import { Panel } from './Panel'

/** Largeur fixe du ruban : les barres ne s'étirent jamais. */
const SLOTS = 120

interface Props {
  ticks: CanaryTick[]
}

/**
 * La pièce maîtresse : une barre par tentative de transaction fictive.
 * Vert = passée, rouge = échouée, hauteur = latence.
 * C'est elle qui prouve la reprise, pas le conteneur qui redémarre.
 */
export function CanaryRibbon({ ticks }: Props) {
  const passed = ticks.filter((t) => t.ok).length
  const failed = ticks.length - passed
  const last = ticks[ticks.length - 1]

  return (
    <Panel
      title="Transactions de contrôle"
      aside={`${passed} passées · ${failed} échouées · ${ticks.length} dernières`}
    >
      <div className="flex h-36 items-end gap-[2px] rounded-lg bg-well/60 px-2 pt-2" aria-hidden="true">
        {Array.from({ length: SLOTS }, (_, i) => {
          const tick = ticks[i - (SLOTS - ticks.length)]
          if (!tick) {
            return <div key={`gap-${i}`} className="h-px min-w-[3px] flex-1 bg-edge" />
          }
          // Les transactions saines occupent une bande franche : le ruban se lit
          // comme un tracé continu, et une seule barre rouge crève l'image.
          const height = tick.ok ? 40 + Math.min(1, tick.ms / 1500) * 60 : 100
          return (
            <div
              key={tick.seq}
              className={`min-w-[3px] flex-1 rounded-t-[2px] transition-[height] duration-300 ${
                tick.ok ? 'bg-good' : 'bg-bad'
              }`}
              style={{ height: `${height}%` }}
            />
          )
        })}
      </div>

      <p className="sr-only">
        {failed === 0
          ? `Les ${ticks.length} dernières transactions de contrôle ont abouti.`
          : `${failed} transactions de contrôle ont échoué sur les ${ticks.length} dernières.`}
      </p>

      <div className="mt-4 flex flex-wrap items-baseline gap-x-10 gap-y-2">
        <Figure
          label="Dernière tentative"
          value={last?.ok ? 'Passée' : 'Échouée'}
          tone={last?.ok ? 'good' : 'bad'}
        />
        <Figure label="Latence" value={last ? `${last.ms} ms` : '—'} />
        <Figure label="Intervalle" value="1 s" />
      </div>
    </Panel>
  )
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'bad' }) {
  const color = tone === 'good' ? 'text-good' : tone === 'bad' ? 'text-bad' : 'text-text'
  return (
    <div>
      <div className="text-xs text-text-2">{label}</div>
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
    </div>
  )
}

import type { Service, ServiceStatus } from '../types'
import { Panel } from './Panel'

const DOT: Record<ServiceStatus, string> = {
  up: 'bg-good',
  down: 'bg-bad',
  restarting: 'bg-accent ring',
  unknown: 'bg-edge',
}

const LABEL: Record<ServiceStatus, string> = {
  up: 'Actif',
  down: 'Arrêté',
  restarting: 'Recréation',
  unknown: 'Inobservable',
}

export function ServiceGrid({ services }: { services: Service[] }) {
  const down = services.filter((s) => s.status !== 'up').length

  return (
    <Panel title="Conteneurs" aside={down === 0 ? 'Tous actifs' : `${down} en anomalie`}>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {services.map((s) => (
          <li
            key={s.id}
            className={`rounded-lg border px-4 py-3 transition-colors ${
              s.status === 'down' ? 'border-bad/30 bg-bad/5' : s.status === 'restarting' ? 'border-accent/30 bg-accent/5' : 'border-edge bg-card'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={`size-2.5 shrink-0 rounded-full ${DOT[s.status]}`} />
              <span className="truncate text-sm font-medium">{s.name}</span>
            </div>
            <div className="mt-1 pl-[18px] text-xs text-text-2">{LABEL[s.status]}</div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

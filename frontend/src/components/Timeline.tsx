import type { EventKind, TimelineEvent } from '../types'
import { Panel } from './Panel'

const TONE: Record<EventKind, string> = {
  attack: 'bg-bad',
  detect: 'bg-note',
  act: 'bg-accent',
  verify: 'bg-accent',
  restore: 'bg-good',
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <Panel title="Chronologie" aside="Le plus récent en haut" className="h-full">
      {events.length === 0 ? (
        <p className="text-sm text-text-2">
          Rien à signaler. Les événements apparaîtront dès la première anomalie.
        </p>
      ) : (
        <ol className="space-y-4">
          {events.map((e) => (
            <li key={`${e.at}-${e.text}`} className="rise flex gap-3">
              <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${TONE[e.kind]}`} />
              <div className="min-w-0">
                <p className="text-sm leading-snug">{e.text}</p>
                <p className="mt-0.5 text-xs text-text-2">
                  {e.at} · {e.actor}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  )
}

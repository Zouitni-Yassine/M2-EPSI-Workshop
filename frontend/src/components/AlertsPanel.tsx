import type { AlertsState, AlertNotification, OpsAlert } from '../types'
import { Panel } from './Panel'

const SEVERITY: Record<string, string> = {
  critical: 'border-bad/40 bg-bad/10 text-bad',
  warning: 'border-note/40 bg-note/10 text-note',
  info: 'border-edge bg-well text-text-2',
}

function Chip({ children, className }: { children: string; className: string }) {
  return <span className={`rounded border px-1.5 py-px text-[11px] font-medium leading-4 ${className}`}>{children}</span>
}

function Tags({ severity, domain, ban }: { severity: string; domain?: string; ban: boolean }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <Chip className={SEVERITY[severity] ?? SEVERITY.info}>{severity}</Chip>
      {domain ? <Chip className="border-edge bg-well text-text-2">{domain}</Chip> : null}
      {ban ? <Chip className="border-bad/40 bg-bad/10 text-bad">IP bannie au WAF</Chip> : null}
    </span>
  )
}

function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString('fr-FR', { hour12: false })
}

function since(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, (Date.now() - t) / 1000)
  const d = s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1).replace('.', ',')} h`
  return `depuis ${clock(t)} (${d})`
}

function Active({ alerts }: { alerts: OpsAlert[] }) {
  if (alerts.length === 0) {
    return (
      <p className="flex items-center gap-2 text-sm text-text-2">
        <span className="size-2.5 shrink-0 rounded-full bg-good" />
        Aucune alerte active.
      </p>
    )
  }
  return (
    <ul className="space-y-3">
      {alerts.map((a) => (
        <li
          key={a.id}
          className={`rounded-lg border px-3 py-2.5 ${a.suppressed ? 'border-edge bg-well' : a.severity === 'critical' ? 'border-bad/30 bg-bad/5' : 'border-note/30 bg-note/5'}`}
        >
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="text-sm font-semibold">{a.name}</span>
            <Tags severity={a.severity} domain={a.domain} ban={a.ban} />
          </div>
          {a.summary ? <p className="mt-1 text-sm leading-snug">{a.summary}</p> : null}
          <p className="mt-0.5 text-xs text-text-2">
            {since(a.startsAt)}
            {a.target && !a.summary.includes(a.target) ? ` · ${a.target}` : ''}
            {a.suppressed ? ' · silenciée' : a.discord ? ' · envoyée sur Discord' : ''}
          </p>
        </li>
      ))}
    </ul>
  )
}

function History({ items }: { items: AlertNotification[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-text-2">Aucune notification sur les 6 dernières heures.</p>
  }
  return (
    <ol className="space-y-3">
      {items.map((n) => (
        <li key={n.id} className="flex gap-3">
          <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${n.status === 'firing' ? 'bg-bad' : 'bg-good'}`} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-text-2">
                {n.status === 'firing' ? 'Alerte' : 'Résolu'}
              </span>
              <span className="truncate text-sm font-medium">{n.title}</span>
            </div>
            {n.lines.map((l, i) => (
              <p key={i} className="text-xs leading-snug text-text-2">
                {l}
              </p>
            ))}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-2">
              {clock(n.at)}
              <Tags severity={n.severity} domain={n.domain} ban={n.ban} />
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}

/** Alertes de la supervision : ce qu'Alertmanager tient pour actif, et ce qu'il a envoyé sur Discord. */
export function AlertsPanel({ alerts }: { alerts?: AlertsState }) {
  const active = alerts?.active
  const firing = active?.filter((a) => !a.suppressed).length ?? 0
  const aside = !alerts ? 'n/d' : active == null ? 'Alertmanager injoignable' : firing === 0 ? 'Aucune active' : `${firing} active(s)`

  return (
    <Panel title="Alertes" aside={aside}>
      <div className="space-y-5">
        <section>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-2">Actives (Alertmanager)</h3>
          {active == null ? <p className="text-sm text-text-2">n/d : Alertmanager ne répond pas.</p> : <Active alerts={active} />}
        </section>
        <section className="border-t border-edge pt-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-2">Envoyées sur Discord · 6 h</h3>
          <div className="max-h-[420px] overflow-y-auto pr-1">
            {alerts?.history == null ? (
              <p className="text-sm text-text-2">n/d : journal des notifications indisponible.</p>
            ) : (
              <History items={alerts.history} />
            )}
          </div>
        </section>
      </div>
    </Panel>
  )
}

import type { InfraState } from '../types'
import { Panel } from './Panel'

type Tone = 'good' | 'bad' | 'note' | 'unknown'

const DOT: Record<Tone, string> = {
  good: 'bg-good',
  bad: 'bg-bad',
  note: 'bg-note',
  unknown: 'bg-edge',
}

const ND = 'n/d'
const CEPH = ['HEALTH_OK', 'HEALTH_WARN', 'HEALTH_ERR']

function age(s: number): string {
  if (s < 90) return `il y a ${Math.round(s)} s`
  if (s < 5400) return `il y a ${Math.round(s / 60)} min`
  return `il y a ${(s / 3600).toFixed(1).replace('.', ',')} h`
}

/** Ce qui porte l'application : hyperviseurs, Swarm, VIP, Ceph, Vault, et la preuve par la sonde. */
export function InfraRow({ infra }: { infra?: InfraState }) {
  const i = infra
  const ratio = (v: { up: number; total: number } | null | undefined) =>
    v ? { value: `${v.up}/${v.total}`, tone: (v.up >= v.total ? 'good' : v.up === 0 ? 'bad' : 'note') as Tone } : null

  const hv = ratio(i?.hypervisors)
  const sw = ratio(i?.swarm ? { up: i.swarm.ready, total: i.swarm.total } : null)

  const tiles: { label: string; value: string; detail: string; tone: Tone }[] = [
    { label: 'Hyperviseurs', value: hv?.value ?? ND, detail: 'Proxmox en ligne', tone: hv?.tone ?? 'unknown' },
    { label: 'Nœuds Swarm', value: sw?.value ?? ND, detail: 'prêts (managers et workers)', tone: sw?.tone ?? 'unknown' },
    {
      label: 'Porteur de la VIP',
      value: i?.vipHolder ?? ND,
      detail: '10.30.1.200 (keepalived)',
      tone: !i ? 'unknown' : i.vipHolder ? 'good' : 'bad',
    },
    {
      label: 'Ceph',
      value: i?.ceph == null ? ND : (CEPH[i.ceph] ?? `état ${i.ceph}`),
      detail: 'stockage des VM',
      tone: i?.ceph == null ? 'unknown' : i.ceph === 0 ? 'good' : i.ceph === 1 ? 'note' : 'bad',
    },
    {
      label: 'Vault',
      value: !i?.vault ? ND : i.vault === 'unsealed' ? 'Descellé' : i.vault === 'sealed' ? 'Scellé' : 'Scellé ou muet',
      detail: 'coffre des secrets',
      tone: !i?.vault ? 'unknown' : i.vault === 'unsealed' ? 'good' : 'bad',
    },
    {
      label: 'Dernier paiement sonde',
      value: i?.probeAgeS == null ? ND : age(i.probeAgeS),
      detail: 'transaction de test réussie',
      tone: i?.probeAgeS == null ? 'unknown' : i.probeAgeS < 120 ? 'good' : i.probeAgeS < 300 ? 'note' : 'bad',
    },
  ]

  const bad = tiles.filter((t) => t.tone === 'bad').length

  return (
    <Panel
      title="Infrastructure"
      aside={!i ? 'VictoriaMetrics injoignable' : bad === 0 ? 'VictoriaMetrics · 15 s' : `${bad} point(s) en défaut`}
    >
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {tiles.map((t) => (
          <li
            key={t.label}
            className={`rounded-lg border px-4 py-3 transition-colors ${
              t.tone === 'bad' ? 'border-bad/30 bg-bad/5' : t.tone === 'note' ? 'border-note/30 bg-note/5' : 'border-edge bg-card'
            }`}
          >
            <div className="flex items-center gap-2">
              <span className={`size-2.5 shrink-0 rounded-full ${DOT[t.tone]}`} />
              <span className="truncate text-xs text-text-2">{t.label}</span>
            </div>
            <div className="mt-1 truncate pl-[18px] text-base font-semibold tracking-tight">{t.value}</div>
            <div className="truncate pl-[18px] text-xs text-text-2">{t.detail}</div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

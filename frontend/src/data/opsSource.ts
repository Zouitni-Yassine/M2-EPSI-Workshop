import type { AlertNotification, AlertsState, BannedIp, InfraState, Metrics, OpsAlert, WafState } from '../types'

/**
 * Supervision de la plateforme vue par VictoriaMetrics, Loki et Alertmanager.
 *
 * Le navigateur n'écrit AUCUNE requête : chaque route /ops/m/<nom> du relais nginx porte sa
 * requête PromQL ou LogQL en dur (frontend/nginx.conf), exige une session d'opérateur, n'accepte
 * que GET sans paramètre et présente elle-même le compte en lecture seule `app-ops`.
 * Une route qui échoue rend sa tuile « n/d » : le reste de la page continue.
 */

const BASE = '/ops/m'
const TIMEOUT_MS = 6000

type Traffic = Pick<Metrics, 'rps' | 'errRate' | 'p95'>

export interface OpsState {
  traffic: Traffic | null
  /** Écart entre l'horloge de VictoriaMetrics et celle du poste (s), pour l'âge de la sonde. */
  infra: (Omit<InfraState, 'probeAgeS'> & { probeTs: number | null; clockOffsetS: number }) | null
  alerts: AlertsState
  waf: WafState
}

interface PromSample {
  metric: Record<string, string>
  value: [number, string]
}

interface LokiStream {
  stream: Record<string, string>
  values: [string, string][]
}

async function get<T>(route: string): Promise<T> {
  const res = await fetch(`${BASE}/${route}`, { signal: AbortSignal.timeout(TIMEOUT_MS), credentials: 'same-origin' })
  if (!res.ok) throw new Error(`${route} : HTTP ${res.status}`)
  return (await res.json()) as T
}

/** Vecteur instantané Prometheus/Loki ; chaque requête combinée étiquette ses valeurs par `m`. */
async function vector(route: string): Promise<PromSample[]> {
  const body = await get<{ status: string; data: { result: PromSample[] } }>(route)
  if (body.status !== 'success') throw new Error(`${route} : ${body.status}`)
  return body.data.result
}

async function lines(route: string): Promise<{ ts: number; line: string; stream: Record<string, string> }[]> {
  const body = await get<{ status: string; data: { result: LokiStream[] } }>(route)
  if (body.status !== 'success') throw new Error(`${route} : ${body.status}`)
  return body.data.result
    .flatMap((s) => s.values.map(([ns, line]) => ({ ts: Number(ns.slice(0, -6)), line, stream: s.stream })))
    .sort((a, b) => b.ts - a.ts)
}

function byKey(samples: PromSample[]): Map<string, PromSample> {
  return new Map(samples.map((s) => [s.metric.m ?? '', s]))
}

function num(s: PromSample | undefined): number | null {
  if (!s) return null
  const v = Number(s.value[1])
  return Number.isFinite(v) ? v : null
}

// ---- Débit, erreurs, p95 (payment-api, toutes les requêtes, fenêtre de 2 min) -------------

async function fetchTraffic(): Promise<Traffic> {
  const m = byKey(await vector('traffic'))
  const rps = num(m.get('rps'))
  if (rps === null) throw new Error('payment-api absent de VictoriaMetrics')
  return {
    rps: Math.round(rps * 10) / 10,
    errRate: num(m.get('err')) ?? 0,
    p95: Math.round((num(m.get('p95')) ?? 0) * 1000),
  }
}

// ---- Infrastructure ------------------------------------------------------------------------

async function fetchInfra(): Promise<NonNullable<OpsState['infra']>> {
  const m = byKey(await vector('infra'))
  const pair = (up: string, total: string) => {
    const t = num(m.get(total))
    return t === null ? null : { up: num(m.get(up)) ?? 0, total: t }
  }
  const hv = pair('pve_up', 'pve_total')
  const sw = pair('swarm_ready', 'swarm_total')
  const vaultV = num(m.get('vault'))
  const now = num(m.get('now'))
  return {
    hypervisors: hv,
    swarm: sw ? { ready: sw.up, total: sw.total } : null,
    vipHolder: m.get('vip')?.metric.host ?? null,
    ceph: num(m.get('ceph')),
    // La métrique disparaît quand Vault est scellé (ou injoignable) : son absence est un état.
    vault: vaultV === null ? 'absent' : vaultV === 1 ? 'unsealed' : 'sealed',
    probeTs: num(m.get('probe_ts')),
    clockOffsetS: now === null ? 0 : now - Date.now() / 1000,
  }
}

// ---- WAF : refus et IP bannies --------------------------------------------------------------

async function fetchWafBlocks(): Promise<number> {
  const r = await vector('waf_blocks')
  // Aucun refus sur la période : Loki ne renvoie aucune série.
  return r.length ? Math.round(Number(r[0].value[1])) : 0
}

/** Journal du récepteur waf-ban (waf01) : « ban ip=… raison=… duree_s=900 », « expiration ip=… », « deban ip=… ». */
async function fetchBans(): Promise<BannedIp[]> {
  const last = new Map<string, { ts: number; kind: string; reason: string; duration: number }>()
  for (const { ts, line } of await lines('waf_bans')) {
    const kind = line.split(' ', 1)[0]
    const ip = /\bip=(\S+)/.exec(line)?.[1]
    if (!ip || last.has(ip)) continue // le plus récent d'abord : seul le dernier événement compte
    last.set(ip, {
      ts,
      kind,
      reason: /\braison=(\S+)/.exec(line)?.[1] ?? '',
      duration: Number(/\bduree_s=(\d+)/.exec(line)?.[1] ?? 900),
    })
  }
  const now = Date.now()
  return [...last.entries()]
    .filter(([, e]) => e.kind === 'ban' && e.ts + e.duration * 1000 > now)
    .map(([ip, e]) => ({ ip, reason: e.reason, until: e.ts + e.duration * 1000 }))
    .sort((a, b) => b.until - a.until)
}

// ---- Alertes : actives (Alertmanager) et notifications envoyées sur Discord (Loki) ----------

interface AmAlert {
  fingerprint: string
  labels: Record<string, string>
  annotations: Record<string, string>
  startsAt: string
  status: { state: string }
  receivers: { name: string }[]
}

const SEVERITY_RANK: Record<string, number> = { critical: 0, warning: 1, info: 2 }

function target(labels: Record<string, string>): string | undefined {
  return labels.source_ip || labels.host || labels.service || labels.instance || labels.job || undefined
}

async function fetchActive(): Promise<OpsAlert[]> {
  const alerts = await get<AmAlert[]>('alerts')
  return alerts
    .filter((a) => a.labels.alertname !== 'Watchdog')
    .map((a) => ({
      id: a.fingerprint,
      name: a.labels.alertname ?? '?',
      severity: a.labels.severity ?? 'info',
      domain: a.labels.domain,
      summary: a.annotations.summary ?? a.annotations.description ?? '',
      target: target(a.labels),
      startsAt: a.startsAt,
      suppressed: a.status.state === 'suppressed',
      ban: a.labels.action === 'ban',
      discord: a.receivers.some((r) => r.name === 'discord'),
    }))
    .sort(
      (a, b) =>
        (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3) || Date.parse(b.startsAt) - Date.parse(a.startsAt),
    )
}

interface Webhook {
  status: 'firing' | 'resolved'
  groupKey?: string
  commonLabels?: Record<string, string>
  alerts: { status: string; labels: Record<string, string>; annotations: Record<string, string> }[]
}

/** Journal des notifications : une ligne par envoi du récepteur Discord (copie webhook locale). */
async function fetchHistory(): Promise<AlertNotification[]> {
  const out: AlertNotification[] = []
  for (const { ts, line } of await lines('notifications')) {
    let n: Webhook
    try {
      // Ligne écrite par le nginx de monitoring01 : {"ts": …, "body": "<JSON du webhook>"}
      n = JSON.parse((JSON.parse(line) as { body: string }).body) as Webhook
    } catch {
      continue
    }
    if (!n?.alerts?.length) continue
    const firing = n.alerts.filter((a) => a.status === 'firing')
    const shown = n.status === 'firing' ? firing : n.alerts
    const names = [...new Set(n.alerts.map((a) => a.labels.alertname ?? '?'))]
    const common = n.commonLabels ?? {}
    out.push({
      id: `${ts}-${n.groupKey ?? ''}`,
      at: ts,
      status: n.status,
      title: names.join(', ') + (shown.length > 1 ? ` (${shown.length})` : ''),
      severity: common.severity ?? n.alerts[0].labels.severity ?? 'info',
      domain: common.domain,
      ban: common.action === 'ban',
      lines: shown.slice(0, 3).map((a) => {
        const t = target(a.labels)
        const s = a.annotations.summary ?? a.annotations.description ?? ''
        return t && !s.includes(t) ? `${s} (${t})` : s
      }),
    })
    if (out.length >= 20) break
  }
  return out
}

// ---- Boucles de rafraîchissement --------------------------------------------------------------

/**
 * Lance les relevés (10 à 15 s ; les données de supervision ne vont pas plus vite : scrape de
 * 30 s, règles Loki toutes les 15 s) et appelle `onChange` à chaque nouvelle valeur.
 */
export function startOpsPolling(onChange: (s: OpsState) => void): () => void {
  const state: OpsState = {
    traffic: null,
    infra: null,
    alerts: { active: null, history: null },
    waf: { blocks15m: null, banned: null },
  }
  const timers: ReturnType<typeof setInterval>[] = []
  let stopped = false

  const every = <T,>(ms: number, load: () => Promise<T>, apply: (v: T | null) => void) => {
    const run = async () => {
      let v: T | null = null
      try {
        v = await load()
      } catch {
        v = null
      }
      if (stopped) return
      apply(v)
      onChange({ ...state, alerts: { ...state.alerts }, waf: { ...state.waf } })
    }
    void run()
    timers.push(setInterval(() => void run(), ms))
  }

  every(10_000, fetchTraffic, (v) => (state.traffic = v))
  every(15_000, fetchInfra, (v) => (state.infra = v))
  every(10_000, fetchActive, (v) => (state.alerts.active = v))
  every(15_000, fetchHistory, (v) => (state.alerts.history = v))
  every(15_000, fetchWafBlocks, (v) => (state.waf.blocks15m = v))
  every(15_000, fetchBans, (v) => (state.waf.banned = v))

  return () => {
    stopped = true
    timers.forEach(clearInterval)
  }
}

/** Âge de la sonde recalculé à chaque image (l'horloge locale avance entre deux relevés). */
export function infraNow(infra: OpsState['infra']): InfraState | undefined {
  if (!infra) return undefined
  const { probeTs, clockOffsetS, ...rest } = infra
  return {
    ...rest,
    probeAgeS: probeTs === null ? null : Math.max(0, Date.now() / 1000 + clockOffsetS - probeTs),
  }
}

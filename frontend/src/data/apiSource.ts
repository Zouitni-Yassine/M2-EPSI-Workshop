import type {
  AnomalyPoint,
  CanaryTick,
  DataSource,
  DetectorState,
  Metrics,
  Service,
  SystemState,
  TimelineEvent,
} from '../types'

const RIBBON = 120
const TICK_MS = 1000
const TIMEOUT_MS = 3000

interface Status {
  api: 'up'
  stripe: { up: boolean; latencyMs: number }
  /** Absent sur un backend plus ancien ; `configured: false` tant que PayPal n'est pas branché. */
  paypal?: { configured: boolean; up: boolean; latencyMs: number }
  /** La base du journal, sondée par payment-api. Absent sur un backend plus ancien. */
  db?: { up: boolean }
  metrics: Metrics
}

interface RemediationState {
  status: 'idle' | 'remediating'
  events: (TimelineEvent & { id: string })[]
  humanActions: number
}

interface Score {
  status: 'learning' | 'ready'
  progress: number
  threshold: number
  current: number | null
  over: boolean
  points: AnomalyPoint[]
}

function clock(): string {
  return new Date().toLocaleTimeString('fr-FR', { hour12: false })
}

/** Les services horodatent en ISO UTC ; on affiche l'heure locale du poste. */
function localTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('fr-FR', { hour12: false })
}

/**
 * Supervision en direct, sans moteur de remédiation : on interroge
 * payment-api chaque seconde (qui sonde lui-même Stripe) et le détecteur ML.
 * Chaque appel à l'API est une transaction de contrôle ; le score du
 * détecteur décide seul de l'état « anomalie ».
 */
export function createApiSource(apiUrl: string, detectorUrl?: string, remediationUrl?: string): DataSource {
  return {
    subscribe(onSnapshot) {
      const startedAt = Date.now()
      let seq = 0
      let prev = { api: true, stripe: true, paypal: true, db: true, over: false, detector: true }
      // La tuile PayPal n'apparaît qu'une fois que payment-api l'a annoncé comme configuré.
      let paypalSeen = false
      let dbSeen = false
      let metrics: Metrics = { rps: 0, errRate: 0, p95: 0, wafBlocks: 0 }
      let anomaly: AnomalyPoint[] = []
      let threshold = 0.55
      let detector: DetectorState = { status: 'absent', progress: 0 }
      let detectorOver = false
      let remediating = false
      let remediationUp = !remediationUrl
      let humanActions = 0
      // Les événements du moteur arrivent avec un identifiant : on ne les affiche qu'une fois.
      const seen = new Set<string>()
      const canary: CanaryTick[] = []
      let events: TimelineEvent[] = []
      let stopped = false

      const push = (kind: TimelineEvent['kind'], text: string) => {
        const event: TimelineEvent = { at: clock(), kind, text, actor: 'plateforme' }
        events = [event, ...events].slice(0, 12)
      }

      const probeApi = async () => {
        const t0 = performance.now()
        try {
          const res = await fetch(`${apiUrl}/status`, { signal: AbortSignal.timeout(TIMEOUT_MS - 100) })
          if (!res.ok) throw new Error(String(res.status))
          const body = (await res.json()) as Status
          metrics = body.metrics
          return {
            apiUp: true,
            stripeUp: body.stripe.up,
            paypal: body.paypal,
            db: body.db,
            ms: Math.round(performance.now() - t0) + body.stripe.latencyMs,
          }
        } catch {
          return { apiUp: false, stripeUp: false, paypal: undefined, db: undefined, ms: TIMEOUT_MS }
        }
      }

      const probeDetector = async () => {
        if (!detectorUrl) return
        try {
          const res = await fetch(`${detectorUrl}/score`, { signal: AbortSignal.timeout(900) })
          if (!res.ok) throw new Error(String(res.status))
          const body = (await res.json()) as Score
          detector = { status: body.status, progress: body.progress }
          threshold = body.threshold
          anomaly = body.points
          detectorOver = body.status === 'ready' && body.over
        } catch {
          detector = { status: 'absent', progress: 0 }
          anomaly = []
          detectorOver = false
        }
      }

      const probeRemediation = async () => {
        if (!remediationUrl) return
        try {
          const res = await fetch(`${remediationUrl}/state`, { signal: AbortSignal.timeout(900) })
          if (!res.ok) throw new Error(String(res.status))
          const body = (await res.json()) as RemediationState
          remediationUp = true
          remediating = body.status === 'remediating'
          humanActions = body.humanActions
          // Les plus anciens d'abord, pour que l'ordre d'arrivée reste chronologique.
          for (const e of [...body.events].reverse()) {
            if (seen.has(e.id)) continue
            seen.add(e.id)
            const incoming: TimelineEvent = { at: localTime(e.at), kind: e.kind, text: e.text, actor: 'plateforme' }
            events = [incoming, ...events].slice(0, 12)
          }
        } catch {
          remediationUp = false
          remediating = false
        }
      }

      const tick = async () => {
        const [probe] = await Promise.all([probeApi(), probeDetector(), probeRemediation()])
        if (stopped) return

        const { apiUp, stripeUp, paypal, db, ms } = probe
        const ok = apiUp && stripeUp
        canary.push({ seq: seq++, ok, ms })
        if (canary.length > RIBBON) canary.shift()

        const current = anomaly.at(-1)?.score ?? 0
        // C'est le détecteur qui confirme (persistance incluse), pas l'interface.
        const over = detectorOver

        if (prev.api && !apiUp) push('detect', 'payment-api ne répond plus — les transactions échouent')
        if (!prev.api && apiUp) push('restore', 'payment-api répond de nouveau')
        if (apiUp && prev.stripe && !stripeUp) push('detect', 'Stripe injoignable depuis payment-api')
        if (apiUp && !prev.stripe && stripeUp) push('restore', 'Stripe joignable de nouveau')
        // PayPal est un moyen de paiement en plus : sa panne s'affiche, mais ne rougit pas le canary carte.
        const paypalUp = paypal?.up ?? false
        paypalSeen ||= Boolean(paypal?.configured)
        if (apiUp && paypal?.configured && prev.paypal && !paypalUp) push('detect', 'PayPal sandbox injoignable depuis payment-api')
        if (apiUp && paypal?.configured && !prev.paypal && paypalUp) push('restore', 'PayPal sandbox joignable de nouveau')
        // Base en panne : les paiements passent encore, mais ne sont plus journalisés.
        const dbUp = db?.up ?? false
        dbSeen ||= db !== undefined
        if (apiUp && db && prev.db && !dbUp) push('detect', 'PostgreSQL injoignable — paiements acceptés mais non journalisés')
        if (apiUp && db && !prev.db && dbUp) push('restore', 'PostgreSQL de retour — journal réconcilié avec Stripe')
        if (!prev.over && over) {
          push('detect', `Score ML ${current.toFixed(2)} au-dessus du seuil ${threshold.toFixed(2)} — anomalie confirmée`)
        }
        if (prev.over && !over && detector.status === 'ready') {
          push('verify', `Score ML ${current.toFixed(2)} revenu sous le seuil`)
        }
        // Détecteur configuré mais muet : la plateforme est aveugle. Ce n'est pas « nominal ».
        const detectorUp = !detectorUrl || detector.status !== 'absent'
        if (prev.detector && !detectorUp) push('detect', 'Détecteur ML injoignable — la plateforme ne surveille plus rien')
        if (!prev.detector && detectorUp) push('restore', 'Détecteur ML de retour, réapprentissage en cours')
        prev = {
          api: apiUp,
          stripe: apiUp ? stripeUp : prev.stripe,
          paypal: apiUp && paypal?.configured ? paypalUp : prev.paypal,
          db: apiUp && db ? dbUp : prev.db,
          over,
          detector: detectorUp,
        }

        const state: SystemState = remediating ? 'remediating' : !ok || over || !detectorUp ? 'degraded' : 'nominal'
        const reason = !apiUp
          ? 'payment-api ne répond pas'
          : !stripeUp
            ? 'Stripe est injoignable depuis payment-api'
            : over
              ? `Le détecteur ML confirme une anomalie (score ${current.toFixed(2)})`
              : !detectorUp
                ? 'Détecteur ML injoignable : aucune détection possible'
                : undefined
        const services: Service[] = [
          { id: 'api', name: 'payment-api', status: apiUp ? 'up' : remediating ? 'restarting' : 'down' },
          // Sans payment-api, personne ne sonde Stripe : on ne prétend pas savoir.
          { id: 'stripe', name: 'stripe (externe)', status: !apiUp ? 'unknown' : stripeUp ? 'up' : 'down' },
          // Sans payment-api, personne ne sonde la base : on ne prétend pas savoir.
          ...(dbSeen ? [{ id: 'db', name: 'postgres', status: !apiUp ? 'unknown' : dbUp ? 'up' : 'down' } as Service] : []),
          ...(paypalSeen
            ? [{ id: 'paypal', name: 'paypal (externe)', status: !apiUp ? 'unknown' : paypalUp ? 'up' : 'down' } as Service]
            : []),
          { id: 'detector', name: 'detector (ML)', status: detector.status === 'absent' ? 'down' : 'up' },
          ...(remediationUrl ? [{ id: 'remediation', name: 'remediation', status: remediationUp ? 'up' : 'down' } as Service] : []),
          { id: 'front', name: 'frontend', status: 'up' },
        ]

        // Les paiements passent mais plus personne ne surveille : ce n'est pas la même alerte.
        const headline = ok && !over && !detectorUp ? 'Surveillance interrompue' : undefined

        onSnapshot({
          state,
          headline,
          reason,
          elapsed: Math.floor((Date.now() - startedAt) / 1000),
          canary: [...canary],
          anomaly,
          threshold,
          detector,
          services,
          events,
          metrics: apiUp ? metrics : { ...metrics, errRate: 1 },
          humanActions,
        })
      }

      void tick()
      const id = setInterval(() => void tick(), TICK_MS)
      return () => {
        stopped = true
        clearInterval(id)
      }
    },
  }
}

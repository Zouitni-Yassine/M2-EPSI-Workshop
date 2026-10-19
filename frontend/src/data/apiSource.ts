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
  metrics: Metrics
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

/**
 * Supervision en direct, sans moteur de remédiation : on interroge
 * payment-api chaque seconde (qui sonde lui-même Stripe) et le détecteur ML.
 * Chaque appel à l'API est une transaction de contrôle ; le score du
 * détecteur décide seul de l'état « anomalie ».
 */
export function createApiSource(apiUrl: string, detectorUrl?: string): DataSource {
  return {
    subscribe(onSnapshot) {
      const startedAt = Date.now()
      let seq = 0
      let prev = { api: true, stripe: true, over: false, detector: true }
      let metrics: Metrics = { rps: 0, errRate: 0, p95: 0, wafBlocks: 0 }
      let anomaly: AnomalyPoint[] = []
      let threshold = 0.55
      let detector: DetectorState = { status: 'absent', progress: 0 }
      let detectorOver = false
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
            ms: Math.round(performance.now() - t0) + body.stripe.latencyMs,
          }
        } catch {
          return { apiUp: false, stripeUp: false, ms: TIMEOUT_MS }
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

      const tick = async () => {
        const [probe] = await Promise.all([probeApi(), probeDetector()])
        if (stopped) return

        const { apiUp, stripeUp, ms } = probe
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
        prev = { api: apiUp, stripe: apiUp ? stripeUp : prev.stripe, over, detector: detectorUp }

        const state: SystemState = !ok || over || !detectorUp ? 'degraded' : 'nominal'
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
          { id: 'api', name: 'payment-api', status: apiUp ? 'up' : 'down' },
          // Sans payment-api, personne ne sonde Stripe : on ne prétend pas savoir.
          { id: 'stripe', name: 'stripe (externe)', status: !apiUp ? 'unknown' : stripeUp ? 'up' : 'down' },
          { id: 'detector', name: 'detector (ML)', status: detector.status === 'absent' ? 'down' : 'up' },
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
          humanActions: 0,
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

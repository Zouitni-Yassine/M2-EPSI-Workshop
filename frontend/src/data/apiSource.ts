import type {
  CanaryTick,
  DataSource,
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

function clock(): string {
  return new Date().toLocaleTimeString('fr-FR', { hour12: false })
}

/**
 * Supervision en direct, sans moteur de remédiation : on interroge
 * payment-api chaque seconde, qui sonde lui-même Stripe. Chaque appel est
 * une transaction de contrôle : si l'un des deux ne répond pas, la barre
 * est rouge et l'événement s'inscrit dans la chronologie.
 *
 * Le score d'anomalie reste vide : il viendra du détecteur ML quand il
 * sera branché. On ne l'invente pas.
 */
export function createApiSource(baseUrl: string): DataSource {
  return {
    subscribe(onSnapshot) {
      const startedAt = Date.now()
      let seq = 0
      let prev = { api: true, stripe: true }
      let metrics: Metrics = { rps: 0, errRate: 0, p95: 0, wafBlocks: 0 }
      const canary: CanaryTick[] = []
      let events: TimelineEvent[] = []
      let stopped = false

      const push = (kind: TimelineEvent['kind'], text: string) => {
        const event: TimelineEvent = { at: clock(), kind, text, actor: 'plateforme' }
        events = [event, ...events].slice(0, 12)
      }

      const tick = async () => {
        const t0 = performance.now()
        let apiUp = false
        let stripeUp = false
        let stripeMs = 0

        try {
          const res = await fetch(`${baseUrl}/status`, { signal: AbortSignal.timeout(TIMEOUT_MS - 100) })
          if (res.ok) {
            const body = (await res.json()) as Status
            apiUp = true
            stripeUp = body.stripe.up
            stripeMs = body.stripe.latencyMs
            metrics = body.metrics
          }
        } catch {
          // payment-api injoignable : la barre sera rouge, c'est tout ce qu'il faut dire.
        }
        if (stopped) return

        const ok = apiUp && stripeUp
        const roundTrip = Math.round(performance.now() - t0)
        canary.push({ seq: seq++, ok, ms: ok ? roundTrip + stripeMs : TIMEOUT_MS })
        if (canary.length > RIBBON) canary.shift()

        if (prev.api && !apiUp) push('detect', 'payment-api ne répond plus — les transactions échouent')
        if (!prev.api && apiUp) push('restore', 'payment-api répond de nouveau')
        if (apiUp && prev.stripe && !stripeUp) push('detect', 'Stripe injoignable depuis payment-api')
        if (apiUp && !prev.stripe && stripeUp) push('restore', 'Stripe joignable de nouveau')
        prev = { api: apiUp, stripe: apiUp ? stripeUp : prev.stripe }

        const state: SystemState = ok ? 'nominal' : 'degraded'
        const services: Service[] = [
          { id: 'api', name: 'payment-api', status: apiUp ? 'up' : 'down' },
          // Sans payment-api, personne ne sonde Stripe : on ne prétend pas savoir.
          { id: 'stripe', name: 'stripe (externe)', status: !apiUp ? 'unknown' : stripeUp ? 'up' : 'down' },
          { id: 'front', name: 'frontend', status: 'up' },
        ]

        onSnapshot({
          state,
          elapsed: Math.floor((Date.now() - startedAt) / 1000),
          canary: [...canary],
          anomaly: [],
          threshold: 0.55,
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

import type { DataSource, Service, Snapshot, SystemState, TimelineEvent } from '../types'
import {
  ANOMALY_THRESHOLD,
  BEATS,
  SCENARIO_LENGTH,
  anomalyScore,
  canaryLatency,
  canaryOk,
  metricsAt,
} from './scenario'

const RIBBON = 120
const TICK_MS = 1000

const BASE_SERVICES: Service[] = [
  { id: 'waf', name: 'waf', status: 'up' },
  { id: 'api', name: 'payment-api', status: 'up' },
  { id: 'auth', name: 'auth-svc', status: 'up' },
  { id: 'db', name: 'postgres', status: 'up' },
  { id: 'front', name: 'frontend', status: 'up' },
  { id: 'engine', name: 'remediation', status: 'up' },
]

function clock(t: number): string {
  const d = new Date(Date.UTC(2026, 9, 23, 9, 14, 0) + t * 1000)
  return d.toISOString().slice(11, 19)
}

/**
 * Rejoue le scenario en boucle et emet un instantane par seconde.
 * Meme forme de donnees que la source live : les composants ne font pas
 * la difference.
 */
export function createMockSource(): DataSource {
  return {
    subscribe(onSnapshot) {
      // ?t=25 demarre le scenario a la 25e seconde, pour inspecter une phase
      // precise sans attendre la boucle complete.
      const start = Number(new URLSearchParams(location.search).get('t') ?? 0)
      let t = Number.isFinite(start) ? Math.max(0, Math.floor(start)) % SCENARIO_LENGTH : 0
      let state: SystemState = 'nominal'
      let services = BASE_SERVICES.map((s) => ({ ...s }))
      let events: TimelineEvent[] = []
      const canary: Snapshot['canary'] = []
      const anomaly: Snapshot['anomaly'] = []

      let first = true

      const emit = () => {
        if (t === 0 && !first) {
          state = 'nominal'
          services = BASE_SERVICES.map((s) => ({ ...s }))
          events = []
          canary.length = 0
          anomaly.length = 0
        }

        for (const beat of BEATS) {
          // Au demarrage differe, on rejoue tous les temps deja passes.
          if (first ? beat.t > t : beat.t !== t) continue
          if (beat.state) state = beat.state
          if (beat.service) {
            services = services.map((s) =>
              s.id === beat.service!.id ? { ...s, status: beat.service!.status } : s,
            )
          }
          if (beat.event) {
            events = [{ at: clock(beat.t), ...beat.event }, ...events].slice(0, 12)
          }
        }

        if (first && t > 0) {
          // Rejoue l'historique pour que le ruban ne soit pas vide au demarrage differe.
          for (let k = Math.max(0, t - RIBBON); k < t; k++) {
            const past = canaryOk(k)
            canary.push({ seq: k, ok: past, ms: Math.round(canaryLatency(k, past)) })
            anomaly.push({ seq: k, score: Number(anomalyScore(k).toFixed(3)) })
          }
        }

        const ok = canaryOk(t)
        canary.push({ seq: t, ok, ms: Math.round(canaryLatency(t, ok)) })
        if (canary.length > RIBBON) canary.shift()

        anomaly.push({ seq: t, score: Number(anomalyScore(t).toFixed(3)) })
        if (anomaly.length > RIBBON) anomaly.shift()

        onSnapshot({
          state,
          elapsed: t,
          canary: [...canary],
          anomaly: [...anomaly],
          threshold: ANOMALY_THRESHOLD,
          detector: { status: 'ready', progress: 1 },
          services,
          events,
          metrics: metricsAt(t),
          humanActions: 0,
        })

        first = false
        t = (t + 1) % SCENARIO_LENGTH
      }

      emit()
      const id = setInterval(emit, TICK_MS)
      return () => clearInterval(id)
    },
  }
}

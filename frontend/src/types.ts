/** Les trois etats que le jury doit pouvoir lire a cinq metres. */
export type SystemState = 'nominal' | 'degraded' | 'remediating'

/** Une tentative de transaction fictive jouee par le canary. */
export interface CanaryTick {
  seq: number
  ok: boolean
  /** Latence en millisecondes. Pilote la hauteur de la barre. */
  ms: number
}

export interface AnomalyPoint {
  seq: number
  score: number
}

export type EventKind = 'attack' | 'detect' | 'act' | 'verify' | 'restore'

export interface TimelineEvent {
  at: string
  kind: EventKind
  text: string
  /** Qui a agi. Aucun evenement ne doit jamais porter 'operateur'. */
  actor: 'attaquant' | 'plateforme'
}

export type ServiceStatus = 'up' | 'down' | 'restarting' | 'unknown'

export interface Service {
  id: string
  name: string
  status: ServiceStatus
}

export interface Metrics {
  rps: number
  errRate: number
  p95: number
  wafBlocks: number
}

/** L'etat complet du systeme a un instant t. */
export interface Snapshot {
  state: SystemState
  elapsed: number
  canary: CanaryTick[]
  anomaly: AnomalyPoint[]
  threshold: number
  services: Service[]
  events: TimelineEvent[]
  metrics: Metrics
  humanActions: number
}

/**
 * Le contrat unique entre l'interface et ses donnees.
 * `mock` le remplit depuis un scenario local, `live` depuis le WebSocket
 * du moteur de remediation. Les composants ne savent pas lequel tourne.
 */
export interface DataSource {
  subscribe(onSnapshot: (s: Snapshot) => void): () => void
}

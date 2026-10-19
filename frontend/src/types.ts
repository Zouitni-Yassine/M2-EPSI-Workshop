/** Les trois états que le jury doit pouvoir lire à cinq mètres. */
export type SystemState = 'nominal' | 'degraded' | 'remediating'

/** Une tentative de transaction fictive jouée par le canary. */
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

/** Où en est le détecteur ML : absent, en apprentissage de la normale, ou prêt. */
export interface DetectorState {
  status: 'absent' | 'learning' | 'ready'
  /** Part de l'échauffement accomplie, de 0 à 1. */
  progress: number
}

export type EventKind = 'attack' | 'detect' | 'act' | 'verify' | 'restore'

export interface TimelineEvent {
  at: string
  kind: EventKind
  text: string
  /** Qui a agi. Aucun événement ne doit jamais porter 'opérateur'. */
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

/** L'état complet du système à un instant t. */
export interface Snapshot {
  state: SystemState
  elapsed: number
  canary: CanaryTick[]
  anomaly: AnomalyPoint[]
  threshold: number
  detector: DetectorState
  services: Service[]
  events: TimelineEvent[]
  metrics: Metrics
  humanActions: number
}

/**
 * Le contrat unique entre l'interface et ses données.
 * `mock` le remplit depuis un scénario local, `api` depuis payment-api et le
 * détecteur, `ws` depuis le moteur de remédiation. Les composants ne savent
 * pas lequel tourne.
 */
export interface DataSource {
  subscribe(onSnapshot: (s: Snapshot) => void): () => void
}

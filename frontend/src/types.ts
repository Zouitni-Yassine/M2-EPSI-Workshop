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
  /** D'où viennent débit, erreurs et p95 : VictoriaMetrics (toutes les requêtes de payment-api)
   *  ou, à défaut, la fenêtre de 10 s tenue par payment-api lui-même (/api/status). */
  source?: 'victoriametrics' | 'api'
}

// ---- Supervision de la plateforme (VictoriaMetrics, Loki, Alertmanager) ------------------
// Lues par des routes FIXES du relais nginx (/ops/m/*), jamais par une requête libre.
// `null` = source injoignable : la tuile affiche « n/d », la page continue de vivre.

export interface InfraState {
  hypervisors: { up: number; total: number } | null
  swarm: { ready: number; total: number } | null
  /** Nœud qui porte l'adresse virtuelle de l'application. */
  vipHolder: string | null
  /** 0 HEALTH_OK, 1 HEALTH_WARN, 2 HEALTH_ERR. */
  ceph: number | null
  /** Métrique absente = Vault scellé ou injoignable (elle disparaît une fois scellé). */
  vault: 'unsealed' | 'sealed' | 'absent' | null
  /** Âge du dernier paiement réussi de la sonde de transaction, en secondes. */
  probeAgeS: number | null
}

export interface OpsAlert {
  id: string
  name: string
  severity: string
  domain?: string
  summary: string
  /** Hôte, service ou IP source concerné. */
  target?: string
  startsAt: string
  /** Silenciée ou inhibée : connue d'Alertmanager mais non notifiée. */
  suppressed: boolean
  ban: boolean
  discord: boolean
}

/** Une notification envoyée sur Discord (un groupe d'alertes d'Alertmanager). */
export interface AlertNotification {
  id: string
  at: number
  status: 'firing' | 'resolved'
  title: string
  severity: string
  domain?: string
  ban: boolean
  lines: string[]
}

export interface AlertsState {
  /** null = Alertmanager injoignable. */
  active: OpsAlert[] | null
  /** null = journal des notifications (Loki) injoignable. */
  history: AlertNotification[] | null
}

export interface BannedIp {
  ip: string
  reason: string
  /** Fin du bannissement, en ms depuis l'epoch. */
  until: number
}

export interface WafState {
  /** Requêtes refusées (403) par le WAF sur les 15 dernières minutes. */
  blocks15m: number | null
  banned: BannedIp[] | null
}

/** L'état complet du système à un instant t. */
export interface Snapshot {
  state: SystemState
  /** Titre du bandeau quand l'état mérite mieux que le libellé par défaut. */
  headline?: string
  /** Pourquoi l'état n'est pas nominal, en une phrase. */
  reason?: string
  elapsed: number
  canary: CanaryTick[]
  anomaly: AnomalyPoint[]
  threshold: number
  detector: DetectorState
  services: Service[]
  events: TimelineEvent[]
  metrics: Metrics
  humanActions: number
  /** Absents en mode démo (mock, ws) : les panneaux affichent « n/d ». */
  infra?: InfraState
  alerts?: AlertsState
  waf?: WafState
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

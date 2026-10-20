import type { EventKind, SystemState } from '../types'

/**
 * Scénario de demonstration, une entree par seconde.
 * Il sert a construire l'interface sans backend et a repeter le passage
 * devant le jury. La chronologie reproduit celle attendue par le sujet :
 * attaque, detection, remediation, verification, retablissement.
 */
export interface Beat {
  t: number
  state?: SystemState
  event?: { kind: EventKind; text: string; actor: 'attaquant' | 'plateforme' }
  service?: { id: string; status: 'up' | 'down' | 'restarting' }
}

export const SCENARIO_LENGTH = 58
export const ANOMALY_THRESHOLD = 0.55

export const ATTACK_AT = 18
export const DETECT_AT = 23
export const REMEDIATE_AT = 25
export const RECOVER_AT = 38

export const BEATS: Beat[] = [
  {
    t: ATTACK_AT,
    event: {
      kind: 'attack',
      actor: 'attaquant',
      text: 'Rafale POST /api/payments depuis 192.168.137.50',
    },
  },
  {
    t: 21,
    event: { kind: 'attack', actor: 'attaquant', text: 'payment-api saturé, 5xx en hausse' },
  },
  {
    t: DETECT_AT,
    state: 'degraded',
    service: { id: 'api', status: 'down' },
    event: {
      kind: 'detect',
      actor: 'plateforme',
      text: 'Score ML 0.81 au-dessus du seuil 0.55 — anomalie confirmée',
    },
  },
  {
    t: REMEDIATE_AT,
    state: 'remediating',
    event: { kind: 'act', actor: 'plateforme', text: '192.168.137.50 bannie au WAF' },
  },
  {
    t: 27,
    service: { id: 'api', status: 'restarting' },
    event: {
      kind: 'act',
      actor: 'plateforme',
      text: 'payment-api recréé depuis l’image saine',
    },
  },
  {
    t: 32,
    service: { id: 'api', status: 'up' },
    event: { kind: 'verify', actor: 'plateforme', text: 'Intégrité de la base vérifiée — conforme' },
  },
  {
    t: 36,
    event: {
      kind: 'verify',
      actor: 'plateforme',
      text: 'Transaction de contrôle passée en 212 ms',
    },
  },
  {
    t: RECOVER_AT,
    state: 'nominal',
    event: {
      kind: 'restore',
      actor: 'plateforme',
      text: 'Service rétabli — 15 s depuis la détection, 0 intervention',
    },
  },
]

/** Score d'anomalie du modele a l'instant t. Monte avec l'attaque, retombe apres la reprise. */
export function anomalyScore(t: number): number {
  const noise = (Math.sin(t * 1.7) + Math.sin(t * 0.6)) * 0.015
  if (t < ATTACK_AT) return 0.11 + noise
  if (t < DETECT_AT + 1) return 0.11 + ((t - ATTACK_AT) / 6) * 0.78 + noise
  if (t < REMEDIATE_AT + 3) return 0.89 + noise
  if (t < RECOVER_AT) return Math.max(0.12, 0.89 - ((t - REMEDIATE_AT - 3) / 10) * 0.77) + noise
  return 0.11 + noise
}

/** Le canary echoue entre la saturation et la fin de la recreation du conteneur. */
export function canaryOk(t: number): boolean {
  return t < 21 || t > 33
}

export function canaryLatency(t: number, ok: boolean): number {
  if (!ok) return 3000
  const base = 180 + Math.sin(t * 2.1) * 25
  if (t >= ATTACK_AT && t < 21) return base + (t - ATTACK_AT) * 420
  if (t > 33 && t < 36) return base + 180
  return base
}

export function metricsAt(t: number) {
  const attacking = t >= ATTACK_AT && t < REMEDIATE_AT + 1
  const calm = { rps: 42, errRate: 0.004, p95: 196, wafBlocks: 0 }
  if (!attacking) {
    return {
      rps: Math.round(calm.rps + Math.sin(t) * 3),
      errRate: calm.errRate,
      p95: Math.round(calm.p95 + Math.sin(t * 1.3) * 14),
      wafBlocks: t >= REMEDIATE_AT ? 1884 : 0,
    }
  }
  const ramp = (t - ATTACK_AT) / (REMEDIATE_AT - ATTACK_AT)
  return {
    rps: Math.round(42 + ramp * 2610),
    errRate: Math.min(0.72, ramp * 0.78),
    p95: Math.round(196 + ramp * 7400),
    wafBlocks: Math.round(ramp * 1884),
  }
}

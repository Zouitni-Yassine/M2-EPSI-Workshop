import type { AnomalyPoint } from '../types'
import { Panel } from './Panel'

const W = 600
const H = 180
const PAD_TOP = 14
const PAD_BOTTOM = 6
const GOOD = '#15803d'
const BAD = '#dc2626'

interface Props {
  points: AnomalyPoint[]
  threshold: number
}

type XY = [number, number]

/** Courbe lissée (Catmull-Rom → Bézier) : le tracé respire au lieu de casser à chaque seconde. */
function smoothPath(pts: XY[]): string {
  if (pts.length < 2) return ''
  let d = `M ${pts[0][0]} ${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0]} ${p2[1]}`
  }
  return d
}

/**
 * Score du modèle dans le temps. La zone d'alerte est teintée plutôt que
 * barrée : le tracé passe au rouge dès qu'il y entre, et c'est tout ce
 * qu'il faut lire.
 */
export function AnomalyChart({ points, threshold }: Props) {
  const current = points.at(-1)?.score ?? 0
  const over = current >= threshold
  const span = Math.max(points.length - 1, 1)
  const plotH = H - PAD_TOP - PAD_BOTTOM
  const x = (i: number) => Number(((i / span) * W).toFixed(1))
  const y = (score: number) => Number((PAD_TOP + plotH - score * plotH).toFixed(1))

  const pts: XY[] = points.map((p, i) => [x(i), y(p.score)])
  const line = smoothPath(pts)
  const area = pts.length >= 2 ? `${line} L ${pts.at(-1)![0]} ${H} L ${pts[0][0]} ${H} Z` : ''
  const yT = y(threshold)
  const last = pts.at(-1)

  return (
    <Panel
      title="Score d'anomalie"
      aside={<span>IsolationForest · 120 dernières secondes</span>}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        className="h-40 w-full"
        role="img"
        aria-label={`Score d'anomalie ${current.toFixed(2)} pour un seuil de ${threshold}`}
      >
        <defs>
          <linearGradient id="anomalyFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={GOOD} stopOpacity="0.22" />
            <stop offset="1" stopColor={GOOD} stopOpacity="0" />
          </linearGradient>
          <clipPath id="belowThreshold">
            <rect x="0" y={yT} width={W} height={H - yT} />
          </clipPath>
          <clipPath id="aboveThreshold">
            <rect x="0" y="0" width={W} height={yT} />
          </clipPath>
        </defs>

        {/* Zone d'alerte : tout ce qui dépasse le seuil. */}
        <rect x="0" y="0" width={W} height={yT} fill={BAD} opacity="0.05" />

        <path d={area} fill="url(#anomalyFill)" />
        <path d={line} fill="none" stroke={GOOD} strokeWidth="2.5" vectorEffect="non-scaling-stroke" clipPath="url(#belowThreshold)" />
        <path d={line} fill="none" stroke={BAD} strokeWidth="2.5" vectorEffect="non-scaling-stroke" clipPath="url(#aboveThreshold)" />

        {last ? (
          <circle cx={last[0]} cy={last[1]} r="4" fill={over ? BAD : GOOD} stroke="#fff" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        ) : null}
      </svg>

      <div className="mt-4 flex items-end justify-between gap-6">
        <div>
          <div className="text-xs text-text-2">Score courant</div>
          <div className={`text-3xl font-semibold tracking-tight ${over ? 'text-bad' : 'text-good'}`}>
            {current.toFixed(2)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-text-2">Seuil d’alerte</div>
          <div className="text-lg font-semibold">{threshold.toFixed(2)}</div>
        </div>
        <p className="hidden max-w-[28ch] text-right text-xs leading-relaxed text-text-2 sm:block">
          Débit, taux de 5xx, latence p95, CPU, RAM, blocages WAF.
        </p>
      </div>
    </Panel>
  )
}

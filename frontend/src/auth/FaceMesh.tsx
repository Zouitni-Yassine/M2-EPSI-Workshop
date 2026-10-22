import { useEffect, useRef, useState } from 'react'
import type { FaceProbe } from './session'

/** Le visage tel qu'il s'affiche : centre, demi-axes et orientation, en pixels de l'image, à l'écran (miroir). */
interface Pose {
  cx: number
  cy: number
  rx: number
  ry: number
  turn: number // radians, positif quand le visage tourne vers la droite de l'écran
  points: [number, number][]
}

interface Oval {
  cx: number
  cy: number
  rx: number
  ry: number
}

const LATITUDES = [-0.84, -0.63, -0.42, -0.21, 0, 0.21, 0.42, 0.63, 0.84]
const MERIDIANS = Array.from({ length: 13 }, (_, i) => ((i - 6) * 14 * Math.PI) / 180)
const SWEEP_MS = 2400
const reducedMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** Ce que voit l'IA, ramené à l'écran : la vidéo est affichée en miroir. */
function toScreen(seen: FaceProbe, width: number, height: number): Pose | null {
  if (!seen.box || seen.faces === 0) return null
  const [x, y, w, h] = seen.box
  return {
    cx: (1 - (x + w / 2)) * width,
    cy: (y + h / 2) * height,
    rx: (w / 2) * width,
    ry: (h / 2) * height,
    // L'orientation mesurée vaut environ 0,2 pour une tête tournée de 25° ; miroir : signe inversé.
    turn: Math.max(-0.95, Math.min(0.95, -(seen.yaw ?? 0) * 2.2)),
    points: (seen.points ?? []).map(([px, py]) => [(1 - px) * width, py * height] as [number, number]),
  }
}

/** Largeur du visage à une hauteur donnée (-1 front, 1 menton) : le menton est plus étroit. */
const breadth = (v: number) => Math.sqrt(Math.max(0, 1 - v * v)) * (v > 0 ? 1 - 0.24 * v : 1)

/**
 * Maillage du visage, à la manière d'un scanner 3D : parallèles et méridiens d'une surface qui
 * tourne avec la tête, petits carrés aux intersections, cadre et repères de l'IA. Les positions
 * reçues quelques fois par seconde sont lissées à chaque image, pour un suivi sans à-coups ; une
 * ligne de balayage parcourt l'ovale et allume les carrés à son passage.
 */
export function FaceMesh({
  seen,
  width,
  height,
  oval,
  tone,
  locked,
  active,
  clipId,
  glowId,
}: {
  seen: FaceProbe | null
  width: number
  height: number
  oval: Oval
  tone: string
  locked: boolean
  active: boolean
  clipId: string
  glowId: string
}) {
  const target = useRef<Pose | null>(null)
  target.current = seen ? toScreen(seen, width, height) : null

  const [view, setView] = useState<{ pose: Pose | null; opacity: number; now: number }>({ pose: null, opacity: 0, now: 0 })

  useEffect(() => {
    if (!active) return
    let raf = 0
    let last = performance.now()
    let pose: Pose | null = null
    let opacity = 0
    const tick = (now: number) => {
      const dt = Math.min(64, now - last)
      last = now
      const goal = target.current
      const follow = 1 - Math.exp(-dt / 110)
      if (goal) {
        if (!pose || pose.points.length !== goal.points.length) pose = { ...goal, points: goal.points.map((p) => [...p] as [number, number]) }
        else {
          pose.cx += (goal.cx - pose.cx) * follow
          pose.cy += (goal.cy - pose.cy) * follow
          pose.rx += (goal.rx - pose.rx) * follow
          pose.ry += (goal.ry - pose.ry) * follow
          pose.turn += (goal.turn - pose.turn) * follow
          pose.points.forEach((p, i) => {
            p[0] += (goal.points[i][0] - p[0]) * follow
            p[1] += (goal.points[i][1] - p[1]) * follow
          })
        }
        opacity += (1 - opacity) * (1 - Math.exp(-dt / 160))
      } else {
        opacity += (0 - opacity) * (1 - Math.exp(-dt / 160))
      }
      setView({ pose: pose && { ...pose, points: pose.points.map((p) => [...p] as [number, number]) }, opacity, now })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active])

  const k = height / 480
  const still = reducedMotion()
  const sweepPhase = still ? 0 : (view.now % SWEEP_MS) / SWEEP_MS
  const sweepY = oval.cy - oval.ry * 1.1 + oval.ry * 2.4 * sweepPhase
  const pose = view.pose

  return (
    <g>
      {/* Balayage vertical dans l'ovale */}
      {active && !still ? (
        <g clipPath={`url(#${clipId})`}>
          <rect
            x={oval.cx - oval.rx}
            y={sweepY - oval.ry * 0.5}
            width={oval.rx * 2}
            height={oval.ry * 0.5}
            fill={`url(#${clipId}-sweep)`}
          />
          <line
            x1={oval.cx - oval.rx}
            x2={oval.cx + oval.rx}
            y1={sweepY}
            y2={sweepY}
            stroke={tone}
            strokeWidth={1.5 * k}
            opacity={0.9}
            filter={`url(#${glowId})`}
          />
        </g>
      ) : null}

      {active && pose && view.opacity > 0.02 ? (
        <g opacity={view.opacity} style={{ color: tone }}>
          <Mesh pose={pose} k={k} sweepY={still || locked ? null : sweepY} glowId={glowId} />
          <Brackets pose={pose} k={k} locked={locked} glowId={glowId} />
        </g>
      ) : null}
    </g>
  )
}

function Mesh({ pose, k, sweepY, glowId }: { pose: Pose; k: number; sweepY: number | null; glowId: string }) {
  const mrx = pose.rx * 1.02
  const mry = pose.ry * 1.1
  const mcy = pose.cy + pose.ry * 0.02
  const at = (v: number, a: number): [number, number] => [pose.cx + mrx * breadth(v) * Math.sin(a), mcy + mry * v]
  // Les carrés s'allument au passage du balayage, et s'estompent vers les bords du visage.
  const lit = (y: number) => (sweepY === null ? 1 : 0.3 + 0.7 * Math.exp(-(((y - sweepY) / (pose.ry * 0.22)) ** 2)))

  const parallels = LATITUDES.map((v) => {
    const pts: string[] = []
    for (let d = -84; d <= 84; d += 12) {
      const [x, y] = at(v, (d * Math.PI) / 180)
      pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
    }
    return pts.join(' ')
  })
  const meridians = MERIDIANS.map((m) => m + pose.turn)
    .filter((a) => Math.abs(a) < Math.PI / 2 - 0.05)
    .map((a) => {
      const pts: string[] = []
      for (let v = -0.96; v <= 0.961; v += 0.12) {
        const [x, y] = at(v, a)
        pts.push(`${x.toFixed(1)},${y.toFixed(1)}`)
      }
      return { a, d: pts.join(' ') }
    })
  const cells: { x: number; y: number; depth: number }[] = []
  for (const { a } of meridians) {
    for (const v of LATITUDES) {
      const [x, y] = at(v, a)
      cells.push({ x, y, depth: Math.cos(a) })
    }
  }

  return (
    <g>
      <g fill="none" stroke="currentColor" strokeWidth={0.8 * k} opacity={0.32}>
        {parallels.map((d, i) => (
          <polyline key={`p${i}`} points={d} />
        ))}
        {meridians.map((m, i) => (
          <polyline key={`m${i}`} points={m.d} opacity={0.4 + 0.6 * Math.cos(m.a)} />
        ))}
      </g>
      <g fill="currentColor" filter={`url(#${glowId})`}>
        {cells.map((c, i) => {
          const s = (2.2 + 2.6 * c.depth) * k
          return (
            <rect
              key={i}
              x={c.x - s / 2}
              y={c.y - s / 2}
              width={s}
              height={s}
              opacity={(0.25 + 0.75 * c.depth) * lit(c.y)}
            />
          )
        })}
      </g>
    </g>
  )
}

function Brackets({ pose, k, locked, glowId }: { pose: Pose; k: number; locked: boolean; glowId: string }) {
  const x0 = pose.cx - pose.rx * 1.2
  const x1 = pose.cx + pose.rx * 1.2
  const y0 = pose.cy - pose.ry * 1.18
  const y1 = pose.cy + pose.ry * 1.16
  const l = Math.min(x1 - x0, y1 - y0) * 0.2
  return (
    <g>
      <path
        d={`M${x0} ${y0 + l} V${y0} H${x0 + l} M${x1 - l} ${y0} H${x1} V${y0 + l} M${x0} ${y1 - l} V${y1} H${x0 + l} M${x1 - l} ${y1} H${x1} V${y1 - l}`}
        fill="none"
        stroke="currentColor"
        strokeWidth={2.6 * k}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter={`url(#${glowId})`}
      />
      <text
        x={x0}
        y={y0 - 7 * k}
        fill="currentColor"
        fontSize={11 * k}
        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
        letterSpacing={1.5 * k}
      >
        {locked ? 'VERROUILLÉ' : 'ANALYSE'}
      </text>
      {/* Repères de l'IA : yeux, nez, coins de la bouche */}
      <g fill="none" stroke="white" strokeWidth={1.2 * k}>
        {pose.points.map(([x, y], i) => (
          <g key={i}>
            <rect x={x - 4 * k} y={y - 4 * k} width={8 * k} height={8 * k} />
            <path d={`M${x - 7 * k} ${y} h${3 * k} M${x + 4 * k} ${y} h${3 * k} M${x} ${y - 7 * k} v${3 * k} M${x} ${y + 4 * k} v${3 * k}`} opacity={0.7} />
          </g>
        ))}
      </g>
    </g>
  )
}

import { useEffect, useId, useRef, useState } from 'react'
import { grabFrame, openCamera, sleep, stopCamera } from './camera'
import { FaceMesh } from './FaceMesh'
import { judge, ovalFor, SIDE, type Pose, type Verdict } from './faceGuide'
import type { FaceProbe } from './session'

export interface ScanStep {
  pose: Pose
  title: string
}

/** Après la capture : vérification en cours côté serveur, puis acceptée ou refusée. */
export type ScanOutcome = 'checking' | 'accepted' | 'refused'

const PROBE_EVERY = 160 // ms entre deux images de guidage, au plus
const TICKS = 72 // graduations autour de l'ovale
const SCAN = 'var(--color-scan)'
const OK = 'var(--color-scan-ok)'
const WARN = 'var(--color-scan-warn)'

type Phase = 'opening' | 'tracking' | 'done'

/**
 * Scan guidé du visage, à la manière des applications d'identité : la caméra suit le visage en
 * direct (l'IA du serveur le localise plusieurs fois par seconde) et ne garde une image que
 * lorsque la tête est bien placée dans l'ovale, à l'angle demandé. La caméra s'éteint dès que
 * toutes les prises sont faites ; `onComplete` reçoit alors les images gardées, étape par étape.
 */
export function FaceScanner({
  steps,
  shots,
  probe,
  onComplete,
  onError,
  onProgress,
  doneLabel,
  outcome = 'checking',
}: {
  steps: ScanStep[]
  /** Images à garder par étape. */
  shots: number
  probe: (frame: Blob) => Promise<FaceProbe>
  onComplete: (shots: Record<Pose, Blob[]>) => void
  onError: (error: unknown) => void
  /** Étape en cours et nombre d'étapes réussies, pour un suivi hors du scanner. */
  onProgress?: (step: number, passed: number) => void
  /** Ce qu'affiche le scanner une fois la capture faite (« Vérification… », « Visage enregistré »). */
  doneLabel: string
  outcome?: ScanOutcome
}) {
  const ids = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const video = useRef<HTMLVideoElement>(null)
  const handlers = useRef({ probe, onComplete, onError, onProgress })
  useEffect(() => {
    handlers.current = { probe, onComplete, onError, onProgress }
  })

  const [size, setSize] = useState({ w: 640, h: 480 })
  const [phase, setPhase] = useState<Phase>('opening')
  const [stepIndex, setStepIndex] = useState(0)
  const [kept, setKept] = useState(0) // images gardées pour l'étape en cours
  const [seen, setSeen] = useState<FaceProbe | null>(null)
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [passed, setPassed] = useState(-1) // dernière étape réussie
  const [still, setStill] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    let stream: MediaStream | null = null
    let stillUrl: string | null = null
    const canvas = document.createElement('canvas')
    void (async () => {
      try {
        const el = video.current
        if (!el) return
        stream = await openCamera(el, () => cancelled)
        if (!stream || cancelled) return
        const width = el.videoWidth || 640
        const height = el.videoHeight || 480
        setSize({ w: width, h: height })
        setPhase('tracking')

        const result = { face: [], gauche: [], droite: [] } as Record<Pose, Blob[]>
        let last: Blob | null = null
        for (let i = 0; i < steps.length; i++) {
          const keep = result[steps[i].pose]
          setStepIndex(i)
          setKept(0)
          setVerdict(null)
          handlers.current.onProgress?.(i, i)
          let streak = 0
          while (keep.length < shots) {
            const started = performance.now()
            const frame = await grabFrame(el, canvas)
            const now = await handlers.current.probe(frame)
            if (cancelled) return
            const v = judge(now, steps[i].pose, width, height)
            setSeen(now)
            setVerdict(v)
            // La première image correcte peut être prise en plein mouvement : on garde à partir de la deuxième d'affilée.
            streak = v.ok ? streak + 1 : 0
            if (streak >= 2) {
              keep.push(frame)
              last = frame
              setKept(keep.length)
            }
            await sleep(Math.max(0, PROBE_EVERY - (performance.now() - started)))
            if (cancelled) return
          }
          setPassed(i)
          handlers.current.onProgress?.(i, i + 1)
          if (i < steps.length - 1) {
            await sleep(800) // le temps de voir l'étape validée
            if (cancelled) return
          }
        }

        if (last) {
          stillUrl = URL.createObjectURL(last)
          setStill(stillUrl)
        }
        stopCamera(stream, el)
        stream = null
        setPhase('done')
        handlers.current.onComplete(result)
      } catch (err) {
        if (!cancelled) handlers.current.onError(err)
      } finally {
        stopCamera(stream, video.current)
      }
    })()
    return () => {
      cancelled = true
      stopCamera(stream, video.current)
      if (stillUrl) URL.revokeObjectURL(stillUrl)
    }
    // Un scanner par montage : pour recommencer, le parent le remonte (prop `key`).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { w, h } = size
  const k = h / 480 // échelle des traits, pour une image de 480 px de haut
  const oval = ovalFor(w, h)
  const step = steps[Math.min(stepIndex, steps.length - 1)]
  const tracking = phase === 'tracking'
  const done = phase === 'done'
  const justPassed = tracking && passed === stepIndex
  const locked = justPassed || (tracking && !!verdict?.ok)
  const progress = done ? 1 : (stepIndex * shots + kept) / (steps.length * shots)
  const crowd = !!seen && seen.faces > 1
  const ring = done ? (outcome === 'refused' ? WARN : outcome === 'accepted' ? OK : SCAN) : crowd ? WARN : locked ? OK : SCAN
  const turnTo = tracking && !justPassed && step.pose !== 'face' ? SIDE[step.pose] : 0 // 1 : vers la gauche de l'écran

  const message =
    phase === 'opening'
      ? 'Activation de la caméra…'
      : done
        ? doneLabel
        : justPassed
          ? `${step.title} : c’est bon`
          : (verdict?.hint ?? 'Placez votre visage dans l’ovale')

  // Voile flouté hors de l'ovale : même ellipse que le tracé, en pourcentage de l'image.
  const hole = `radial-gradient(ellipse ${(oval.rx / w) * 100}% ${(oval.ry / h) * 100}% at 50% ${(oval.cy / h) * 100}%, transparent 99%, #000 100%)`

  const ticks = Array.from({ length: TICKS }, (_, i) => {
    const t = -Math.PI / 2 + (i / TICKS) * 2 * Math.PI // départ en haut, sens des aiguilles d'une montre
    const cos = Math.cos(t)
    const sin = Math.sin(t)
    const nx = cos / oval.rx
    const ny = sin / oval.ry
    const n = Math.hypot(nx, ny)
    const x = oval.cx + oval.rx * cos
    const y = oval.cy + oval.ry * sin
    // Écran en miroir : la gauche de la personne est à gauche de l'écran (cos < 0).
    const toward = turnTo !== 0 && cos * -turnTo > 0.35
    const lit = i < Math.round(progress * TICKS)
    const len = lit ? 19 : toward ? 22 : 13
    return { x1: x + (nx / n) * 8 * k, y1: y + (ny / n) * 8 * k, x2: x + (nx / n) * len * k, y2: y + (ny / n) * len * k, lit, toward }
  })

  return (
    <div
      className="relative w-full overflow-hidden rounded-2xl bg-[#05070d] text-white shadow-float ring-1 ring-white/10"
      style={{ aspectRatio: `${w} / ${h}` }}
    >
      <video ref={video} muted playsInline className="absolute inset-0 size-full -scale-x-100 object-cover" />
      {done && still ? <img src={still} alt="" className="fade absolute inset-0 size-full -scale-x-100 object-cover" /> : null}

      {/* Hors de l'ovale : image floutée et assombrie */}
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[#05070d]/35"
        style={{
          backdropFilter: 'blur(14px) saturate(0.6) brightness(0.55)',
          WebkitBackdropFilter: 'blur(14px) saturate(0.6) brightness(0.55)',
          maskImage: hole,
          WebkitMaskImage: hole,
        }}
      />

      <svg aria-hidden="true" className="absolute inset-0 size-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid slice">
        <defs>
          <clipPath id={`${ids}-oval`}>
            <ellipse cx={oval.cx} cy={oval.cy} rx={oval.rx} ry={oval.ry} />
          </clipPath>
          <linearGradient id={`${ids}-oval-sweep`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={locked ? OK : SCAN} stopOpacity="0" />
            <stop offset="1" stopColor={locked ? OK : SCAN} stopOpacity="0.35" />
          </linearGradient>
          <filter id={`${ids}-glow`} x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation={2.2 * k} result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Repères de visée aux coins de l'image */}
        <g fill="none" stroke="rgb(255 255 255 / 0.35)" strokeWidth={1.5 * k} strokeLinecap="round">
          {[
            [18, 18, 1, 1],
            [w - 18, 18, -1, 1],
            [18, h - 18, 1, -1],
            [w - 18, h - 18, -1, -1],
          ].map(([x, y, sx, sy]) => (
            <path key={`${x}-${y}`} d={`M${x} ${y + sy * 22 * k} V${y} H${x + sx * 22 * k}`} />
          ))}
        </g>

        <FaceMesh
          seen={tracking ? seen : null}
          width={w}
          height={h}
          oval={oval}
          tone={crowd ? WARN : locked ? OK : SCAN}
          locked={locked}
          active={tracking}
          clipId={`${ids}-oval`}
          glowId={`${ids}-glow`}
        />

        {/* Ovale et graduations : elles s'allument à mesure que les prises sont gardées */}
        <ellipse
          cx={oval.cx}
          cy={oval.cy}
          rx={oval.rx}
          ry={oval.ry}
          fill="none"
          stroke={ring}
          strokeOpacity={tracking && !locked ? 0.55 : 1}
          strokeWidth={1.6 * k}
          style={{ transition: 'stroke 240ms' }}
        />
        <g filter={`url(#${ids}-glow)`} strokeLinecap="round">
          {ticks.map((t, i) => (
            <line
              key={i}
              x1={t.x1}
              y1={t.y1}
              x2={t.x2}
              y2={t.y2}
              strokeWidth={(t.lit ? 3.2 : 2.4) * k}
              stroke={t.lit ? (done && outcome === 'refused' ? WARN : OK) : t.toward ? SCAN : 'rgb(255 255 255 / 0.22)'}
              className={!t.lit && t.toward ? 'scan-pulse' : undefined}
              style={{ transition: 'stroke 240ms' }}
            />
          ))}
        </g>

        {/* Onde à chaque étape validée */}
        {justPassed || (done && outcome !== 'checking') ? (
          <ellipse
            key={done ? `done-${outcome}` : `step-${passed}`}
            cx={oval.cx}
            cy={oval.cy}
            rx={oval.rx}
            ry={oval.ry}
            fill="none"
            stroke={ring}
            strokeWidth={3 * k}
            className="scan-ripple"
          />
        ) : null}

        {/* Flèches vers le côté où tourner la tête */}
        {turnTo !== 0 ? (
          <g transform={`translate(${oval.cx - turnTo * (oval.rx + 48 * k)} ${oval.cy})`} filter={`url(#${ids}-glow)`}>
            {[0, 1, 2].map((i) => (
              <path
                key={i}
                d={`M${turnTo * (5 - i * 13) * k} ${-11 * k} L${turnTo * (-6 - i * 13) * k} 0 L${turnTo * (5 - i * 13) * k} ${11 * k}`}
                fill="none"
                stroke={SCAN}
                strokeWidth={3.5 * k}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="scan-chevron"
                style={{ animationDelay: `${i * 0.18}s` }}
              />
            ))}
          </g>
        ) : null}
      </svg>

      {/* Marque centrale : étape validée, vérification, puis verdict */}
      {justPassed || done ? (
        <div key={done ? `done-${outcome}` : passed} className="pointer-events-none absolute inset-0 grid place-items-center">
          <svg width="68" height="68" viewBox="0 0 56 56" fill="none" aria-hidden="true" className="drop-shadow-[0_0_14px_rgb(0_0_0/0.5)]">
            <circle cx="28" cy="28" r="26" fill="rgb(5 7 13 / 0.6)" />
            {done && outcome === 'checking' ? (
              <circle cx="28" cy="28" r="26" stroke={SCAN} strokeWidth="2.5" strokeDasharray="40 124" strokeLinecap="round" className="spin origin-center" />
            ) : (
              <>
                <circle className="draw-circle" cx="28" cy="28" r="26" stroke={ring} strokeWidth="2.5" />
                <path
                  className="draw-check"
                  d={done && outcome === 'refused' ? 'M19 19l18 18M37 19L19 37' : 'M17 28.5l7.5 7.5L39.5 20'}
                  stroke={ring}
                  strokeWidth="3"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </>
            )}
          </svg>
        </div>
      ) : null}

      {/* Bandeau du haut */}
      <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between gap-3 px-4 pt-3.5 font-mono text-[10px] uppercase tracking-[0.18em] text-white/80">
        <span className="flex items-center gap-2">
          <span className={`size-1.5 rounded-full ${tracking ? 'animate-pulse bg-scan-warn' : done ? 'bg-scan-ok' : 'bg-white/40'}`} />
          {done ? 'Capture terminée' : 'Analyse biométrique'}
        </span>
        {steps.length > 1 ? (
          <StepTrack count={steps.length} current={stepIndex} passed={done ? steps.length : passed + 1} kept={kept / shots} />
        ) : (
          <span className="text-white/55">IA locale</span>
        )}
      </div>

      {/* Consigne */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col items-center gap-2 px-3 pb-3.5">
        <div className="flex max-w-full items-center gap-2.5 rounded-full border border-white/15 bg-[#05070d]/60 py-1.5 pl-1.5 pr-4 shadow-lg backdrop-blur-md">
          <HeadIcon pose={step.pose} moving={turnTo !== 0} state={done ? outcome : locked ? 'locked' : 'idle'} />
          <div className="min-w-0 text-left">
            <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/55">{done ? 'Résultat' : step.title}</p>
            <p role="status" className="truncate text-sm font-semibold leading-tight">
              {message}
            </p>
          </div>
        </div>
        <YawGauge seen={tracking && seen && seen.faces > 0 ? seen : null} pose={step.pose} />
      </div>
    </div>
  )
}

/** Une barre par étape : pleine si réussie, remplie au fil des prises pour l'étape en cours. */
function StepTrack({ count, current, passed, kept }: { count: number; current: number; passed: number; kept: number }) {
  return (
    <span className="flex items-center gap-2">
      <span className="text-white/55">
        {Math.min(current + 1, count)}/{count}
      </span>
      <span className="flex gap-1">
        {Array.from({ length: count }, (_, i) => (
          <span key={i} className="relative h-1 w-6 overflow-hidden rounded-full bg-white/20">
            <span
              className={`absolute inset-y-0 left-0 rounded-full transition-[width] duration-200 ${i < passed ? 'bg-scan-ok' : 'bg-scan'}`}
              style={{ width: `${i < passed ? 100 : i === current ? kept * 100 : 0}%` }}
            />
          </span>
        ))}
      </span>
    </span>
  )
}

/** Petite tête qui montre le geste attendu : de face, ou qui tourne vers la gauche ou la droite de l'écran. */
export function HeadIcon({
  pose,
  moving = false,
  state = 'idle',
  className = 'size-9',
}: {
  pose: Pose
  moving?: boolean
  state?: 'idle' | 'locked' | ScanOutcome
  className?: string
}) {
  const shift = pose === 'face' ? 0 : SIDE[pose] * -3.5 // écran en miroir : gauche de la personne = gauche de l'écran
  const color = state === 'refused' ? WARN : state === 'locked' || state === 'accepted' ? OK : SCAN
  return (
    <span className={`grid shrink-0 place-items-center rounded-full bg-white/10 ${className}`} aria-hidden="true">
      <svg viewBox="0 0 28 28" className="size-[70%]" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round">
        <ellipse cx="14" cy="14" rx="8.5" ry="10.5" />
        <g
          className={moving ? 'head-turn' : undefined}
          style={{ transform: moving ? undefined : `translateX(${shift}px)`, ['--turn' as string]: `${shift}px` }}
        >
          <path d="M10.5 11.5h.01M17.5 11.5h.01" strokeWidth="2.4" />
          <path d="M14 13v3.2l-1.3.6" />
          <path d="M11.5 19.2c1.5.9 3.5.9 5 0" />
        </g>
      </svg>
    </span>
  )
}

/**
 * Où en est la rotation de la tête, et où il faut l'amener. L'écran est en miroir : tourner la
 * tête vers sa gauche déplace le repère vers la gauche.
 */
function YawGauge({ seen, pose }: { seen: FaceProbe | null; pose: Pose }) {
  const range = 0.45
  const at = (yaw: number) => 50 - Math.max(-1, Math.min(1, yaw / range)) * 46
  const front = seen?.frontMaxYaw ?? 0.12
  const side = seen?.sideMinYaw ?? 0.18
  const [from, to] =
    pose === 'face' ? [at(front), at(-front)] : pose === 'gauche' ? [at(range), at(side)] : [at(-side), at(-range)]
  return (
    <div className={`relative h-1 w-48 rounded-full bg-white/15 transition-opacity ${seen ? 'opacity-100' : 'opacity-0'}`}>
      <div className="absolute inset-y-0 rounded-full bg-scan-ok/70 shadow-[0_0_8px_var(--color-scan-ok)]" style={{ left: `${from}%`, width: `${to - from}%` }} />
      <div className="absolute left-1/2 top-1/2 h-2.5 w-px -translate-y-1/2 bg-white/45" />
      <div
        className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-scan shadow-[0_0_10px_var(--color-scan)] transition-[left] duration-150 ease-linear"
        style={{ left: `${at(seen?.yaw ?? 0)}%` }}
      />
    </div>
  )
}

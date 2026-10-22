import type { FaceProbe } from './session'

/** Les angles du scan : de face, puis la tête tournée vers la gauche et vers la droite. */
export type Pose = 'face' | 'gauche' | 'droite'

/** L'ovale où placer le visage, en pixels de l'image : centré, un peu haut, en portrait. */
export function ovalFor(width: number, height: number) {
  const ry = height * 0.34
  return { cx: width / 2, cy: height * 0.45, rx: ry * 0.78, ry }
}

/**
 * Sens de l'orientation mesurée par le serveur (décalage du nez par rapport au milieu des yeux,
 * dans l'image brute). L'image brute n'est pas en miroir : quand la personne tourne la tête vers
 * SA gauche, son nez part vers la droite de l'image, et l'orientation devient positive.
 */
export const SIDE: Record<Exclude<Pose, 'face'>, 1 | -1> = { gauche: 1, droite: -1 }

export interface Verdict {
  ok: boolean
  hint: string
}

/** La tête est-elle bien placée pour cette prise ? Sinon, ce qu'il faut corriger. */
export function judge(seen: FaceProbe, pose: Pose, width: number, height: number): Verdict {
  if (seen.faces === 0 || !seen.box) return { ok: false, hint: 'Placez votre visage dans l’ovale' }
  if (seen.faces > 1) return { ok: false, hint: 'Une seule personne devant la caméra' }

  const oval = ovalFor(width, height)
  const [x, y, w, h] = seen.box
  const dx = ((x + w / 2) * width - oval.cx) / oval.rx
  const dy = ((y + h / 2) * height - oval.cy) / oval.ry
  const size = (h * height) / (2 * oval.ry) // hauteur du visage rapportée à celle de l'ovale
  if (size < 0.4) return { ok: false, hint: 'Approchez-vous un peu' }
  if (size > 1.05) return { ok: false, hint: 'Reculez un peu' }
  // De côté, la boîte du visage se décale avec la rotation : un peu plus de marge.
  if (Math.abs(dx) > (pose === 'face' ? 0.35 : 0.55) || Math.abs(dy) > 0.3) {
    return { ok: false, hint: 'Centrez votre visage dans l’ovale' }
  }

  const yaw = seen.yaw ?? 0
  if (pose === 'face') {
    return Math.abs(yaw) <= seen.frontMaxYaw
      ? { ok: true, hint: 'Ne bougez plus…' }
      : { ok: false, hint: 'Regardez droit la caméra' }
  }
  const turned = yaw * SIDE[pose]
  const side = pose === 'gauche' ? 'la gauche' : 'la droite'
  if (turned >= seen.sideMinYaw) return { ok: true, hint: 'Ne bougez plus…' }
  if (turned <= -seen.sideMinYaw / 2) return { ok: false, hint: `Pas de ce côté : vers ${side}` }
  if (turned >= seen.sideMinYaw / 2) return { ok: false, hint: 'Encore un peu…' }
  return { ok: false, hint: `Tournez lentement la tête vers ${side}` }
}

/**
 * Caméra du poste (la webcam USB du PC hôte) : allumée juste le temps de prendre quelques
 * images, puis éteinte. Le navigateur n'y donne accès qu'en HTTPS, ou depuis localhost.
 */

/**
 * Ouvre la caméra et l'affiche dans `video`. Si `isCancelled()` devient vrai pendant l'ouverture
 * (composant démonté, ou monté deux fois par React en développement), le flux est fermé sans
 * jamais toucher à la vidéo : il ne peut pas effacer l'image d'une ouverture plus récente.
 */
export async function openCamera(video: HTMLVideoElement, isCancelled: () => boolean = () => false): Promise<MediaStream | null> {
  const stream = await requestCamera()
  if (isCancelled()) {
    stream.getTracks().forEach((t) => t.stop())
    return null
  }
  video.srcObject = stream
  await video.play().catch(() => undefined)
  await waitForPicture(video)
  return stream
}

async function requestCamera(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Caméra inaccessible : ouvrez le back-office en HTTPS, ou depuis le poste lui-même.')
  }
  let stream: MediaStream
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
      audio: false,
    })
  } catch (err) {
    throw new Error(cameraProblem(err))
  }
  return stream
}

/** Ce qui empêche d'ouvrir la caméra, dit pour que l'utilisateur sache où agir. */
function cameraProblem(err: unknown): string {
  const name = err instanceof DOMException ? err.name : ''
  const detail = err instanceof Error ? err.message : ''
  if (name === 'NotAllowedError' && /system/i.test(detail)) {
    return 'Le système bloque la caméra : Paramètres Windows › Confidentialité et sécurité › Caméra, autorisez les applications de bureau, puis réessayez.'
  }
  if (name === 'NotAllowedError') {
    return 'Le navigateur refuse la caméra : icône à gauche de l’adresse › Caméra › Autoriser, puis réessayez. (Le navigateur intégré à certaines applications n’y a pas accès : utilisez Chrome ou Edge.)'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'Aucune caméra détectée sur ce poste : branchez la caméra USB.'
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return 'Caméra déjà utilisée par une autre application (Teams, Zoom, appareil photo…) : fermez-la, puis réessayez.'
  }
  if (name === 'SecurityError') {
    return 'Caméra interdite sur cette adresse : ouvrez le back-office en HTTPS, ou depuis le poste lui-même.'
  }
  return `Caméra inaccessible${detail ? ` (${detail})` : ''}.`
}

/** Éteint la caméra. La vidéo n'est vidée que si elle affiche ce flux-là, pas un plus récent. */
export function stopCamera(stream: MediaStream | null, video?: HTMLVideoElement | null): void {
  stream?.getTracks().forEach((t) => t.stop())
  if (video && stream && video.srcObject === stream) video.srcObject = null
}

function waitForPicture(video: HTMLVideoElement, ms = 4000): Promise<void> {
  if (video.videoWidth > 0) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer)
      video.removeEventListener('loadeddata', done)
      resolve()
    }
    const timer = setTimeout(done, ms)
    video.addEventListener('loadeddata', done)
  })
}

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** L'image affichée par la vidéo, en JPEG de 640 px au plus. */
export async function grabFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement): Promise<Blob> {
  const width = video.videoWidth || 640
  const height = video.videoHeight || 480
  const scale = Math.min(1, 640 / Math.max(width, height))
  canvas.width = Math.round(width * scale)
  canvas.height = Math.round(height * scale)
  canvas.getContext('2d')?.drawImage(video, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', 0.85))
  if (!blob) throw new Error('Image de la caméra illisible.')
  return blob
}

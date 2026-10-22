import { useSyncExternalStore } from 'react'

export type Role = 'client' | 'operator'

export interface SessionUser {
  username: string
  role: Role
  firstName?: string
  lastName?: string
}

/**
 * Le jeton n'est jamais ici : il vit dans un cookie httpOnly posé par /auth/login, que le
 * navigateur joint lui-même à chaque appel (même origine, derrière le relais nginx).
 * Le JavaScript ne connaît que l'utilisateur et l'heure d'expiration, pour l'affichage.
 */
export interface Session {
  /** En secondes depuis l'époque, comme `exp` dans le jeton. */
  expiresAt: number
  user: SessionUser
}

interface AuthState {
  session: Session | null
  /** Vrai le temps de demander au serveur si le cookie ouvre encore une session. */
  checking: boolean
  /** Pourquoi la dernière session s'est terminée, affiché sur la page de connexion. */
  notice?: string
}

// Vide par défaut : mêmes origine et chemins que l'application, via le relais nginx.
const AUTH_URL = import.meta.env.VITE_AUTH_URL ?? ''

let state: AuthState = { session: null, checking: true }
let expiry: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<() => void>()

function set(next: AuthState): void {
  state = next
  clearTimeout(expiry)
  if (next.session) {
    expiry = setTimeout(() => endSession('Session expirée, reconnectez-vous.'), next.session.expiresAt * 1000 - Date.now())
  }
  listeners.forEach((l) => l())
}

// Au chargement : le cookie ouvre-t-il encore une session ? Un rechargement de page ne déconnecte pas.
void (async () => {
  try {
    const res = await fetch(`${AUTH_URL}/auth/me`, { signal: AbortSignal.timeout(5000) })
    if (res.ok) {
      // /auth/me renvoie l'utilisateur complet (prénom compris, affiché dans le header) et l'expiration.
      const { expiresAt, ...user } = (await res.json()) as SessionUser & { expiresAt: number }
      set({ session: { expiresAt, user }, checking: false })
      return
    }
  } catch {
    // Service injoignable : on affiche la connexion, qui dira pourquoi elle échoue.
  }
  set({ session: null, checking: false })
})()

export function useAuth(): AuthState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l)
      return () => listeners.delete(l)
    },
    () => state,
  )
}

/**
 * Erreur du service d'authentification. `restart` : il faut recommencer l'identification
 * (identifiant vidé, caméra éteinte) ; `retryAfter` : secondes avant un nouvel essai.
 */
export class AuthError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly restart = false,
    readonly retryAfter = 0,
    readonly lock = '',
  ) {
    super(message)
  }
}

function authError(res: Response, body: { detail?: unknown }, fallback: string): AuthError {
  return new AuthError(
    typeof body.detail === 'string' ? body.detail : `${fallback} (${res.status}).`,
    res.status,
    res.headers.get('X-Auth-Restart') === 'identify',
    Number(res.headers.get('Retry-After') ?? 0) || 0,
    res.headers.get('X-Auth-Lock') ?? '',
  )
}

async function authFetch(path: string, init: RequestInit, timeout = 5000): Promise<Response> {
  try {
    return await fetch(`${AUTH_URL}${path}`, { ...init, signal: AbortSignal.timeout(timeout) })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
}

export type IdentifyResult =
  | { step: 'password' }
  | { step: 'face'; challenge: string; frames: number; captureSeconds: number }

/** Première étape : un compte du back-office passe d'abord la caméra, les autres vont au mot de passe. */
export async function identify(username: string): Promise<IdentifyResult> {
  const res = await authFetch('/auth/identify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  })
  const body = (await res.json().catch(() => ({}))) as IdentifyResult & { detail?: unknown }
  if (!res.ok) throw authError(res, body, 'Identification impossible')
  return body
}

export type FaceResult =
  | { status: 'recognized'; passwordSeconds: number }
  | { status: 'rejected' | 'locked'; retryAfter: number; reason: string }

/** Les images de la caméra ; le serveur les compare au visage enregistré pour ce compte, sans les garder. */
export async function sendFaceFrames(challenge: string, frames: Blob[]): Promise<FaceResult> {
  const form = new FormData()
  frames.forEach((f, i) => form.append('frames', f, `image-${i}.jpg`))
  const res = await authFetch(`/auth/identify/${encodeURIComponent(challenge)}/frames`, { method: 'POST', body: form }, 20000)
  const body = (await res.json().catch(() => ({}))) as FaceResult & { detail?: unknown }
  if (!res.ok) throw authError(res, body, 'Vérification du visage impossible')
  return body
}

/** Où l'IA du serveur voit le visage dans une image (de 0 à 1), et les angles qu'elle attend. */
export interface FaceProbe {
  faces: number
  box?: [number, number, number, number]
  points?: [number, number][]
  yaw?: number
  frontMaxYaw: number
  sideMinYaw: number
}

/** Guidage pendant la capture : rien n'est jugé, l'image sert seulement à placer le visage. */
export async function probeFace(challenge: string, frame: Blob): Promise<FaceProbe> {
  const form = new FormData()
  form.append('frame', frame, 'guidage.jpg')
  const res = await authFetch(`/auth/identify/${encodeURIComponent(challenge)}/probe`, { method: 'POST', body: form }, 8000)
  const body = (await res.json().catch(() => ({}))) as FaceProbe & { detail?: unknown }
  if (!res.ok) throw authError(res, body, 'Caméra : guidage impossible')
  return body
}

export async function login(username: string, password: string, challenge?: string): Promise<void> {
  const res = await authFetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, ...(challenge ? { challenge } : {}) }),
  })
  const body = (await res.json().catch(() => ({}))) as Partial<Session> & { detail?: unknown }
  if (!res.ok || !body.user || !body.expiresAt) throw authError(res, body, 'Connexion impossible')
  set({ session: { expiresAt: body.expiresAt, user: body.user }, checking: false })
}

async function sessionCall(path: string, payload: unknown, fallback: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${AUTH_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
  // Comme à la connexion, le jeton arrive dans un cookie httpOnly : la réponse ne porte que l'utilisateur.
  const body = (await res.json().catch(() => ({}))) as Partial<Session> & { detail?: unknown }
  if (!res.ok || !body.user || !body.expiresAt) {
    throw new Error(typeof body.detail === 'string' ? body.detail : `${fallback} (${res.status}).`)
  }
  set({ session: { expiresAt: body.expiresAt, user: body.user }, checking: false })
}

export async function register(email: string, firstName: string, lastName: string, password: string): Promise<void> {
  await sessionCall('/auth/register', { email, firstName, lastName, password }, 'Création impossible')
}

/** Demande l'e-mail de réinitialisation. La réponse est volontairement la même, compte ou pas. */
export async function forgotPassword(email: string): Promise<string> {
  let res: Response
  try {
    res = await fetch(`${AUTH_URL}/auth/forgot`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
  const body = (await res.json().catch(() => ({}))) as { detail?: unknown }
  if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Demande impossible (${res.status}).`)
  return typeof body.detail === 'string' ? body.detail : 'Si un compte existe avec cette adresse, un e-mail vient de partir.'
}

export async function resetPassword(token: string, password: string): Promise<void> {
  await sessionCall('/auth/reset', { token, password }, 'Réinitialisation impossible')
}

export async function logout(): Promise<void> {
  // Le cookie est httpOnly : seul le serveur peut l'effacer.
  await fetch(`${AUTH_URL}/auth/logout`, { method: 'POST' }).catch(() => undefined)
  set({ session: null, checking: false })
}

export function endSession(notice: string): void {
  if (state.session) set({ session: null, checking: false, notice })
}

/** À appeler sur chaque réponse en erreur de l'API : un 401 veut dire que la session ne vaut plus rien. */
export function checkSession(res: Response): void {
  if (res.status === 401) endSession('Session expirée ou révoquée, reconnectez-vous.')
}

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

export async function login(username: string, password: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${AUTH_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Session> & { detail?: unknown }
  if (!res.ok || !body.user || !body.expiresAt) {
    throw new Error(typeof body.detail === 'string' ? body.detail : `Connexion impossible (${res.status}).`)
  }
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

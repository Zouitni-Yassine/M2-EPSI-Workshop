import { useSyncExternalStore } from 'react'

export type Role = 'client' | 'operator'

export interface SessionUser {
  username: string
  role: Role
}

export interface Session {
  token: string
  /** En secondes depuis l'époque, comme `exp` dans le jeton. */
  expiresAt: number
  user: SessionUser
}

interface AuthState {
  session: Session | null
  /** Pourquoi la dernière session s'est terminée, affiché sur la page de connexion. */
  notice?: string
}

const KEY = 'resilience.session'
const AUTH_URL = import.meta.env.VITE_AUTH_URL ?? 'http://localhost:8300'

// sessionStorage plutôt que localStorage : la session meurt avec l'onglet.
function restore(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const session = JSON.parse(raw) as Session
    return session.expiresAt * 1000 > Date.now() ? session : null
  } catch {
    return null
  }
}

function persist(session: Session | null): void {
  try {
    if (session) sessionStorage.setItem(KEY, JSON.stringify(session))
    else sessionStorage.removeItem(KEY)
  } catch {
    // Stockage indisponible (navigation privée stricte) : la session vit le temps de la page.
  }
}

let state: AuthState = { session: restore() }
let expiry: ReturnType<typeof setTimeout> | undefined
const listeners = new Set<() => void>()

function set(next: AuthState): void {
  state = next
  persist(next.session)
  clearTimeout(expiry)
  if (next.session) {
    expiry = setTimeout(() => endSession('Session expirée, reconnectez-vous.'), next.session.expiresAt * 1000 - Date.now())
  }
  listeners.forEach((l) => l())
}

if (state.session) set(state)

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
  if (!res.ok || !body.token || !body.user || !body.expiresAt) {
    throw new Error(typeof body.detail === 'string' ? body.detail : `Connexion impossible (${res.status}).`)
  }
  set({ session: { token: body.token, expiresAt: body.expiresAt, user: body.user } })
}

export async function register(username: string, password: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${AUTH_URL}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
      signal: AbortSignal.timeout(5000),
    })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
  const body = (await res.json().catch(() => ({}))) as Partial<Session> & { detail?: unknown }
  if (!res.ok || !body.token || !body.user || !body.expiresAt) {
    throw new Error(typeof body.detail === 'string' ? body.detail : `Création impossible (${res.status}).`)
  }
  set({ session: { token: body.token, expiresAt: body.expiresAt, user: body.user } })
}

export function logout(): void {
  set({ session: null })
}

export function endSession(notice: string): void {
  if (state.session) set({ session: null, notice })
}

export function authHeaders(): Record<string, string> {
  return state.session ? { Authorization: `Bearer ${state.session.token}` } : {}
}

/** À appeler sur chaque réponse en erreur de l'API : un 401 veut dire que la session ne vaut plus rien. */
export function checkSession(res: Response): void {
  if (res.status === 401) endSession('Session expirée ou révoquée, reconnectez-vous.')
}

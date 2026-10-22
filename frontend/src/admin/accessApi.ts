import { checkSession, type FaceProbe, type Role } from '../auth/session'

// Mêmes origine et chemins que l'application, via le relais nginx ; la session part dans le cookie.
const AUTH_URL = import.meta.env.VITE_AUTH_URL ?? ''

export interface Account {
  username: string
  role: Role
  disabled: boolean
  firstName: string
  lastName: string
  createdAt: string | null
  /** Nombre de gabarits de visage enregistrés. */
  faces: number
  /** Dispensé de visage depuis le réseau interne (la sonde de transaction). */
  serviceAccount: boolean
  serviceFromConfig: boolean
  faceRequired: boolean
  self: boolean
}

export interface AccessEvent {
  at: string | null
  kind: string
  username: string | null
  actor: string | null
  ip: string | null
  detail: string
}

async function call<T>(path: string, init: RequestInit = {}, timeout = 8000): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${AUTH_URL}${path}`, { ...init, signal: AbortSignal.timeout(timeout) })
  } catch {
    throw new Error('Service d’authentification injoignable. Réessayez dans un instant.')
  }
  checkSession(res)
  const body = (await res.json().catch(() => ({}))) as T & { detail?: unknown }
  if (!res.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Action impossible (${res.status}).`)
  return body
}

function post<T>(path: string, payload?: unknown): Promise<T> {
  return call<T>(path, {
    method: 'POST',
    headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
}

const at = (username: string) => `/auth/admin/accounts/${encodeURIComponent(username)}`

export async function listAccounts(): Promise<Account[]> {
  return (await call<{ accounts: Account[] }>('/auth/admin/accounts')).accounts
}

export async function listEvents(limit = 40): Promise<AccessEvent[]> {
  return (await call<{ events: AccessEvent[] }>(`/auth/admin/events?limit=${limit}`)).events
}

export function createAccount(account: { username: string; password: string; role: Role; firstName: string; lastName: string }) {
  return post<{ username: string }>('/auth/admin/accounts', account)
}

export function updateAccount(username: string, change: { role?: Role; disabled?: boolean; serviceAccount?: boolean }) {
  return post<{ ok: boolean }>(at(username), change)
}

export function setAccountPassword(username: string, password: string) {
  return post<{ ok: boolean }>(`${at(username)}/password`, { password })
}

export function enrollFace(username: string, frames: Blob[]) {
  const form = new FormData()
  frames.forEach((f, i) => form.append('frames', f, `image-${i}.jpg`))
  return call<{ faces: number }>(`${at(username)}/face`, { method: 'POST', body: form }, 20000)
}

export type ScanPose = 'face' | 'gauche' | 'droite'

/** Guidage du scan, image par image : position et orientation de la tête, rien n'est enregistré. */
export function probeScan(frame: Blob) {
  const form = new FormData()
  form.append('frame', frame, 'guidage.jpg')
  return call<FaceProbe>('/auth/admin/face/probe', { method: 'POST', body: form })
}

/** Scan sous trois angles : le serveur vérifie chaque angle et remplace les gabarits du compte. */
export function scanFace(username: string, shots: Record<ScanPose, Blob[]>) {
  const form = new FormData()
  for (const pose of ['face', 'gauche', 'droite'] as const) {
    shots[pose].forEach((f, i) => form.append(pose, f, `${pose}-${i}.jpg`))
  }
  return call<{ faces: number; angles: Record<ScanPose, number> }>(`${at(username)}/face/scan`, { method: 'POST', body: form }, 30000)
}

export function deleteFace(username: string) {
  return post<{ deleted: number }>(`${at(username)}/face/delete`)
}

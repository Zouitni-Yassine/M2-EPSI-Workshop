import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { FaceScanner, HeadIcon, type ScanOutcome, type ScanStep } from '../auth/FaceScanner'
import type { Role } from '../auth/session'
import { Panel } from '../components/Panel'
import { Field } from '../payments/components/Field'
import {
  createAccount,
  deleteFace,
  listAccounts,
  listEvents,
  probeScan,
  scanFace,
  setAccountPassword,
  updateAccount,
  type AccessEvent,
  type Account,
  type ScanPose,
} from './accessApi'

const EVENTS: Record<string, string> = {
  face_ok: 'Visage reconnu',
  face_ko: 'Visage refusé',
  locked: 'Identifiant bloqué',
  login_ok: 'Connexion au back-office',
  password_ko: 'Mot de passe refusé',
  face_enrolled: 'Visage scanné',
  face_deleted: 'Visage supprimé',
  account_created: 'Compte créé',
  account_updated: 'Habilitations modifiées',
  password_set: 'Mot de passe défini',
}
const BAD_EVENTS = new Set(['face_ko', 'locked', 'password_ko'])

const button =
  'rounded-lg border border-edge bg-card px-3 py-1.5 text-xs font-semibold text-text transition-colors hover:border-text-2/50 disabled:cursor-not-allowed disabled:opacity-50'
const primary =
  'rounded-lg bg-inkwarm px-4 py-2 text-sm font-semibold text-paper transition-colors hover:bg-walnut disabled:cursor-not-allowed disabled:opacity-60'

function when(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' }) : '—'
}

function fullName(a: Account): string {
  return [a.firstName, a.lastName].filter(Boolean).join(' ')
}

/** Les trois angles du scan. L'aperçu est en miroir, comme dans une glace. */
const SCAN_STEPS: (ScanStep & { hint: string })[] = [
  { pose: 'face', title: 'De face', hint: 'Regardez droit la caméra' },
  { pose: 'gauche', title: 'Côté gauche', hint: 'Tournez lentement la tête vers la gauche' },
  { pose: 'droite', title: 'Côté droit', hint: 'Puis vers la droite' },
]
const SHOTS_PER_POSE = 3
const ROLES: Record<Role, string> = { operator: 'Opérateur du back-office', client: 'Client' }

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err))
const angle = (value: number) =>
  value.toLocaleString('fr-FR', { signDisplay: 'always', minimumFractionDigits: 2, maximumFractionDigits: 2 })

const darkPrimary =
  'rounded-full bg-white px-5 py-2.5 text-sm font-semibold text-[#05070d] transition-colors hover:bg-white/85 disabled:cursor-not-allowed disabled:opacity-50'
const darkGhost =
  'rounded-full border border-white/20 px-5 py-2.5 text-sm font-semibold text-white/85 transition-colors hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-40'

/**
 * Scan guidé sous trois angles, en plein écran comme les applications d'identité : de face, puis
 * la tête tournée d'un côté et de l'autre. Chaque prise part dès que la tête est bien placée ; le
 * serveur vérifie ensuite chaque angle et qu'il s'agit bien de la même personne.
 */
function ScanDialog({ account, onDone, onCancel }: { account: Account; onDone: (message: string) => void; onCancel: () => void }) {
  const titleId = useId()
  const alive = useRef(true)
  const closeButton = useRef<HTMLButtonElement>(null)
  const finishButton = useRef<HTMLButtonElement>(null)
  // Incrémenté par « Recommencer » : remonte le scanner, donc rouvre la caméra.
  const [run, setRun] = useState(0)
  const [progress, setProgress] = useState({ step: 0, passed: 0 })
  const [outcome, setOutcome] = useState<ScanOutcome | null>(null) // null : capture en cours
  const [result, setResult] = useState<{ faces: number; angles: Record<ScanPose, number> } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const saving = outcome === 'checking'

  useEffect(() => {
    alive.current = true
    closeButton.current?.focus()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      alive.current = false
      document.body.style.overflow = overflow
    }
  }, [])

  // Échap ferme la fenêtre, sauf pendant la vérification.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [saving, onCancel])

  useEffect(() => {
    if (outcome === 'accepted') finishButton.current?.focus()
  }, [outcome])

  async function save(shots: Record<ScanPose, Blob[]>) {
    setOutcome('checking')
    try {
      const saved = await scanFace(account.username, shots)
      if (!alive.current) return
      setResult(saved)
      setOutcome('accepted')
    } catch (err) {
      if (!alive.current) return
      setError(errorText(err))
      setOutcome('refused')
    }
  }

  function restart() {
    setError(null)
    setOutcome(null)
    setResult(null)
    setProgress({ step: 0, passed: 0 })
    setRun((r) => r + 1)
  }

  const name = fullName(account) || account.username
  const doneLabel =
    outcome === 'accepted' ? 'Visage enregistré' : outcome === 'refused' ? 'Scan refusé' : 'Vérification des trois angles…'

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className="fade fixed inset-0 z-[80] overflow-y-auto bg-[#05070d] text-white"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 bg-[radial-gradient(55%_45%_at_42%_45%,rgb(143_176_255/0.13),transparent_70%)]"
      />
      <div className="relative mx-auto flex min-h-full max-w-[1280px] flex-col px-5 py-5 sm:px-8">
        <header className="flex items-start justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-scan">Enrôlement biométrique</p>
            <h2 id={titleId} className="mt-1.5 font-head text-2xl font-bold tracking-tight sm:text-3xl">
              {name}
            </h2>
            <p className="mt-0.5 text-sm text-white/55">
              {account.username} · {ROLES[account.role]}
            </p>
          </div>
          <button
            ref={closeButton}
            type="button"
            onClick={onCancel}
            disabled={saving}
            aria-label="Fermer"
            className="grid size-10 shrink-0 place-items-center rounded-full border border-white/15 text-white/80 transition-colors hover:bg-white/10 hover:text-white disabled:opacity-40"
          >
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </header>

        <div className="grid flex-1 items-center gap-8 py-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="mx-auto w-full max-w-[min(860px,calc((100dvh-170px)*4/3))]">
            <FaceScanner
              key={run}
              steps={SCAN_STEPS}
              shots={SHOTS_PER_POSE}
              probe={probeScan}
              onComplete={(shots) => void save(shots)}
              onError={(err) => {
                if (alive.current) setError(errorText(err))
              }}
              onProgress={(step, passed) => setProgress({ step, passed })}
              doneLabel={doneLabel}
              outcome={outcome ?? 'checking'}
            />
          </div>

          <aside className="space-y-5">
            <ol className="space-y-2">
              {SCAN_STEPS.map((s, i) => {
                const state = i < progress.passed ? 'done' : i === progress.step && !error ? 'current' : 'next'
                return (
                  <li
                    key={s.pose}
                    className={`flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
                      state === 'current' ? 'border-scan/50 bg-scan/10' : state === 'done' ? 'border-scan-ok/30 bg-scan-ok/5' : 'border-white/10'
                    }`}
                  >
                    <HeadIcon
                      pose={s.pose}
                      moving={state === 'current' && s.pose !== 'face'}
                      state={state === 'done' ? 'accepted' : 'idle'}
                      className="size-10"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold">{s.title}</p>
                      <p className="text-xs text-white/55">{s.hint}</p>
                    </div>
                    <span
                      className={`font-mono text-[10px] uppercase tracking-[0.14em] ${
                        state === 'done' ? 'text-scan-ok' : state === 'current' ? 'text-scan' : 'text-white/35'
                      }`}
                    >
                      {state === 'done' ? 'Fait' : state === 'current' ? 'En cours' : 'À venir'}
                    </span>
                  </li>
                )
              })}
            </ol>

            {outcome === 'accepted' && result ? (
              <div className="rise rounded-xl border border-scan-ok/30 bg-scan-ok/10 p-4">
                <p className="font-semibold text-scan-ok">Visage enregistré</p>
                <p className="mt-1 text-sm text-white/70">
                  {result.faces} gabarits remplacent les précédents. Orientation mesurée par l'IA :
                </p>
                <dl className="mt-3 grid grid-cols-3 gap-2 font-mono text-xs">
                  {SCAN_STEPS.map((s) => (
                    <div key={s.pose} className="rounded-lg bg-white/5 px-2.5 py-2">
                      <dt className="text-white/50">{s.title}</dt>
                      <dd className="mt-0.5 text-sm text-white">{angle(result.angles[s.pose])}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ) : (
              <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4 text-sm text-white/65">
                <p className="flex items-center gap-2 font-semibold text-white">
                  <svg viewBox="0 0 24 24" className="size-4 text-scan" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="5" y="11" width="14" height="10" rx="2" />
                    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                  </svg>
                  Aucune image conservée
                </p>
                <p className="mt-1.5">
                  Chaque prise part toute seule dès que la tête est bien placée. Le serveur vérifie les trois angles et
                  qu'il s'agit de la même personne, puis ne garde que trois gabarits : des vecteurs de 128 nombres
                  calculés par l'IA. Un nouveau scan remplace l'ancien.
                </p>
              </div>
            )}

            {error ? (
              <p role="alert" className="rise rounded-xl border border-scan-warn/30 bg-scan-warn/10 px-4 py-3 text-sm font-medium text-scan-warn">
                {error}
              </p>
            ) : null}

            <div className="flex flex-wrap gap-2">
              {outcome === 'accepted' ? (
                <button
                  ref={finishButton}
                  type="button"
                  className={darkPrimary}
                  onClick={() => onDone(`Visage de ${account.username} scanné sous 3 angles (${result?.faces ?? 3} gabarits).`)}
                >
                  Terminer
                </button>
              ) : null}
              {error ? (
                <button type="button" className={darkPrimary} onClick={restart}>
                  Recommencer le scan
                </button>
              ) : null}
              {outcome !== 'accepted' ? (
                <button type="button" className={darkGhost} onClick={onCancel} disabled={saving}>
                  Annuler
                </button>
              ) : null}
            </div>
          </aside>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function NewAccountForm({ onCreated }: { onCreated: (message: string) => void }) {
  const [username, setUsername] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [role, setRole] = useState<Role>('operator')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { username: created } = await createAccount({ username: username.trim(), password, role, firstName, lastName })
      setUsername('')
      setFirstName('')
      setLastName('')
      setPassword('')
      onCreated(`Compte ${created} créé${role === 'operator' ? ' : enrôlez maintenant son visage' : ''}.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel title="Créer un compte" aside="Un compte nominatif par personne">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <Field id="acc-username" label="Identifiant" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="prenom.nom" />
        <div className="grid grid-cols-2 gap-3">
          <Field id="acc-first" label="Prénom" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
          <Field id="acc-last" label="Nom" value={lastName} onChange={(e) => setLastName(e.target.value)} />
        </div>
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-medium text-text">Rôle</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="h-11 w-full rounded-lg border border-edge bg-card px-3 text-[15px]"
          >
            <option value="operator">Opérateur (back-office, visage exigé)</option>
            <option value="client">Client (boutique)</option>
          </select>
        </label>
        <Field
          id="acc-password"
          label="Mot de passe initial"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          hint="Au moins 8 caractères."
        />
        {error ? <p role="alert" className="rounded-lg bg-bad/10 px-3 py-2 text-sm font-medium text-bad">{error}</p> : null}
        <button type="submit" className={primary} disabled={busy || !username.trim() || !password}>
          {busy ? 'Création…' : 'Créer le compte'}
        </button>
      </form>
    </Panel>
  )
}

export function AccessPage() {
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [events, setEvents] = useState<AccessEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [enrolling, setEnrolling] = useState<Account | null>(null)
  const [passwordFor, setPasswordFor] = useState<string | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const [a, e] = await Promise.all([listAccounts(), listEvents()])
      setAccounts(a)
      setEvents(e)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function act(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key)
    setError(null)
    setInfo(null)
    try {
      await action()
      setInfo(success)
      await reload()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(null)
    }
  }

  const done = (message: string) => {
    setEnrolling(null)
    setInfo(message)
    void reload()
  }

  return (
    <main className="mx-auto max-w-[1200px] space-y-5 px-6 py-8">
      <div>
        <h1 className="font-head text-2xl font-bold tracking-tight">Habilitations du back-office</h1>
        <p className="mt-1 max-w-[80ch] text-sm text-text-2">
          Qui accède au back-office, avec quel rôle et quel visage. Tout opérateur passe la reconnaissance faciale à
          la connexion, sauf un compte de service, et seulement depuis le réseau interne.
        </p>
      </div>

      {info ? <p className="rise rounded-lg bg-good/10 px-3.5 py-2.5 text-sm font-medium text-good">{info}</p> : null}
      {error ? (
        <p role="alert" className="rise rounded-lg bg-bad/10 px-3.5 py-2.5 text-sm font-medium text-bad">
          {error}
        </p>
      ) : null}

      {enrolling ? <ScanDialog account={enrolling} onDone={done} onCancel={() => setEnrolling(null)} /> : null}

      <section className="overflow-hidden rounded-panel border border-edge bg-card shadow-panel">
        <div className="flex items-baseline justify-between border-b border-edge px-5 py-3.5">
          <h2 className="text-sm font-semibold">Comptes</h2>
          <span className="text-xs text-text-2">{accounts ? `${accounts.length} comptes` : 'Chargement…'}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge bg-well/60 text-left text-xs font-medium text-text-2">
                <th className="px-5 py-3">Compte</th>
                <th className="px-5 py-3">Rôle</th>
                <th className="px-5 py-3">Accès</th>
                <th className="px-5 py-3">Visage</th>
                <th className="px-5 py-3">Type</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(accounts ?? []).map((a) => {
                const missingFace = a.faceRequired && a.faces === 0
                return (
                  <tr key={a.username} className={`border-b border-edge last:border-0 ${a.disabled ? 'opacity-60' : ''}`}>
                    <td className="px-5 py-3">
                      <div className="font-medium">{fullName(a) || a.username}</div>
                      <div className="text-xs text-text-2">
                        {a.username}
                        {a.self ? ' · vous' : ''}
                      </div>
                    </td>
                    <td className="px-5 py-3">
                      <select
                        value={a.role}
                        disabled={a.self || busy !== null}
                        onChange={(e) => void act(`role-${a.username}`, () => updateAccount(a.username, { role: e.target.value as Role }), `Rôle de ${a.username} modifié.`)}
                        className="rounded-md border border-edge bg-card px-2 py-1 text-sm disabled:opacity-60"
                      >
                        <option value="operator">Opérateur</option>
                        <option value="client">Client</option>
                      </select>
                    </td>
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        disabled={a.self || busy !== null}
                        onClick={() =>
                          void act(
                            `dis-${a.username}`,
                            () => updateAccount(a.username, { disabled: !a.disabled }),
                            `Compte ${a.username} ${a.disabled ? 'réactivé' : 'désactivé'}.`,
                          )
                        }
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold disabled:cursor-not-allowed ${
                          a.disabled ? 'bg-bad/10 text-bad' : 'bg-good/10 text-good'
                        }`}
                      >
                        {a.disabled ? 'Désactivé' : 'Actif'}
                      </button>
                    </td>
                    <td className="px-5 py-3">
                      {a.faces > 0 ? (
                        <span className="text-good">
                          {a.faces} gabarit{a.faces > 1 ? 's' : ''}
                        </span>
                      ) : missingFace ? (
                        <span className="font-medium text-bad">À enrôler</span>
                      ) : (
                        <span className="text-text-2">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {a.role === 'operator' ? (
                        <label className="flex items-center gap-2 text-xs text-text-2">
                          <input
                            type="checkbox"
                            checked={a.serviceAccount}
                            disabled={a.self || a.serviceFromConfig || busy !== null}
                            onChange={() =>
                              void act(
                                `svc-${a.username}`,
                                () => updateAccount(a.username, { serviceAccount: !a.serviceAccount }),
                                a.serviceAccount ? `${a.username} doit maintenant montrer son visage.` : `${a.username} devient compte de service.`,
                              )
                            }
                          />
                          Compte de service{a.serviceFromConfig ? ' (configuration)' : ''}
                        </label>
                      ) : (
                        <span className="text-xs text-text-2">Client</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-wrap justify-end gap-1.5">
                        <button type="button" className={button} disabled={a.disabled || busy !== null} onClick={() => setEnrolling(a)}>
                          {a.faces > 0 ? 'Refaire le scan' : 'Scanner le visage'}
                        </button>
                        {a.faces > 0 ? (
                          <button
                            type="button"
                            className={button}
                            disabled={busy !== null}
                            onClick={() => void act(`del-${a.username}`, () => deleteFace(a.username), `Visage de ${a.username} supprimé.`)}
                          >
                            Supprimer le visage
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className={button}
                          disabled={a.disabled || busy !== null}
                          onClick={() => {
                            setPasswordFor(passwordFor === a.username ? null : a.username)
                            setNewPassword('')
                          }}
                        >
                          Mot de passe
                        </button>
                      </div>
                      {passwordFor === a.username ? (
                        <form
                          className="mt-2 flex justify-end gap-1.5"
                          onSubmit={(e) => {
                            e.preventDefault()
                            void act(`pw-${a.username}`, () => setAccountPassword(a.username, newPassword), `Mot de passe de ${a.username} changé.`).then(() =>
                              setPasswordFor(null),
                            )
                          }}
                        >
                          <input
                            type="password"
                            value={newPassword}
                            onChange={(e) => setNewPassword(e.target.value)}
                            placeholder="Nouveau mot de passe"
                            autoComplete="new-password"
                            className="w-44 rounded-md border border-edge px-2 py-1 text-sm"
                          />
                          <button type="submit" className={button} disabled={newPassword.length < 8 || busy !== null}>
                            Valider
                          </button>
                        </form>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[380px_1fr]">
        <NewAccountForm
          onCreated={(message) => {
            setInfo(message)
            void reload()
          }}
        />

        <Panel title="Journal des accès" aside="Les 40 derniers événements">
          {events.length === 0 ? (
            <p className="text-sm text-text-2">Aucun événement pour l'instant.</p>
          ) : (
            <ul className="divide-y divide-edge text-sm">
              {events.map((e, i) => (
                <li key={`${e.at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2">
                  <span className="w-32 shrink-0 text-xs tabular-nums text-text-2">{when(e.at)}</span>
                  <span className={`font-medium ${BAD_EVENTS.has(e.kind) ? 'text-bad' : 'text-text'}`}>{EVENTS[e.kind] ?? e.kind}</span>
                  <span>{e.username ?? ''}</span>
                  <span className="text-xs text-text-2">
                    {e.detail}
                    {e.actor ? ` · par ${e.actor}` : ''}
                    {e.ip ? ` · ${e.ip}` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </main>
  )
}

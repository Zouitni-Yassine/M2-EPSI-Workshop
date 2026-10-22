import { useEffect, useState, type FormEvent } from 'react'
import { Wordmark } from '../components/Wordmark'
import { Field } from '../payments/components/Field'
import { FaceCheck } from './FaceCheck'
import { AuthError, forgotPassword, identify, login, register, resetPassword, type FaceResult } from './session'

type Mode = 'login' | 'signup' | 'forgot' | 'reset'
/** Connexion : l'identifiant, puis la caméra pour un compte du back-office, puis le mot de passe. */
type Step = 'identify' | 'face' | 'password'

const TITLES: Record<Mode, [string, string]> = {
  login: ['Bon retour', 'Connectez-vous pour commander et suivre vos paiements.'],
  signup: ['Créer un compte', 'Une minute suffit, et la première commande peut partir.'],
  forgot: ['Mot de passe oublié', 'Indiquez votre adresse : un lien de réinitialisation vous attend ensuite dans votre boîte mail.'],
  reset: ['Nouveau mot de passe', 'Choisissez-en un nouveau, puis reconnectez-vous d’un geste.'],
}

function duration(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  return s >= 60 ? `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s` : `${s} s`
}

/** L'heure courante, rafraîchie chaque seconde tant qu'un compte à rebours est affiché. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return now
}

export function LoginPage({ notice, onBack, resetToken, onClearReset }: { notice?: string; onBack?: () => void; resetToken?: string; onClearReset?: () => void }) {
  const [mode, setMode] = useState<Mode>(resetToken ? 'reset' : 'login')
  const [step, setStep] = useState<Step>('identify')
  const [challenge, setChallenge] = useState<{ id: string; frames: number } | null>(null)
  const [deadline, setDeadline] = useState(0)
  const [blockedUntil, setBlockedUntil] = useState(0)
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const now = useNow(blockedUntil > Date.now() || deadline > 0)
  const blockedFor = blockedUntil > now ? (blockedUntil - now) / 1000 : 0
  const passwordLeft = deadline > 0 ? (deadline - now) / 1000 : 0

  /** On recommence toute l'identification : identifiant vidé, caméra éteinte. */
  function restartIdentification(message: string | null, wait = 0) {
    setStep('identify')
    setChallenge(null)
    setDeadline(0)
    setEmail('')
    setPassword('')
    if (wait > 0) setBlockedUntil(Date.now() + wait * 1000)
    setError(message)
    setInfo(null)
    setBusy(false)
  }

  // Visage reconnu, mais le mot de passe tarde : le délai passé, on recommence.
  useEffect(() => {
    if (step === 'password' && deadline > 0 && now >= deadline) {
      restartIdentification('Délai dépassé : recommencez l’identification.')
    }
  }, [now, deadline, step])

  function switchMode(next: Mode) {
    // Quitter le formulaire de réinitialisation oublie le jeton : le prochain passage
    // par « Se connecter » affiche bien l'e-mail et le mot de passe.
    if (mode === 'reset' && next !== 'reset') onClearReset?.()
    setMode(next)
    setStep('identify')
    setChallenge(null)
    setDeadline(0)
    setError(null)
    setInfo(null)
    setConfirm('')
  }

  function onFace(result: FaceResult) {
    if (result.status === 'recognized') {
      setStep('password')
      setDeadline(Date.now() + result.passwordSeconds * 1000)
      setError(null)
      setInfo('Visage reconnu : saisissez votre mot de passe.')
    } else if (result.status === 'locked') {
      restartIdentification(`Visage non reconnu (${result.reason}). Identifiant bloqué ${duration(result.retryAfter)}.`, result.retryAfter)
    } else {
      restartIdentification(`Visage non reconnu (${result.reason}). Nouvel essai possible dans ${duration(result.retryAfter)}.`, result.retryAfter)
    }
  }

  function onFaceError(err: unknown) {
    restartIdentification(err instanceof Error ? err.message : String(err), err instanceof AuthError ? err.retryAfter : 0)
  }

  const needsConfirm = mode === 'signup' || mode === 'reset'
  const [title, subtitle] = TITLES[mode]
  const identifying = mode === 'login' && step === 'identify'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (needsConfirm && password !== confirm) {
      setError('Les deux mots de passe ne correspondent pas.')
      return
    }
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      if (mode === 'signup') {
        await register(email.trim(), firstName.trim(), lastName.trim(), password)
      } else if (mode === 'forgot') {
        setInfo(await forgotPassword(email.trim()))
        setBusy(false)
      } else if (mode === 'reset') {
        await resetPassword(resetToken ?? '', password)
      } else if (step === 'identify') {
        const next = await identify(email.trim())
        if (next.step === 'face') {
          setChallenge({ id: next.challenge, frames: next.frames })
          setStep('face')
        } else {
          setStep('password')
        }
        setBusy(false)
      } else {
        await login(email.trim(), password, challenge?.id)
      }
    } catch (err) {
      if (err instanceof AuthError && mode === 'login' && err.restart) {
        restartIdentification(err.message)
        return
      }
      if (err instanceof AuthError && err.status === 429 && err.retryAfter) {
        setBlockedUntil(Date.now() + err.retryAfter * 1000)
      }
      setError(err instanceof Error ? err.message : String(err))
      if (mode === 'login') setPassword('')
      setBusy(false)
    }
  }

  const showPassword = mode !== 'forgot' && !(mode === 'login' && step !== 'password')
  const disabled =
    busy ||
    (identifying && blockedFor > 0) ||
    (mode !== 'reset' && !email.trim()) ||
    (showPassword && !password) ||
    (needsConfirm && !confirm) ||
    (mode === 'signup' && (!firstName.trim() || !lastName.trim()))

  return (
    <main className="grid min-h-dvh lg:grid-cols-[5fr_4fr]">
      {/* ---- Visuel ---- */}
      <section className="relative hidden lg:block" aria-hidden="true">
        <img src="/img/hero-3.jpg" alt="" className="absolute inset-0 size-full object-cover" />
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/10 to-black/20" />
        <div className="absolute inset-x-0 top-0 p-10">
          <Wordmark light />
        </div>
        <div className="absolute inset-x-0 bottom-0 p-10">
          <p className="max-w-[24ch] font-head text-4xl font-extrabold leading-[1.08] text-white">
            Des pièces choisies pour durer.
          </p>
          <p className="mt-3 max-w-[44ch] text-[15px] text-white/80">
            Créez votre compte pour commander, suivre vos paiements et retrouver vos reçus.
          </p>
        </div>
      </section>

      {/* ---- Formulaire ---- */}
      <section className="flex items-center justify-center bg-card px-6 py-10">
        <div className="rise w-full max-w-[400px]">
          <div className="mb-8 lg:hidden">
            <Wordmark />
          </div>

          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="mb-6 text-sm font-medium text-text-2 transition-colors hover:text-text"
            >
              ← Revenir à la boutique
            </button>
          ) : null}

          <h1 className="font-head text-3xl font-bold tracking-tight">{title}</h1>
          <p className="mt-1.5 text-[15px] text-text-2">{subtitle}</p>

          {notice && !error && !info ? (
            <p className="mt-5 rounded-lg bg-note/10 px-3.5 py-2.5 text-sm text-note">{notice}</p>
          ) : null}
          {info ? (
            <p className="rise mt-5 rounded-lg bg-good/10 px-3.5 py-2.5 text-sm font-medium text-good">{info}</p>
          ) : null}
          {error ? (
            <p role="alert" className="rise mt-5 rounded-lg bg-bad/10 px-3.5 py-2.5 text-sm font-medium text-bad">
              {error}
            </p>
          ) : null}

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            {mode !== 'reset' ? (
              <Field
                id="auth-email"
                label={mode === 'login' ? 'Adresse e-mail ou identifiant' : 'Adresse e-mail'}
                type={mode === 'login' ? 'text' : 'email'}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                readOnly={mode === 'login' && step !== 'identify'}
                autoComplete={mode === 'login' ? 'username' : 'email'}
                placeholder="vous@exemple.fr"
                trailing={
                  mode === 'login' && step !== 'identify' ? (
                    <button
                      type="button"
                      onClick={() => restartIdentification(null)}
                      className="shrink-0 text-xs font-semibold text-text-2 hover:text-text"
                    >
                      Modifier
                    </button>
                  ) : undefined
                }
              />
            ) : null}

            {mode === 'login' && step === 'face' && challenge ? (
              <FaceCheck challenge={challenge.id} frames={challenge.frames} onResult={onFace} onError={onFaceError} />
            ) : null}

            {mode === 'signup' ? (
              <div className="grid grid-cols-2 gap-3">
                <Field
                  id="auth-firstname"
                  label="Prénom"
                  value={firstName}
                  onChange={(e) => setFirstName(e.target.value)}
                  autoComplete="given-name"
                />
                <Field
                  id="auth-lastname"
                  label="Nom"
                  value={lastName}
                  onChange={(e) => setLastName(e.target.value)}
                  autoComplete="family-name"
                />
              </div>
            ) : null}

            {showPassword ? (
              <Field
                id="auth-password"
                label={mode === 'reset' ? 'Nouveau mot de passe' : 'Mot de passe'}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                autoFocus={mode === 'login'}
                placeholder={mode === 'login' ? undefined : 'Au moins 8 caractères'}
                hint={passwordLeft > 0 ? `Temps restant pour le saisir : ${duration(passwordLeft)}` : undefined}
              />
            ) : null}

            {needsConfirm ? (
              <Field
                id="auth-confirm"
                label="Confirmez le mot de passe"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            ) : null}

            {mode === 'login' && step !== 'face' ? (
              <div className="text-right">
                <button
                  type="button"
                  onClick={() => switchMode('forgot')}
                  className="text-sm font-medium text-text-2 transition-colors hover:text-text"
                >
                  Mot de passe oublié ?
                </button>
              </div>
            ) : null}

            {mode === 'login' && step === 'face' ? null : (
              <button
                type="submit"
                disabled={disabled}
                className="w-full rounded-lg bg-inkwarm px-5 py-3 text-[15px] font-semibold text-paper transition-colors hover:bg-walnut disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy
                  ? 'Un instant…'
                  : identifying && blockedFor > 0
                    ? `Patientez ${duration(blockedFor)}`
                    : mode === 'signup'
                      ? 'Créer mon compte'
                      : mode === 'forgot'
                        ? 'Envoyer le lien'
                        : mode === 'reset'
                          ? 'Changer le mot de passe'
                          : identifying
                            ? 'Continuer'
                            : 'Se connecter'}
              </button>
            )}
          </form>

          <p className="mt-6 text-center text-sm text-text-2">
            {mode === 'signup' ? (
              <>
                Déjà un compte ?{' '}
                <button type="button" onClick={() => switchMode('login')} className="font-semibold text-text underline-offset-2 hover:underline">
                  Se connecter
                </button>
              </>
            ) : mode === 'login' ? (
              <>
                Première visite ?{' '}
                <button type="button" onClick={() => switchMode('signup')} className="font-semibold text-text underline-offset-2 hover:underline">
                  Créer un compte
                </button>
              </>
            ) : (
              <button type="button" onClick={() => switchMode('login')} className="font-semibold text-text underline-offset-2 hover:underline">
                ← Revenir à la connexion
              </button>
            )}
          </p>

          <p className="mt-8 text-center text-xs text-text-2">
            Plateforme de démonstration — données et paiements fictifs. Back-office protégé par reconnaissance faciale.
          </p>
        </div>
      </section>
    </main>
  )
}

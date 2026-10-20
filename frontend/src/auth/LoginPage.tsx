import { useState, type FormEvent } from 'react'
import { Wordmark } from '../components/Wordmark'
import { Field } from '../payments/components/Field'
import { forgotPassword, login, register, resetPassword } from './session'

type Mode = 'login' | 'signup' | 'forgot' | 'reset'

const TITLES: Record<Mode, [string, string]> = {
  login: ['Bon retour', 'Connectez-vous pour commander et suivre vos paiements.'],
  signup: ['Créer un compte', 'Une minute suffit, et la première commande peut partir.'],
  forgot: ['Mot de passe oublié', 'Indiquez votre adresse : un lien de réinitialisation vous attend ensuite dans votre boîte mail.'],
  reset: ['Nouveau mot de passe', 'Choisissez-en un nouveau, puis reconnectez-vous d’un geste.'],
}

export function LoginPage({ notice, onBack, resetToken }: { notice?: string; onBack?: () => void; resetToken?: string }) {
  const [mode, setMode] = useState<Mode>(resetToken ? 'reset' : 'login')
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setInfo(null)
    setConfirm('')
  }

  const needsConfirm = mode === 'signup' || mode === 'reset'
  const [title, subtitle] = TITLES[mode]

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
        // La session est ouverte : on nettoie le lien pour qu'un rechargement ne rejoue pas le jeton.
        window.history.replaceState(null, '', window.location.pathname)
      } else {
        await login(email.trim(), password)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      if (mode === 'login') setPassword('')
      setBusy(false)
    }
  }

  const disabled =
    busy ||
    (mode !== 'reset' && !email.trim()) ||
    (mode !== 'forgot' && !password) ||
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
                label="Adresse e-mail"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                placeholder="vous@exemple.fr"
              />
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

            {mode !== 'forgot' ? (
              <Field
                id="auth-password"
                label={mode === 'reset' ? 'Nouveau mot de passe' : 'Mot de passe'}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                placeholder={mode === 'login' ? undefined : 'Au moins 8 caractères'}
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

            {mode === 'login' ? (
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

            <button
              type="submit"
              disabled={disabled}
              className="w-full rounded-lg bg-inkwarm px-5 py-3 text-[15px] font-semibold text-paper transition-colors hover:bg-walnut disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy
                ? 'Un instant…'
                : mode === 'signup'
                  ? 'Créer mon compte'
                  : mode === 'forgot'
                    ? 'Envoyer le lien'
                    : mode === 'reset'
                      ? 'Changer le mot de passe'
                      : 'Se connecter'}
            </button>
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
            Plateforme de démonstration — données et paiements fictifs.
          </p>
        </div>
      </section>
    </main>
  )
}

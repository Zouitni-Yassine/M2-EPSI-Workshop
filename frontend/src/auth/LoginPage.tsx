import { useState, type FormEvent } from 'react'
import { Wordmark } from '../components/Wordmark'
import { Field } from '../payments/components/Field'
import { login, register } from './session'

type Mode = 'login' | 'signup'

export function LoginPage({ notice, onBack }: { notice?: string; onBack?: () => void }) {
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const signup = mode === 'signup'

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
    setConfirm('')
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (signup && password !== confirm) {
      setError('Les deux mots de passe ne correspondent pas.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (signup) await register(username.trim(), password)
      else await login(username.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      if (!signup) setPassword('')
      setBusy(false)
    }
  }

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

          <h1 className="font-head text-3xl font-bold tracking-tight">
            {signup ? 'Créer un compte' : 'Bon retour'}
          </h1>
          <p className="mt-1.5 text-[15px] text-text-2">
            {signup ? 'Une minute suffit, et la première commande peut partir.' : 'Connectez-vous pour commander et suivre vos paiements.'}
          </p>

          {notice && !error ? (
            <p className="mt-5 rounded-lg bg-note/10 px-3.5 py-2.5 text-sm text-note">{notice}</p>
          ) : null}
          {error ? (
            <p role="alert" className="rise mt-5 rounded-lg bg-bad/10 px-3.5 py-2.5 text-sm font-medium text-bad">
              {error}
            </p>
          ) : null}

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <Field
              id="auth-username"
              label="Identifiant"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder={signup ? 'En minuscules : lettres, chiffres, . _ -' : undefined}
            />
            <Field
              id="auth-password"
              label="Mot de passe"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={signup ? 'new-password' : 'current-password'}
              placeholder={signup ? 'Au moins 8 caractères' : undefined}
            />
            {signup ? (
              <Field
                id="auth-confirm"
                label="Confirmez le mot de passe"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
              />
            ) : null}

            <button
              type="submit"
              disabled={busy || !username.trim() || !password || (signup && !confirm)}
              className="w-full rounded-lg bg-inkwarm px-5 py-3 text-[15px] font-semibold text-paper transition-colors hover:bg-walnut disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? 'Un instant…' : signup ? 'Créer mon compte' : 'Se connecter'}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-text-2">
            {signup ? (
              <>
                Déjà un compte ?{' '}
                <button type="button" onClick={() => switchMode('login')} className="font-semibold text-text underline-offset-2 hover:underline">
                  Se connecter
                </button>
              </>
            ) : (
              <>
                Première visite ?{' '}
                <button type="button" onClick={() => switchMode('signup')} className="font-semibold text-text underline-offset-2 hover:underline">
                  Créer un compte
                </button>
              </>
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

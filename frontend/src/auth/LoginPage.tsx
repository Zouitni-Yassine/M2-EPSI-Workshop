import { useState, type FormEvent } from 'react'
import { Wordmark } from '../components/Wordmark'
import { Field } from '../payments/components/Field'
import { login } from './session'

export function LoginPage({ notice, onBack }: { notice?: string; onBack?: () => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="rise w-full max-w-[400px]">
        <div className="mb-6 flex justify-center">
          <Wordmark />
        </div>
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            className="mb-4 text-sm font-medium text-text-2 transition-colors hover:text-text"
          >
            ← Revenir à la boutique
          </button>
        ) : null}

        <form onSubmit={submit} className="rounded-panel border border-edge bg-card px-6 py-7 shadow-panel sm:px-8">
          <h1 className="text-xl font-semibold tracking-tight">Connexion</h1>
          <p className="mt-1 text-sm text-text-2">Accédez au paiement et à vos transactions.</p>

          {notice && !error ? (
            <p className="mt-5 rounded-lg bg-note/10 px-3.5 py-2.5 text-sm text-note">{notice}</p>
          ) : null}
          {error ? (
            <p role="alert" className="rise mt-5 rounded-lg bg-bad/10 px-3.5 py-2.5 text-sm font-medium text-bad">
              {error}
            </p>
          ) : null}

          <div className="mt-5 space-y-4">
            <Field
              label="Identifiant"
              name="username"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
            <Field
              label="Mot de passe"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            className="mt-6 h-11 w-full rounded-lg bg-accent text-[15px] font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-wait disabled:opacity-70"
          >
            {busy ? 'Connexion…' : 'Se connecter'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-text-2">
          Plateforme de démonstration — données et paiements fictifs.
        </p>
      </div>
    </main>
  )
}

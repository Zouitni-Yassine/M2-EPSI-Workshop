import { useEffect, useRef, useState } from 'react'
import { euros } from '../domain/money'
import type { Cents } from '../domain/types'

interface Props {
  amount: Cents
  last4: string
  busy: boolean
  error?: string
  onSubmit: (code: string) => void
  onCancel: () => void
}

/**
 * Authentification forte. L'écran imite celui de l'émetteur, parce que
 * c'est ce que vit réellement un porteur : il quitte le marchand.
 */
export function ThreeDSChallenge({ amount, last4, busy, error, onSubmit, onCancel }: Props) {
  const [code, setCode] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    input.current?.focus()
  }, [])

  useEffect(() => {
    if (error) setCode('')
  }, [error])

  return (
    <div className="fade fixed inset-0 z-50 grid place-items-center bg-text/45 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Authentification de votre banque"
        className={`rise w-full max-w-[420px] overflow-hidden rounded-2xl bg-card shadow-float ${error ? 'shake' : ''}`}
      >
        <div className="flex items-center gap-3 border-b border-edge px-6 py-4">
          <span className="grid size-9 place-items-center rounded-full bg-well text-text">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" stroke="currentColor" strokeWidth="1.5" />
            </svg>
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold">Banque Fictive</p>
            <p className="text-xs text-text-2">Vérification de votre identité</p>
          </div>
        </div>

        <form
          className="px-6 py-6"
          onSubmit={(e) => {
            e.preventDefault()
            onSubmit(code)
          }}
        >
          <p className="text-sm leading-relaxed text-text-2">
            Pour confirmer le paiement de{' '}
            <strong className="font-semibold text-text">{euros(amount)}</strong> avec la carte se
            terminant par <strong className="font-semibold text-text">{last4}</strong>, saisissez
            le code envoyé par SMS au 06 •• •• •• 42.
          </p>

          <label className="mt-6 block">
            <span className="mb-2 block text-[13px] font-medium">Code de sécurité</span>
            <input
              ref={input}
              inputMode="numeric"
              maxLength={4}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              disabled={busy}
              className={`field-input h-14 w-full rounded-lg border bg-card text-center text-3xl font-semibold tracking-[0.5em] transition-[border-color,box-shadow] ${
                error ? 'border-bad ring-4 ring-bad/10' : 'border-edge focus:border-accent focus:ring-4 focus:ring-accent/15'
              }`}
            />
          </label>

          {error ? <p className="rise mt-2 text-sm font-medium text-bad">{error}</p> : null}

          <div className="mt-6 grid gap-2">
            <button
              type="submit"
              disabled={busy || code.length < 4}
              className="h-11 rounded-lg bg-accent text-sm font-semibold text-white transition-colors hover:bg-accent-strong disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Vérification…' : 'Confirmer'}
            </button>
            <button
              type="button"
              onClick={onCancel}
              disabled={busy}
              className="h-11 rounded-lg text-sm font-medium text-text-2 transition-colors hover:bg-well hover:text-text"
            >
              Annuler le paiement
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

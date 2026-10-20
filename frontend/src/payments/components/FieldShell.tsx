import type { ReactNode } from 'react'

interface Props {
  label: string
  hint?: string
  error?: string
  focused?: boolean
  trailing?: ReactNode
  children: ReactNode
}

/** Le même cadre que `Field`, pour un contenu qui n'est pas un `<input>` — un iframe Stripe. */
export function FieldShell({ label, hint, error, focused, trailing, children }: Props) {
  const box = error
    ? 'border-bad ring-4 ring-bad/10'
    : focused
      ? 'border-accent ring-4 ring-accent/15'
      : 'border-edge hover:border-text-2/50'

  return (
    <div>
      <span className="mb-1.5 block text-[13px] font-medium text-text">{label}</span>
      <div
        className={`flex h-11 items-center gap-2 rounded-lg border bg-card px-3.5 transition-[border-color,box-shadow] duration-150 ${box}`}
      >
        <div className="min-w-0 flex-1">{children}</div>
        {trailing}
      </div>
      {error ? (
        <span className="rise mt-1.5 block text-xs font-medium text-bad">{error}</span>
      ) : hint ? (
        <span className="mt-1.5 block text-xs text-text-2">{hint}</span>
      ) : null}
    </div>
  )
}

import type { InputHTMLAttributes, ReactNode } from 'react'

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
  error?: string
  trailing?: ReactNode
  wrapperClassName?: string
}

export function Field({ label, hint, error, trailing, wrapperClassName = '', className = '', ...input }: Props) {
  const box = error
    ? 'border-bad ring-4 ring-bad/10'
    : 'border-edge hover:border-text-2/50 focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/15'

  return (
    <label className={`block ${wrapperClassName}`}>
      <span className="mb-1.5 block text-[13px] font-medium text-text">{label}</span>
      <span
        className={`flex h-11 items-center gap-2 rounded-lg border bg-card px-3.5 transition-[border-color,box-shadow] duration-150 ${box}`}
      >
        <input
          {...input}
          className={`field-input h-full w-full bg-transparent text-[15px] text-text outline-none placeholder:text-text-2/55 disabled:text-text-2 ${className}`}
        />
        {trailing}
      </span>
      {error ? (
        <span className="rise mt-1.5 block text-xs font-medium text-bad">{error}</span>
      ) : hint ? (
        <span className="mt-1.5 block text-xs text-text-2">{hint}</span>
      ) : null}
    </label>
  )
}

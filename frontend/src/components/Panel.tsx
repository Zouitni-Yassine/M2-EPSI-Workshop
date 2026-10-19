import type { ReactNode } from 'react'

interface Props {
  title: string
  aside?: ReactNode
  children: ReactNode
  className?: string
}

export function Panel({ title, aside, children, className = '' }: Props) {
  return (
    <section className={`rounded-panel border border-edge bg-card shadow-panel ${className}`}>
      <div className="flex items-baseline justify-between gap-4 border-b border-edge px-5 py-3.5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside ? <div className="text-xs text-text-2">{aside}</div> : null}
      </div>
      <div className="p-5">{children}</div>
    </section>
  )
}

import type { Brand } from '../domain/types'
import { BrandLogo } from './BrandLogo'

interface Props {
  number: string
  holder: string
  expiry: string
  cvc: string
  brand: Brand
  flipped: boolean
}

const SURFACE: Record<Brand, string> = {
  visa: 'from-[#1e3a8a] to-[#1d4ed8]',
  mastercard: 'from-[#1f2937] to-[#0f172a]',
  amex: 'from-[#0f6ab4] to-[#0b4a80]',
  unknown: 'from-[#334155] to-[#1e293b]',
}

function groups(brand: Brand): number[] {
  return brand === 'amex' ? [4, 6, 5] : [4, 4, 4, 4]
}

/** Remplit les chiffres saisis, complète par des points. */
function printed(number: string, brand: Brand): string[] {
  const out: string[] = []
  let i = 0
  for (const g of groups(brand)) {
    const chunk = number.slice(i, i + g)
    out.push(chunk.padEnd(g, '•'))
    i += g
  }
  return out
}

function printedExpiry(expiry: string): string {
  const mm = expiry.slice(0, 2).padEnd(2, '•')
  const yy = expiry.slice(2, 4).padEnd(2, '•')
  return `${mm}/${yy}`
}

/**
 * La carte telle que le porteur la tient : elle se remplit à mesure qu'il
 * tape, et se retourne quand il cherche le cryptogramme au dos.
 */
export function CardPreview({ number, holder, expiry, cvc, brand, flipped }: Props) {
  const cvcLen = brand === 'amex' ? 4 : 3

  return (
    <div className="card-scene w-full max-w-[400px]">
      <div className={`card-body relative aspect-[1.586] w-full ${flipped ? 'is-flipped' : ''}`}>
        {/* Recto */}
        <div
          className={`card-face absolute inset-0 flex flex-col justify-between rounded-2xl bg-gradient-to-br p-6 text-white shadow-float ${SURFACE[brand]}`}
          style={{ transition: 'background 400ms' }}
        >
          <div className="flex items-start justify-between">
            <Chip />
            <Contactless />
          </div>

          <div className="flex gap-4 font-ui text-[22px] font-medium tracking-[0.14em] tabular-nums">
            {printed(number, brand).map((g, i) => (
              <span key={i} className="transition-opacity">{g}</span>
            ))}
          </div>

          <div className="flex items-end justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-white/60">
                Titulaire
              </div>
              <div className="truncate text-sm font-semibold uppercase tracking-[0.08em]">
                {holder.trim() || 'Nom du titulaire'}
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-white/60">
                Expire
              </div>
              <div className="text-sm font-semibold tracking-[0.12em]">{printedExpiry(expiry)}</div>
            </div>
            <div className="h-7 w-14 shrink-0 text-white">
              <BrandLogo brand={brand} className="h-full w-full" />
            </div>
          </div>
        </div>

        {/* Verso */}
        <div
          className={`card-face back absolute inset-0 overflow-hidden rounded-2xl bg-gradient-to-br text-white shadow-float ${SURFACE[brand]}`}
        >
          <div className="mt-6 h-11 w-full bg-black/85" />
          <div className="px-6 pt-6">
            <div className="flex h-10 items-center rounded-md bg-white/95 px-3">
              <div className="h-6 flex-1 bg-[repeating-linear-gradient(0deg,transparent,transparent_3px,rgb(0_0_0/0.06)_3px,rgb(0_0_0/0.06)_4px)]" />
              <span className="ml-3 font-ui text-base font-semibold italic tracking-[0.3em] text-text">
                {cvc.padEnd(cvcLen, '•').slice(0, cvcLen)}
              </span>
            </div>
            <p className="mt-3 text-[10px] leading-relaxed text-white/60">
              Le cryptogramme visuel figure dans la bande de signature. Ne le communiquez jamais
              par téléphone ou par e-mail.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function Chip() {
  return (
    <svg width="46" height="34" viewBox="0 0 46 34" aria-hidden="true">
      <rect width="46" height="34" rx="6" fill="#e6c25a" />
      <rect width="46" height="34" rx="6" fill="url(#chipShade)" />
      <path
        d="M0 12h16M0 22h16M30 12h16M30 22h16M16 0v34M30 0v34"
        stroke="#9a7c1f"
        strokeWidth="1.2"
        fill="none"
      />
      <defs>
        <linearGradient id="chipShade" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.25" />
          <stop offset="1" stopColor="#000" stopOpacity="0.15" />
        </linearGradient>
      </defs>
    </svg>
  )
}

function Contactless() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="text-white/80">
      <path d="M6 8.5a6 6 0 0 1 0 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M9.5 6a10 10 0 0 1 0 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M13 3.5a14 14 0 0 1 0 17" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

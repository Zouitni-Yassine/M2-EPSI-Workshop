import type { Brand } from '../domain/types'

interface Props {
  brand: Brand
  className?: string
}

/**
 * Marques des réseaux. Visa hérite de la couleur du parent (bleu sur fond
 * clair, blanc sur la carte) ; Mastercard et Amex gardent leurs couleurs.
 */
export function BrandLogo({ brand, className = '' }: Props) {
  if (brand === 'visa') {
    return (
      <svg viewBox="0 0 48 16" className={className} role="img" aria-label="Visa">
        <text
          x="0"
          y="14.5"
          fontFamily="Inter, Arial, sans-serif"
          fontWeight="800"
          fontStyle="italic"
          fontSize="18.5"
          letterSpacing="-0.8"
          fill="currentColor"
        >
          VISA
        </text>
      </svg>
    )
  }
  if (brand === 'mastercard') {
    return (
      <svg viewBox="0 0 32 20" className={className} role="img" aria-label="Mastercard">
        <circle cx="11" cy="10" r="9" fill="#EB001B" />
        <circle cx="21" cy="10" r="9" fill="#F79E1B" />
        <path d="M16 3.1a9 9 0 0 1 0 13.8 9 9 0 0 1 0-13.8z" fill="#FF5F00" />
      </svg>
    )
  }
  if (brand === 'amex') {
    return (
      <svg viewBox="0 0 32 20" className={className} role="img" aria-label="American Express">
        <rect width="32" height="20" rx="2.5" fill="#006FCF" />
        <text
          x="16"
          y="13.6"
          textAnchor="middle"
          fontFamily="Inter, Arial, sans-serif"
          fontWeight="800"
          fontSize="8.5"
          letterSpacing="0.4"
          fill="#fff"
        >
          AMEX
        </text>
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 32 20" className={className} aria-hidden="true">
      <rect x="1" y="1" width="30" height="18" rx="3" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="1" y="5.5" width="30" height="3.5" fill="currentColor" />
    </svg>
  )
}

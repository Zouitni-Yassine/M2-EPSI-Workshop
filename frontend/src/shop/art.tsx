import type React from 'react'
/**
 * Visuels produits dessinés en SVG : la démo reste belle sans réseau ni photos.
 * Trois tons par pièce, posés sur le socle teinté du produit.
 */

const WOOD = '#8a6a4b'
const WOOD_DARK = '#6e5138'
const FABRIC = '#efe9dc'
const FABRIC_SHADE = '#ddd3bf'
const METAL = '#a98a52'
const CLAY = '#b4785a'
const SHADOW = 'rgba(38, 33, 26, 0.12)'

function Ground() {
  return <ellipse cx="110" cy="188" rx="72" ry="9" fill={SHADOW} />
}

const ART: Record<string, React.ReactElement> = {
  'canape-aalto': (
    <g>
      <Ground />
      <rect x="28" y="96" width="164" height="62" rx="16" fill={FABRIC} />
      <rect x="40" y="76" width="140" height="44" rx="14" fill={FABRIC_SHADE} />
      <rect x="40" y="112" width="68" height="34" rx="10" fill={FABRIC} />
      <rect x="112" y="112" width="68" height="34" rx="10" fill={FABRIC} />
      <rect x="22" y="100" width="22" height="52" rx="10" fill={FABRIC_SHADE} />
      <rect x="176" y="100" width="22" height="52" rx="10" fill={FABRIC_SHADE} />
      <rect x="46" y="158" width="10" height="20" rx="3" fill={WOOD_DARK} />
      <rect x="164" y="158" width="10" height="20" rx="3" fill={WOOD_DARK} />
    </g>
  ),
  'fauteuil-ryo': (
    <g>
      <Ground />
      <path d="M62 78a48 48 0 0 1 96 0v46a20 20 0 0 1-20 20H82a20 20 0 0 1-20-20Z" fill={FABRIC} />
      <path d="M74 84a36 36 0 0 1 72 0v34H74Z" fill={FABRIC_SHADE} />
      <rect x="62" y="118" width="96" height="28" rx="14" fill={FABRIC} />
      <rect x="104" y="146" width="12" height="22" fill={WOOD_DARK} />
      <path d="M72 180h76" stroke={WOOD_DARK} strokeWidth="8" strokeLinecap="round" />
    </g>
  ),
  'table-noma': (
    <g>
      <Ground />
      <ellipse cx="110" cy="96" rx="82" ry="18" fill={WOOD} />
      <ellipse cx="110" cy="90" rx="82" ry="18" fill="#9c7a57" />
      <path d="M58 106l-14 72M110 112v76M162 106l14 72" stroke={WOOD_DARK} strokeWidth="9" strokeLinecap="round" />
      <ellipse cx="110" cy="82" rx="26" ry="6" fill={CLAY} opacity="0.5" />
    </g>
  ),
  'chaise-brume': (
    <g>
      <Ground />
      <path d="M84 36c-4 34-4 56 0 78" stroke={WOOD} strokeWidth="9" strokeLinecap="round" fill="none" />
      <path d="M136 36c4 34 4 56 0 78" stroke={WOOD} strokeWidth="9" strokeLinecap="round" fill="none" />
      <rect x="80" y="40" width="60" height="12" rx="6" fill={WOOD} />
      <rect x="72" y="112" width="78" height="14" rx="7" fill="#d9c9a3" />
      <path d="M78 126l-8 56M144 126l8 56M110 126v56" stroke={WOOD_DARK} strokeWidth="8" strokeLinecap="round" />
      <path d="M80 118h62" stroke="#c9b88f" strokeWidth="4" strokeDasharray="3 5" strokeLinecap="round" />
    </g>
  ),
  'lampadaire-orne': (
    <g>
      <Ground />
      <path d="M74 182V70a40 40 0 0 1 60-34" stroke={METAL} strokeWidth="7" strokeLinecap="round" fill="none" />
      <path d="M118 28h40l-8 34h-26Z" fill={FABRIC} />
      <path d="M118 28h40l-2 9h-36Z" fill={FABRIC_SHADE} />
      <ellipse cx="139" cy="78" rx="22" ry="8" fill="#f6e7b6" opacity="0.7" />
      <path d="M52 182h46" stroke={METAL} strokeWidth="8" strokeLinecap="round" />
    </g>
  ),
  'suspension-halo': (
    <g>
      <path d="M110 10v44" stroke={WOOD_DARK} strokeWidth="4" strokeLinecap="round" />
      <circle cx="110" cy="112" r="56" fill={FABRIC} />
      <circle cx="110" cy="112" r="56" fill="none" stroke={FABRIC_SHADE} strokeWidth="3" />
      <circle cx="92" cy="94" r="18" fill="#ffffff" opacity="0.55" />
      <ellipse cx="110" cy="186" rx="52" ry="7" fill="#f3e6bb" opacity="0.65" />
    </g>
  ),
  'vase-terra': (
    <g>
      <Ground />
      <path d="M92 42h36v16c22 10 30 30 30 52 0 36-22 58-48 58s-48-22-48-58c0-22 8-42 30-52Z" fill={CLAY} />
      <path d="M92 42h36v12H92Z" fill="#9c6448" />
      <path d="M72 118c10 8 66 8 76 0" stroke="#9c6448" strokeWidth="4" fill="none" opacity="0.6" />
      <path d="M128 70c10 10 14 24 14 40" stroke="#d99b77" strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.8" />
    </g>
  ),
  'miroir-lune': (
    <g>
      <Ground />
      <circle cx="110" cy="100" r="74" fill={WOOD} />
      <circle cx="110" cy="100" r="62" fill="#dfe7e4" />
      <path d="M74 72a52 52 0 0 1 44-22" stroke="#ffffff" strokeWidth="9" strokeLinecap="round" fill="none" opacity="0.8" />
      <rect x="102" y="174" width="16" height="12" rx="3" fill={WOOD_DARK} />
    </g>
  ),
  'tapis-dune': (
    <g>
      <path d="M30 60h160l16 108H14Z" fill="#dcc9a4" />
      <path d="M30 60h160l4 28H26Z" fill="#e7d7b4" />
      <path d="M40 112c30-10 110-10 142 0M34 142c34-12 120-12 154 0" stroke={CLAY} strokeWidth="6" strokeLinecap="round" fill="none" opacity="0.65" />
      <path d="M46 86c26-8 96-8 122 0" stroke={WOOD} strokeWidth="5" strokeLinecap="round" fill="none" opacity="0.5" />
    </g>
  ),
  'etagere-fjord': (
    <g>
      <Ground />
      <path d="M52 22v160M168 22v160" stroke="#3f3a32" strokeWidth="7" strokeLinecap="round" />
      {[40, 76, 112, 148].map((y) => (
        <rect key={y} x="46" y={y} width="128" height="10" rx="4" fill={WOOD} />
      ))}
      <rect x="64" y="52" width="18" height="24" rx="2" fill={CLAY} />
      <rect x="140" y="88" width="22" height="24" rx="11" fill={FABRIC_SHADE} />
      <rect x="92" y="124" width="30" height="24" rx="2" fill="#7d8a6f" />
    </g>
  ),
}

export function ProductArt({ id, className }: { id: string; className?: string }) {
  return (
    <svg viewBox="0 0 220 200" className={className} role="img" aria-hidden="true">
      {ART[id] ?? <circle cx="110" cy="100" r="60" fill={FABRIC_SHADE} />}
    </svg>
  )
}

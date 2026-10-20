import type { Cents } from '../payments/domain/types'

export type Category = 'salon' | 'luminaires' | 'deco' | 'rangement'

export const CATEGORIES: { id: Category; label: string }[] = [
  { id: 'salon', label: 'Salon' },
  { id: 'luminaires', label: 'Luminaires' },
  { id: 'deco', label: 'Décoration' },
  { id: 'rangement', label: 'Rangement' },
]

export interface Product {
  id: string
  name: string
  category: Category
  /** Matière et dimension, affichées sous le nom. */
  detail: string
  price: Cents
  /** Teinte du socle sur lequel le produit est dessiné. */
  plinth: string
  /** Une phrase pour la fiche produit. */
  story: string
}

export const PRODUCTS: Product[] = [
  {
    id: 'canape-aalto',
    name: 'Canapé Aalto',
    category: 'salon',
    detail: 'Lin lavé, 3 places · L 228 cm',
    price: 129_900,
    plinth: '#E7DECF',
    story: 'Une assise profonde en lin lavé, dessinée pour les fins de journée qui durent.',
  },
  {
    id: 'fauteuil-ryo',
    name: 'Fauteuil Ryo',
    category: 'salon',
    detail: 'Bouclette écrue, pivotant · L 82 cm',
    price: 64_900,
    plinth: '#E3E0D5',
    story: 'La bouclette enveloppe une coque pivotante : le coin lecture devient un point de vue.',
  },
  {
    id: 'table-noma',
    name: 'Table basse Noma',
    category: 'salon',
    detail: 'Chêne massif huilé · Ø 90 cm',
    price: 37_900,
    plinth: '#EADFCE',
    story: 'Un plateau de chêne épais posé sur trois pieds fuselés, huilé pour vieillir avec vous.',
  },
  {
    id: 'chaise-brume',
    name: 'Chaise Brume',
    category: 'salon',
    detail: 'Hêtre cintré, assise paillée · H 79 cm',
    price: 18_900,
    plinth: '#E6E2D8',
    story: 'Le hêtre cintré à la vapeur, la paille tressée main : une silhouette qui ne se démode pas.',
  },
  {
    id: 'lampadaire-orne',
    name: 'Lampadaire Orne',
    category: 'luminaires',
    detail: 'Laiton brossé, abat-jour lin · H 148 cm',
    price: 25_900,
    plinth: '#E8E0CC',
    story: 'Un arc de laiton brossé qui penche la lumière exactement là où on lit.',
  },
  {
    id: 'suspension-halo',
    name: 'Suspension Halo',
    category: 'luminaires',
    detail: 'Verre soufflé opalin · Ø 38 cm',
    price: 14_900,
    plinth: '#E2DFD6',
    story: 'Le verre opalin diffuse une lumière de fin d’après-midi, à n’importe quelle heure.',
  },
  {
    id: 'vase-terra',
    name: 'Vase Terra',
    category: 'deco',
    detail: 'Grès émaillé main · H 32 cm',
    price: 5_900,
    plinth: '#EBDFD2',
    story: 'Tourné puis émaillé à la main : aucun exemplaire n’a exactement la même robe.',
  },
  {
    id: 'miroir-lune',
    name: 'Miroir Lune',
    category: 'deco',
    detail: 'Cadre frêne teinté · Ø 75 cm',
    price: 21_900,
    plinth: '#E4E1DA',
    story: 'Un plein cercle de frêne qui agrandit la pièce et adoucit la lumière du matin.',
  },
  {
    id: 'tapis-dune',
    name: 'Tapis Dune',
    category: 'deco',
    detail: 'Laine tuftée main · 200 × 300 cm',
    price: 42_900,
    plinth: '#E9E2D0',
    story: 'Des lignes de dune tuftées dans une laine dense, douce sous les pieds nus.',
  },
  {
    id: 'etagere-fjord',
    name: 'Étagère Fjord',
    category: 'rangement',
    detail: 'Chêne et acier thermolaqué · H 190 cm',
    price: 53_900,
    plinth: '#E5DFD3',
    story: 'Cinq niveaux de chêne portés par un trait d’acier : le rangement qui se fait oublier.',
  },
]

export function productById(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id)
}

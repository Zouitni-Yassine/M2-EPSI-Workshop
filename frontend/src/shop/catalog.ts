import type { Cents } from '../payments/domain/types'

export type Category = 'salon' | 'chambre' | 'luminaires'

export const CATEGORIES: { id: Category; label: string; image: string }[] = [
  { id: 'salon', label: 'Salon', image: '/img/dept-salon.jpg' },
  { id: 'chambre', label: 'Chambre', image: '/img/dept-chambre.jpg' },
  { id: 'luminaires', label: 'Luminaires', image: '/img/dept-luminaires.jpg' },
]

export interface Product {
  id: string
  name: string
  /** Éditeur fictif, affiché au-dessus du nom comme chez les revendeurs. */
  maker: string
  category: Category
  /** Matière et dimension, affichées sous le nom. */
  detail: string
  price: Cents
  /** Prix barré : la différence s'affiche comme une remise. */
  compareAt?: Cents
  badge?: 'Nouveau' | 'Tendance' | 'Promo'
  image: string
  /** Cadrage du recadrage 4:5 (object-position CSS), quand le sujet n'est pas centré. */
  pos?: string
  /** Une phrase pour la fiche produit. */
  story: string
}

export const PRODUCTS: Product[] = [
  {
    id: 'canape-aalto',
    name: 'Canapé Aalto',
    maker: 'Atelier Nord',
    category: 'salon',
    detail: 'Cuir fauve pleine fleur · L 228 cm',
    price: 129_900,
    badge: 'Tendance',
    image: '/img/p-aalto.jpg',
    story: 'Un cuir fauve qui se patine avec les années, tendu sur une assise ferme et profonde.',
  },
  {
    id: 'canape-monceau',
    name: 'Canapé Monceau',
    maker: 'Maison Loir',
    category: 'salon',
    detail: 'Velours sapin, 3 places · L 214 cm',
    price: 114_900,
    image: '/img/p-monceau.jpg',
    story: 'Le velours profond et les pieds compas : une silhouette des années 50, remise à l’échelle d’aujourd’hui.',
  },
  {
    id: 'fauteuil-soleil',
    name: 'Fauteuil Soleil',
    maker: 'Maison Loir',
    category: 'salon',
    detail: 'Velours ocre, dossier haut · L 78 cm',
    price: 64_900,
    compareAt: 74_900,
    badge: 'Promo',
    image: '/img/p-soleil.jpg',
    story: 'Une touche d’ocre qui réchauffe la pièce entière, à côté d’un lampadaire en laiton.',
  },
  {
    id: 'chaise-brume',
    name: 'Chaise Brume',
    maker: 'Atelier Nord',
    category: 'salon',
    detail: 'Laine grise, piètement hêtre · H 92 cm',
    price: 18_900,
    image: '/img/p-brume.jpg',
    story: 'Un dossier galbé qui tient le dos, une laine chinée qui pardonne tout.',
  },
  {
    id: 'chaise-ore',
    pos: 'center 72%',
    name: 'Chaise Öre',
    maker: 'Studio Öre',
    category: 'salon',
    detail: 'Coque noire, assise cuir · H 81 cm',
    price: 14_900,
    badge: 'Nouveau',
    image: '/img/p-ore.jpg',
    story: 'La coque nordique classique, posée sur un chêne clair : simple, stable, infatigable.',
  },
  {
    id: 'table-carbone',
    pos: 'center 62%',
    name: 'Table Carbone',
    maker: 'Studio Öre',
    category: 'salon',
    detail: 'Chêne teinté noir · L 220 cm',
    price: 79_900,
    image: '/img/p-carbone.jpg',
    story: 'Huit couverts sur un plateau noir mat qui absorbe la lumière et met la table en scène.',
  },
  {
    id: 'lit-velours',
    pos: 'center 28%',
    name: 'Lit Velours',
    maker: 'Maison Loir',
    category: 'chambre',
    detail: 'Tête capitonnée, 160 × 200 cm',
    price: 89_900,
    badge: 'Tendance',
    image: '/img/p-velours.jpg',
    story: 'Une tête de lit matelassée du sol au plafond, pour les chambres qui assument le soir.',
  },
  {
    id: 'parure-brume',
    name: 'Parure Brume',
    maker: 'Atelier Nord',
    category: 'chambre',
    detail: 'Lin lavé, housse + 2 taies · 240 × 220 cm',
    price: 8_900,
    image: '/img/p-parure.jpg',
    story: 'Un lin lavé qui se froisse juste ce qu’il faut, et s’adoucit à chaque lavage.',
  },
  {
    id: 'lampadaire-orne',
    pos: '32% 45%',
    name: 'Lampadaire Orne',
    maker: 'Studio Öre',
    category: 'luminaires',
    detail: 'Acier noir, bras orientable · H 168 cm',
    price: 25_900,
    image: '/img/p-orne.jpg',
    story: 'Un grand bras articulé qui penche la lumière exactement là où on lit.',
  },
  {
    id: 'suspension-laiton',
    name: 'Suspension Laiton',
    maker: 'Maison Loir',
    category: 'luminaires',
    detail: 'Laiton brossé, 6 branches · Ø 92 cm',
    price: 22_900,
    compareAt: 26_900,
    badge: 'Promo',
    image: '/img/p-laiton.jpg',
    story: 'Six branches de laiton qui dessinent un lustre contemporain, sans un gramme de nostalgie.',
  },
  {
    id: 'lampe-arche',
    name: 'Lampe Arche',
    maker: 'Atelier Nord',
    category: 'luminaires',
    detail: 'Arc acier blanc, socle marbre · H 196 cm',
    price: 19_900,
    image: '/img/p-arche.jpg',
    story: 'L’arc classique en blanc cassé : elle enjambe le canapé et éclaire sans encombrer.',
  },
]

export function productById(id: string): Product | undefined {
  return PRODUCTS.find((p) => p.id === id)
}

# Resilience Pay — frontend

Trois vues dans une seule application React + Tailwind, derrière une page de connexion :

| Vue | Rôle | Accès |
| --- | --- | --- |
| **Paiement** | Le tunnel de paiement par carte, branché sur Stripe en mode test | client, opérateur |
| **Transactions** | Le journal : ses propres paiements pour un client ; tout le compte marchand, solde et client de chaque paiement pour un opérateur | client, opérateur |
| **Supervision** | Le dashboard que le jury regarde pendant l'attaque et la reprise | opérateur |

La connexion passe par le service `auth/` (`VITE_AUTH_URL`). Le jeton est gardé dans le
`sessionStorage` de l'onglet et joint à chaque appel de l'API (`src/auth/session.ts`) ; un
`401` ou l'expiration ramène à la page de connexion avec le motif. Masquer un onglet ne protège
rien : c'est l'API qui refuse.

## Démarrer

```bash
cd frontend
npm install
cp .env.example .env        # renseigner VITE_STRIPE_PUBLISHABLE_KEY
npm run dev                 # http://localhost:5173
```

Le service d'authentification doit tourner pour se connecter (voir `auth/README.md`).
Le backend doit tourner à côté (voir `backend/README.md`), sinon le tunnel bascule en
**simulation locale** et l'affiche clairement dans une bannière.

## Paiement : Stripe en mode test

Au démarrage, le front appelle `GET /api/health`. Si le backend répond avec une clé Stripe,
le tunnel passe par Stripe, selon `VITE_CARD_ENTRY` :

| Mode | Champs carte | Comment le numéro arrive à Stripe | Usage |
| --- | --- | --- | --- |
| `own` (défaut) | les nôtres — la carte à l'écran se remplit au fil de la saisie | il n'y arrive **jamais** : le backend le remplace par le jeton de test Stripe correspondant (`pm_card_visa`, …) | démonstration, cartes de test uniquement |
| `elements` | iframes Stripe Elements | directement, depuis l'iframe, sans passer par notre code | voie de production |

Dans les deux modes, c'est Stripe qui ouvre sa propre fenêtre 3-D Secure quand l'émetteur
l'exige (`handleNextAction` en mode `own`). Le mode `own` ne peut fonctionner qu'avec des
cartes de test, par construction : un numéro inconnu de la table des jetons est refusé avant
tout appel à Stripe.

Cartes de test Stripe, date future, cryptogramme à 3 chiffres (4 pour Amex) :

| Numéro | Résultat |
| --- | --- |
| `4242 4242 4242 4242` | Visa acceptée |
| `5555 5555 5555 4444` | Mastercard acceptée |
| `3782 822463 10005` | American Express acceptée |
| `4000 0025 0000 3155` | 3-D Secure — fenêtre Stripe, bouton **Complete / Terminer** |
| `4000 0000 0000 9995` | Refus : provision insuffisante |
| `4000 0000 0000 0002` | Refus émetteur |
| `4000 0000 0000 0069` | Carte expirée |
| `4000 0000 0000 0127` | Cryptogramme incorrect |
| `4000 0000 0000 0119` | Erreur de traitement |
| `4100 0000 0000 0019` | Bloquée par le contrôle de fraude |

Aucune donnée bancaire réelle n'est acceptée : le compte Stripe est en mode test.

### Filet de sécurité hors ligne

Si le backend ou Internet ne répond pas, le front se rabat sur `localEngine`, qui reproduit
la même sémantique (mêmes cartes, mêmes statuts, mêmes codes de refus) sans réseau, et le
dit dans une bannière « Mode hors ligne ». Dans ce mode seulement, le 3-D Secure est simulé
par notre propre fenêtre avec le code `1234`.

## Paiement : PayPal en sandbox

Quand `VITE_PAYPAL_CLIENT_ID` est renseigné **et** que `GET /api/health` répond `"paypal": true`,
un panneau **Payer avec PayPal** s'affiche au-dessus du formulaire carte. Il s'ajoute au moteur
carte, qu'il s'agisse de Stripe ou de la simulation locale.

1. Le bouton vient du SDK JS v6 de PayPal (`@paypal/react-paypal-js/sdk-v6`), chargé avec
   `environment="sandbox"` en dur.
2. Au clic, le front demande au backend de créer la commande (`POST /api/paypal/orders`).
3. Le payeur se connecte dans la fenêtre PayPal avec un **compte acheteur sandbox**
   (developer.paypal.com > Testing Tools > Sandbox Accounts, compte *Personal*).
4. Après approbation, le backend capture (`POST /api/paypal/orders/:id/capture`). Le stepper
   avance, le reçu et l'onglet Transactions affichent le paiement avec la marque PayPal.

Sans Internet, le panneau indique que PayPal n'a pas pu être chargé : le paiement par carte
reste disponible.

> Le paiement PayPal exige un clic humain dans la fenêtre PayPal. Il ne peut donc pas servir
> de transaction de contrôle automatique après la remédiation : le canary reste sur la carte.

## Un contrat, deux moteurs (et PayPal à côté)

| Contrat | Fichier | Implémentations |
| --- | --- | --- |
| `PaymentEngine` | `src/payments/domain/types.ts` | `engine/stripeEngine.ts` (backend + Stripe.js), `engine/localEngine.ts` (hors ligne) |
| `PayPalCheckout` | `src/payments/engine/paypalCheckout.ts` | Commandes PayPal via le backend ; renvoie le même `PaymentIntent` avec `method: 'paypal'` |
| `DataSource` (supervision) | `src/types.ts` | `data/liveSource.ts` (WebSocket), `data/mockSource.ts` (scénario) |

Les composants ne savent pas quel moteur tourne. Le choix se fait une fois par session
dans `engine/index.ts`.

```bash
# .env
VITE_API_URL=http://localhost:8000/api
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_xxx
VITE_PAYPAL_CLIENT_ID=...      # client ID de l'app PayPal sandbox (facultatif)
VITE_DATA_SOURCE=mock          # ou live, avec VITE_WS_URL
```

## Supervision : répéter une phase précise

`?t=<seconde>` démarre le scénario à un instant donné, historique reconstitué :

| URL | Ce qu'on voit |
| --- | --- |
| `?t=16` | Nominal, juste avant l'attaque |
| `?t=22` | Dégradation en cours, pas encore détectée |
| `?t=27` | Remédiation en cours |
| `?t=44` | Service rétabli, incident visible dans l'historique |

## Partis pris

**Le stepper montre le trajet réel d'un paiement.** Autorisation, authentification forte,
capture, compensation — l'étape qui échoue vire au rouge, avec le vrai `decline_code` Stripe.

**Le ruban de transactions du dashboard est la preuve de reprise.** Une barre par tentative
du canary, verte si elle aboutit, rouge sinon. Le sujet est explicite : un conteneur qui
redémarre ne prouve rien.

**Le compteur d'interventions humaines reste à zéro, en permanence.** Et le type
`TimelineEvent` n'autorise que `attaquant` et `plateforme` comme acteurs.

**Une panne ne laisse jamais l'écran muet.** Backend injoignable, Stripe qui refuse,
réseau coupé : chaque cas produit un message précis, à l'endroit où l'utilisateur regarde.

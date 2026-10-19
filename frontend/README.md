# Resilience Pay — frontend

Deux surfaces dans une seule application React + Tailwind :

| Vue | Rôle | Thème |
| --- | --- | --- |
| **Paiement** / **Transactions** | La plateforme de paiement fictive que le canary sollicite et que l'attaque vise | Clair |
| **Supervision** | Le dashboard que le jury regarde pendant l'attaque et la reprise | Sombre (écran mural) |

## Démarrer

```bash
npm install
npm run dev        # http://localhost:5173
```

Par défaut tout tourne hors ligne sur des moteurs locaux : aucun backend n'est requis.

## Paiement : cartes de test

La plateforme reproduit la sémantique Stripe en local. Saisissez n'importe quelle
carte de test Stripe, expiration future, cryptogramme à 3 chiffres (4 pour Amex) :

| Numéro | Résultat |
| --- | --- |
| `4242 4242 4242 4242` | Visa acceptée |
| `5555 5555 5555 4444` | Mastercard acceptée |
| `3782 822463 10005` | American Express acceptée |
| `4000 0025 0000 3155` | 3-D Secure — **code de confirmation `1234`** |
| `4000 0000 0000 9995` | Refus : provision insuffisante |
| `4000 0000 0000 0002` | Refus émetteur |
| `4000 0000 0000 0069` | Carte expirée |
| `4000 0000 0000 0127` | Cryptogramme incorrect |
| `4000 0000 0000 0119` | Erreur de traitement |
| `4100 0000 0000 0019` | Bloquée par le contrôle de fraude |

Tout autre numéro valide au sens de Luhn est refusé (`card_declined`). Aucune
donnée bancaire réelle n'est acceptée ni stockée.

## Deux sources, un contrat

Les composants ne connaissent que deux interfaces, et ne savent pas si les données
viennent d'une simulation locale ou du backend :

| Contrat | Fichier | Mode `mock` / local | Mode `live` |
| --- | --- | --- | --- |
| `PaymentEngine` | `src/payments/domain/types.ts` | `engine/localEngine.ts` | `engine/apiEngine.ts` → API FastAPI |
| `DataSource` (supervision) | `src/types.ts` | `data/mockSource.ts` | `data/liveSource.ts` → WebSocket |

Bascule par variables d'environnement, sans toucher aux composants :

```bash
cp .env.example .env
# VITE_DATA_SOURCE=live
# VITE_API_URL=http://192.168.137.1:8080/api
# VITE_WS_URL=ws://192.168.137.1:8080/ws/state
```

### Ce que le backend paiement doit exposer

| Route | Corps | Réponse |
| --- | --- | --- |
| `POST /payment_intents` | `{ amount, card: { brand, last4, holder } }` | `PaymentIntent` |
| `POST /payment_intents/:id/confirm` | `{ card: CardInput }` | `PaymentIntent` |
| `POST /payment_intents/:id/authenticate` | `{ code }` | `PaymentIntent` |
| `GET /payment_intents` | — | `PaymentIntent[]` |
| `GET /balance` | — | `Balance` |

Le type `PaymentIntent` fait foi : statut Stripe (`requires_confirmation`,
`requires_action`, `processing`, `succeeded`, `canceled`), code de refus Stripe,
clé d'idempotence, et le `rail` — l'état des quatre étapes Autorisation /
3-D Secure / Capture / Compensation que le stepper affiche.

## Supervision : répéter une phase précise

`?t=<seconde>` démarre le scénario à un instant donné, historique reconstitué :

| URL | Ce qu'on voit |
| --- | --- |
| `?t=16` | Nominal, juste avant l'attaque |
| `?t=22` | Dégradation en cours, pas encore détectée |
| `?t=27` | Remédiation en cours |
| `?t=44` | Service rétabli, incident visible dans l'historique |

## Partis pris

**Hors ligne par construction.** Le jour du jury la plateforme tourne sur un
hotspot Windows sans garantie de sortie Internet. Rien ne dépend de l'API Stripe.

**Le stepper montre le trajet réel d'un paiement.** Autorisation, authentification
forte, capture, compensation : l'étape qui échoue vire au rouge. Un bouton qui
tourne cacherait le mécanisme ; un jury qui évalue une plateforme de paiement veut le voir.

**Le ruban de transactions du dashboard est la preuve de reprise.** Une barre par
tentative du canary, verte si elle aboutit, rouge sinon. Le sujet est explicite :
un conteneur qui redémarre ne prouve rien.

**Le compteur d'interventions humaines reste à zéro, en permanence.** Et le type
`TimelineEvent` n'autorise que `attaquant` et `plateforme` comme acteurs.

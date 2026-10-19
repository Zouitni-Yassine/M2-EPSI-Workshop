# Resilience Pay — frontend

Trois vues dans une seule application React + Tailwind :

| Vue | Rôle |
| --- | --- |
| **Paiement** | Le tunnel de paiement par carte, branché sur Stripe en mode test |
| **Transactions** | Le journal du compte marchand : solde, paiements, détail de chaque machine à états |
| **Supervision** | Le dashboard que le jury regarde pendant l'attaque et la reprise |

## Démarrer

```bash
cd frontend
npm install
cp .env.example .env        # renseigner VITE_STRIPE_PUBLISHABLE_KEY
npm run dev                 # http://localhost:5173
```

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

## Un contrat, deux moteurs

| Contrat | Fichier | Implémentations |
| --- | --- | --- |
| `PaymentEngine` | `src/payments/domain/types.ts` | `engine/stripeEngine.ts` (backend + Stripe.js), `engine/localEngine.ts` (hors ligne) |
| `DataSource` (supervision) | `src/types.ts` | `data/liveSource.ts` (WebSocket), `data/mockSource.ts` (scénario) |

Les composants ne savent pas quel moteur tourne. Le choix se fait une fois par session
dans `engine/index.ts`.

```bash
# .env
VITE_API_URL=http://localhost:8000/api
VITE_STRIPE_PUBLISHABLE_KEY=pk_test_xxx
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

# Resilience Pay — API de paiement

Service FastAPI qui porte la clé secrète Stripe et sert au frontend une vue
normalisée de chaque paiement. C'est le conteneur `payment-api` du démonstrateur :
celui que le canary teste et que l'attaque vise.

## Démarrer

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
cp .env.example .env                                 # puis renseigner STRIPE_SECRET_KEY
uvicorn app.main:app --reload --port 8000
```

`GET http://localhost:8000/api/health` doit répondre `{"ok": true, "stripe": true, "mode": "test"}`.

## Routes

| Route | Accès | Rôle |
| --- | --- | --- |
| `GET /api/health` | ouvert | Le frontend l'appelle au démarrage pour choisir Stripe ou la simulation locale |
| `GET /api/status` | ouvert | Sonde lue chaque seconde par le détecteur, le moteur de remédiation et le canary |
| `POST /api/payment_intents` | connecté | Crée un `PaymentIntent` chez Stripe au nom de l'utilisateur, renvoie le `clientSecret` |
| `GET /api/payment_intents/:id` | propriétaire ou opérateur | Relit le paiement après confirmation : statut, réseau, 4 derniers chiffres, refus |
| `GET /api/payment_intents` | connecté | Les 25 derniers paiements : les siens pour un client, tous pour un opérateur |
| `GET /api/balance` | opérateur | Solde Stripe (disponible / en attente) |
| `POST /api/paypal/orders` | connecté | Crée une commande PayPal sandbox (`{"amount": centimes}`) |
| `POST /api/paypal/orders/:id/capture` | propriétaire ou opérateur | Capture après approbation du payeur dans la fenêtre PayPal |
| `GET /api/paypal/orders/:id` | propriétaire ou opérateur | Relit une commande PayPal |
| `GET /api/paypal/orders` | connecté | Les 25 dernières commandes PayPal de ce conteneur, filtrées comme les paiements |

**Accès.** Les routes protégées attendent `Authorization: Bearer <jeton>`, délivré par le
service d'authentification (`auth/`, `POST /auth/login`). L'API vérifie le jeton elle-même avec
la clé publique de `AUTH_URL/auth/jwks.json`, chargée une fois puis gardée en mémoire
(`app/security.py`). Chaque paiement porte son propriétaire : en métadonnée chez Stripe, dans le
`custom_id` chez PayPal. Un client qui demande le paiement d'un autre reçoit `404`, pas `403` :
on ne lui confirme même pas qu'il existe.

La réponse suit exactement le type `PaymentIntent` de `frontend/src/payments/domain/types.ts`
— y compris le `rail` (Autorisation / 3-D Secure / Capture / Compensation) et le code de refus
Stripe (`insufficient_funds`, `card_declined`…).

## PayPal sandbox

Le module `app/paypal.py` parle à l'API Orders v2 de PayPal. Il rend chaque commande sous la
même forme `PaymentIntent` que Stripe, avec `"method": "paypal"`.

**Mise en place (une fois, par la personne qui gère le compte) :**

1. Se connecter sur [developer.paypal.com](https://developer.paypal.com/dashboard/), onglet **Sandbox**.
2. **Apps & Credentials > Create App** (type *Merchant*), puis copier le *Client ID* et le *Secret*.
3. Les mettre dans `backend/.env` (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`) et le client ID
   seul dans `frontend/.env` (`VITE_PAYPAL_CLIENT_ID`).
4. **Testing Tools > Sandbox Accounts** : le compte *Personal* sert de payeur dans la fenêtre
   PayPal (*View/Edit account* donne son mot de passe).

`GET /api/health` doit alors répondre `"paypal": true`, et `GET /api/status` expose
`paypal.up` pour la supervision.

**Garde-fous :**

- L'URL de l'API est figée sur `api-m.sandbox.paypal.com` : même un identifiant live collé
  par erreur ne déclenche aucun paiement réel.
- `PAYPAL_MAX_RPS` (5 par défaut) plafonne les appels sortants. Une attaque sur payment-api
  reçoit des 429 au lieu de rebondir sur PayPal, qui est un service tiers hors périmètre.
- Une seconde capture de la même commande ne double pas le paiement : PayPal répond
  `ORDER_ALREADY_CAPTURED` et l'API relit la commande.
- Si PayPal ne répond pas pendant la capture, l'API relit la commande au lieu d'annoncer
  un refus.

**Limite connue :** PayPal n'expose pas d'API pour lister les commandes. Le journal PayPal est
donc tenu en mémoire et se vide au redémarrage du conteneur. Il faudra le brancher sur la base
de données du SI.

## Journal des paiements (PostgreSQL)

Stripe et PayPal restent la source de vérité de l'argent ; la table `payments` garde notre vue
(propriétaire, dernier état connu, de quoi afficher le journal) dans `app/store.py`.

| Situation | Comportement |
| --- | --- |
| Paiement créé, confirmé, relu ou capturé | Écrit en base (création ou mise à jour), sans `clientSecret` |
| `GET /api/payment_intents`, `GET /api/paypal/orders` | Lus en base, filtrés par propriétaire |
| payment-api redémarré par la remédiation | Journal intact : il est en base, plus en mémoire |
| Base en panne | Les paiements passent, l'écriture est sautée et journalisée ; le journal Stripe est relu chez Stripe, celui de PayPal répond `503` |
| Base de retour (ou démarrage) | Réconciliation : les 100 derniers paiements Stripe sont rejoués en base |

Une sonde interroge la base toutes les deux secondes en tâche de fond ; `/api/status` et
`/api/health` exposent `db` sans jamais attendre la base, pour qu'une base lente ne fasse
pas passer l'API pour morte aux yeux du détecteur. `/api/health` reste à `200` quand la base
tombe : redémarrer l'API ne la réparerait pas.

`DATABASE_URL` choisit la base (SQLite `./data/payments.db` par défaut hors Docker), le mot de
passe vient de `DB_PASSWORD` ou du fichier `DB_PASSWORD_FILE`, jamais de l'URL.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Les tests PayPal tournent contre un faux PayPal (`httpx.MockTransport`) : aucun appel réseau
et aucun identifiant réel. `test_security.py` fait de même avec un faux service
d'authentification : jeton expiré, mauvaise audience, autre clé, HS256 forgé, rôle inconnu.
Chaque test a sa base SQLite jetable (`tests/conftest.py`), avec le même code SQLAlchemy que
PostgreSQL ; `test_store.py` couvre la panne de la base et la réconciliation.

## Secrets

`STRIPE_SECRET_KEY`, `PAYPAL_CLIENT_ID` et `PAYPAL_CLIENT_SECRET` ne sont lus que depuis
l'environnement. Jamais dans le code, jamais dans l'archive. Dans le démonstrateur, ils arrivent
par Vault ou SOPS via `docker-compose`. Pour PayPal, `PAYPAL_CLIENT_SECRET_FILE` permet aussi
de lire le secret depuis un fichier (secret Docker, rendu Vault Agent, sortie SOPS).

## Docker

```bash
docker build -t resilience/payment-api .
docker run --rm -p 8000:8000 --env-file .env resilience/payment-api
```

Le conteneur tourne sans privilège et expose un `HEALTHCHECK` sur `/api/health`.

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

| Route | Rôle |
| --- | --- |
| `GET /api/health` | Le frontend l'appelle au démarrage pour choisir Stripe ou la simulation locale |
| `POST /api/payment_intents` | Crée un `PaymentIntent` chez Stripe, renvoie le `clientSecret` |
| `GET /api/payment_intents/:id` | Relit le paiement après confirmation : statut, réseau, 4 derniers chiffres, refus |
| `GET /api/payment_intents` | Les 25 derniers paiements, pour l'onglet Transactions |
| `GET /api/balance` | Solde Stripe (disponible / en attente) |
| `POST /api/paypal/orders` | Crée une commande PayPal sandbox (`{"amount": centimes}`) |
| `POST /api/paypal/orders/:id/capture` | Capture après approbation du payeur dans la fenêtre PayPal |
| `GET /api/paypal/orders/:id` | Relit une commande PayPal |
| `GET /api/paypal/orders` | Les 25 dernières commandes PayPal de ce conteneur |

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

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Les tests PayPal tournent contre un faux PayPal (`httpx.MockTransport`) : aucun appel réseau
et aucun identifiant réel.

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

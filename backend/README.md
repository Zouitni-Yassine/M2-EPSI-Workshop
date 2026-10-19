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

La réponse suit exactement le type `PaymentIntent` de `frontend/src/payments/domain/types.ts`
— y compris le `rail` (Autorisation / 3-D Secure / Capture / Compensation) et le code de refus
Stripe (`insufficient_funds`, `card_declined`…).

## Secrets

`STRIPE_SECRET_KEY` n'est lue que depuis l'environnement. Jamais dans le code, jamais
dans l'archive. Dans le démonstrateur elle arrive par Vault ou SOPS via `docker-compose`.

## Docker

```bash
docker build -t resilience/payment-api .
docker run --rm -p 8000:8000 --env-file .env resilience/payment-api
```

Le conteneur tourne sans privilège et expose un `HEALTHCHECK` sur `/api/health`.

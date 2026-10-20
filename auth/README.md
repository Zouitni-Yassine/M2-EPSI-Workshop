# Resilience Pay — authentification

Service FastAPI qui vérifie un identifiant et un mot de passe, puis délivre un jeton
signé (JWT Ed25519) portant le rôle de l'utilisateur : `client` ou `operator`.

## Démarrer

```bash
cd auth
pip install -r requirements.txt
cp .env.example .env        # renseigner AUTH_PASSWORD_OPERATEUR et AUTH_PASSWORD_CLIENT
uvicorn app.main:app --port 8300
```

`GET http://localhost:8300/health` → `{"ok": true, "db": true}`.

## Routes

| Route | Usage |
| --- | --- |
| `POST /auth/login` | `{"username", "password"}` → `{"token", "expiresAt", "user": {"username", "role"}}` |
| `GET /auth/me` | Relit l'utilisateur du jeton (`Authorization: Bearer …`), en vérifiant qu'il n'est pas désactivé |
| `GET /auth/jwks.json` | Clé publique de signature, pour que les autres services vérifient les jetons eux-mêmes |
| `GET /metrics` | `auth_login_total{result="success\|failure\|locked"}` au format Prometheus |
| `GET /health` | Vérifie la base |

## Rôles

| Rôle | Paiement | Transactions | Solde marchand | Supervision |
| --- | --- | --- | --- | --- |
| `client` | oui | les siennes | non | non |
| `operator` | oui | toutes | oui | oui |

## Choix de sécurité

- **Signature asymétrique (Ed25519).** La clé privée ne quitte pas ce service.
  `payment-api` récupère la clé publique et vérifie chaque jeton localement : compromis, il
  ne peut pas fabriquer un jeton d'opérateur. Si ce service tombe, les sessions ouvertes
  continuent de fonctionner.
- **Algorithme figé.** Un jeton `alg: none`, ou HS256 signé avec la clé publique, est refusé.
- **Mots de passe en argon2id**, jamais stockés ni journalisés en clair. Un identifiant
  inconnu prend le même temps qu'un mauvais mot de passe et reçoit la même réponse : on ne
  peut pas deviner quels comptes existent.
- **Force brute freinée.** Après 5 échecs en 5 minutes depuis une même adresse sur un même
  identifiant, ou 20 échecs depuis une adresse tous identifiants confondus, réponse `429`
  sans vérifier le mot de passe. Le blocage porte sur l'adresse, pas sur le compte : un
  attaquant ne peut pas enfermer l'opérateur dehors.
- **Traces exploitables.** Chaque tentative est une ligne JSON sur stdout (Loki, SIEM) et un
  compteur Prometheus. C'est le signal d'une attaque par force brute.
- **Aucun compte par défaut.** Un compte de démonstration n'est créé que si son mot de passe
  (8 caractères minimum) est fourni.

## Comptes

Les comptes de `AUTH_SEED_USERS` sont créés ou mis à jour à chaque démarrage. Pour en ajouter
un à la main :

```bash
python -m app.users add alice client          # en local
docker compose exec -it auth python -m app.users add alice client
python -m app.users list
```

## Données

Sous Docker (compose ou Swarm), le service est **sans état** :

- comptes dans PostgreSQL, base `auth` (`DATABASE_URL`, mot de passe dans `DB_PASSWORD_FILE`) ;
- clé de signature en secret Docker (`JWT_PRIVATE_KEY_FILE`), créée par
  `scripts/init-secrets.py`. Toutes les réplicas signent avec la même clé : un jeton émis par
  l'une est vérifiable partout, et un redémarrage ne déconnecte personne.

Au démarrage, le service attend la base jusqu'à une minute (Swarm ne garantit aucun ordre).
Lancé seul, sans ces variables, il retombe sur SQLite et une clé générée dans `AUTH_DATA_DIR`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

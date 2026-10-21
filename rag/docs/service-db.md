# Resilience Pay — base de données

PostgreSQL 16, une instance pour le SI, **une base et un rôle par service** :

| Base | Rôle | Service | Contenu |
| --- | --- | --- | --- |
| `auth` | `auth` | `auth/` | comptes, rôles, hachés argon2id |
| `payments` | `payments` | `backend/` | journal des paiements Stripe et PayPal |

Chaque rôle ne peut ouvrir que sa base (`REVOKE ALL … FROM PUBLIC`) : un `payment-api`
compromis ne lit pas les mots de passe, un `auth` compromis ne lit pas les paiements.
Les rôles et les bases sont créés par [`init/01-roles.sh`](init/01-roles.sh), une seule fois,
quand le volume `db-data` est vide.

## Mise en place

```bash
python scripts/init-secrets.py   # crée secrets/*.txt et la clé de signature, sans rien écraser
docker compose up --build
```

Les mots de passe arrivent en **secrets Docker** (`/run/secrets/…`), jamais en variable
d'environnement ni dans l'URL : les services lisent `DB_PASSWORD_FILE`. En production,
les fichiers de `secrets/` sont produits par Vault ou SOPS.

## Exposition

Aucun port publié. La base est seule sur le réseau `data`, interne (pas d'accès sortant) ;
seuls `auth` et `payment-api` y sont aussi attachés.

## Opérations

```bash
docker compose exec db psql -U postgres -d payments -c "select id, owner, status, amount from payments order by created_at desc limit 10"
docker compose exec db psql -U postgres -d auth -c "select username, role, disabled from users"
docker compose down -v           # repart de zéro : base, rôles et mots de passe réinitialisés
```

Changer un mot de passe dans `secrets/` après le premier démarrage impose `down -v` : les
rôles ne sont créés qu'à l'initialisation du volume.

## Swarm

Même fichier `docker-compose.yml` (secrets et config `db_init` déclarés en `file:`). Le volume
est local au nœud : épingler le service sur un nœud (contrainte de placement) ou utiliser un
volume partagé, sinon la base repart vide si elle change de nœud.

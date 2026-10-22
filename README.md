# M2 EPSI Workshop — Project RESILIENCE-ALPHA

Démonstrateur de cyber-résilience : une plateforme de paiement qui détecte une
anomalie et se répare seule, sans intervention humaine.

```
                 seul port publié (:5173)
navigateur ──► frontend : nginx, relais ──/auth/──► auth (jetons Ed25519, cookie httpOnly) ──┐
                    │                    ──/api/───► payment-api ──► PostgreSQL (réseau interne)
                    │ supervision (opérateurs)            ▲    └──► Stripe (test), PayPal (sandbox)
                    ▼                                     │ redémarrage, via proxy Docker à droits réduits
               detector (IsolationForest) ──► remediation (décide, agit, vérifie)
```

| Dossier | Rôle | Doc |
| --- | --- | --- |
| `frontend/` | Boutique, connexion, paiement, journal, supervision ; son nginx est le relais unique | [README](frontend/README.md) |
| `auth/` | Comptes, rôles client / opérateur, jetons signés, freinage de la force brute | [README](auth/README.md) |
| `backend/` | API de paiement, porte la clé Stripe, vérifie les jetons, journal en base, expose métriques et sonde | [README](backend/README.md) |
| `db/` | PostgreSQL : une base et un rôle par service, secrets Docker | [README](db/README.md) |
| `detector/` | Score d'anomalie chaque seconde, appris sur le trafic normal | [README](detector/README.md) |
| Mailpit | Boîte mail de démonstration (réinitialisation de mot de passe), UI sur `http://localhost:8025` | — |
| `remediation/` | Écoute le verdict, redémarre la cible, vérifie la reprise | [README](remediation/README.md) |
| `redteam/` | Tests WAF/SOC et stimuli applicatifs bornés depuis le PC attaquant | [Guide de démarrage](redteam/README.md) |

## Lancer le démonstrateur

```bash
# 1. Secrets, jamais commités
python scripts/init-secrets.py               # mots de passe PostgreSQL, clé de signature des jetons (secrets/)
cp backend/.env.example backend/.env         # STRIPE_SECRET_KEY, PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET
cp auth/.env.example auth/.env               # AUTH_PASSWORD_OPERATEUR, AUTH_PASSWORD_CLIENT (8 caractères min.)
cp detector/.env.example detector/.env       # DETECTOR_ADMIN_TOKEN
echo "VITE_STRIPE_PUBLISHABLE_KEY=pk_test_..." > .env
echo "VITE_PAYPAL_CLIENT_ID=..." >> .env     # facultatif : même client ID que dans backend/.env

# 2. Tout monter
docker compose up --build -d

# 3. Tout arrêter : « down », pas « stop » — les services redémarreraient au prochain lancement de Docker
docker compose down
```

Puis http://localhost:5173 — ou `http://<ip-de-l'hôte>:5173` depuis une autre machine, par exemple
`http://192.168.137.1:5173` sur le point d'accès —, connexion avec `operateur` (accès à la
supervision) ou `client` (boutique). Le détecteur apprend la normale pendant `WARMUP_SECONDS`
(60 par défaut, réglable dans `.env`) avant de scorer.

## Déployer sur le Swarm

Le même `docker-compose.yml` sert au Swarm et suit le
[contrat de déploiement](infra/docs/contrat-deploiement.md) : image à tag figé pour chaque
service, secrets et configs Docker, conteneurs en lecture seule avec `tmpfs`, section `deploy`
(ressources, politique de redémarrage, retour arrière), aucun `depends_on`.

```bash
export REGISTRY=ghcr.io/<org>                 # registre joignable par tous les nœuds
docker compose build
docker compose push auth payment-api detector remediation frontend
PAYMENT_API_RESTART=on-failure DOCKER_SOCKET_PROXY_REPLICAS=0 \
  docker stack deploy -c docker-compose.yml paiement
```

| Variable | Local (défaut) | Swarm | Pourquoi |
| --- | --- | --- | --- |
| `PAYMENT_API_RESTART` | `none` | `on-failure` | En local, seule la remédiation relance l'API : c'est la démo. Sur le Swarm, un crash est relancé, un arrêt volontaire reste à la remédiation. |
| `DOCKER_SOCKET_PROXY_REPLICAS` | `1` | `0` | Le contrat interdit de monter `docker.sock` ; sur le Swarm, le moteur passe par la passerelle SSH (`infra/docs/remediation.md`). |

Reste à faire pour une démo sur le Swarm : brancher le moteur de remédiation sur la passerelle
SSH, épingler la base sur un nœud. Publier le frontal en mode `host` pour que le relais voie
l'adresse réelle des clients (le maillage de routage la masque).

## Rejouer la séquence de résilience

1. Onglet **Supervision** : bandeau vert, score d'anomalie bas.
2. Provoquer l'incident — par exemple arrêter le conteneur visé depuis le PC attaquant.
3. En quelques secondes : barres rouges, score qui franchit le seuil, « anomalie confirmée ».
4. Le bandeau passe au **bleu** : le moteur de remédiation redémarre `payment-api`.
5. Transaction de contrôle passée, bandeau **vert**, « Service rétabli en N s — 0 intervention humaine ».

Pendant toute la séquence, personne ne touche au clavier. C'est le point que le jury note.

## Séquence mesurée pendant le développement

Panne provoquée par `docker stop payment-api` à 14:35:02, puis plus aucune action humaine :

| Délai | Événement | Acteur |
| --- | --- | --- |
| +12 s | Anomalie confirmée par le détecteur (score 0.78 ≥ 0.55) | détecteur ML |
| +12 s | Décision : recréer payment-api → échec, proxy trop restrictif (403) | moteur |
| +1 min 42 | Deuxième tentative → échec, proxy mal configuré (502), « escalade nécessaire » | moteur |
| +3 min 13 | Troisième tentative : redémarrage via le proxy Docker | moteur |
| +3 min 15 | Transaction de contrôle passée — API et Stripe joignables | moteur |
| +3 min 19 | **Service rétabli en 5 s — 0 intervention humaine** | moteur |

Les deux premiers échecs venaient du proxy Docker, corrigé entre-temps. Le moteur ne les a
pas cachés et n'a pas bouclé : il a attendu sa temporisation et réessayé tant que le verdict
du détecteur persistait. Détecteur seul, avant la distance robuste : une panne totale obtenait
0.50, à la frontière du seuil — voir `detector/README.md`.

## Sécurité vérifiée

Depuis le conteneur du moteur de remédiation, vers le proxy Docker :

| Requête | Réponse |
| --- | --- |
| `GET /containers/json` | 200 |
| `POST /containers/payment-api/restart` | autorisé |
| `POST /containers/create` | 403 |
| `POST /containers/payment-api/exec` | 403 |
| `POST /containers/payment-api/stop` | 403 |
| `POST /containers/detector/restart` | 403 |
| `GET /images/json` | 403 |

- Le proxy (`proxy/nginx.conf`) n'accepte que ces deux requêtes, en lecture seule, sans
  capacité, sur un réseau Docker interne.
- Le moteur n'expose aucune route d'écriture ; seul le verdict du détecteur le déclenche.
- `POST /reset` du détecteur exige un jeton (`DETECTOR_ADMIN_TOKEN`), CORS limité en `GET`.
- Un détecteur injoignable **dégrade** l'état (« Surveillance interrompue ») au lieu de laisser
  le bandeau vert.
- Les clés Stripe ne sont lues que depuis l'environnement ; aucun `.env` n'est commité.
- Paiements et transactions exigent un jeton délivré par `auth/` ; un client ne voit et ne
  confirme que ses paiements, le solde marchand est réservé aux opérateurs. Jetons Ed25519
  vérifiés localement par l'API (algorithme figé), mots de passe en argon2id, `429` après
  5 échecs depuis une adresse. Détail dans [auth/README.md](auth/README.md).
- PostgreSQL n'est joignable que depuis `auth` et `payment-api` (réseau interne, aucun port
  publié) ; une base et un rôle par service, mots de passe en secrets Docker.
- Un seul port publié, le frontal nginx (`frontend/nginx.conf`). Il relaie `/auth/` et `/api/` ;
  `/api/status`, `/detector/score` et `/remediation/state` exigent une session d'opérateur,
  vérifiée par le service d'authentification (`auth_request`). Ni `/metrics`, ni `/reset` du
  détecteur, ni la base, ni le proxy Docker ne sont joignables de l'extérieur.
- La session est un cookie `httpOnly`, `SameSite=Strict` : le JavaScript ne voit jamais le jeton,
  un autre site ne peut pas s'en servir. Les scripts obtiennent un jeton par `POST /auth/token`.

## État par pilier

| Pilier | Fait | Reste à faire |
| --- | --- | --- |
| **DEV** | Tunnel Stripe test, journal en PostgreSQL, dashboard, moteur de remédiation, service d’authentification et rôles, métriques Prometheus et logs JSON | Playbooks supplémentaires (bannir une IP, restaurer la base) |
| **IA** | Détecteur IsolationForest + distance robuste, verdict qui déclenche l'action | Assistant RAG Ollama + LangChain, réapprentissage continu, variables CPU/RAM |
| **INFRA** | `docker compose` complet (db, auth, payment-api compatibles Swarm), proxy Docker à liste blanche | Ansible, Prometheus, Grafana, Loki |
| **CYBER** | Droits du moteur réduits, `/reset` protégé, état dégradé si aveugle | WAF, SIEM/SOC, Vault ou SOPS, scénario d'attaque depuis le PC attaquant |
| **GOUV** | — | EBIOS RM, PCA/PRA, analyse NIS2/DORA |

## Développer sans Docker

Chaque service se lance seul (voir son README). Le frontend fonctionne même sans
backend : il bascule sur une simulation locale et l'affiche.

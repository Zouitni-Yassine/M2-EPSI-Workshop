# Documentation des API : Resilience Pay

Les quatre services Python de la plateforme sont des applications FastAPI. Leur contrat OpenAPI 3.1
est versionné ici, **extrait des conteneurs en production** le 21/10/2026 (stack Swarm `paiement`,
images au commit `4566245`), sans rien modifier dans les conteneurs :

| Service | Version | Fichier OpenAPI | Port interne | Préfixe exposé par le frontal |
|---|---|---|---|---|
| payment-api (`backend/`) | 0.4.0 | [`payment-api.openapi.json`](payment-api.openapi.json) | 8000 | `/api/` |
| auth (`auth/`) | 0.3.0 | [`auth.openapi.json`](auth.openapi.json) | 8300 | `/auth/` |
| detector (`detector/`) | 0.1.0 | [`detector.openapi.json`](detector.openapi.json) | 8100 | `/detector/score` seulement (opérateurs) |
| remediation (`remediation/`) | 0.1.0 | [`remediation.openapi.json`](remediation.openapi.json) | 8200 | `/remediation/state` seulement (opérateurs) |

Les fichiers ne contiennent aucun secret (vérifié : pas d'exemple, seule valeur par défaut, une
chaîne vide pour l'en-tête `x-admin-token` du détecteur). Pour les lire de façon interactive, on
peut les ouvrir dans un visualiseur OpenAPI (Swagger Editor, Redocly) ou utiliser la documentation
Swagger servie par l'application elle-même :

- https://app.slabreze.fr/api/docs (payment-api)
- https://app.slabreze.fr/auth/docs (auth)

Le détecteur et le moteur ont aussi un `/docs` FastAPI, mais le frontal ne le relaie pas. On ne
peut le consulter que depuis le réseau interne de la stack.

**Régénérer les fichiers** (lecture seule, depuis le poste de contrôle) : trouver le nœud de la
tâche (`sudo docker service ps paiement_<service> --filter desired-state=running` sur un manager),
puis lancer sur ce nœud :

```sh
sudo docker exec <conteneur> python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:<port><chemin>').read().decode())"
```

Le chemin vaut `/api/openapi.json` pour payment-api, `/auth/openapi.json` pour auth et
`/openapi.json` pour le détecteur et le moteur. Les deux premiers services publient leur
documentation sous leur préfixe, parce que c'est le seul que le relais leur transmet.

---

## 1. Accès : un seul point d'entrée

```text
client ── https://app.slabreze.fr ──> NPM (TLS public) ──> WAF waf01 (ModSecurity, bannissement)
       ──> adresse virtuelle 10.30.1.200:5173 ──> frontal paiement_frontend (nginx, 3 réplicas)
              /auth/...            ──> auth:8300
              /api/...             ──> payment-api:8000
              /api/status          ──> payment-api:8000   (session opérateur exigée)
              /detector/score      ──> detector:8100/score (session opérateur exigée)
              /remediation/state   ──> remediation:8200/state (session opérateur exigée)
```

- **Base URL publique** : `https://app.slabreze.fr`. Depuis le réseau d'administration, sans NAT
  en épingle : `curl --resolve app.slabreze.fr:443:172.16.1.10 https://app.slabreze.fr/...`.
- **Accès interne, sans WAF** (tests depuis le poste de contrôle) : `http://10.30.1.200:5173`.
  Avec `app_url` en `https://`, le cookie de session porte l'attribut `Secure`. Il n'est alors pas
  renvoyé en HTTP : sur cet accès, utiliser le jeton Bearer (`POST /auth/token`).
- **Ce que le frontal ne relaie pas** : `/metrics` des services (collectés par le vmagent du Swarm
  sur le réseau overlay `monitoring`), `/health` d'auth, du détecteur et du moteur,
  `POST /reset` du détecteur, la base PostgreSQL. Une URL inconnue renvoie la page de
  l'application (`index.html`, code 200) et jamais une donnée interne. Par exemple,
  `https://app.slabreze.fr/metrics` renvoie la page d'accueil.
- **Routes réservées aux opérateurs** (`frontend/nginx.conf`) : `/api/status`,
  `/detector/score` et `/remediation/state` passent par `auth_request` vers
  `GET /auth/verify?role=operator`, avec le verdict gardé 30 s en cache. Seul `GET` est accepté
  (`limit_except GET { deny all; }`). Sans session, le relais répond `401`. Avec une session
  `client`, il répond `403`. Ces deux réponses sont des pages HTML de nginx, pas du JSON.

### Authentification

| Mécanisme | Pour qui | Détail |
|---|---|---|
| Cookie `rp_session` | navigateur | Posé par `POST /auth/login`, `/auth/register` et `/auth/reset`. Attributs `httpOnly` et `SameSite=Strict`, plus `Secure` quand l'application est servie en HTTPS. Le JavaScript ne voit jamais le jeton |
| `Authorization: Bearer <jeton>` | scripts, sonde, Swagger | Jeton obtenu par `POST /auth/token` |

- Jetons JWT signés en **Ed25519** (`alg: EdDSA`, algorithme figé à la vérification), émetteur
  `resilience-auth`, audience `resilience-pay`, durée 120 min (`TOKEN_TTL_MINUTES`). payment-api
  les vérifie localement, avec la clé publique lue sur `GET /auth/jwks.json`.
- Deux rôles : `client` (ses propres paiements) et `operator` (tous les paiements, solde,
  supervision). Les comptes `operateur` et `client` sont créés au démarrage ; leurs mots de passe
  sont dans Vault (`secret/infra/paiement-app`), **jamais dans le dépôt**. Les comptes créés par
  `/auth/register` sont toujours `client`.
- **Freinage de la force brute** (en mémoire, par réplica d'auth) : 5 échecs par couple
  (adresse, identifiant) ou 20 échecs par adresse en 300 s donnent un `429` avec `Retry-After`.
  L'adresse est celle du client réel : NPM puis le WAF la transmettent dans `X-Forwarded-For`, et
  le frontal ne fait confiance qu'au réseau ingress du Swarm. **En amont**, le WAF bannit 15 min
  une IP qui accumule au moins 10 échecs de connexion en 2 min (voir [`../waf.md`](../waf.md#5-bannissement-automatique)).

### Réponses produites en amont des services

| Code | Émis par | Cas |
|---|---|---|
| 403 | WAF | requête bloquée par ModSecurity (injection SQL, XSS...), **ou IP bannie** (toutes les routes sauf `/healthz`, pendant 15 min) |
| 401 / 403 | frontal (nginx) | route opérateur sans session, ou avec une session `client` |
| 403 | frontal (nginx) | méthode autre que `GET` sur une route opérateur |
| 413 | frontal (nginx) | corps de plus de 16 Ko (`client_max_body_size`) |
| 502 / 504 | frontal (nginx) | service cible injoignable, par exemple pendant un redémarrage par la remédiation (quelques secondes) |

---

## 2. payment-api : paiements

Rôle : crée et confirme les paiements chez **Stripe (mode test)** et **PayPal (sandbox)**, tient le
journal des paiements dans PostgreSQL et publie l'état que lisent le détecteur et le moteur. Seul
ce service détient la clé secrète Stripe (secret Swarm, lue dans Vault). Le navigateur ne
transmet jamais de numéro de carte à Stripe : le serveur remplace un numéro de **carte de test**
par le jeton de test Stripe correspondant.

| Méthode | Chemin public | Auth | Rôle | Corps → réponse principale | Erreurs propres |
|---|---|---|---|---|---|
| GET | `/api/health` | non | — | → `{ok, stripe, mode ("test"\|"live"\|"none"), paypal, db}` | — (200 tant que le processus répond, voir la remarque) |
| GET | `/api/status` | session (relais) | operator | → `{api, stripe{up, latencyMs}, paypal{configured, up, latencyMs}, db{up}, metrics{rps, errRate, p95, wafBlocks}, time}` | 401/403 (relais) |
| POST | `/api/payment_intents` | oui | client, operator | `{amount, holder?}` → **201** paiement + `clientSecret` | 401, 422, 502 (Stripe), 503 (clé Stripe absente) |
| POST | `/api/payment_intents/{intent_id}/confirm` | oui | propriétaire ou operator | `{number, holder?}` → paiement + `clientSecret` | 400 (pas une carte de test), 404 (pas à vous), 401, 422, 502 |
| GET | `/api/payment_intents` | oui | client : les siens ; operator : tous | → liste des 25 derniers (base, ou Stripe si la base est en panne) | 401, 502 |
| GET | `/api/payment_intents/{intent_id}` | oui | propriétaire ou operator | → paiement relu chez Stripe et mis à jour en base | 401, 404, 502 |
| GET | `/api/balance` | oui | operator | → `{available, pending, nextPayoutAt}` (centimes EUR) | 401, 403, 502 |
| POST | `/api/paypal/orders` | oui | client, operator | `{amount}` → **201** commande | 401, 422, 429 (débit sortant), 502, 503 (PayPal non configuré) |
| POST | `/api/paypal/orders/{order_id}/capture` | oui | propriétaire ou operator | → commande capturée (une seconde capture est sans effet) | 400 (identifiant invalide), 404, 409 (non approuvée par le payeur), 429, 502 |
| GET | `/api/paypal/orders/{order_id}` | oui | propriétaire ou operator | → commande | 400, 404, 502 |
| GET | `/api/paypal/orders` | oui | client : les siennes ; operator : toutes | → liste | 401, 503 (base injoignable) |
| GET | `/metrics` | interne | — | format Prometheus (hors schéma OpenAPI, non relayé) | — |

**Champs** (schémas `CreateIntent`, `ConfirmIntent`, `CreateOrder`) :

- `amount` : entier en **centimes**, de 1 à 99 999 999 ;
- `holder` : titulaire, 120 caractères au plus, facultatif ;
- `number` : de 12 à 23 caractères, espaces tolérés. Seules les cartes de test Stripe sont
  acceptées : `4242 4242 4242 4242` passe ; `4000 0000 0000 0002` est refusée par l'émetteur ;
  `4000 0027 6000 3184` exige le 3-D Secure.

**Objet paiement** renvoyé par les routes `payment_intents` (même forme que le type
`PaymentIntent` du frontal) : `id`, `idempotencyKey`, `amount`, `currency` (`EUR`), `status`
(`requires_confirmation`, `requires_action`, `processing`, `succeeded`, `canceled`), `card`
(`brand`, `last4`, `holder`), `createdAt`, `reference` (`RSL-xxxx-xxxx`), `owner`, `rail` (étapes
`authorization`, `authentication`, `capture`, `settlement`), `history` (événements datés),
`error` (`code`, `message`) en cas de refus. `clientSecret` est le secret client Stripe de ce
paiement, remis à son seul propriétaire.

**Remarques** :

- `GET /api/health` **reste à 200 quand la base est en panne** (`"db": false`). C'est
  volontaire : redémarrer l'API ne répare pas une base, donc le moteur ne doit pas être
  déclenché pour ça. La santé réelle de la base se lit dans le champ `db`, et dans
  `demo-check.sh`.
- `/api/status` est ouverte dans le code (le détecteur et le moteur la lisent chaque seconde sur
  le réseau interne). Le frontal la réserve aux opérateurs. `metrics.wafBlocks` vaut toujours 0
  (champ prévu, non alimenté).
- Les appels à `/api/health` et `/api/status` ne comptent pas dans les métriques de trafic
  (`rps`, `errRate`, `p95` sur 10 s glissantes), qui sont les variables du détecteur.

## 3. auth : comptes et sessions

Rôle : comptes (PostgreSQL, mots de passe en argon2id), émission des jetons Ed25519, session du
navigateur, vérification du rôle pour le relais, freinage de la force brute, réinitialisation du
mot de passe par e-mail (Mailpit en démo).

| Méthode | Chemin public | Auth | Corps → réponse principale | Erreurs propres |
|---|---|---|---|---|
| POST | `/auth/login` | non | `{username, password}` → `{expiresAt, user}` + cookie `rp_session` | 401 (identifiants), 429 (+ `Retry-After`), 422 |
| POST | `/auth/token` | non | `{username, password}` → `{token, expiresAt, user}` (pour `Authorization: Bearer`) | 401, 429, 422 |
| POST | `/auth/register` | non | `{email, firstName, lastName, password}` → **201** `{expiresAt, user}` + cookie, rôle `client` | 409 (adresse prise), 422 (champs, mot de passe < 8), 429 |
| POST | `/auth/logout` | non | → **204**, cookie effacé | — |
| GET | `/auth/me` | oui | → `{username, role, firstName, lastName, expiresAt}` (relu en base) | 401 |
| GET | `/auth/verify?role=<rôle>` | oui | → `{}` si la session vaut pour ce rôle. Utilisée par le relais (`auth_request`) | 401, 403 (rôle insuffisant) |
| POST | `/auth/forgot` | non | `{email}` → toujours le même message, que le compte existe ou non | 429, 422 |
| POST | `/auth/reset` | non | `{token, password}` → `{expiresAt, user}` + cookie | 401 (lien invalide, expiré ou déjà utilisé), 422 (mot de passe < 8) |
| GET | `/auth/jwks.json` | non | → `{keys: [JWK Ed25519 publique]}`, mise en cache 300 s | — |
| GET | `/health` | interne | → `{ok, db}`, **503** si la base est injoignable | non relayée |
| GET | `/metrics` | interne | format Prometheus (`auth_login_total{result}`...) | non relayée |

`user` = `{username, role, firstName, lastName}`. Le lien de réinitialisation est valable
15 min (`RESET_TTL_MINUTES`). Il est scellé sur l'empreinte du mot de passe : il ne sert qu'une
fois.

## 4. detector : score d'anomalie (ML)

Rôle : interroge `GET /api/status` de payment-api chaque seconde. Six variables :
`rps`, `errRate`, `p95`, `stripeLatency`, `apiUp`, `stripeUp`. Le service apprend la normale
pendant `WARMUP_SECONDS` (60 s sur le Swarm), puis attribue un score de 0 à 1 (IsolationForest et
distance robuste). L'anomalie est **confirmée** après 3 secondes de suite au-dessus du seuil 0,55.

| Méthode | Chemin public | Auth | Réponse principale | Erreurs |
|---|---|---|---|---|
| GET | `/detector/score` (→ `/score`) | session (relais) | `{status ("learning"\|"ready"), progress, warmupSeconds, threshold, current, over, persistence, points[{seq, score}] (120 dernières s), features, last{...}, trainedAt}` | 401/403 (relais) |
| GET | `/health` | interne | `{ok, status, samples}` | — |
| POST | `/reset` | interne, en-tête `x-admin-token` | `{ok: true}` : réapprend la normale à partir de maintenant | 403 (jeton invalide), 503 (jeton non configuré) |
| GET | `/metrics` | interne | `detector_anomaly_score`, `detector_anomaly`, `detector_ready`... | — |

`over: true` est le verdict que lit le moteur de remédiation. `/reset` n'est **jamais relayé** :
effacer la normale aveuglerait la détection. Le jeton (Vault `PAIEMENT_DETECTOR_ADMIN_TOKEN`)
n'est connu que de l'opérateur.

## 5. remediation : moteur de remédiation

Rôle : chaque seconde, lit le verdict du détecteur. Si l'anomalie est confirmée, il redémarre
la cible (`paiement_payment-api`) par la passerelle SSH `remediate` des managers, vérifie la
reprise (`/api/status`, puis retrait du verdict), puis respecte un délai de 45 s avant toute
nouvelle action. **Il n'expose aucune route d'écriture** : seul le verdict du détecteur le
déclenche.

| Méthode | Chemin public | Auth | Réponse principale |
|---|---|---|---|
| GET | `/remediation/state` (→ `/state`) | session (relais) | `{status ("idle"\|"remediating"), events[{id, at, kind, text, actor}] (50 derniers, du plus récent au plus ancien), actions, humanActions, cooldownUntil, lastRecoverySeconds, targets}` |
| GET | `/health` | interne | `{ok, status, targets, mode ("docker"\|"ssh")}` |

`kind` vaut `detect`, `act`, `verify` ou `restore`. `humanActions` reste à 0 : c'est le compteur
« 0 intervention humaine » affiché par la supervision. La passerelle a ses propres limites (60 s
entre deux actions sur un même service, 10 actions par 10 min et par manager), décrites dans
[`../remediation.md`](../remediation.md).

---

## 6. Exemples

Aucun secret dans ces commandes : le mot de passe est lu au clavier, sans écho, et ne passe ni
dans la ligne de commande ni dans l'historique. `jq` est facultatif.

```sh
BASE=https://app.slabreze.fr
# Depuis le réseau d'administration (pas de NAT en épingle) :
# alias curl='curl --resolve app.slabreze.fr:443:172.16.1.10'

# Santé (publique)
curl -s $BASE/api/health
# {"ok":true,"stripe":true,"mode":"test","paypal":true,"db":true}

# Jeton pour un script (compte <identifiant>, mot de passe saisi sans écho)
read -rp 'Identifiant : ' U; read -rsp 'Mot de passe : ' P; echo
TOKEN=$(printf '{"username":"%s","password":"%s"}' "$U" "$P" |
  curl -s -H 'Content-Type: application/json' -d @- $BASE/auth/token | jq -r .token)

# Qui suis-je ?
curl -s -H "Authorization: Bearer $TOKEN" $BASE/auth/me

# Paiement de 12,50 € avec la carte de test Stripe 4242...
ID=$(curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"amount":1250,"holder":"Démo"}' $BASE/api/payment_intents | jq -r .id)
curl -s -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"number":"4242 4242 4242 4242","holder":"Démo"}' \
  $BASE/api/payment_intents/$ID/confirm | jq '{id, status, reference, rail}'
# "status": "succeeded"

# Journal (25 derniers paiements visibles par ce compte)
curl -s -H "Authorization: Bearer $TOKEN" $BASE/api/payment_intents | jq '.[] | {reference, amount, status}'

# Supervision (compte operateur seulement ; 401 sans session, 403 avec un compte client)
curl -s -H "Authorization: Bearer $TOKEN" $BASE/detector/score | jq '{status, current, threshold, over}'
curl -s -H "Authorization: Bearer $TOKEN" $BASE/remediation/state | jq '{status, actions, humanActions, lastRecoverySeconds, dernier: .events[0]}'
curl -s -H "Authorization: Bearer $TOKEN" $BASE/api/status | jq .metrics

# Session navigateur simulée : cookie dans un fichier temporaire, effacé ensuite
J=$(mktemp); printf '{"username":"%s","password":"%s"}' "$U" "$P" |
  curl -s -c $J -H 'Content-Type: application/json' -d @- $BASE/auth/login >/dev/null
curl -s -b $J $BASE/auth/me; rm -f $J

unset P TOKEN    # fin de session : ne rien laisser dans le shell
```

Codes attendus sans authentification (vérifiés le 21/10/2026 par l'URL publique) :

| Requête | Code |
|---|---|
| `GET /`, `/api/health`, `/api/docs`, `/auth/docs`, `/auth/jwks.json` | 200 |
| `GET /api/status`, `/detector/score`, `/remediation/state` | 401 (relais) |
| `GET /api/payment_intents`, `/api/balance`, `/auth/me`, `POST /api/payment_intents` | 401 (service) |
| `GET /metrics` | 200, page de l'application (pas de métriques) |
| `GET /?id=1' OR 1=1--` | 403 (WAF) |

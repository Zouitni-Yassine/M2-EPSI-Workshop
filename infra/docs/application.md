# Application Resilience Pay sur le Swarm

Portage de l'application des développeurs sur le cluster Swarm (20/10/2026), en quatre volets :
registre et build des images, stack et secrets, moteur de remédiation en mode SSH, exposition
publique. Réseau : [reseau.md](reseau.md) ; supervision de l'application : [supervision.md](supervision.md).

## Registre et build

Les images de l'application sont construites par Ansible à partir d'une révision figée du dépôt,
puis poussées dans un registre privé hébergé dans le Swarm. Un seul playbook fait les deux :

```bash
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook app-build.yml                    # registre + 5 images
vault-env ansible-playbook app-build.yml --tags registry    # registre seul
vault-env ansible-playbook app-build.yml --tags build       # images seules
vault-env ansible-playbook app-build.yml --tags build -e '{"app_build_images": ["remediation"]}'
vault-env ansible-playbook app-build.yml --tags build -e app_git_ref=<sha complet>
vault-env ansible-playbook app-build.yml --tags build -e app_build_force=true   # tout reconstruire
```

Rôles : `app_registry` (stack du registre, confiance TLS, `docker login`) et `app_build`
(clone, construction, envoi).

### Registre

| | |
|---|---|
| Adresse | **`10.30.1.221:5000`** (variable `app_registry`, `roles/app_registry/defaults/main.yml`) |
| Stack / service | `registry` / `registry_registry`, image `registry:2.8.3` |
| Nœud | `dockerwrk01`, épinglé par contrainte de placement (`app_registry_node`) |
| Données | volume local `registry_registry-data` sur dockerwrk01 |
| TLS | certificat émis par la CA interne (rôle `internal_ca`, `issue.yml`) ; SAN : `dockerwrk01`, `dockerwrk01.epsi.lsn`, `10.30.1.221`, `127.0.0.1` ; installé dans `/etc/registry/tls` du nœud et monté en lecture seule |
| Authentification | Basic, htpasswd bcrypt en secret Swarm `registry_htpasswd_<empreinte>` |
| Identifiants | Vault `secret/infra/registry` : `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` (exportés par `vault-env`) |
| Santé, métriques | port de debug `5001` non publié : `/debug/health` (healthcheck), `/metrics` (Prometheus), joignable sur le réseau overlay `monitoring` |

**Pourquoi un seul nœud.** `registry:2` stocke ses couches sur disque ; sans stockage partagé
(S3, NFS), deux réplicas auraient deux contenus différents. Le service est donc épinglé sur
dockerwrk01 avec un volume local, et publie son port en **mode host** : l'adresse du registre
est celle de ce nœud, la même que dans le certificat et dans le nom des images.
**Limite** : si dockerwrk01 tombe, le registre est indisponible. Les services déjà déployés
continuent de tourner (images en cache sur chaque worker), mais un nouveau placement sur un
worker qui n'a pas encore l'image échoue jusqu'au retour du nœud (la VM est en HA Proxmox,
elle redémarre seule sur un autre hyperviseur, disque sur Ceph : les données sont conservées).
Le volume n'est pas sauvegardé : les images se reconstruisent à l'identique par ce playbook.
Évolution possible : stockage S3 du registre (bucket dédié du tenant) et plusieurs réplicas
derrière l'ingress.

**Accès réseau.** Un port publié par un service Swarm passe par la chaîne FORWARD et contourne
le firewall de l'hôte (`host_fw`, hook input). Le port 5000 n'est donc filtré que par la
passerelle UniFi : seuls RA-APP (les nœuds du Swarm) et MANAGEMENT (poste de contrôle) le
joignent. C'est acceptable : il est en plus protégé par TLS et par mot de passe.

**Confiance et identifiants des nœuds.** Tous les nœuds ont la CA interne dans le magasin
système (rôle `internal_ca`) et, explicitement pour Docker, dans
`/etc/docker/certs.d/10.30.1.221:5000/ca.crt`. Seuls les **managers** sont connectés au
registre (`docker login`, `/root/.docker/config.json`) : le déploiement se fait par
`docker stack deploy --with-registry-auth` (ou `with_registry_auth: true` du module
`docker_stack`), et Swarm transmet ces identifiants aux workers le temps du téléchargement.
Aucun mot de passe n'est stocké sur les workers.

**Rotation du mot de passe.**

```bash
python3 roles/app_registry/files/registry-credentials.py --rotate   # nouveau mot de passe dans Vault
vault-env ansible-playbook app-build.yml --tags registry
```

Le nom du secret htpasswd porte une empreinte des identifiants : la rotation crée un nouveau
secret, met à jour le service, refait `docker login` sur les managers et supprime l'ancien
secret. Redéployer ensuite les stacks applicatives avec `--with-registry-auth` pour que Swarm
transmette les nouveaux identifiants. Le certificat (1 an) est renouvelé par le rôle
`internal_ca` ; un nouveau certificat redémarre le registre (handler).

### Build

- **Où** : sur `dockermgr01` (le poste de contrôle est un LXC sans Docker). Dossier de travail
  `/var/lib/app-build/src`, clone du dépôt public `Zouitni-Yassine/M2-EPSI-Workshop`.
- **Quelle révision** : `app_git_ref`, un commit complet (une branche est refusée : une même
  commande doit toujours produire les mêmes images). Par défaut le commit courant de
  `/srv/M2-EPSI-Workshop` sur le poste de contrôle, qui **doit avoir été poussé** sur GitHub.
- **Quoi** : les services de `app_build_images` (par défaut `auth`, `payment-api`, `detector`,
  `remediation`, `frontend`). Nom, version, contexte et build args sont lus dans le
  `docker-compose.yml` de la racine, à la même révision : une nouvelle version dans le compose
  donne automatiquement un nouveau tag.
- **Tags** : pour chaque image, deux tags dans `10.30.1.221:5000/<nom>` :
  - `<version>-<commit court>` : **figé**, jamais réécrit, à utiliser pour un retour arrière
    précis ; pour le frontend, suivi d'une empreinte de ses build args
    (`0.2.0-17985c9-85dcfad5`), car l'image dépend de la clé Stripe ;
  - `<version>` : le tag du `docker-compose.yml` (`auth:0.3.0`…), recopié côté registre
    (`docker buildx imagetools create`) sur la dernière construction. Avec
    `REGISTRY=10.30.1.221:5000`, le compose de la racine désigne donc directement ces images.
- **Idempotence** : une image dont le tag figé existe déjà dans le registre n'est pas
  reconstruite ; le tag `<version>` n'est recopié que s'il ne pointe pas sur le même manifeste.
  Second passage : `changed=0`. `app_build_force=true` force la reconstruction.
- **Labels** des images : `org.opencontainers.image.revision` (commit complet), `.source`, `.version`.

**Frontend et clés de paiement.** Les build args `${VAR}` du compose prennent leur valeur dans
`app_build_arg_values` : `VITE_STRIPE_PUBLISHABLE_KEY` et `PAYPAL_CLIENT_ID` lus dans Vault
`secret/infra/paiement` (via `vault-env`), `VITE_CARD_ENTRY=own`. Ils sont passés par
l'environnement de `docker build` (`--build-arg NOM` sans valeur) : rien dans la ligne de commande
ni dans la sortie d'Ansible. **Sans clé Stripe**, le frontend est construit quand même : le
paiement par carte est alors simulé localement, avec une bannière à l'écran
(`frontend/src/payments/engine/index.ts`). Dès que la clé est rangée dans Vault, relancer :

```bash
vault-env ansible-playbook app-build.yml --tags build -e '{"app_build_images": ["frontend"]}'
```

L'empreinte des build args change, donc le tag figé aussi : le frontend est reconstruit et
`frontend:0.2.0` est déplacé sur la nouvelle image (redéployer la stack ensuite).

**Code modifié non encore poussé.** Le build part toujours de GitHub : pour construire une
modification (par exemple `remediation/`), la pousser sur la branche, mettre à jour le poste de
contrôle, puis relancer le build de cette seule image.

### Vérifications

```bash
# 401 sans identifiants, catalogue avec (identifiants lus par vault-env, jamais affichés)
curl -s -o /dev/null -w '%{http_code}\n' https://10.30.1.221:5000/v2/_catalog          # 401
vault-env sh -c 'curl -s -u "$REGISTRY_USERNAME:$REGISTRY_PASSWORD" https://10.30.1.221:5000/v2/_catalog'
# {"repositories":["auth","detector","frontend","payment-api","remediation"]}
```

Faites le 20/10/2026 : 401 sans authentification ; catalogue des 5 images avec leurs deux tags ;
`docker pull 10.30.1.221:5000/payment-api:0.4.0` depuis dockerwrk02 (label `revision` =
commit attendu) ; second passage du playbook à `changed=0`.

Le ménage des anciens tags n'est pas automatisé (API `DELETE` activée, puis
`registry garbage-collect` dans le conteneur) ; le cache de build de dockermgr01 se purge par
`docker builder prune`.

## Stack et secrets de l'application

L'application « Resilience Pay » (code à la racine du dépôt) tourne sur le Swarm dans la stack
**`paiement`**. Elle est déployée par Ansible à partir d'un template dérivé de
`docker-compose.yml` ; ses secrets sont générés dans Vault puis montés en secrets Swarm.

| Fichier | Rôle |
|---|---|
| `infra/app/paiement-stack.yml.j2` | Template de la stack (dérivé de `docker-compose.yml`) |
| `infra/app/init-secrets-vault.py` | Génère les secrets de l'application dans Vault (idempotent) |
| `infra/ansible/roles/app_stack/` | Secrets et configs Swarm, rendu du template, `docker stack deploy` |
| `infra/ansible/app-deploy.yml` | Playbook : contrôles préalables puis rôle `app_stack` sur `swarm_managers[0]` |

### Architecture des services

| Service Swarm | Image | Réseaux | Exposition | Réplicas, redémarrage |
|---|---|---|---|---|
| `paiement_frontend` | `<registre>/frontend` (nginx : SPA + relais) | resilience | **port 5173** (ingress, tous les nœuds) | 1, any |
| `paiement_auth` | `<registre>/auth` | resilience, data, **monitoring** | aucun (relais `/auth/`) ; `/metrics` :8300 | 1 (freinage force brute en mémoire), any |
| `paiement_payment-api` | `<registre>/payment-api` | resilience, data, **monitoring** | aucun (relais `/api/`) ; `/metrics` :8000 | 1, **on-failure** |
| `paiement_detector` | `<registre>/detector` | resilience | aucun (relais `/detector/score`, opérateurs) | 1 (modèle en mémoire), any |
| `paiement_remediation` | `<registre>/remediation` | resilience | aucun (relais `/remediation/state`, opérateurs) | 1 (un seul décideur), any |
| `paiement_db` | `postgres:16-alpine` | data (interne) | aucun | 1, épinglée sur `dockerwrk01` |
| `paiement_mailpit` | `axllent/mailpit:v1.20` | resilience | aucun (non publié sur le cluster) | 1, any |

- Réseaux overlay de la stack **chiffrés** (IPsec, ESP autorisé par le firewall des nœuds) :
  `resilience` (relais et services) et `data` (`internal: true`, sans accès sortant : base).
  `monitoring` est le réseau externe de la stack de supervision : seuls `auth` et
  `payment-api` y sont attachés, pour la collecte de leurs `/metrics` par le vmagent du Swarm.
- Tous les services sur les workers (`node.role == worker`, managers drainés), répartis par
  hyperviseur (`spread: node.labels.pve_node`). Durcissement repris du compose : `read_only`,
  `cap_drop: [ALL]` (+ capacités minimales pour postgres et nginx), tmpfs, utilisateurs non root
  des images. Limites CPU/mémoire, healthchecks (ceux des images, celui de la base dans la
  stack) et `update_config` (start-first, rollback automatique) identiques au compose.
- **Différences avec `docker-compose.yml`** : images du registre privé à tag figé
  (`<version>-<commit court>`, produit par `app-build.yml`) ; pas de `build`, `container_name`,
  `security_opt`, `env_file` (variables explicites dans la stack) ; **pas de
  `docker-socket-proxy`** (contrat : jamais le socket Docker) ; `payment-api` en
  `restart_policy: on-failure` (un crash est relancé par Swarm, un arrêt volontaire, code 0,
  est laissé au moteur de remédiation) ; Mailpit non publié ; base épinglée.
- **Moteur de remédiation en mode SSH** : il agit par la passerelle `remediate` des managers
  ([remediation.md](remediation.md)) : `REMEDIATION_MODE=ssh`,
  `REMEDIATION_GATEWAYS=10.30.1.211,10.30.1.212,10.30.1.213` (construit depuis l'inventaire),
  `REMEDIATION_SSH_USER=remediation`, `REMEDIATION_SSH_KEY_FILE=/run/secrets/remediation_ssh_key`
  (secret externe `remediation_ssh_key`, propriétaire uid 10003, mode 0400),
  `REMEDIATION_KNOWN_HOSTS_FILE=/run/configs/remediation_known_hosts` (config externe),
  `TARGETS=paiement_payment-api`. La stack `paiement` figure dans `remediation_allowed_stacks`.
- `APP_URL` / `CORS_ORIGINS` : variable `app_url` (par défaut `http://10.30.1.221:5173`,
  accès direct à un worker). Quand le WAF publiera `https://app.slabreze.fr` :
  `-e app_url=https://app.slabreze.fr` (ou modifier le défaut) ; le cookie de session passe
  alors automatiquement en `Secure`.

### Secrets

Aucune valeur dans le dépôt, dans le fichier de stack ou dans la spec des services : les
secrets Swarm sont montés en fichiers sous `/run/secrets/<nom attendu par le code>`.

| Chemin Vault | Clés | Origine |
|---|---|---|
| `secret/infra/paiement-app` | `PAIEMENT_POSTGRES_PASSWORD`, `PAIEMENT_AUTH_DB_PASSWORD`, `PAIEMENT_PAYMENTS_DB_PASSWORD`, `PAIEMENT_JWT_PRIVATE_KEY` (PEM Ed25519), `PAIEMENT_DETECTOR_ADMIN_TOKEN`, `PAIEMENT_AUTH_PASSWORD_OPERATEUR`, `PAIEMENT_AUTH_PASSWORD_CLIENT` | Générées par `init-secrets-vault.py` (32 caractères aléatoires) |
| `secret/infra/paiement` | `STRIPE_SECRET_KEY`, `VITE_STRIPE_PUBLISHABLE_KEY`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (facultatifs) | Saisies par l'utilisateur |
| `secret/infra/registry` | `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` | Rôle `app_registry` |

| Secret de la stack (`/run/secrets/…`) | Clé Vault | Services |
|---|---|---|
| `postgres_password` | `PAIEMENT_POSTGRES_PASSWORD` | db (`POSTGRES_PASSWORD_FILE`) |
| `auth_db_password` | `PAIEMENT_AUTH_DB_PASSWORD` | db (init), auth (`DB_PASSWORD_FILE`) |
| `payments_db_password` | `PAIEMENT_PAYMENTS_DB_PASSWORD` | db (init), payment-api (`DB_PASSWORD_FILE`) |
| `jwt_private_key` | `PAIEMENT_JWT_PRIVATE_KEY` | auth (`JWT_PRIVATE_KEY_FILE`) |
| `auth_password_operateur`, `auth_password_client` | `PAIEMENT_AUTH_PASSWORD_*` | auth (`AUTH_PASSWORD_<COMPTE>_FILE`, comptes semés `AUTH_SEED_USERS`) |
| `detector_admin_token` | `PAIEMENT_DETECTOR_ADMIN_TOKEN` | detector (*) |
| `stripe_secret_key` | `STRIPE_SECRET_KEY` | payment-api (*) ; absent = pas de secret |
| `paypal_client_secret` | `PAYPAL_CLIENT_SECRET` | payment-api (`PAYPAL_CLIENT_SECRET_FILE`) ; facultatif |
| `remediation_ssh_key` (externe) | — (rôle `remediation_gateway`) | remediation |

(*) Variables sans variante `_FILE` dans le code : la commande du service est surchargée par
`sh -c 'export VAR="$(cat /run/secrets/x)"; exec uvicorn …'` (commande d'origine des
Dockerfile), la valeur n'apparaît donc ni dans la spec ni dans `docker service inspect`.

- **Noms versionnés** : `paiement_<secret>_<empreinte>` (SHA-256 salé et tronqué à 12
  caractères), label `com.epsi.usage=paiement` ; la config `paiement_db_init_<empreinte>`
  porte `db/init/01-roles.sh`. Une nouvelle valeur dans Vault crée un nouveau secret et met à
  jour les services concernés ; les anciens sont supprimés en fin de rôle (au passage suivant
  s'ils étaient encore utilisés).
- **Rotation des mots de passe de la base** : ils ne servent qu'à l'initialisation du volume.
  En changer dans Vault exige aussi `ALTER ROLE … PASSWORD` dans la base (ou la recréation du
  volume) ; sinon auth et payment-api ne se connectent plus. Les mots de passe des comptes
  semés et la clé JWT se changent librement (la rotation de la clé déconnecte les sessions).

### Commandes

```sh
cd /srv/M2-EPSI-Workshop/infra/ansible
python3 ../app/init-secrets-vault.py          # secrets générés (une fois ; n'écrase jamais)
vault-env ansible-playbook app-build.yml      # registre + images (agent A, docs/application.md)
vault-env ansible-playbook app-deploy.yml     # stack paiement
# Sans clé Stripe dans Vault (frontal en paiement simulé) :
vault-env ansible-playbook app-deploy.yml -e app_require_stripe=false
# Révision d'images différente du commit courant :
vault-env ansible-playbook app-deploy.yml -e app_git_ref=<sha>
```

Contrôles préalables du playbook (message explicite en cas d'échec) : secrets générés
présents (≥ 16 caractères, PEM pour la clé JWT), `STRIPE_SECRET_KEY` présente
(sauf `app_require_stripe=false`), identifiants du registre, et présence de chaque image au tag
attendu dans le registre (`/v2/<image>/tags/list`).

Le moteur de remédiation ne peut agir sur `paiement` qu'après le passage du rôle
`remediation_gateway` avec `remediation_allowed_stacks: [demo, paiement]` (`swarm.yml`).

### Vérifications

```sh
M="ssh -i /root/.ssh/id_ed25519_infra debian@10.30.1.211"
$M sudo docker stack services paiement                      # toutes les réplicas 1/1
curl -s -o /dev/null -w '%{http_code}\n' http://10.30.1.221:5173/            # 200
curl -s -o /dev/null -w '%{http_code}\n' http://10.30.1.221:5173/api/health  # 200 via le relais
# Connexion d'un compte semé, sans afficher le mot de passe (code HTTP seulement) :
vault-env sh -c 'printf "{\"username\":\"client\",\"password\":\"%s\"}" "$PAIEMENT_AUTH_PASSWORD_CLIENT" |
  curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" -d @- \
  http://10.30.1.221:5173/auth/login'                                         # 200
vault-env ansible-playbook app-deploy.yml                   # second passage : changed=0
```

### Limites

- **Base sans bascule** : volume local sur `dockerwrk01` (contrainte de placement). Si ce
  worker tombe, la base (donc les paiements et la connexion) reste indisponible jusqu'à son
  retour ; les données ne suivent pas. Pistes : volume partagé (Ceph RBD/CephFS via un plugin
  de volume), ou PostgreSQL répliqué (Patroni) ; et sauvegarde `pg_dump` vers le PBS/S3.
- **Réplicas uniques** (auth, payment-api, detector, remediation) : choix de l'application
  (état en mémoire), un redémarrage provoque une courte coupure. C'est aussi ce qui rend la
  démonstration de remédiation visible.
- **Port 5173 publié en mode ingress** : ouvert sur tous les nœuds et hors du firewall nftables
  des hôtes (un port publié par Swarm le contourne). À filtrer en amont (passerelle UniFi /
  WAF) : seul le WAF devrait joindre ce port une fois `app.slabreze.fr` en place.
- **Mailpit non publié** : les e-mails de réinitialisation ne sont pas lisibles de l'extérieur
  (volontaire : l'attaquant partage le réseau de démo). Pour une démo, lire via
  `docker exec` dans le conteneur ou publier temporairement le port avec un filtrage amont.
- Les clés Stripe/PayPal publiques sont intégrées **à la construction** du frontend
  (`VITE_*`, app-build.yml) : les changer impose de reconstruire l'image `frontend`.

## Moteur de remédiation en mode SSH

Le moteur de Resilience Pay (`remediation/app/main.py`) redémarrait sa cible par le socket
Docker, à travers un proxy nginx. Sur le Swarm c'est interdit (contrat de déploiement, §7 :
pas de `docker.sock`) et impossible (la tâche visée peut tourner sur n'importe quel nœud). Il a
donc un second chemin d'action, choisi par `REMEDIATION_MODE` :

| Mode | Où | Chemin |
|---|---|---|
| `docker` (défaut) | compose local | proxy du socket Docker, `POST /containers/<cible>/restart` (inchangé) |
| `ssh` | stack Swarm `paiement` | passerelle `remediate` des managers ([remediation.md](remediation.md)) |

### Variables fournies par la stack

| Variable | Valeur sur le Swarm |
|---|---|
| `REMEDIATION_MODE` | `ssh` |
| `REMEDIATION_GATEWAYS` | `10.30.1.211,10.30.1.212,10.30.1.213` (essayés dans l'ordre) |
| `REMEDIATION_SSH_USER` | `remediation` |
| `REMEDIATION_SSH_KEY_FILE` | `/run/secrets/remediation_ssh_key` (secret Swarm `remediation_ssh_key`) |
| `REMEDIATION_KNOWN_HOSTS_FILE` | `/run/configs/remediation_known_hosts` (config Swarm `remediation_known_hosts`) |
| `TARGETS` | `paiement_payment-api` (nom du service Swarm, pas du conteneur) |
| `REMEDIATION_SSH_TIMEOUT` | facultatif, 200 s par défaut (la passerelle attend la convergence, 180 s au plus) |

### Fonctionnement

1. Le détecteur confirme une anomalie ; le moteur publie sa décision dans sa chronologie.
2. Il appelle `ssh -T -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes
   -o UserKnownHostsFile=<config> -o ConnectTimeout=5 -i <clé> remediation@<manager>
   "restart paiement_payment-api"`, lancé par `subprocess` avec une liste d'arguments
   (jamais de shell).
3. Il interprète le code retour et la réponse JSON de la passerelle :

| Code | Traitement par le moteur |
|---|---|
| 255 (ssh) | manager injoignable (ou empreinte, ou authentification) : événement, manager suivant |
| 0 | événement « redémarré par la passerelle X en N s, R/R réplicas en marche », puis vérification |
| 2, 3, 5 | « Échec du redémarrage » avec la cause, puis vérification habituelle (escalade si rien ne revient) |
| 4 | « Action différée » : pas de vérification, nouvel essai après `retry_in` (au moins 5 s) |
| délai dépassé | échec, **sans** essayer un autre manager : l'action est peut-être en cours |

4. La vérification de reprise ne change pas : `GET /api/status` (API et Stripe), puis attente
   que le détecteur retire son verdict, puis `COOLDOWN_SECONDS` avant toute nouvelle action.

### Sécurité

- **Liste fermée côté moteur** : seule une cible de `TARGETS` est envoyée, et elle doit en plus
  respecter la règle de nom de la passerelle (`^[a-z0-9][a-z0-9_.-]{0,62}$`). Managers et
  compte SSH sont validés au démarrage : une valeur mal formée arrête le conteneur.
- **Liste fermée côté infra** : la clé n'ouvre que la commande forcée `remediate`, depuis les
  workers, sur les stacks de `remediation_allowed_stacks`, avec limitation de débit.
- **Hôtes vérifiés** : `StrictHostKeyChecking=yes` avec les empreintes de la config Swarm, pas
  de confiance au premier contact.
- **Clé** : le secret est copié au démarrage dans un fichier 0600 du tmpfs `/tmp` (le conteneur
  est `read_only`) ; ssh refuse une clé aux droits trop ouverts. Jamais journalisée.
- **Image** : `python:3.12-slim` + `openssh-client` (sans paquets recommandés), utilisateur
  10003, compatible `read_only`, `cap_drop: [ALL]`, `no-new-privileges`.

### Tests (20/10/2026)

- **Unitaires** (`remediation/tests`, pytest, `subprocess.run` simulé) : 12/12, sous Windows
  et dans `python:3.12-slim` sur dockerwrk01. Mode `docker` inchangé ; ssh réussi ; premier
  manager injoignable puis réussite sur le second ; aucun manager joignable ; délai dépassé
  sans second essai ; refus code 3 ; code 4 (report sans vérification, temporisation) ; cible
  invalide ou hors liste refusée sans appel ssh ; clé absente.
- **Réel** : image construite sur dockerwrk01, job Swarm éphémère (`read_only`, `cap_drop ALL`,
  tmpfs `/tmp`, secret `remediation_ssh_key` en 0444, config `remediation_known_hosts`),
  managers `10.30.1.250` (inexistant), `10.30.1.211`, `10.30.1.212`, cible `demo_web` :

| Cas | Résultat |
|---|---|
| copie de la clé | fichier 0600 dans `/tmp` |
| `status demo_web` | `.250` injoignable (« No route to host »), réponse de `.211`, code 0, 3/3 réplicas |
| `restart demo_web` | code 0 via `.211`, 50,6 s, 3/3 réplicas |
| second `restart` immédiat | code 4, `RateLimited`, `retry_in` 5 s |
| cible `demo_web;id` | refusée par le moteur, aucun appel ssh |
| journal de la passerelle | `caller=10.30.1.221` (le worker), actions et refus tracés |

### Limites

- Les managers sont essayés dans l'ordre à chaque appel : un premier manager en panne coûte
  `ConnectTimeout` (5 s) par appel.
- Les limites de débit sont comptées par manager (voir [remediation.md](remediation.md), §7).
- Seul `restart` est utilisé ; `rollback` et `scale` sont disponibles côté passerelle pour une
  escalade future.

## Exposition publique de l'application

« Resilience Pay » est publiée sur Internet sous `https://app.slabreze.fr`, derrière le WAF de
l'équipe cyber. Ce document décrit le chemin complet, ce que chaque équipe configure, et l'état
au 20/10/2026. Segmentation réseau : [reseau.md](reseau.md).

### 1. Chemin d'une requête

```mermaid
flowchart LR
  NET["Internet<br/>app.slabreze.fr"] -- "443 (TLS)" --> NPM["NPM<br/>172.16.1.10<br/>DMZ VLAN 9, zone Internal"]
  NPM -- "8443 (TLS, CA interne)" --> WAF["waf01<br/>10.30.2.251 (RA-DMZ)<br/>ModSecurity + CRS"]
  WAF -- "5173 (HTTP)" --> SW["Swarm RA-APP<br/>10.30.1.221-223:5173<br/>maillage ingress"]
  SW --> FE["paiement_frontend<br/>nginx : fichiers statiques<br/>+ relais /api /auth"]
  FE --> API["paiement_payment-api"] & AUTH["paiement_auth"]
```

| Étape | Qui gère | Rôle |
|---|---|---|
| NPM (Nginx Proxy Manager) 172.16.1.10 | l'utilisateur (hors projet) | Terminaison TLS publique (Let's Encrypt), un proxy host par nom |
| `waf01` | équipe cyber | Filtrage applicatif (OWASP CRS, paranoïa 1, blocage), journal d'audit dans Loki |
| Frontal `paiement_frontend` | équipe dev / infra (stack `paiement`) | **Seul port publié** de la plateforme (5173), relaie `/api/` et `/auth/` vers les services internes |

Le frontal est publié en mode `ingress` : les 6 nœuds du Swarm (managers compris, bien que
drainés) répondent sur 5173 et le maillage de routage envoie la requête à la réplica. Un port
publié par Swarm **contourne le firewall nftables des nœuds** : le filtrage est fait par la
passerelle UniFi (règle `ra-dmz-to-app`, section 3), pas sur les hôtes.

### 2. Ce que fait chaque équipe

#### Utilisateur : proxy host NPM

| Champ NPM | Valeur |
|---|---|
| Domain Names | `app.slabreze.fr` |
| Scheme | `https` |
| Forward Hostname / IP | `10.30.2.251` (waf01, une fois en RA-DMZ ; aujourd'hui 10.0.1.251) |
| Forward Port | `8443` |
| Cache Assets | non (le frontal gère lui-même le cache : `no-store` sur la page, `immutable` sur `/assets/`) |
| Block Common Exploits | non : c'est le rôle du WAF, et un double filtrage rend les blocages difficiles à expliquer |
| Websockets Support | non nécessaire (voir ci-dessous), sans risque si activé |
| SSL | certificat Let's Encrypt pour `app.slabreze.fr`, **Force SSL** et **HTTP/2** activés, HSTS activé une fois le parcours validé |

Onglet *Advanced* (configuration nginx personnalisée) :

```nginx
# NPM ajoute déjà X-Forwarded-For, X-Forwarded-Proto, X-Real-IP et Host.
# Le WAF présente un certificat de la CA interne : NPM ne le vérifie pas par défaut
# (proxy_ssl_verify off), ce qui est acceptable sur ce lien interne.
proxy_set_header X-Forwarded-Host $host;
client_max_body_size 16k;      # même limite que le frontal : un paiement fait quelques centaines d'octets
proxy_read_timeout 30s;
```

**WebSocket** : le frontal est construit avec `VITE_DATA_SOURCE=api` (défaut du Dockerfile) :
le tableau de supervision interroge `/api/status`, `/detector/score` et `/remediation/state` en
HTTP. `VITE_WS_URL` n'est utilisé qu'en mode `ws` (moteur qui pousse l'état), qui n'est pas
celui de l'image déployée. Si l'équipe dev passe en mode `ws`, il faudra activer *Websockets
Support* dans NPM et les en-têtes `Upgrade`/`Connection` dans le WAF.

#### Équipe cyber : WAF

Aujourd'hui `waf01` est en 10.0.1.251 (MANAGEMENT) et relaie vers une page de test
(`127.0.0.1:18080`). À faire, **avec l'accord du propriétaire** de la VM :

1. **Déplacer la VM en RA-DMZ** : carte réseau sur le vnet Proxmox `radmz`, adresse
   `10.30.2.251/24`, passerelle `10.30.2.254`, DNS `10.30.2.254`. Alloy continue d'envoyer ses
   logs à Loki (règle `ra-dmz-to-loki` déjà en place) ; l'adresse change dans l'inventaire
   Ansible (`waf01`, groupe `waf`). Le SSH depuis MANAGEMENT reste possible (`ra-mgmt-to-dmz`).
2. **Upstream** vers le frontal, avec les trois workers (le maillage ingress répond sur chacun,
   un nœud tombé est simplement évité) :

   ```nginx
   upstream resilience_app {
       server 10.30.1.221:5173 max_fails=2 fail_timeout=10s;
       server 10.30.1.222:5173 max_fails=2 fail_timeout=10s;
       server 10.30.1.223:5173 max_fails=2 fail_timeout=10s;
       keepalive 16;
   }
   ```

   puis `proxy_pass http://resilience_app;` à la place de `http://127.0.0.1:18080`, avec
   `proxy_next_upstream error timeout http_502 http_503;` pour basculer sur un autre nœud.
3. **Nom et certificat** : ajouter `app.slabreze.fr` à `server_name` du serveur 8443 (et au
   certificat si NPM doit un jour le vérifier).
4. **Adresse du client** : derrière NPM, le WAF voit toutes les requêtes venir de 172.16.1.10.
   Le WAF écrase aujourd'hui `X-Forwarded-For` par `$remote_addr` (bon réflexe, rien n'est usurpable),
   il faut donc lui faire lire l'adresse transmise par NPM, **et seulement par NPM** :

   ```nginx
   set_real_ip_from 172.16.1.10;
   real_ip_header X-Forwarded-For;
   real_ip_recursive on;
   ```

   Sans cela, les règles ModSecurity par adresse, les journaux et un éventuel bannissement
   d'IP verraient un seul client.
5. **Firewall nftables du WAF** (`waf-firewall.nft`) : ouvrir 8443 à `172.16.1.10` (NPM), et
   remplacer `10.0.1.0/24` par les réseaux d'administration voulus.
6. **Santé** : `/healthz` (8080) reste réservé à la supervision depuis MANAGEMENT.

#### Équipe dev / infra : stack `paiement`

- **`app_url`** (défaut `http://10.30.1.221:5173`, rôle `app_stack`) devient
  `https://app.slabreze.fr`. Il sert aux liens envoyés par mail (réinitialisation du mot de passe)
  et, comme il commence par `https://`, active `COOKIE_SECURE` : le cookie de session n'est alors
  plus envoyé sur `http://10.30.1.221:5173`. **La connexion ne marche plus en accès direct** :
  tester par l'URL publique (ou un `/etc/hosts` pointant vers NPM).
- **`app_cors_origins`** (défaut `{{ app_url }}`) suit `app_url`. Le navigateur appelle la même
  origine que la page (chemins relatifs, relais nginx) : CORS ne sert que si une autre origine
  appelle l'API. Pour garder l'accès direct pendant les tests :
  `app_cors_origins: "https://app.slabreze.fr,http://10.30.1.221:5173"`.
- **Adresse du client jusqu'à `auth`** : le relais du frontal écrase `X-Forwarded-For` par son
  `$remote_addr`. Or derrière le maillage ingress, `$remote_addr` est une adresse du réseau
  `ingress` (172.20.0.0/24), pas celle du WAF ni du client. **Conséquence : le freinage de la
  force brute de `auth` compte tous les clients comme une seule adresse** et une attaque
  bloquerait tout le monde. Correction proposée (stack + image frontal) :
  1. publier 5173 en `mode: host` sur les workers (le WAF liste déjà les trois workers) : la
     source vue par le frontal est alors l'adresse du WAF ; une réplica `global` ou 3 réplicas
     avec `max_replicas_per_node: 1` et `order: stop-first` (voir le piège du contrat) ;
  2. dans `frontend/nginx.conf`, faire confiance au seul WAF :
     `set_real_ip_from 10.30.2.251; real_ip_header X-Forwarded-For;`. Le reste du fichier
     (`proxy_set_header X-Forwarded-For $remote_addr`) transmet alors l'adresse réelle.

  Tant que ce n'est pas fait, la limite est à présenter au jury, et le WAF reste le premier
  rempart contre la force brute (l'alerte `PaiementAuthBruteForce` signale les rafales).

### 3. Règles réseau (passerelle UniFi)

Fichier [`unifi/ra-network.yml`](../unifi/ra-network.yml), appliqué par `vault-env unifi/unifi-ra --apply`.

| Règle | De → vers | Ports | État |
|---|---|---|---|
| `ra-dmz-to-app` | `RA-DMZ` → `RA-APP` | tcp 5173 | **Appliquée le 20/10/2026** (second plan : « aucun changement ») |
| `ra-npm-to-waf` | 172.16.1.10 (zone Internal) → `RA-DMZ` | tcp 8443 | **En commentaire**, à activer quand le WAF sera en RA-DMZ |
| `ra-dmz-to-loki` | `RA-DMZ` → 10.0.1.233 | tcp 3100 | En place (logs du WAF) |
| `ra-mgmt-to-dmz`, `ra-mgmt-to-app` | MANAGEMENT → `RA-DMZ`, `RA-APP` | tous | En place (administration, tests depuis .110) |

Le script ne sait viser qu'une zone `RA-*` entière en destination : `ra-dmz-to-app` ouvre 5173
à toute la DMZ (dont le futur serveur NetBird), et `ra-npm-to-waf` ouvrira 8443 vers toute la
DMZ. Le filtrage fin est fait par le firewall nftables du WAF (8443 réservé à NPM) ; sur les
nœuds Swarm, il est impossible (port publié par Swarm), d'où l'intérêt de garder 5173 comme
seul port publié.

Pour activer `ra-npm-to-waf` : retirer le `#` de la ligne, puis

```sh
cd /srv/M2-EPSI-Workshop/infra
vault-env unifi/unifi-ra            # plan : doit annoncer « + politique ra-npm-to-waf »
vault-env unifi/unifi-ra --apply    # sauvegarde de la console puis application
vault-env unifi/unifi-ra            # « aucun changement »
```

NPM est sur un réseau hors projet : **aucune autre règle** de ce réseau vers `RA-*` n'est ouverte,
et `RA-*` ne peut pas initier de connexion vers NPM (trafic de retour seulement).

### 4. Vérifications

Depuis le poste de contrôle (MANAGEMENT) :

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://10.30.1.221:5173/        # 200 : frontal
curl -s -o /dev/null -w '%{http_code}\n' http://10.30.1.221:5173/api/health   # 200 : relais vers payment-api
```

Depuis `waf01`, une fois en RA-DMZ : les mêmes requêtes vers les trois workers (règle
`ra-dmz-to-app`), puis depuis Internet :

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://app.slabreze.fr/                     # 200
curl -s -o /dev/null -w '%{http_code}\n' "https://app.slabreze.fr/?id=1%27%20OR%201=1--"  # 403 : WAF
curl -s -o /dev/null -w '%{http_code}\n' https://app.slabreze.fr/metrics             # page de l'appli (index.html), jamais les métriques
```

Logs (Grafana > Explore > Loki) : `{host="waf01",service="resilience-waf"} | json | status="403"`
pour les blocages, `{stack="paiement", service="paiement_frontend"}` pour le relais.

**État au 20/10/2026** : règle `ra-dmz-to-app` appliquée. Stack `paiement` déployée : depuis .110,
`/` et `/api/health` répondent 200 sur 10.30.1.221, .222, .223 (et sur le manager .211 : maillage
ingress). Le WAF est toujours en MANAGEMENT et le proxy host NPM n'est pas créé : le chemin
public reste à tester de bout en bout.

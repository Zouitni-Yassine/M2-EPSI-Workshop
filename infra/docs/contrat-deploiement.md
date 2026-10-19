# Contrat de déploiement des applications sur le Swarm

Règles à respecter pour que les services de l'équipe applicative soient déployables,
supervisés et réparables automatiquement. L'exemple complet et testé est
[`infra/remediation/demo-stack.yml`](../remediation/demo-stack.yml).

**En une phrase** : un fichier Compose, des images déjà construites, un healthcheck par
service, des politiques de redémarrage et de retour arrière, les métriques sur le réseau
`monitoring`, les secrets en secrets Docker, et rien de publié à part le frontal.

## 1. Format et déploiement

- **Format Compose standard**, déployé par `docker stack deploy -c stack.yml <stack>`.
  Le même fichier sert en local (`docker compose`) et sur le cluster.
- **Nom de stack** : un nom court en minuscules, par exemple `paiement`. Les services
  deviennent `paiement_api`, `paiement_db`… Le moteur de remédiation ne peut agir que sur
  les stacks déclarées dans `remediation_allowed_stacks` (`infra/ansible/inventory/group_vars/swarm.yml`).
- **Pas de `build:`** : Swarm ne construit pas d'image, il les télécharge sur chaque nœud.
  Les images doivent être poussées dans un registre accessible aux workers, avec un
  **tag figé** (`api:1.4.2`, jamais `latest`), sinon un retour arrière ne revient pas à la
  même image. Le registre est **à décider** : GHCR, Docker Hub, ou un registre privé dans le
  Swarm.
- **Clés Compose ignorées par Swarm**, à ne pas utiliser : `build`, `container_name`,
  `depends_on` (l'ordre de démarrage n'est pas garanti : l'application doit savoir attendre
  sa base et réessayer), `restart` (remplacé par `deploy.restart_policy`) et `tmpfs`
  (remplacé par `volumes: - { type: tmpfs, target: /tmp }`).

## 2. Ce que chaque service doit déclarer

```yaml
services:
  api:
    image: ghcr.io/<org>/paiement-api:1.4.2
    healthcheck:                         # obligatoire : sans lui, Swarm ne sait pas si le service va bien
      test: ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:8000/health"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 20s
    networks: [front, back, monitoring]
    secrets: [db_password]
    deploy:
      replicas: 2                        # au moins 2 pour l'API : un redémarrage ne coupe pas le service
      placement:
        constraints: [node.role == worker]
        preferences:
          - spread: node.labels.pve_node # réplicas sur des hyperviseurs différents
      resources:
        limits: { cpus: "1", memory: 512M }
        reservations: { memory: 128M }
      restart_policy: { condition: any, delay: 5s, window: 30s }
      update_config:                     # mise à jour progressive, retour arrière automatique
        parallelism: 1
        order: start-first
        failure_action: rollback
        monitor: 30s
      rollback_config: { parallelism: 1, order: start-first }
```

| Élément | Pourquoi |
|---|---|
| `healthcheck` sur `/health` | Swarm remplace seul un conteneur malade et refuse une mise à jour défaillante. `/health` doit vérifier les dépendances essentielles (base de données), pas seulement répondre 200. |
| `replicas: 2` et `spread` | La perte d'un nœud ou d'un hyperviseur ne coupe pas le service. |
| `limits` | Un service qui fuit ou subit un déni de service ne peut pas saturer le nœud. |
| `update_config` | Une mauvaise version revient automatiquement à la précédente. |
| `constraints: node.role == worker` | Les managers sont drainés et réservés au plan de contrôle. |

**Piège** : ne pas combiner `max_replicas_per_node: 1` avec `order: start-first` si le
nombre de réplicas peut atteindre le nombre de workers (3). La mise à jour se bloque, faute
de nœud libre pour démarrer la nouvelle tâche.

## 3. Réseaux et exposition

| Réseau | Usage |
|---|---|
| `front` | Frontal web, derrière le WAF |
| `back` | API, authentification |
| `data` | Base de données, avec `internal: true` (pas d'accès sortant) |
| `monitoring` | **Externe**, créé par l'infra : à rejoindre pour être scrapé |

- **Seul le point d'entrée web est publié** (`ports:`), derrière le WAF. Base de données,
  API interne, moteur de remédiation et interfaces d'administration ne publient **aucun
  port** : ils communiquent par les réseaux overlay.
- Déclaration du réseau de supervision :

```yaml
networks:
  monitoring:
    external: true
```

## 4. Métriques

- Exposer les métriques au **format Prometheus** sur un port HTTP, par exemple
  `:8000/metrics` ou un port dédié (bibliothèques `prometheus-client` en Python,
  `prom-client` en Node.js, `client_golang` en Go).
- Attacher le service au réseau `monitoring`, puis déclarer la cible dans
  `swarm_scrape_targets` (`infra/ansible/inventory/group_vars/swarm.yml`) :

```yaml
swarm_scrape_targets:
  - { service: paiement_api, port: 8000, path: /metrics }
```

- Le vmagent du Swarm découvre chaque réplica par DNS (`tasks.paiement_api`). Les séries
  arrivent dans VictoriaMetrics avec les labels `job`, `service`, `stack` et `instance`, et
  une réplica injoignable déclenche l'alerte `TargetDown`.
- Métriques utiles pour la détection et la démo : transactions par statut
  (`payments_total{status="ok|error|refused"}`), latence (histogramme), erreurs HTTP par code,
  échecs d'authentification. Le CPU, la mémoire et le réseau des conteneurs sont déjà
  collectés par cAdvisor, sans rien faire.

## 5. Logs

- Écrire sur **stdout / stderr**, sans fichier de log dans le conteneur, et sans changer le
  driver de logs : le driver journald du cluster envoie tout à Loki, avec les labels
  `service` et `stack`.
- Une ligne par événement, en **JSON** de préférence (`{"level":"error","msg":...,"tx_id":...}`) :
  Loki peut alors filtrer sur les champs (`| json | level="error"`).
- Ne jamais écrire de secret, de jeton ou de numéro de carte dans les logs.

## 6. Secrets

- Les secrets passent par des **secrets Docker** : le conteneur les lit dans
  `/run/secrets/<nom>`, jamais dans une variable d'environnement en clair ni dans le dépôt.
  Côté code : lire `DB_PASSWORD_FILE=/run/secrets/db_password` plutôt que `DB_PASSWORD`.
- Leur création (depuis Vault ou SOPS) est faite par l'équipe cyber. La stack les déclare en
  `external: true`.

## 7. Durcissement attendu

- Utilisateur **non root** dans l'image (`USER` dans le Dockerfile).
- `read_only: true`, avec un volume `tmpfs` pour `/tmp` si l'application écrit des fichiers
  temporaires.
- `cap_drop: [ALL]`, et ne rajouter que les capacités nécessaires.
- **Jamais** de montage du socket Docker (`/var/run/docker.sock`) : c'est un accès root à
  tout le cluster. Le moteur de remédiation passe par la passerelle (section 8).

## 8. Intégration du moteur de remédiation

Le moteur tourne comme un service de la stack applicative, sur les workers. Il agit sur le
cluster **uniquement** par la passerelle `remediate` des managers, en SSH, avec une clé
limitée à une liste fermée d'actions. Le détail est dans [remediation.md](remediation.md).

```yaml
services:
  remediation:
    image: ghcr.io/<org>/remediation-engine:1.0.0
    secrets:
      - source: remediation_ssh_key            # créé par l'infra
        target: id_ed25519
        mode: 0400
      - source: remediation_alertmanager_password   # créé par l'infra : compte "remediation"
        target: alertmanager_password
        mode: 0400
    configs:
      - source: remediation_known_hosts        # créé par l'infra : empreintes des managers
        target: /etc/ssh/ssh_known_hosts
    environment:
      REMEDIATION_GATEWAYS: "10.0.1.211,10.0.1.212,10.0.1.213"  # essayer le suivant si l'un ne répond pas
      ALERTMANAGER_URL: "http://10.0.1.233:9093"
      ALERTMANAGER_USER: "remediation"
    networks: [back]
    deploy:
      replicas: 1
      placement:
        constraints: [node.role == worker]    # obligatoire : la clé n'est acceptée que depuis les workers

secrets:
  remediation_ssh_key:
    external: true
  remediation_alertmanager_password:
    external: true
configs:
  remediation_known_hosts:
    external: true
```

Appel depuis le moteur (sortie JSON sur stdout, code retour significatif) :

```sh
ssh -T -i /run/secrets/id_ed25519 -o BatchMode=yes -o ConnectTimeout=5 \
    remediation@10.0.1.211 "restart paiement_api"
```

**Réception des alertes : le moteur interroge Alertmanager** (toutes les 5 s), il ne reçoit
pas de webhook. Alertmanager tourne hors du Swarm (monitoring01) : pour recevoir un webhook,
le moteur devrait publier un port, et un port publié par Swarm contourne le firewall des
hôtes. En interrogeant l'API, le moteur n'a **aucun port entrant**.

```sh
curl -s -u remediation:$(cat /run/secrets/alertmanager_password) \
  'http://10.0.1.233:9093/api/v2/alerts?active=true&silenced=false&inhibited=false&filter=remediation%3D%22auto%22'
```

La réponse est une liste d'alertes. Pour chacune : `labels` (dont `alertname`, `service`,
`stack`, `action`), `annotations.summary`, `startsAt` et `fingerprint`. Le `fingerprint`
identifie l'alerte : à mémoriser pour ne pas traiter deux fois le même incident.

Labels posés sur les règles d'alerte qui déclenchent la remédiation :

| Label | Valeur | Rôle |
|---|---|---|
| `remediation` | `auto` | à traiter par le moteur (les autres alertes sont pour les humains) |
| `service`, `stack` | `paiement_api`, `paiement` | cible de l'action |
| `action` | `restart`, `rollback`, `scale` | action suggérée ; le moteur reste libre de décider |

Le moteur peut aussi poser un **silence** sur l'alerte qu'il traite (`POST /api/v2/silences`),
pour qu'Alertmanager n'en renvoie pas de copie sur Discord pendant la remédiation.
Les règles d'alerte métier sont écrites ensemble, dans `infra/monitoring/vmalert/rules/`.

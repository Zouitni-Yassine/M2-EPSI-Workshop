# Resilience Pay — moteur de remédiation

Le composant qui fait la différence entre une panne réparée par un humain (0/5) et
une reprise autonome. Il écoute le détecteur, décide, agit sur le conteneur visé,
puis vérifie que le métier répond avant de déclarer la reprise.

## Ce qu'il fait, dans l'ordre

| Étape | Action | Événement publié |
| --- | --- | --- |
| 1 | Lit `GET /score` du détecteur chaque seconde | — |
| 2 | `over = true` et pas de remédiation en cours → décision | « Anomalie confirmée par le détecteur » · « Décision : recréer payment-api » |
| 3 | `POST /containers/payment-api/restart` via le proxy Docker (mode `docker`), ou `restart <service>` par la passerelle SSH des managers (mode `ssh`, voir plus bas) | « payment-api redémarré via le proxy Docker » · « paiement_payment-api redémarré par la passerelle 10.30.1.211 en 42 s » |
| 4 | Attend que `GET /api/status` réponde **et** que la sonde Stripe passe (40 s max) | « Transaction de contrôle passée » |
| 5 | Attend que le détecteur retire son verdict (30 s max) | « Service rétabli en N s — 0 intervention humaine » |
| 6 | Temporisation de 45 s avant toute nouvelle action | — |

La reprise est jugée sur le **métier** (API + Stripe), pas sur l'état du conteneur.
C'est la distinction que le sujet impose : un conteneur qui redémarre ne prouve rien.

## Ce qu'il ne peut pas faire — par construction

Le sujet prévient (§3.4) : un moteur de remédiation a des droits élevés et ne doit pas
devenir une porte d'entrée. Trois garde-fous :

- **Il ne voit jamais le socket Docker.** Sur le Swarm (mode `ssh`), il n'a qu'une clé SSH
  qui n'ouvre qu'une liste fermée d'actions sur les managers (voir plus bas). En local, il parle à `docker-socket-proxy`, un nginx à liste
  blanche de deux requêtes : `GET /containers/json` et `POST /containers/payment-api/restart`
  (`proxy/nginx.conf`). Tout le reste répond 403 — pas d'`exec`, pas de création, pas d'arrêt,
  pas d'images. Vérifié depuis le conteneur du moteur. Le proxy tourne en lecture seule, sans
  capacité, sur un réseau Docker `internal` injoignable de l'extérieur.
- **Il ne redémarre que sa liste.** `TARGETS=payment-api`. Toute autre cible lève `PermissionError`.
- **Il n'expose aucune route d'écriture.** `GET /health`, `GET /state`, c'est tout. Personne ne peut
  lui demander d'agir ; seul le verdict du détecteur le déclenche.

## Routes

| Route | Rôle |
| --- | --- |
| `GET /health` | état et cibles autorisées |
| `GET /state` | `idle` ou `remediating`, journal des actions, compteur d'interventions humaines (0), durée de la dernière reprise |

La supervision lit `/state` chaque seconde : l'état bleu « Remédiation en cours » et les
événements de la chronologie viennent de là.

## Variables

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `DETECTOR_URL` | `http://detector:8100` | d'où vient le verdict |
| `API_URL` | `http://payment-api:8000/api` | ce qu'on vérifie après l'action |
| `DOCKER_URL` | `http://docker-socket-proxy:2375` | le seul chemin vers Docker |
| `TARGETS` | `payment-api` | conteneurs (mode `docker`) ou services Swarm (mode `ssh`) qu'on a le droit de redémarrer |
| `COOLDOWN_SECONDS` | `45` | délai minimal entre deux actions |
| `VERIFY_TIMEOUT` | `40` | temps accordé au service pour revenir |
| `REMEDIATION_MODE` | `docker` | `docker` : proxy du socket (compose local) ; `ssh` : passerelle du Swarm |
| `REMEDIATION_GATEWAYS` | — | mode `ssh` : managers portant la passerelle, essayés dans l'ordre |
| `REMEDIATION_SSH_USER` | `remediation` | mode `ssh` : compte de la passerelle |
| `REMEDIATION_SSH_KEY_FILE` | `/run/secrets/remediation_ssh_key` | mode `ssh` : clé privée (secret Swarm) |
| `REMEDIATION_KNOWN_HOSTS_FILE` | `/run/configs/remediation_known_hosts` | mode `ssh` : empreintes des managers (config Swarm) |
| `REMEDIATION_SSH_TIMEOUT` | `200` | mode `ssh` : attente maximale d'une réponse (la passerelle attend la convergence, 180 s au plus) |

## Mode `ssh` : sur le cluster Swarm

Sur le Swarm, pas de socket Docker (règle du contrat de déploiement de l'infra), et la tâche
visée peut tourner sur n'importe quel nœud. Le moteur passe alors par la **passerelle
`remediate`** des managers (`infra/docs/remediation.md`) :

```sh
ssh -T -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=/run/configs/remediation_known_hosts -o ConnectTimeout=5 \
    -i /tmp/remediation-key-XXXX remediation@10.30.1.211 "restart paiement_payment-api"
```

- **Passerelles en série** : si ssh ne joint pas un manager (code 255 : réseau, empreinte,
  authentification), on essaie le suivant, et la chronologie le dit. Une réponse de la
  passerelle, même un refus, est définitive. Un délai dépassé ne fait pas essayer le suivant :
  l'action est peut-être en cours, la relancer ailleurs la doublerait.
- **Codes de la passerelle** : 0 réussite (durée et réplicas dans l'événement) ; 2 requête
  invalide, 3 refus de la politique (stack non autorisée, interrupteur d'arrêt), 5 échec Docker
  → « Échec du redémarrage », puis la vérification habituelle ; **4 limite de débit** → pas un
  échec : « Action différée », pas de vérification, nouvel essai après `retry_in` secondes
  (au moins 5 s, `COOLDOWN_SECONDS` si la passerelle n'en donne pas). Jamais de boucle sans
  temporisation.
- **Clé** : le secret Swarm est copié au démarrage dans un fichier 0600 de `/tmp` (tmpfs, le
  conteneur est en lecture seule), car ssh peut refuser un fichier aux droits trop larges. La
  clé n'est jamais journalisée. Une clé absente est signalée dans les logs dès le démarrage.
- **Pas d'injection** : la cible vient de `TARGETS` (liste fermée) et doit en plus respecter la
  règle de nom de la passerelle (`^[a-z0-9][a-z0-9_.-]{0,62}$`) ; ssh est lancé par
  `subprocess` avec une liste d'arguments, jamais par un shell. Les managers et le compte sont
  validés au démarrage.
- **Vérification de reprise** : inchangée (`/api/status` + Stripe, puis verdict du détecteur).

Exemple de service dans la stack Swarm (le reste est dans `infra/docs/contrat-deploiement.md`) :

```yaml
  remediation:
    image: <registre>/remediation:<tag figé>
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    volumes:
      - { type: tmpfs, target: /tmp }          # copie 0600 de la clé
    secrets:
      - source: remediation_ssh_key
        target: remediation_ssh_key
        uid: "10003"                            # utilisateur de l'image
        mode: 0400
    configs:
      - source: remediation_known_hosts
        target: /run/configs/remediation_known_hosts
    environment:
      REMEDIATION_MODE: ssh
      REMEDIATION_GATEWAYS: "10.30.1.211,10.30.1.212,10.30.1.213"
      REMEDIATION_SSH_KEY_FILE: /run/secrets/remediation_ssh_key
      REMEDIATION_KNOWN_HOSTS_FILE: /run/configs/remediation_known_hosts
      REMEDIATION_SSH_USER: remediation
      TARGETS: paiement_payment-api             # nom du service Swarm : <stack>_<service>
    deploy:
      placement:
        constraints: [node.role == worker]    # la clé n'est acceptée que depuis les workers
```

## Tests

```sh
cd remediation
pip install -r requirements.txt pytest
python -m pytest -q tests
```

Les tests remplacent `requests.post` et `subprocess.run` : aucun appel réseau. Ils couvrent le
mode `docker` inchangé, le mode `ssh` (réussite, première passerelle injoignable, aucune
passerelle, délai dépassé, refus, code 4, cible invalide ou hors liste refusée sans appel ssh,
clé absente).

## Limites, à dire au jury

- Une seule action possible : redémarrer. Bannir une IP au WAF, restaurer une base, basculer
  sur une réplique — ce sont les playbooks suivants, et ils demandent un WAF et une base.
- Si le service ne revient pas en 40 s, le moteur le dit (« escalade nécessaire ») et s'arrête.
  Il ne boucle pas : relancer à l'infini un conteneur qui ne revient pas, c'est aggraver la panne.

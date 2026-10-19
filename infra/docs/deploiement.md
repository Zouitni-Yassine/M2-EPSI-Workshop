# Déploiement de l'infrastructure

Ce guide part d'un cluster Proxmox VE 9 vide (3 nœuds Ceph) et aboutit au cluster Docker Swarm
supervisé. Chaque étape est rejouable : relancer une commande sur une infra déjà en place ne casse rien.

| Étape | Outil | Résultat |
|---|---|---|
| 1 | Terraform | Template `debian13-cloud` (VMID 9000), image cloud Debian 13 brute |
| 2 | Packer | Template `debian13-docker` (VMID 9100) : Debian 13 + Docker CE, durci |
| 3 | Terraform | 6 VM Swarm, 3 LXC de supervision, HA Proxmox |
| 4 | Ansible | Cluster Swarm, stack d'observabilité, dashboards, alertes |
| 5 | — | Vérifications |

Plan d'adressage (LAN `10.0.1.0/24`, VMID = dernier octet de l'IP) :

| Machine | IP | Hyperviseur d'origine | Rôle |
|---|---|---|---|
| ceph01 / ceph02 / ceph03 | .100 / .101 / .102 | — | Proxmox VE + Ceph |
| poste de contrôle | .110 | — | Terraform, Packer, Ansible, dépôt Git |
| dockermgr01-03 | .211-.213 | ceph01-03 | Managers Swarm (drainés) |
| dockerwrk01-03 | .221-.223 | ceph01-03 | Workers Swarm |
| vmagent01 / vmagent02 | .231 / .232 | ceph02 / ceph03 | Collecte des métriques |
| monitoring01 | .233 | ceph01 | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana |

---

## 1. Prérequis

### Poste de contrôle (10.0.1.110)

Versions utilisées et validées :

| Outil | Version |
|---|---|
| Terraform | 1.16.6 (provider `bpg/proxmox` 0.117.0, figé dans `.terraform.lock.hcl`) |
| Packer | 1.16.1 (plugin `hashicorp/proxmox` ~> 1.2) |
| Ansible | ansible-core 2.19 |
| Collections | `community.docker` 4.7.0, `community.general` 11.2.1 |
| Python | 3.13, avec `passlib` (hachage des mots de passe Alertmanager et Loki par `password_hash`) |

Organisation :

- Dépôt cloné dans `/srv/M2-EPSI-Workshop`, branche `DEV`.
- `/terraform` est un lien symbolique vers `/srv/M2-EPSI-Workshop/infra/terraform`.
- Le wrapper `/usr/local/bin/tf` est une copie de `infra/terraform/scripts/tf` :

  ```sh
  install -m 0755 /srv/M2-EPSI-Workshop/infra/terraform/scripts/tf /usr/local/bin/tf
  ln -s /srv/M2-EPSI-Workshop/infra/terraform /terraform
  ```

### Clés SSH

| Clé | Usage |
|---|---|
| `/root/.ssh/id_ed25519_proxmox` | Terraform vers les hyperviseurs (root), pour les opérations que l'API ne couvre pas (import de disque) |
| `/root/.ssh/id_ed25519_infra` | Clé injectée par cloud-init dans les VM (utilisateur `debian`) et dans les LXC (`root`). Utilisée par Packer et Ansible |

`ansible.cfg` active `host_key_checking`. Après la création ou la recréation d'une machine,
enregistrer sa clé d'hôte :

```sh
ssh-keygen -R 10.0.1.221 && ssh-keyscan -t ed25519 10.0.1.221 >> /root/.ssh/known_hosts
```

### Proxmox : utilisateurs, rôles, tokens

| Utilisateur | Token | Rôle (ACL sur `/`) | Usage |
|---|---|---|---|
| `terraform@pve` | `tf` | `TerraformRole` | Terraform |
| `terraform@pve` | `packer` | `TerraformRole` | Packer |
| `svc_monitoring@pve` | `monitoring` | `PVEAuditor` | prometheus-pve-exporter (lecture seule) |

`TerraformRole` regroupe les privilèges `Datastore.*`, `Pool.*`, `SDN.Use`, `Sys.Audit`,
`Sys.Console`, `Sys.Modify` et `VM.*` (allocation, clone, config, migrate, power, snapshot...).

Trois pièges :

- **Un token créé avec `privsep=1` n'hérite pas des droits de son utilisateur.** Il ne reçoit que
  l'intersection entre ses propres ACL et celles de l'utilisateur. Sans ACL propre, il ne voit
  presque rien. Il faut donc donner l'ACL à l'utilisateur **et** au token :

  ```sh
  pveum acl modify / --users 'svc_monitoring@pve' --roles PVEAuditor
  pveum acl modify / --tokens 'svc_monitoring@pve!monitoring' --roles PVEAuditor
  ```

- **L'API HA (`/cluster/ha/...`) exige `Sys.Console`.** Sans ce privilège, `proxmox_haresource`
  et `proxmox_harule` échouent.
- **Les commentaires HA doivent être en ASCII.** Un caractère accentué provoque une erreur
  500 « Wide character » (voir le dépannage).

### Hyperviseurs (hors Ansible)

Aucun playbook ne configure les nœuds Proxmox. Ils sont seulement des cibles de supervision. À faire
une fois, sur chaque nœud :

```sh
apt install prometheus-node-exporter      # métriques système des hyperviseurs (:9100)
```

Sur un seul nœud, pour activer le module Prometheus du mgr Ceph (`:9283`, servi par le mgr actif) :

```sh
ceph mgr module enable prometheus
```

---

## 2. Secrets

Aucun secret n'est dans le dépôt, et le dépôt est public. Les `.gitignore` excluent `.env`,
`*.env`, `*.tfstate*`, `*.tfplan`, `*.tfvars`, `*.pkrvars.hcl`, `backend.hcl`, `id_*`, `*.pem`
et `*.key`. Avant chaque push, un scan compare le diff sortant aux valeurs réelles des secrets.

Les secrets vivent dans quatre fichiers du poste de contrôle, tous en `chmod 600`.

### `/terraform/.env` (source de vérité pour les tokens et le S3)

```ini
TOKEN-ID=
TOKEN-SECRET=
MONITOR-TOKEN-ID=
MONITOR-TOKEN-SECRET=
S3-ACCESS-KEY=
S3-SECRET-KEY=
```

### `/root/.proxmox-env` (Terraform et Packer)

Chargé automatiquement par le wrapper `tf`. Pour Packer, le charger à la main.

```sh
export PROXMOX_VE_API_TOKEN=          # "<TOKEN-ID>=<TOKEN-SECRET>", construit depuis /terraform/.env
export PKR_VAR_proxmox_token_id=      # terraform@pve!packer
export PKR_VAR_proxmox_token_secret=
export AWS_ACCESS_KEY_ID=             # S3-ACCESS-KEY de /terraform/.env (backend du state)
export AWS_SECRET_ACCESS_KEY=         # S3-SECRET-KEY de /terraform/.env
```

### `/root/.monitoring-env` (Ansible)

À charger avec `source` avant **tout** playbook, y compris `swarm.yml` : Alloy, sur les nœuds
Swarm, a besoin du mot de passe de Loki.

```sh
export GRAFANA_ADMIN_PASSWORD=        # >= 16 caractères ; appliqué au premier démarrage de Grafana uniquement
export HEALTHCHECKS_PING_URL=         # vide = route Watchdog désactivée
export PVE_MONITOR_TOKEN_ID=          # MONITOR-TOKEN-ID de /terraform/.env
export PVE_MONITOR_TOKEN_SECRET=      # MONITOR-TOKEN-SECRET de /terraform/.env
export DISCORD_WEBHOOK_URL=           # vide = pas d'envoi vers Discord
export VM_AUTH_PASSWORD=              # VictoriaMetrics, vmagent, vmalert (utilisateur "monitoring")
export ALERTMANAGER_AUTH_PASSWORD=    # Alertmanager (utilisateur "monitoring")
export LOKI_AUTH_PASSWORD=            # Loki via nginx (utilisateur "monitoring")
```

`monitoring.yml` refuse de démarrer si un mot de passe fait moins de 16 caractères ou si le token
PVE est absent. Pour générer un mot de passe :

```sh
openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32
```

### `infra/terraform/backend.hcl` (non versionné)

Copie de `backend.hcl.example`, versionné :

```hcl
bucket    = "<nom-du-bucket>"
endpoints = { s3 = "https://<domaine-s3>" }
```

Pour une nouvelle installation, on peut versionner des fichiers d'exemple qui ne contiennent que les
noms de variables ci-dessus : `env.example`, `proxmox-env.example` et `monitoring-env.example`.

---

## 3. Déploiement

### Étape 1 : template `debian13-cloud` (Terraform)

`template-debian13.tf` télécharge l'image cloud officielle Debian 13 (checksum SHA-512 vérifié) sur
`ceph01`. Il l'importe ensuite comme disque d'un template (VMID 9000), avec un lecteur cloud-init,
une console série et l'utilisateur `debian` muni de la clé `id_ed25519_infra.pub`.

Première initialisation, avec le backend S3 :

```sh
cd /terraform
cp backend.hcl.example backend.hcl    # puis renseigner bucket et endpoint
source /root/.proxmox-env
terraform init -backend-config=backend.hcl
```

Lors d'une installation à partir de zéro, le template 9100 n'existe pas encore. Il faut donc
cibler le template 9000 seul :

```sh
tf apply -target=proxmox_virtual_environment_vm.debian13_cloud
```

#### Pourquoi le state est sur S3 sans `use_lockfile`

Le state est sur un bucket S3 externe (DataCore Swarm). Le verrouillage natif de Terraform
(`use_lockfile`) repose sur des écritures conditionnelles (`If-None-Match`), que ce stockage
refuse (HTTP 501, testé). C'est le wrapper `tf` qui prend le verrou, avec
`flock -n /run/lock/terraform.lock`. Si une autre exécution est en cours, il sort avec le code 75.

**Toujours passer par `tf`, jamais par `terraform` directement**, sauf pour le `init`. Le verrou
n'est valable que sur le poste de contrôle : Terraform n'est lancé que depuis .110.

### Étape 2 : template `debian13-docker` (Packer)

Packer clone le 9000 en VM temporaire (IP de build `10.0.1.200`), puis lance les scripts
`scripts/00-wait-cloud-init.sh`, `10-base.sh`, `20-docker.sh`, `30-hardening.sh` et `90-cleanup.sh`.
Il convertit enfin la VM en template 9100 avec un lecteur cloud-init.

```sh
source /root/.proxmox-env
cd /srv/M2-EPSI-Workshop/infra/packer/debian13-docker
packer init .
packer build .
```

Pour reconstruire le template, supprimer d'abord le 9100 existant : Packer ne remplace pas un
VMID occupé. Les VM déjà clonées ne sont pas touchées, car Terraform ignore les changements de
`clone`.

### Étape 3 : VM Swarm, LXC de supervision et HA (Terraform)

```sh
tf plan
tf apply
```

Ce que l'apply crée :

- **`swarm.tf`** : 6 VM, clones complets du 9100. Managers : 2 vCPU, 4 Go de RAM, 30 Go de disque.
  Workers : 4 vCPU, 12 Go, 80 Go. Un manager et un worker par hyperviseur.
- **`monitoring.tf`** : 3 LXC Debian 13 non privilégiés, avec `nesting=1`, requis par le sandboxing
  systemd. Le template LXC est téléchargé sur chacun des 3 nœuds, car le stockage `local` n'est pas
  partagé.
- **`ha.tf`** : HA sur les 9 invités (`max_restart 2`, `max_relocate 1`, `failback`), plus deux
  types de règles :
  - `home-cephXX` (node-affinity non stricte) : chaque invité préfère son nœud d'origine et y
    revient quand le nœud remonte ;
  - `vmagents-apart` (resource-affinity négative) : les 2 vmagents ne sont jamais sur le même
    hyperviseur. Proxmox interdit de mettre une ressource à la fois dans cette règle et dans une
    règle node-affinity à plusieurs priorités, d'où l'exclusion des vmagents des règles `home-*`.

`node_name` est ignoré après la création (`lifecycle.ignore_changes`) : une migration HA ne
provoque pas de dérive dans Terraform.

### Étape 4 : configuration (Ansible)

```sh
cd /srv/M2-EPSI-Workshop/infra/ansible
source /root/.monitoring-env
ansible-playbook site.yml               # = swarm.yml puis monitoring.yml
```

On peut aussi lancer les deux playbooks séparément, dans cet ordre :

| Playbook | Cibles | Contenu |
|---|---|---|
| `swarm.yml` | `swarm` | Rôles `docker_host` (daemon.json, nftables) et `alloy`, nœud par nœud (`serial: 1`) pour préserver le quorum. Puis `swarm init`, `join`, labels `role` et `pve_node`, drain des managers. cAdvisor sur les workers |
| `monitoring.yml` | `monitoring` | `lxc_base` et `alloy` sur les 3 LXC. `pve_exporter` et `vmagent` sur les vmagents. `vmsingle`, `alertmanager`, `vmalert`, `loki` (+ nginx), `grafana` sur monitoring01 |

Les playbooks sont idempotents : un second passage doit afficher `changed=0`.

Si l'on change les mots de passe de la stack, lancer `swarm.yml` **avant** `monitoring.yml`. Un
client qui envoie des identifiants à un serveur qui ne les exige pas encore n'est pas gêné.
L'inverse provoquerait des refus (401) le temps du déploiement.

### Étape 5 : vérifications

Préparation :

```sh
source /root/.monitoring-env
M=10.0.1.233
K=/root/.ssh/id_ed25519_infra
```

**Swarm** : 6 nœuds `Ready`, les 3 managers `Drain`, un `Leader` :

```sh
ssh -i $K debian@10.0.1.211 sudo docker node ls
```

**Authentification.** Sans identifiants, chaque URL doit répondre `401` :

```sh
for u in $M:8428/api/v1/query?query=up 10.0.1.231:8429/targets $M:8880/api/v1/alerts \
         $M:9093/api/v2/status $M:3100/loki/api/v1/labels; do
  curl -s -o /dev/null -w "%{http_code}  $u\n" http://$u
done
```

Avec identifiants, chaque requête doit répondre `200` :

```sh
curl -s -o /dev/null -w "%{http_code}\n" -u monitoring:$VM_AUTH_PASSWORD           "http://$M:8428/api/v1/query?query=up"
curl -s -o /dev/null -w "%{http_code}\n" -u monitoring:$ALERTMANAGER_AUTH_PASSWORD http://$M:9093/api/v2/status
curl -s -o /dev/null -w "%{http_code}\n" -u monitoring:$LOKI_AUTH_PASSWORD         http://$M:3100/loki/api/v1/labels
```

**Cibles de scrape.** Le résultat doit être vide :

```sh
curl -s -u monitoring:$VM_AUTH_PASSWORD --data-urlencode 'query=up == 0' http://$M:8428/api/v1/query
```

**Logs.** Chaque hôte doit apparaître :

```sh
curl -s -u monitoring:$LOKI_AUTH_PASSWORD -G http://$M:3100/loki/api/v1/query \
  --data-urlencode 'query=sum by (host) (count_over_time({job="journal"}[5m]))'
```

**Grafana** : ouvrir http://10.0.1.233:3000 (utilisateur `admin`, mot de passe
`GRAFANA_ADMIN_PASSWORD`). Contrôler l'état des sources :

```sh
for ds in victoriametrics loki; do
  curl -s -u admin:$GRAFANA_ADMIN_PASSWORD http://$M:3000/api/datasources/uid/$ds/health; echo
done
curl -s -o /dev/null -w "%{http_code}\n" -u admin:$GRAFANA_ADMIN_PASSWORD \
  http://$M:3000/api/datasources/proxy/uid/alertmanager/api/v2/status   # 200
```

**Alerte de test.** Elle doit arriver sur Discord après environ 30 s (`group_wait`) :

```sh
curl -s -u monitoring:$ALERTMANAGER_AUTH_PASSWORD -H 'Content-Type: application/json' \
  -X POST http://$M:9093/api/v2/alerts -d '[{
    "labels": {"alertname":"TestDeploiement","severity":"info","host":"monitoring01","job":"test"},
    "annotations": {"summary":"Alerte de test du guide de déploiement"}}]'
```

Pour la résoudre, renvoyer le même JSON avec `"endsAt"` à l'heure courante :

```sh
date -u +%Y-%m-%dT%H:%M:%SZ
```

**Watchdog.** L'alerte `Watchdog` est toujours active et Alertmanager la renvoie chaque minute
vers healthchecks.io. Le check doit être vert sur healthchecks.io, et le compteur ci-dessous doit
augmenter sans échec :

```sh
curl -s -u monitoring:$ALERTMANAGER_AUTH_PASSWORD http://$M:9093/metrics \
  | grep -E 'alertmanager_notifications(_failed)?_total\{integration="(webhook|discord)"'
```

**HA** : toutes les ressources doivent être en `started` :

```sh
ssh -i /root/.ssh/id_ed25519_proxmox root@10.0.1.100 ha-manager status
```

---

## 4. Opérations courantes

### Ajouter un worker Swarm

1. Dans `infra/terraform/swarm.tf`, ajouter une entrée dans `local.swarm_nodes` :

   ```hcl
   dockerwrk04 = { role = "worker", vm_id = 224, ip = "10.0.1.224", node = "ceph01" }
   ```

   La ressource HA et l'appartenance à la règle `home-<nœud>` suivent automatiquement, via
   `local.ha_guests` dans `ha.tf`.
2. Lancer `tf apply`.
3. Dans `infra/ansible/inventory/hosts.yml`, sous `swarm_workers`, ajouter :

   ```yaml
   dockerwrk04: { ansible_host: 10.0.1.224, pve_node: ceph01 }
   ```

4. Enregistrer la clé d'hôte (`ssh-keyscan`, voir les prérequis).
5. Lancer `ansible-playbook swarm.yml` : le nœud rejoint le Swarm.
6. Lancer `ansible-playbook monitoring.yml --limit vmagents` : les cibles node, docker et cAdvisor
   du nouveau nœud sont ajoutées au scrape.

### Monter de version VictoriaMetrics

Modifier `vm_version` dans `inventory/group_vars/monitoring.yml`, puis lancer
`ansible-playbook monitoring.yml`.

Le rôle `vm_install` télécharge la release GitHub et vérifie son checksum dans
`/opt/victoriametrics/<version>/`. Il bascule ensuite le lien `/usr/local/bin/<binaire>` et
redémarre les services concernés. L'ancienne version reste sur disque : pour revenir en arrière,
remettre l'ancienne valeur de `vm_version` et relancer le playbook.

### Ajouter un dashboard Grafana

1. Déposer le JSON dans `monitoring/grafana/dashboards/<Dossier>/`. Le nom du répertoire devient
   le dossier Grafana.
2. Lancer `ansible-playbook monitoring.yml --limit monitoring_core`.

Grafana relit les fichiers toutes les 60 s. Un fichier retiré du dépôt est supprimé du serveur,
et le dashboard disparaît (`disableDeletion: false`). Les dashboards ne sont pas modifiables dans
l'interface (`allowUiUpdates: false`) : on modifie le fichier.

Deux dashboards sont générés par script : `monitoring/grafana/scripts/gen-central-dashboard.py` et
`monitoring/grafana/scripts/gen-proxmox-dashboard.py`. Les dashboards communautaires viennent de
`monitoring/grafana/scripts/fetch-dashboards.py`.

### Ajouter une règle d'alerte

1. Ajouter la règle dans `infra/monitoring/vmalert/rules/monitoring.yml`, ou dans un nouveau
   fichier `.yml` du même dossier : tous les fichiers du dossier sont déployés et validés
   (`vmalert -dryRun`) avant d'être installés.
2. Mettre les labels `severity` et, si possible, `host`, ainsi qu'une annotation `summary` : ces
   champs sont repris dans le message Discord.
3. Lancer `ansible-playbook monitoring.yml --limit monitoring_core`.

Chaque fichier est validé par `vmalert -dryRun` avant d'être copié, puis vmalert est rechargé.

### Faire tourner un secret

Exemple avec le mot de passe de Loki :

```sh
# 1. remplacer la valeur de LOKI_AUTH_PASSWORD dans /root/.monitoring-env
source /root/.monitoring-env
cd /srv/M2-EPSI-Workshop/infra/ansible
ansible-playbook swarm.yml          # Alloy des nœuds Swarm
ansible-playbook monitoring.yml     # Alloy des LXC, vmagents (scrape), htpasswd nginx, Grafana
```

Pendant la rotation, les pushes refusés sont retentés par Alloy.

| Secret | À faire |
|---|---|
| `VM_AUTH_PASSWORD`, `ALERTMANAGER_AUTH_PASSWORD` | `monitoring.yml` seul suffit : seuls les LXC les utilisent |
| `DISCORD_WEBHOOK_URL`, `HEALTHCHECKS_PING_URL` | `monitoring.yml --limit monitoring_core` |
| `GRAFANA_ADMIN_PASSWORD` | N'est appliqué qu'à la création de la base de Grafana. Ensuite : `grafana cli admin reset-admin-password` sur monitoring01 |
| Token Proxmox | Régénérer le token dans Proxmox, mettre à jour `/terraform/.env`, puis relancer `monitoring.yml --limit vmagents` (exporter PVE) |

### Reconstruire un LXC

Exemple avec `vmagent01` (procédure non testée à ce jour : vérifier le plan avant d'appliquer) :

```sh
tf apply -replace='proxmox_virtual_environment_container.monitoring["vmagent01"]' \
         -replace='proxmox_haresource.guests["vmagent01"]'
ssh-keygen -R 10.0.1.231 && ssh-keyscan -t ed25519 10.0.1.231 >> /root/.ssh/known_hosts
cd /srv/M2-EPSI-Workshop/infra/ansible && source /root/.monitoring-env
ansible-playbook monitoring.yml --limit vmagent01
```

Le second vmagent continue de collecter pendant la reconstruction.

Pour **monitoring01** :
- les données de VictoriaMetrics (30 jours) et de Loki (14 jours) sont perdues ;
- les vmagents gardent les métriques en tampon disque (jusqu'à `vmagent_buffer_max`, 8 Go) et
  les renvoient au retour du service ;
- tout le reste est recréé par le playbook : configuration, dashboards, sources et règles.

---

## 5. Dépannage

Erreurs rencontrées pendant la construction, avec leur cause et leur correctif.

| Symptôme | Cause | Correctif |
|---|---|---|
| Les VM clonées du 9100 ne prennent ni IP ni clé | Template Packer sans lecteur cloud-init | `cloud_init = true` et `cloud_init_storage_pool = "vm-fastec"` dans le `.pkr.hcl` |
| SSH injoignable sur un LXC après un reload | Le template LXC Proxmox active à la fois `ssh.socket` et `ssh.service`, qui se disputent le port 22 | `lxc_base` désactive `ssh.socket` et redémarre `ssh` au lieu de le recharger |
| HA : `500 Wide character` | Caractère accentué dans le `comment` d'une ressource ou d'une règle HA | Commentaires HA en ASCII uniquement |
| HA : `400 ... resources are in node affinity rules with multiple priorities` | Une ressource est à la fois dans une resource-affinity et dans une node-affinity à priorités multiples | Les vmagents sont exclus des règles `home-*` (`ha.tf`) |
| HA : création des règles en échec aléatoire | Terraform créait les règles en parallèle | `depends_on = [proxmox_harule.home_node]` sur `vmagents_apart` |
| HA : `403` sur `/cluster/ha` | Privilège `Sys.Console` absent du rôle du token | L'ajouter à `TerraformRole` |
| `terraform init` / `apply` : `501 Not Implemented` sur le state | `use_lockfile` envoie `If-None-Match`, que le stockage S3 ne gère pas | Pas de `use_lockfile`, verrou local via `tf` |
| Le dashboard Proxmox n'affiche presque aucun invité | Token de supervision `privsep=1` sans ACL propre | `pveum acl modify / --tokens 'svc_monitoring@pve!monitoring' --roles PVEAuditor` |
| Lignes en double dans les tableaux Grafana | La transformation *merge* exige des jeux de labels identiques, or `__name__` diffère d'une requête à l'autre | Envelopper chaque requête du tableau dans `max by (clé) (...)` |
| Un dashboard supprimé du dépôt reste dans Grafana | Fournisseur en `disableDeletion: true` et fichier resté sur le serveur | `disableDeletion: false`. La tâche Ansible supprime les JSON absents du dépôt |
| Mot de passe admin Grafana ignoré | `admin_password` n'est lu qu'à la création de la base | `grafana cli admin reset-admin-password` |
| Ansible : `pip` échoue sur un vmagent | `python3-packaging` absent | Installé par le rôle `pve_exporter` |
| `tar: Cannot change ownership to uid ...` en synchronisant depuis Windows | tar conserve les uid/gid Windows | `tar xf - --no-same-owner --no-same-permissions`, puis vérifier `git status` (bits d'exécution) |
| Un script envoyé par `ssh host 'bash -s' < script` s'arrête au milieu | Un `ssh` imbriqué dans le script consomme le reste de stdin | `ssh -n` pour les appels imbriqués |
| `401` dans les logs d'Alloy ou de vmagent | Mot de passe changé côté serveur avant les clients, ou `.monitoring-env` non chargé | `source /root/.monitoring-env`, puis relancer `swarm.yml` et `monitoring.yml` |

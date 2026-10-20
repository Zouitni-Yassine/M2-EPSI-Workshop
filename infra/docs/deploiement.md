# Déploiement de l'infrastructure

Ce guide part d'un cluster Proxmox VE 9 vide (3 nœuds Ceph) et aboutit au cluster Docker Swarm
supervisé. Chaque étape est rejouable : relancer une commande sur une infra déjà en place ne casse rien.

| Étape | Outil | Résultat |
|---|---|---|
| 1 | Terraform | Template `debian13-cloud` (VMID 9000), image cloud Debian 13 brute |
| 2 | Packer | Template `debian13-docker` (VMID 9100) : Debian 13 + Docker CE, durci |
| 3 | Terraform | 6 VM Swarm, 3 LXC de supervision, 3 LXC d'identité, HA Proxmox |
| 4 | Ansible | Cluster Swarm, stack d'observabilité, dashboards, alertes, identités et secrets |
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
| iam01 / vault01 / vaultwarden01 | .241 / .242 / .243 | ceph02 / ceph03 / ceph01 | Keycloak, Vault, Vaultwarden |
| waf01 | .251 | ceph01 | WAF de l'équipe cyber (hors Terraform) |

Groupes de l'inventaire Ansible (`inventory/hosts.yml`) :

| Groupe | Machines | Ce qu'Ansible y gère |
|---|---|---|
| `swarm` (`swarm_managers`, `swarm_workers`) | dockermgr01-03, dockerwrk01-03 | Tout (`swarm.yml`) |
| `monitoring` (`vmagents`, `monitoring_core`) | vmagent01-02, monitoring01 | Tout (`monitoring.yml`) |
| `identity` (`keycloak_servers`, `vault_servers`, `vaultwarden_servers`) | iam01, vault01, vaultwarden01 | Tout (`identity.yml`) |
| `pve` | ceph01-03 | CA interne, SSO Proxmox, envoi des logs (Alloy) |
| `control` | control01 (= .110, connexion locale) | Envoi des logs (Alloy) |
| `waf` | waf01 | **Envoi des logs seulement** (rôle `alloy`) : la VM et son firewall nftables appartiennent à l'équipe cyber |

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
- Trois scripts copiés dans `/usr/local/bin` :
  - `tf` (`infra/terraform/scripts/tf`) : Terraform avec verrou local, secrets lus dans Vault ;
  - `vault-env` (`infra/scripts/vault-env`) : lance une commande avec les secrets de Vault dans
    son environnement (§2) ;
  - `vault-unseal` (`infra/scripts/vault-unseal`) : descelle Vault après un redémarrage.

  ```sh
  R=/srv/M2-EPSI-Workshop/infra
  install -m 0755 $R/terraform/scripts/tf  /usr/local/bin/tf
  install -m 0755 $R/scripts/vault-env     /usr/local/bin/vault-env
  install -m 0755 $R/scripts/vault-unseal  /usr/local/bin/vault-unseal
  ln -s $R/terraform /terraform
  ```

  Après une modification d'un de ces scripts dans le dépôt, refaire le `install`.

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
| `terraform@pve` | `tf-20261020` | `TerraformRole` | Terraform |
| `terraform@pve` | `packer-20261020` | `TerraformRole` | Packer |
| `svc_monitoring@pve` | `monitoring-20261020` | `PVEAuditor` | prometheus-pve-exporter (lecture seule) |

Le nom porte la date de création : une rotation crée un nouveau token à côté de l'ancien
(bleu/vert, [comptes-et-rotation.md](comptes-et-rotation.md#26-tokens-proxmox--bleuvert)).
Les identifiants sont dans Vault (`secret/infra/terraform`, `secret/infra/monitoring`).

`TerraformRole` regroupe les privilèges `Datastore.*`, `Pool.*`, `SDN.Use`, `Sys.Audit`,
`Sys.Console`, `Sys.Modify` et `VM.*` (allocation, clone, config, migrate, power, snapshot...).

Trois pièges :

- **Un token créé avec `privsep=1` n'hérite pas des droits de son utilisateur.** Il ne reçoit que
  l'intersection entre ses propres ACL et celles de l'utilisateur. Sans ACL propre, il ne voit
  presque rien. Il faut donc donner l'ACL à l'utilisateur **et** au token :

  ```sh
  pveum acl modify / --users 'svc_monitoring@pve' --roles PVEAuditor
  pveum acl modify / --tokens 'svc_monitoring@pve!monitoring-20261020' --roles PVEAuditor
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

**Depuis le 20/10/2026, tous les secrets sont dans HashiCorp Vault** (https://10.0.1.242:8200),
sous `secret/infra/*`. Les anciens fichiers `/terraform/.env`, `/root/.proxmox-env`,
`/root/.monitoring-env` et `/root/.iam-env` sont détruits.

| Chemin Vault | Clés | Pour |
|---|---|---|
| `secret/infra/monitoring` | `GRAFANA_ADMIN_PASSWORD`, `VM_AUTH_PASSWORD`, `ALERTMANAGER_AUTH_PASSWORD`, `LOKI_AUTH_PASSWORD`, `REMEDIATION_AM_PASSWORD`, `PVE_MONITOR_TOKEN_ID`, `PVE_MONITOR_TOKEN_SECRET`, `DISCORD_WEBHOOK_URL`, `HEALTHCHECKS_PING_URL` | `swarm.yml`, `monitoring.yml` |
| `secret/infra/identity` | `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_DB_PASSWORD`, `VAULTWARDEN_ADMIN_TOKEN` | `identity.yml` |
| `secret/infra/terraform` | `PROXMOX_VE_API_TOKEN`, `PKR_VAR_proxmox_token_id`, `PKR_VAR_proxmox_token_secret`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Terraform, Packer, backend S3 |
| `secret/infra/unifi` | `UNIFI_URL`, `UNIFI_USERNAME`, `UNIFI_PASSWORD` | Compte de service UniFi |

**`vault-env`** (`infra/scripts/vault-env`) se connecte avec l'AppRole `ansible`, lit tous ces
secrets, exporte chaque clé comme variable d'environnement du même nom, révoque son token, puis
lance la commande. Toute commande qui a besoin d'un secret passe par lui :

```sh
vault-env ansible-playbook site.yml
vault-env packer build .
tf plan                     # le wrapper tf se relance lui-même par vault-env
```

- Les playbooks refusent de démarrer si un mot de passe fait moins de 16 caractères ou si le
  token PVE est absent (lancement sans `vault-env`).
- Si Vault est scellé, `vault-env` s'arrête : lancer d'abord `vault-unseal`
  ([Démarrage du lab](#démarrage-du-lab)).
- `HEALTHCHECKS_PING_URL` ou `DISCORD_WEBHOOK_URL` vide : route correspondante désactivée.
- `GRAFANA_ADMIN_PASSWORD` est réappliqué par le rôle `grafana` s'il ne correspond plus.

Pour générer une valeur, directement dans Vault (sur vault01, token admin) :

```sh
vault kv patch secret/infra/monitoring LOKI_AUTH_PASSWORD="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32)"
```

Politiques, AppRole, compte de secours, descellement : [identites.md](identites.md#4-vault--secrets-des-machines).
Inventaire de tous les comptes et rotation : [comptes-et-rotation.md](comptes-et-rotation.md).

Fichiers sensibles sur le poste de contrôle, hors du dépôt :

- `/root/.vault/approle-ansible.json` : identifiants de l'AppRole `ansible` (`0600`), utilisables
  depuis 10.0.1.110 seulement ;
- `/root/.vault/init.json` : clés de descellement et token root de Vault (`0600`), copiés dans
  Vaultwarden, **gardés jusqu'après la démo du 23/10** puis supprimés ;
- `/root/.pki/` : clé et certificat de la CA interne, certificats émis (`0700`) ;
- `/root/.remediation/` : clé SSH du moteur de remédiation (`swarm.yml`).

### `infra/terraform/backend.hcl` (non versionné)

Copie de `backend.hcl.example`, versionné :

```hcl
bucket    = "<nom-du-bucket>"
endpoints = { s3 = "https://<domaine-s3>" }
```

### Réinstallation à partir de zéro

Vault ne peut pas fournir les secrets dont il a besoin pour être installé. Sur un lab vide :
exporter à la main les variables ci-dessus dans un shell (valeurs reprises de Vaultwarden ou
générées), dérouler les étapes 1 à 4 **sans** `vault-env` (`export VAULT_ENV_LOADED=1` : le
wrapper `tf` ne tente alors pas de se relancer par `vault-env`), puis écrire les secrets dans
`secret/infra/*`. Les lancements suivants passent par `vault-env`.

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
tf init -backend-config=backend.hcl
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

**Toujours passer par `tf`, jamais par `terraform` directement** : il charge aussi les secrets
(token Proxmox, clés S3) depuis Vault par `vault-env`. Le verrou
n'est valable que sur le poste de contrôle : Terraform n'est lancé que depuis .110.

### Étape 2 : template `debian13-docker` (Packer)

Packer clone le 9000 en VM temporaire (IP de build `10.0.1.200`), puis lance les scripts
`scripts/00-wait-cloud-init.sh`, `10-base.sh`, `20-docker.sh`, `30-hardening.sh` et `90-cleanup.sh`.
Il convertit enfin la VM en template 9100 avec un lecteur cloud-init.

```sh
cd /srv/M2-EPSI-Workshop/infra/packer/debian13-docker
packer init .
vault-env packer build .     # PKR_VAR_proxmox_token_id / _secret lus dans Vault
```

Pour reconstruire le template, supprimer d'abord le 9100 existant : Packer ne remplace pas un
VMID occupé. Les VM déjà clonées ne sont pas touchées, car Terraform ignore les changements de
`clone`.

### Étape 3 : VM Swarm, LXC de supervision et d'identité, HA (Terraform)

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
- **`identity.tf`** : 3 LXC Debian 13 non privilégiés pour Keycloak (iam01), Vault (vault01) et
  Vaultwarden (vaultwarden01), un par hyperviseur.
- **`ha.tf`** : HA sur les 12 invités (`max_restart 2`, `max_relocate 1`, `failback`), plus deux
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
vault-env ansible-playbook site.yml     # = swarm.yml, monitoring.yml, identity.yml
```

On peut aussi lancer les trois playbooks séparément (toujours par `vault-env`), dans cet ordre :

| Playbook | Cibles | Contenu |
|---|---|---|
| `swarm.yml` | `swarm` | Rôles `docker_host` (daemon.json, nftables) et `alloy`, nœud par nœud (`serial: 1`) pour préserver le quorum. Puis `swarm init`, `join`, labels `role` et `pve_node`, drain des managers. cAdvisor sur les workers |
| `monitoring.yml` | `monitoring`, puis `pve:control:waf` | `lxc_base` et `alloy` sur les 3 LXC. `alloy` seul sur les hyperviseurs, le poste de contrôle et le WAF (play « Envoi des logs »). `pve_exporter` et `vmagent` sur les vmagents. `vmsingle`, `alertmanager`, `vmalert`, `loki` (+ nginx), `grafana` sur monitoring01 |
| `identity.yml` | `identity`, puis tous les hôtes pour la CA | `lxc_base` et `alloy` sur les 3 LXC. `internal_ca` (CA dans le magasin de confiance de toutes les machines). `keycloak` (+ realm `epsi`), `vault` (initialisation, politiques, AppRole), `vaultwarden`. `grafana_oidc` et `pve_oidc` (SSO). Voir [identites.md](identites.md) |

Les playbooks sont idempotents : un second passage doit afficher `changed=0`.

Si l'on change les mots de passe de la stack, pousser aux **clients avant le serveur** : un
client qui envoie des identifiants à un serveur qui ne les exige pas encore n'est pas gêné.
L'inverse provoque des refus (401) et, pour Loki, des logs perdus. Procédure :
[comptes-et-rotation.md](comptes-et-rotation.md#22-basic-auth-et-loki--les-clients-dabord).

### Étape 5 : vérifications

Préparation, dans un shell ouvert par `vault-env bash` (secrets en variables jusqu'à `exit`) :

```sh
vault-env bash
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

**Logs.** Chaque hôte doit apparaître (17 machines, dont waf01, parfois muet sur 5 min) :

```sh
curl -s -u monitoring:$LOKI_AUTH_PASSWORD -G http://$M:3100/loki/api/v1/query \
  --data-urlencode 'query=sum by (host) (count_over_time({job="journal"}[1h]))'
```

**Grafana** : ouvrir http://10.0.1.233:3000 et se connecter par Keycloak (compte de secours :
`admin`, mot de passe `GRAFANA_ADMIN_PASSWORD`). Contrôler l'état des sources :

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

### Démarrage du lab

Le lab est éteint chaque nuit. Check-list du matin, et **d'avant démo**, depuis .110. Vault
redémarre toujours scellé : tant qu'il l'est, `vault-env`, donc Ansible et `tf`, refusent de
tourner.

1. **Hyperviseurs et HA** : quorum, toutes les ressources HA en `started` :

   ```sh
   ssh -i /root/.ssh/id_ed25519_proxmox root@10.0.1.100 'pvecm status | grep -i quorate; ha-manager status'
   ```

2. **Desceller Vault** (l'alerte `VaultSealed` est alors active) :

   ```sh
   vault-unseal                 # clés lues dans /root/.vault/init.json tant qu'il existe,
                                # sinon 3 clés saisies sans écho (Vaultwarden)
   vault-env true && echo OK    # vault-env refonctionne
   ```

   `vault-unseal` ne dépend ni d'Ansible ni de `vault-env` et n'affiche aucune clé. Ne pas
   utiliser `identity.yml` pour desceller : il passe par `vault-env`, qui échoue tant que Vault
   est scellé. Détails : [identites.md](identites.md#descellement).

3. **Swarm** : 6 nœuds `Ready`, managers `Drain` :

   ```sh
   ssh -i /root/.ssh/id_ed25519_infra debian@10.0.1.211 sudo docker node ls
   ```

4. **Supervision**, dans un shell ouvert par `vault-env bash` (variables jusqu'à `exit`, le
   token Vault est déjà révoqué) :

   ```sh
   vault-env bash
   M=10.0.1.233
   J() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

   # 0 cible down : []
   curl -s -u monitoring:$VM_AUTH_PASSWORD --data-urlencode 'query=up == 0' \
     http://$M:8428/api/v1/query | J 'd["data"]["result"]'

   # Alertes actives : Watchdog seulement
   curl -s -u monitoring:$ALERTMANAGER_AUTH_PASSWORD \
     "http://$M:9093/api/v2/alerts?active=true&silenced=false&inhibited=false" \
     | J '" ".join(a["labels"]["alertname"] for a in d)'

   # Sources Grafana : OK, OK, puis 200 pour Alertmanager
   for ds in victoriametrics loki; do
     curl -s -u admin:$GRAFANA_ADMIN_PASSWORD http://$M:3000/api/datasources/uid/$ds/health | J 'd["status"]'
   done
   curl -s -o /dev/null -w "%{http_code}\n" -u admin:$GRAFANA_ADMIN_PASSWORD \
     http://$M:3000/api/datasources/proxy/uid/alertmanager/api/v2/status

   # Logs : les 17 machines sur la dernière heure (waf01 peut être muet sur 5 min)
   curl -s -u monitoring:$LOKI_AUTH_PASSWORD -G http://$M:3100/loki/api/v1/query \
     --data-urlencode 'query=sum by (host) (count_over_time({job=~".+"}[1h]))' \
     | J 'sorted(r["metric"]["host"] for r in d["data"]["result"])'
   exit
   ```

5. **healthchecks.io** : le check du Watchdog est vert. **Discord** : l'alerte `VaultSealed` du
   matin est passée en « RÉSOLU ».
6. **Avant la démo** : ouvrir Grafana (dashboard « Plateforme - vue centrale »), se connecter
   par Keycloak (TOTP prêt), vérifier que la stack applicative et la stack `demo` sont à leur
   nombre de réplicas (`docker service ls` sur un manager).

Contrôlé le 20/10/2026 : quorum OK, 6 nœuds Swarm prêts, `[]` pour les cibles down, `Watchdog`
seule alerte active, sources Grafana `OK`, 17 machines dans Loki sur une heure.

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
5. Lancer `vault-env ansible-playbook swarm.yml` : le nœud rejoint le Swarm.
6. Lancer `vault-env ansible-playbook monitoring.yml --limit vmagents` : les cibles node, docker et cAdvisor
   du nouveau nœud sont ajoutées au scrape.

### Monter de version VictoriaMetrics

Modifier `vm_version` dans `inventory/group_vars/monitoring.yml`, puis lancer
`vault-env ansible-playbook monitoring.yml`.

Le rôle `vm_install` télécharge la release GitHub et vérifie son checksum dans
`/opt/victoriametrics/<version>/`. Il bascule ensuite le lien `/usr/local/bin/<binaire>` et
redémarre les services concernés. L'ancienne version reste sur disque : pour revenir en arrière,
remettre l'ancienne valeur de `vm_version` et relancer le playbook.

### Ajouter un dashboard Grafana

1. Déposer le JSON dans `monitoring/grafana/dashboards/<Dossier>/`. Le nom du répertoire devient
   le dossier Grafana.
2. Lancer `vault-env ansible-playbook monitoring.yml --limit monitoring_core`.

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
3. Lancer `vault-env ansible-playbook monitoring.yml --limit monitoring_core`.

Chaque fichier est validé par `vmalert -dryRun` avant d'être copié, puis vmalert est rechargé.

### Faire tourner un secret

Nouvelle valeur générée directement dans Vault, puis `vault-env ansible-playbook site.yml` deux
fois (application, puis `changed=0`). Ordre clients puis serveur pour les mots de passe de la
stack, cas particuliers (Keycloak, Grafana, tokens Proxmox, `root@pam`, secrets Swarm) et
inventaire complet : [comptes-et-rotation.md](comptes-et-rotation.md).

### Desceller Vault après un redémarrage

Alerte `VaultSealed` sur Discord, et `vault-env` refuse de tourner. Lancer `vault-unseal` sur
.110 (voir [Démarrage du lab](#démarrage-du-lab) et [identites.md](identites.md#descellement)).

### Renouveler un certificat interne

Supprimer `/root/.pki/issued/<hôte>/` sur le poste de contrôle, puis relancer
`vault-env ansible-playbook identity.yml` :
le rôle réémet le certificat (1 an), l'installe et redémarre le service.

### Reconstruire un LXC

Exemple avec `vmagent01` (procédure non testée à ce jour : vérifier le plan avant d'appliquer) :

```sh
tf apply -replace='proxmox_virtual_environment_container.monitoring["vmagent01"]' \
         -replace='proxmox_haresource.guests["vmagent01"]'
ssh-keygen -R 10.0.1.231 && ssh-keyscan -t ed25519 10.0.1.231 >> /root/.ssh/known_hosts
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook monitoring.yml --limit vmagent01
```

Le second vmagent continue de collecter pendant la reconstruction.

Pour **monitoring01** :
- les données de VictoriaMetrics (30 jours) et de Loki (14 jours) sont perdues ;
- les vmagents gardent les métriques en tampon disque (jusqu'à `vmagent_buffer_max`, 8 Go) et
  les renvoient au retour du service ;
- tout le reste est recréé par le playbook : configuration, dashboards, sources et règles.

---

## 5. Dépannage

Erreurs rencontrées au déploiement des services d'identité (corrigées dans les rôles) :

| Symptôme | Cause | Correction |
|---|---|---|
| Keycloak redémarre en boucle : `Unknown option: '--config-file'` | `--config-file` est une option globale de `kc.sh`, à placer avant la sous-commande | `kc.sh --config-file=... start --optimized` |
| Vault redémarre en boucle : `failed to open bolt file: .../vault.db: no such file or directory` | Le stockage Raft ne crée pas son répertoire | Le rôle crée `/var/lib/vault/data` (`0700`, vault) |
| Docker refusé dans un LXC non privilégié | L'option `keyctl` est réservée à `root@pam` | Vaultwarden extrait de l'image et lancé en natif |
| vmagent01-02 et monitoring01 **sans firewall** depuis leur création (seule la table Debian par défaut chargée) | Le premier passage de `monitoring.yml` a échoué avant les handlers : `/etc/nftables.conf` écrit mais jamais rechargé, et plus aucun changement détecté ensuite | `force_handlers = True` dans `ansible.cfg` ; `lxc_base` vérifie que la table `host_fw` est chargée et recharge sinon. Corrigé le 19/10/2026 |

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
| `401` dans les logs d'Alloy ou de vmagent, « dropping data » chez Alloy | Mot de passe changé côté serveur avant les clients | Pousser aux clients, puis au serveur ([comptes-et-rotation.md](comptes-et-rotation.md#22-basic-auth-et-loki--les-clients-dabord)) |
| `vault-env : Vault est scellé` | Redémarrage de vault01 (lab rallumé, bascule HA) | `vault-unseal` |
| `Secrets absents : lancer le playbook par vault-env` | Playbook lancé sans `vault-env` | `vault-env ansible-playbook ...` |
| Token Proxmox supprimé : « ignore invalid acl token » dans les logs | ACL du token restée dans `user.cfg` | Retirer l'ACL avant de supprimer le token ([comptes-et-rotation.md](comptes-et-rotation.md#26-tokens-proxmox--bleuvert)) |

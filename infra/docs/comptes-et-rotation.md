# Comptes, secrets et rotation

Inventaire de tous les comptes et secrets de l'infrastructure, et procédure pour les faire
tourner, telle qu'appliquée le 20/10/2026. Les outils (Keycloak, Vault, Vaultwarden) sont décrits
dans [identites.md](identites.md).

Principes :

- **Source de vérité : Vault.** Tout secret utilisé par une machine est dans `secret/infra/*`
  (arborescence : [identites.md](identites.md#arborescence-des-secrets-kv-v2-secret)). Ansible et
  Terraform le lisent par `vault-env` à chaque exécution. Aucun fichier `.env` ne subsiste.
- **Vaultwarden pour les humains** : comptes de secours, clés de descellement. Chaque élément
  indique dans ses notes son chemin dans Vault ; Vault fait foi.
- **Aucune valeur dans ce document**, seulement des noms.

## 1. Inventaire

Dernière rotation : `20/10/2026`, ou « jamais » pour les secrets que nous ne pouvons pas
régénérer nous-mêmes, ou pas encore fait.

### Humains (SSO)

| Compte | Où il vit | Qui l'utilise | Droits | Rotation | Dernière |
|---|---|---|---|---|---|
| Comptes nominatifs du realm `epsi` (`keycloak_users`) | Keycloak (iam01), mot de passe et TOTP choisis par la personne | Administrateurs de l'équipe | Groupe `infra-admins` : Admin Grafana, Administrator Proxmox ; groupe `viewers` : lecture seule | Par la personne (`/realms/epsi/account`). Départ : retrait du groupe ou désactivation dans Keycloak, effet à la connexion suivante | gérée par chaque personne |

### Comptes de secours (hors SSO)

Ils doivent fonctionner quand Keycloak est en panne. Tous sont dans Vaultwarden.

| Compte | Où il vit | Source de vérité | Droits | Rotation | Dernière |
|---|---|---|---|---|---|
| `root@pam` (Proxmox) | `/etc/shadow` des 3 hyperviseurs | `secret/breakglass/proxmox-root` | Tout le cluster | `chpasswd` sur chaque nœud (§2.7) | 20/10/2026 |
| `admin` du realm `master` (Keycloak) | Base PostgreSQL de Keycloak | `secret/infra/identity` : `KEYCLOAK_ADMIN_PASSWORD` | Administration de Keycloak | API d'administration, **avant** l'écriture dans Vault (§2.5) | 20/10/2026 |
| `breakglass` (Vault, userpass) | Vault | `secret/breakglass/vault-admin` | Politique `admin` (tout), jetons 1 h / 8 h | `vault write auth/userpass/users/breakglass password=-` sur vault01, puis mise à jour de `secret/breakglass/vault-admin` | 20/10/2026 |
| `admin` local de Grafana | Base SQLite de Grafana (monitoring01) | `secret/infra/monitoring` : `GRAFANA_ADMIN_PASSWORD` | Administrateur Grafana | Nouvelle valeur dans Vault, puis `monitoring.yml` : le rôle `grafana` réinitialise le mot de passe (§2.4) | 20/10/2026 |
| Token de la page `/admin` (Vaultwarden) | `/etc/vaultwarden/vaultwarden.env`, haché (Argon2id) | `secret/infra/identity` : `VAULTWARDEN_ADMIN_TOKEN` | Administration de Vaultwarden (invitations, utilisateurs) | Nouvelle valeur dans Vault, puis `identity.yml --limit vaultwarden_servers` | 20/10/2026 |
| Token root de Vault | Vault ; `/root/.vault/init.json` ; Vaultwarden | `init.json` | Tout | **Révocation planifiée après la démo du 23/10**, avec suppression de `init.json` | jamais (à révoquer) |
| 5 clés de descellement | `/root/.vault/init.json` ; Vaultwarden | `init.json` | Desceller Vault (3 sur 5) | `vault operator rekey` (nouvelles clés à redistribuer) | jamais |

### Comptes de service

| Compte / secret | Où il vit | Source de vérité (Vault) | Qui l'utilise | Droits | Rotation | Dernière |
|---|---|---|---|---|---|---|
| Token `svc_monitoring@pve!monitoring-20261020` | Proxmox ; `/etc/pve-exporter/pve.yml` des vmagents | `secret/infra/monitoring` : `PVE_MONITOR_TOKEN_ID`, `PVE_MONITOR_TOKEN_SECRET` | prometheus-pve-exporter (vmagent01-02) | `PVEAuditor` sur `/` (lecture seule) | Bleu/vert (§2.6), puis `monitoring.yml --limit vmagents` | 20/10/2026 |
| Token `terraform@pve!tf-20261020` | Proxmox | `secret/infra/terraform` : `PROXMOX_VE_API_TOKEN` | Terraform (`tf`) | `TerraformRole` sur `/` | Bleu/vert (§2.6) | 20/10/2026 |
| Token `terraform@pve!packer-20261020` | Proxmox | `secret/infra/terraform` : `PKR_VAR_proxmox_token_id`, `PKR_VAR_proxmox_token_secret` | Packer | `TerraformRole` sur `/` | Bleu/vert (§2.6) | 20/10/2026 |
| AppRole `ansible` | Vault ; `/root/.vault/approle-ansible.json` (`0600`) sur .110 | (identifiant de Vault lui-même) | `vault-env`, donc Ansible, `tf`, Packer | Politique `ansible-read` : lecture de `secret/infra/*`. Depuis 10.0.1.110/32 uniquement | Nouveau `secret_id` émis sur vault01 avec un token admin (`vault write -f auth/approle/role/ansible/secret-id`), fichier remplacé sur .110 (`0600`), test `vault-env true`, puis destruction de l'ancien par son accesseur (`secret-id-accessor/destroy`) | 20/10/2026 (création) |
| Basic auth `monitoring` de VictoriaMetrics, vmagent, vmalert | VictoriaMetrics, vmagent et vmalert (fichiers `0640`) ; Grafana (`secureJsonData`) ; secret Swarm `vm_auth_password_<empreinte>` | `secret/infra/monitoring` : `VM_AUTH_PASSWORD` | vmagents, vmalert, Grafana, vmagent du Swarm | Lecture, écriture et suppression de séries | §2.2 et §2.3 | 20/10/2026 |
| Basic auth `monitoring` d'Alertmanager | Alertmanager (hash bcrypt) ; vmalert ; Grafana | `secret/infra/monitoring` : `ALERTMANAGER_AUTH_PASSWORD` | vmalert, Grafana | Toute l'API d'Alertmanager | §2.2 | 20/10/2026 |
| Basic auth `monitoring` de Loki | nginx devant Loki (SHA-512 crypt) ; `/etc/alloy/loki_password` des 17 machines ; Grafana | `secret/infra/monitoring` : `LOKI_AUTH_PASSWORD` | Alloy (envoi des logs), Grafana | Écriture et lecture des logs | §2.2 (clients d'abord) | 20/10/2026 |
| Basic auth `remediation` d'Alertmanager | Alertmanager (hash bcrypt) ; secret Swarm `remediation_alertmanager_password` | `secret/infra/monitoring` : `REMEDIATION_AM_PASSWORD` | Moteur de remédiation (lecture des alertes par l'API) | Toute l'API d'Alertmanager | §2.2 | 20/10/2026 |
| Client OIDC `grafana` | Keycloak ; `/etc/grafana/oidc.env` (`0640`, groupe `grafana`) | Keycloak (généré par lui, pas dans Vault) | Grafana | Échanger un code d'autorisation contre un jeton | « Regenerate » dans Keycloak, puis `identity.yml --limit monitoring_core` (le rôle relit le secret et le pousse) | 20/10/2026 |
| Client OIDC `proxmox` | Keycloak ; `/etc/pve/domains.cfg` (realm `keycloak`) | Keycloak (généré par lui, pas dans Vault) | Proxmox | Idem | « Regenerate », puis `identity.yml --limit pve` | 20/10/2026 |
| Utilisateur PostgreSQL `keycloak` | PostgreSQL (iam01, 127.0.0.1) ; `/etc/keycloak/keycloak.conf` (`0640`) | `secret/infra/identity` : `KEYCLOAK_DB_PASSWORD` | Keycloak | Propriétaire de la base `keycloak` | Nouvelle valeur dans Vault, puis `identity.yml --limit keycloak_servers` | 20/10/2026 |
| Clé SSH du moteur de remédiation | `/root/.remediation/` sur .110 ; secret Swarm `remediation_ssh_key` ; `authorized_keys` des managers | Fichier sur .110 (pas dans Vault) | Moteur de remédiation, vers la passerelle `remediate` | Actions fermées de la passerelle ([remediation.md](remediation.md)) | Nouvelle paire de clés, `swarm.yml --limit swarm_managers`, redéploiement du moteur | jamais |
| Compte UniFi `svc_claude` | Contrôleur UniFi | `secret/infra/unifi` : `UNIFI_URL`, `UNIFI_USERNAME`, `UNIFI_PASSWORD` | Outillage d'administration réseau | Défini dans UniFi | Dans l'interface UniFi, puis nouvelle valeur dans Vault | jamais |
| Webhook Discord | Discord ; `/etc/prometheus/discord_webhook_url` (`0640`) | `secret/infra/monitoring` : `DISCORD_WEBHOOK_URL` | Alertmanager | Poster dans le salon d'alertes | Régénérer dans Discord, Vault, puis `monitoring.yml --limit monitoring_core` | jamais |
| URL de ping healthchecks.io | healthchecks.io ; `/etc/prometheus/healthchecks_url` (`0640`) | `secret/infra/monitoring` : `HEALTHCHECKS_PING_URL` | Alertmanager (Watchdog) | Pinger un check | Régénérer dans healthchecks.io, Vault, puis `monitoring.yml --limit monitoring_core` | jamais |
| Clés S3 du backend Terraform | Portail S3 du fournisseur | `secret/infra/terraform` : `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Terraform (state) | Bucket du state (le tenant porte d'autres buckets, à ne pas toucher) | Nouvelle clé dans le portail S3, Vault, `tf plan`, puis retrait de l'ancienne | jamais |

Hors de cette liste : la clé de la CA interne (`/root/.pki/ca.key`, renouvellement = nouvelle CA à
réimporter partout) et les clés SSH d'administration de .110 (`id_ed25519_infra`,
`id_ed25519_proxmox`).

## 2. Procédure de rotation

### 2.1 Cas général

1. **Générer la nouvelle valeur directement dans Vault**, sans passer par un fichier ni
   l'afficher. KV v2 garde l'ancienne version : retour arrière possible par
   `vault kv rollback -version=<n>`. Avec le CLI de vault01 et un token admin :

   ```sh
   vault kv patch secret/infra/monitoring \
     LOKI_AUTH_PASSWORD="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32)"
   ```

2. **Appliquer**, puis **repasser** pour contrôler :

   ```sh
   cd /srv/M2-EPSI-Workshop/infra/ansible
   vault-env ansible-playbook site.yml     # application
   vault-env ansible-playbook site.yml     # changed=0 attendu
   ```

3. Contrôler : 0 cible down, aucune alerte autre que `Watchdog`, sources Grafana `OK`, logs de
   toutes les machines dans Loki (check-list de [deploiement.md](deploiement.md#démarrage-du-lab)).
4. **Mettre à jour Vaultwarden** si le compte y figure (comptes de secours, basic auth).

### 2.2 Basic auth et Loki : les clients d'abord

Un serveur qui exige le nouveau mot de passe avant que ses clients ne l'aient refuse leurs
requêtes (401). **Constaté le 20/10** : pendant la fenêtre où Loki (nginx) avait le nouveau mot
de passe et les Alloy encore l'ancien, des lots de logs ont été perdus (« dropping data » dans
le journal d'Alloy). Ordre à suivre :

1. pousser le nouveau mot de passe aux **clients** (Alloy sur toutes les machines, vmagents,
   vmalert, Grafana) ;
2. puis au **serveur** (nginx de Loki, VictoriaMetrics, Alertmanager).

Avec `site.yml`, `swarm.yml` passe avant `monitoring.yml`, mais monitoring01 (serveur Loki) est
traité avant les LXC d'identité et les hyperviseurs. Pour Loki, limiter le premier passage aux
clients, par exemple :

```sh
vault-env ansible-playbook swarm.yml
vault-env ansible-playbook monitoring.yml --limit 'all:!monitoring_core'
vault-env ansible-playbook identity.yml --limit identity
vault-env ansible-playbook monitoring.yml --limit monitoring_core   # serveur en dernier
vault-env ansible-playbook site.yml                                  # contrôle : changed=0
```

Recherche des pertes : `{job="journal", unit="alloy.service"} |= "dropping data"`.

### 2.3 Secrets Swarm : immuables

Un secret Swarm ne se modifie pas. Le rôle `swarm_monitoring` nomme donc celui de
VictoriaMetrics par une **empreinte salée** de sa valeur (`vm_auth_password_<12 caractères>`) :
une nouvelle valeur crée un nouveau secret, le service est mis à jour, puis le rôle supprime les
anciens. L'empreinte est salée et tronquée : elle ne permet pas de retrouver le mot de passe.

`remediation_alertmanager_password` et `remediation_ssh_key` (rôle `remediation_gateway`) ont un
nom fixe : à vérifier au premier changement de valeur une fois le moteur déployé (un secret
utilisé par un service ne peut pas être supprimé).

### 2.4 Admin local de Grafana

`admin_password` de `grafana.ini` n'est lu qu'à la création de la base. Le rôle `grafana` teste
donc le mot de passe de Vault sur l'API (`/api/user`) et, sur un 401, lance
`grafana cli admin reset-admin-password --password-from-stdin` sous l'utilisateur `grafana`,
depuis `/usr/share/grafana` (le CLI lit son répertoire courant). Le mot de passe ne passe pas
par la ligne de commande.

### 2.5 Admin `master` de Keycloak

`KEYCLOAK_ADMIN_PASSWORD` sert à Ansible pour s'authentifier sur l'API d'administration : si
Vault change avant Keycloak, le rôle ne peut plus se connecter. Ordre :

1. changer le mot de passe **par l'API d'administration** (ou la console), avec l'ancien ;
2. **ensuite** écrire la nouvelle valeur dans `secret/infra/identity` ;
3. `vault-env ansible-playbook identity.yml --limit keycloak_servers` (changed=0 attendu).

### 2.6 Tokens Proxmox : bleu/vert

Les noms de tokens portent la date (`-20261020`). Pour chaque token :

1. créer le **nouveau token** (`privsep=1`) et lui donner **la même ACL** que l'ancien
   (`pveum acl modify / --tokens '<user>!<nouveau>' --roles <rôle>`) ;
2. le **tester** (exporter PVE, `tf plan`, Packer) ;
3. **basculer dans Vault** (`PVE_MONITOR_TOKEN_*`, `PROXMOX_VE_API_TOKEN`, `PKR_VAR_*`), puis
   `monitoring.yml --limit vmagents` pour l'exporter ;
4. **retirer l'ACL de l'ancien token, puis le supprimer.** Dans l'autre ordre, l'ACL reste
   orpheline dans `user.cfg` et Proxmox journalise « ignore invalid acl token » à chaque lecture.

### 2.7 `root@pam`

Nouveau mot de passe dans `secret/breakglass/proxmox-root`, puis `chpasswd` sur les **3 nœuds**,
par SSH par clé depuis .110. Le cluster n'est pas affecté : corosync et le SSH entre nœuds
utilisent des clés, pas le mot de passe de root. Contrôles :

```sh
for n in ceph01 ceph02 ceph03; do
  ssh -i /root/.ssh/id_ed25519_proxmox root@10.0.1.100 \
    "ssh -o BatchMode=yes -o HostKeyAlias=$n -o UserKnownHostsFile=/etc/pve/nodes/$n/ssh_known_hosts $n true && echo $n OK"
done
ssh -i /root/.ssh/id_ed25519_proxmox root@10.0.1.100 'pvecm status | grep -i quorate; ha-manager status | head -3'
```

Puis connexion à l'interface web avec `root@pam` (realm « Linux PAM ») et mise à jour de
Vaultwarden.

### 2.8 Secrets que nous ne pouvons pas régénérer

Webhook Discord, URL healthchecks.io, clés S3, compte UniFi : à régénérer dans l'interface du
fournisseur, puis nouvelle valeur dans Vault et passage du playbook concerné (tableau §1). Pas
faits le 20/10 : dernière rotation « jamais ».

## 3. Leçons du 20/10/2026

| Constat | Correction |
|---|---|
| Logs perdus pendant la rotation du mot de passe Loki (serveur avant clients) | Ordre clients puis serveur (§2.2) |
| Un secret Swarm ne peut pas changer de valeur | Nom à empreinte salée, anciens secrets supprimés par le rôle (§2.3) |
| Le mot de passe admin Grafana de `grafana.ini` est ignoré après la création | Réinitialisation par le CLI dans le rôle `grafana` (§2.4) |
| L'admin Keycloak changé dans Vault d'abord coupe Ansible de l'API | Changer dans Keycloak, puis dans Vault (§2.5) |
| ACL orpheline « ignore invalid acl token » après suppression d'un token | Retirer l'ACL avant de supprimer le token (§2.6) |
| `vault-env` impossible quand Vault est scellé | `vault-unseal`, indépendant d'Ansible ([identites.md](identites.md#descellement)) |

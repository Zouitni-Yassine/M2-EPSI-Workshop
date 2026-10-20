# Identités et secrets : Keycloak, Vault, Vaultwarden

Trois services pour trois besoins distincts, chacun dans un LXC dédié :

| Besoin | Outil | Qui l'utilise |
|---|---|---|
| **Authentifier les administrateurs** une seule fois, avec double authentification, et leur donner des droits par groupe | **Keycloak** (SSO, OIDC) | Les humains, pour Grafana, Proxmox, PBS, Vault |
| **Fournir les secrets aux machines** (mots de passe de services, tokens, clés), avec audit et rotation | **HashiCorp Vault** | Ansible, Terraform, les services |
| **Ranger les mots de passe de l'équipe** que le SSO ne couvre pas : comptes de secours, comptes externes, clés de descellement de Vault | **Vaultwarden** (compatible Bitwarden) | Les humains |

Ces trois services remplacent les fichiers `.env` du poste de contrôle, **supprimés le
20/10/2026** : tous les secrets d'infra sont dans Vault, lus à chaque exécution par
`vault-env` (§4). Grafana et Proxmox se connectent par Keycloak. Restent le SSO de PBS et de
Vault, et la révocation du token root, planifiée après la démo (§8).

Inventaire de tous les comptes et procédure de rotation : [comptes-et-rotation.md](comptes-et-rotation.md).

## 1. Architecture

| Machine | VMID / IP | Hyperviseur | Ressources | Service | Accès |
|---|---|---|---|---|---|
| iam01 | 241 / 10.0.1.241 | ceph02 | 2 vCPU, 3 Go, 20 Go | Keycloak 26.8.1, PostgreSQL 17 | https://10.0.1.241/admin |
| vault01 | 242 / 10.0.1.242 | ceph03 | 1 vCPU, 1 Go, 10 Go | Vault 2.2.0 (stockage Raft) | https://10.0.1.242:8200 |
| vaultwarden01 | 243 / 10.0.1.243 | ceph01 | 1 vCPU, 1 Go, 10 Go | Vaultwarden 1.37.4 (SQLite) | https://10.0.1.243 |

- **Hors du Swarm.** Le Swarm héberge l'application qui sera attaquée pendant la démo. Les
  services d'identité n'y sont pas exposés : un conteneur compromis ne partage ni le noyau ni le
  réseau overlay avec eux.
- **Un service par hyperviseur.** La perte d'un nœud ne coupe qu'un service, que la HA Proxmox
  redémarre ailleurs (règles `home-cephXX`, retour automatique sur le nœud d'origine).
- **LXC non privilégiés**, avec le même socle que la supervision (rôle `lxc_base`) :
  - SSH root par clé uniquement ;
  - firewall nftables en `drop` par défaut ;
  - mises à jour de sécurité automatiques ;
  - node_exporter, et Alloy pour envoyer les logs dans Loki.
- **Installation native, sans Docker.** Chaque service tourne sous systemd, avec un compte
  système dédié et un durcissement systemd :
  - `NoNewPrivileges`, `ProtectSystem=strict`, `PrivateTmp` ;
  - `CAP_NET_BIND_SERVICE` seulement pour écouter sur le port 443 sans être root ;
  - les fichiers du programme appartiennent à root : le service ne peut pas modifier son propre
    code.

Fichiers : `infra/terraform/identity.tf`, `infra/ansible/identity.yml`, rôles `internal_ca`,
`keycloak`, `vault` et `vaultwarden`, variables dans `inventory/group_vars/identity.yml`.

### Accès réseau

Depuis le LAN du lab (10.0.1.0/24) et depuis le VPN d'administration (10.10.0.0/24), sur les
seuls ports web : 443 (Keycloak, Vaultwarden) et 8200 (Vault). Le port de gestion de Keycloak
(9000), node_exporter et SSH restent limités au LAN. Variables : `fw_admin_web_allowed`
(`group_vars/all.yml`) et `fw_admin_ports` (par groupe).

## 2. Autorité de certification interne

Vaultwarden exige HTTPS : le navigateur refuse d'y faire de la cryptographie sans contexte
sécurisé. OIDC et Vault en ont aussi besoin. Faute de DNS public pour ces adresses internes,
on utilise une **CA interne** (rôle `internal_ca`).

| Élément | Emplacement | Détail |
|---|---|---|
| Clé de la CA | `/root/.pki/ca.key` sur le poste de contrôle | ECDSA P-384. **Ne quitte jamais .110** |
| Certificat de la CA | `/root/.pki/ca.crt`, copie publique dans [`infra/pki/ca.crt`](../pki/ca.crt) | Valable 10 ans, `CA:TRUE, pathlen:0` |
| Certificats serveurs | `/root/.pki/issued/<hôte>/` puis `/etc/<service>/tls.{crt,key}` | ECDSA P-256, 1 an. Noms couverts : nom court, `<hôte>.epsi.lsn`, IP de l'hôte, `127.0.0.1` |

- **Le certificat de la CA est installé dans le magasin de confiance** de toutes les machines
  gérées par Ansible, et de .110. Les collecteurs et Grafana peuvent ainsi interroger ces services
  en HTTPS sans désactiver la vérification.
- **Côté navigateur**, importer `infra/pki/ca.crt` dans le magasin « Autorités de certification
  racines de confiance » de Windows, ou dans celui du navigateur. Le fichier est public, sans
  risque à diffuser à l'équipe.
- **Renouvellement** : un certificat serveur est réémis si on supprime son répertoire
  `/root/.pki/issued/<hôte>/` et qu'on relance `identity.yml`.

## 3. Keycloak : SSO des administrateurs

- **Installation** :
  - archive officielle, vérifiée par son empreinte SHA-1 publiée ;
  - Java 21 de Debian ;
  - base PostgreSQL locale, en écoute sur 127.0.0.1 uniquement, encodée en UTF-8 (créée depuis
    `template0` : la locale du LXC étant `C`, elle serait sinon en `SQL_ASCII`) ;
  - la configuration est compilée une fois (`kc.sh build`), puis lancée en mode `--optimized`.
- **Configuration** : `/etc/keycloak/keycloak.conf` (droits `0640`, groupe `keycloak`, contient le
  mot de passe de la base).
  - Adresse publique et émetteur des jetons OIDC : `https://10.0.1.241`.
  - HTTPS sur 443, HTTP désactivé.
  - Santé et métriques sur l'interface de gestion (port 9000, HTTPS).
- **Compte d'amorçage** : `admin`, créé au premier démarrage à partir de `/etc/keycloak/bootstrap.env`
  (`0600`, root), avec le mot de passe `KEYCLOAK_ADMIN_PASSWORD`. Une fois le realm et un vrai
  compte admin créés, ce compte devient le **compte de secours** : il reste en dehors du SSO, et
  son mot de passe va dans Vaultwarden.
- **Logs** : journald, donc Loki (`{host="iam01", unit="keycloak.service"}`).
- **Événements de sécurité** : chaque connexion, réussie ou non, et chaque action d'administration
  est écrite dans le journal (`org.keycloak.events`), donc dans Loki. Ces événements alimentent le
  SIEM, par exemple pour repérer des échecs répétés :
  `{host="iam01"} |= "org.keycloak.events" |= "LOGIN_ERROR"`.

### Realm `epsi`

Les administrateurs se connectent dans le realm `epsi`. Le realm `master` ne sert qu'au compte
de secours. Toute la configuration est en code : `roles/keycloak/tasks/realm.yml`, variables dans
`group_vars/keycloak_servers.yml`. Elle est appliquée par l'API d'administration depuis .110.

| Réglage | Valeur |
|---|---|
| HTTPS | Obligatoire pour toutes les requêtes (`ssl_required: all`) |
| Inscription, mot de passe oublié, « se souvenir de moi » | Désactivés : pas de serveur mail, les comptes sont gérés par un administrateur |
| Mot de passe | 12 caractères minimum, différent de l'identifiant, pas de réutilisation des 3 derniers |
| **Double authentification** | **TOTP obligatoire** : l'action « Configurer l'OTP » est imposée à tout nouveau compte, puis le code est demandé à chaque connexion. Compatible avec Bitwarden, Aegis et Google Authenticator (6 chiffres, 30 s) |
| Force brute | Verrouillage progressif après 5 échecs, jusqu'à 15 min (aussi sur `master`) |
| Sessions | 30 min d'inactivité, 10 h au maximum |
| Événements | Connexions conservées 7 jours dans Keycloak, et envoyées dans Loki |

| Groupe | Grafana | Proxmox | Vault |
|---|---|---|---|
| `infra-admins` | Admin | Administrator | Politique d'administration |
| `viewers` | Viewer | PVEAuditor | Aucun accès |

Les droits par outil sont appliqués par les clients OIDC (ci-dessous). Vault reste à raccorder
(§8) : la politique `admin` existe déjà, seule la méthode `oidc` manque.

### Clients OIDC : Grafana et Proxmox

Chaque outil est un **client confidentiel** du realm `epsi`, déclaré dans `keycloak_oidc_clients`
(`group_vars/keycloak_servers.yml`) :

- flux « authorization code » uniquement, avec **PKCE S256 obligatoire** : pas de flux implicite,
  pas d'envoi de mot de passe par l'application, pas de compte de service ;
- redirections **exactes**, sans joker ;
- un mapper ajoute le claim `groups` (noms courts : `infra-admins`, `viewers`) aux jetons et à
  `userinfo`.

**Secrets des clients** : Keycloak les génère à la création. Les rôles `grafana_oidc` et
`pve_oidc` les relisent à chaque exécution (`keycloak_clientsecret_info`) et les écrivent
directement chez l'outil. Ils ne sont ni dans le dépôt, ni sur .110. Pour faire tourner un
secret : « Regenerate » dans la console Keycloak (realm `epsi`, Clients, onglet Credentials),
puis relancer `vault-env ansible-playbook identity.yml --limit monitoring_core,pve`.

| | Grafana | Proxmox |
|---|---|---|
| Rôle Ansible (play de `identity.yml`) | `grafana_oidc` (monitoring01) | `pve_oidc` (une fois pour le cluster, sur ceph01) |
| Où va le secret | `/etc/grafana/oidc.env` (`0640`, groupe `grafana`), chargé par une surcharge systemd (`grafana-server.service.d/oidc.conf`) | `/etc/pve/domains.cfg`, realm `keycloak` (fichier du cluster, `0640` root:www-data : lisible par root et par l'interface web de Proxmox) |
| Connexion | Bouton « Sign in with Keycloak » sur http://10.0.1.233:3000/login | Realm « Keycloak (SSO, double authentification) » dans la liste déroulante de la page de connexion |
| Identifiant | `preferred_username` (e-mail : `<identifiant>@epsi.lsn` si le compte n'en a pas) | `<identifiant>@keycloak`, créé à la première connexion |
| `infra-admins` | `GrafanaAdmin` : Admin de l'organisation et administrateur du serveur | Groupe `infra-admins-keycloak` : `Administrator` sur `/` |
| `viewers` | `Viewer` | Groupe `viewers-keycloak` : `PVEAuditor` sur `/` |
| Aucun des deux groupes | Connexion refusée (`role_attribute_strict`) | Connexion acceptée, mais aucun droit |
| Retrait d'un groupe dans Keycloak | Rôle recalculé à la connexion suivante | Groupes Proxmox réécrits à la connexion suivante (`groups-overwrite`) |

- **Grafana** : les réglages passent par des variables `GF_AUTH_GENERIC_OAUTH_*`, prioritaires sur
  `grafana.ini`. Le rôle `grafana`, lancé par `monitoring.yml` avant que Keycloak existe, n'en
  dépend donc pas. Le formulaire local reste actif : **le compte `admin` local est le compte de
  secours**. La déconnexion ferme aussi la session Keycloak.
- **Proxmox** :
  - les groupes `<groupe>-keycloak` et leurs ACL sont **créés d'avance** par Ansible
    (`groups-autocreate` désactivé) : un nouveau groupe Keycloak ne donne aucun droit sur Proxmox
    tant qu'il n'est pas déclaré dans `pve_oidc_group_roles` ;
  - `root@pam`, le realm `pve` et les tokens existants (supervision, Terraform) ne sont pas
    modifiés. `root@pam` reste le compte de secours ;
  - les hyperviseurs reconnaissent la CA interne (play `internal_ca`, étendu au groupe `pve`) :
    Proxmox vérifie le certificat de Keycloak.
- **Double authentification** : c'est Keycloak qui demande le TOTP. Grafana et Proxmox n'ont pas
  de second facteur propre pour ces comptes.

**Créer un compte** :
1. L'ajouter dans `keycloak_users`, avec son groupe, puis lancer
   `vault-env ansible-playbook identity.yml --limit keycloak_servers`. Le compte est créé sans
   mot de passe.
2. Lui fixer un mot de passe **temporaire** dans la console (realm `epsi`, Users, Credentials),
   puis le transmettre par un « Send » Vaultwarden à usage unique.
3. À sa première connexion (`https://10.0.1.241/realms/epsi/account`), la personne choisit son
   mot de passe et enrôle son TOTP.

Aucun mot de passe d'utilisateur n'est stocké dans le dépôt ni dans les variables Ansible.

## 4. Vault : secrets des machines

- **Installation** : binaire officiel de `releases.hashicorp.com`, vérifié par la liste
  d'empreintes SHA-256 publiée. La signature GPG de cette liste n'est pas vérifiée.
- **Configuration** : `/etc/vault.d/vault.hcl`.
  - Stockage Raft intégré (`/var/lib/vault/data`), nœud unique, extensible à 3 nœuds.
  - Écoute HTTPS sur 8200, interface web activée.
  - `disable_mlock` : impossible en LXC non privilégié, et recommandé avec Raft.
  - Métriques Prometheus lisibles sans token (`/v1/sys/metrics?format=prometheus`), le port
    étant filtré par le firewall.
- **Initialisation** :
  - **5 clés de descellement (Shamir), dont 3 nécessaires** ;
  - le résultat (clés et token root) est écrit sur vault01 en `0600`, rapatrié sur .110 dans
    `/root/.vault/init.json` (`0600`), puis **effacé de vault01**.
- **Configuration initiale**, avec le token root :
  - moteur de secrets **KV v2** sur `secret/` ;
  - **audit de chaque requête** vers syslog (identifiant `vault-audit`), donc dans Loki :
    `{host="vault01", identifier="vault-audit"}`.

### Politiques, AppRole et compte de secours

Appliqués par `roles/vault/tasks/config.yml`, à chaque passage de `identity.yml`. Token utilisé :
le token root tant que `/root/.vault/init.json` existe, ensuite celui d'un administrateur
(variable `VAULT_TOKEN` exportée sur .110, obtenue avec le compte `breakglass` : voir §9). Sans
l'un ni l'autre, cette partie est sautée. Le CLI `vault` n'est installé que sur vault01
(`VAULT_ADDR` déjà positionné pour root) ; depuis .110, on passe par l'API.

| Politique | Fichier | Droits |
|---|---|---|
| `ansible-read` | `roles/vault/files/policies/ansible-read.hcl` | Lecture de `secret/data/infra/*`, liste de `secret/metadata/infra/*`. Rien sur `secret/breakglass/*` |
| `admin` | `roles/vault/files/policies/admin.hcl` | `path "*"`, tous les droits (dont `sudo`). Remplace le token root : chaque action est rattachée à une identité dans l'audit |

| Identité | Méthode | Politique | Durée des jetons | Restrictions |
|---|---|---|---|---|
| `ansible` | AppRole | `ansible-read` | 30 min, 2 h au maximum | `secret_id` **et** jetons utilisables depuis `10.0.1.110/32` seulement (`vault_ansible_cidr`). Testé : refus `400` depuis monitoring01 |
| `breakglass` | userpass | `admin` | 1 h, 8 h au maximum | Compte de secours des administrateurs, indépendant de Keycloak |

- **Identifiants de l'AppRole** (`role_id`, `secret_id`) : `/root/.vault/approle-ansible.json`
  sur .110 (`0600`), émis une seule fois (le rôle n'en réémet pas si le fichier existe).
- **Mot de passe de `breakglass`** : généré par le rôle, rangé dans
  `secret/breakglass/vault-admin`, puis recopié dans Vaultwarden. L'AppRole ne peut pas le lire
  (testé : `403`).

### Arborescence des secrets (KV v2, `secret/`)

Noms de clés seulement. Chaque clé de `secret/infra/*` devient une variable d'environnement du
même nom (voir `vault-env` ci-dessous).

| Chemin | Clés | Utilisé par |
|---|---|---|
| `secret/infra/monitoring` | `GRAFANA_ADMIN_PASSWORD`, `VM_AUTH_PASSWORD`, `ALERTMANAGER_AUTH_PASSWORD`, `LOKI_AUTH_PASSWORD`, `REMEDIATION_AM_PASSWORD`, `PVE_MONITOR_TOKEN_ID`, `PVE_MONITOR_TOKEN_SECRET`, `DISCORD_WEBHOOK_URL`, `HEALTHCHECKS_PING_URL` | `swarm.yml`, `monitoring.yml` |
| `secret/infra/identity` | `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_DB_PASSWORD`, `VAULTWARDEN_ADMIN_TOKEN` | `identity.yml` |
| `secret/infra/terraform` | `PROXMOX_VE_API_TOKEN`, `PKR_VAR_proxmox_token_id`, `PKR_VAR_proxmox_token_secret`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | `tf`, Packer, backend S3 |
| `secret/infra/unifi` | `UNIFI_URL`, `UNIFI_USERNAME`, `UNIFI_PASSWORD` | Compte de service UniFi |
| `secret/breakglass/vault-admin` | `username`, `password` | Humains seulement (compte `breakglass`) |
| `secret/breakglass/proxmox-root` | `username`, `password` | Humains seulement (`root@pam`) |

KV v2 garde les versions précédentes : une rotation ratée se corrige par
`vault kv rollback -version=<n> secret/infra/<chemin>` sur vault01, avec un token admin.

### `vault-env` : les secrets pour Ansible et Terraform

`infra/scripts/vault-env`, installé dans `/usr/local/bin` :

```sh
install -m 0755 /srv/M2-EPSI-Workshop/infra/scripts/vault-env    /usr/local/bin/vault-env
install -m 0755 /srv/M2-EPSI-Workshop/infra/scripts/vault-unseal /usr/local/bin/vault-unseal
```

1. Connexion par l'AppRole `ansible` (identifiants de `/root/.vault/approle-ansible.json`).
2. Lecture de tous les secrets sous `secret/infra/*`.
3. Export de chaque clé en variable d'environnement du même nom.
4. **Révocation de son token**, puis `exec` de la commande.

Rien n'est écrit sur disque ni affiché.

```sh
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook site.yml
tf plan                                   # le wrapper tf se relance lui-même par vault-env
```

Si Vault est scellé, `vault-env` s'arrête avec « Vault est scellé : lancer vault-unseal ».

### Descellement

Vault démarre **scellé** après tout redémarrage, y compris une bascule HA. Il tourne, mais ne
peut rien lire tant que 3 clés n'ont pas été saisies. Le lab étant éteint chaque nuit, **le
descellement fait partie du démarrage du matin**, et de la check-list d'avant démo
([deploiement.md](deploiement.md#démarrage-du-lab)).

- **L'alerte `VaultSealed`** (critique) part sur Discord une minute après.
- **Commande unique : `vault-unseal`**, sur .110 (`infra/scripts/vault-unseal`). Elle ne dépend
  ni d'Ansible ni de `vault-env`, qui ont besoin d'un Vault descellé :
  - tant que `/root/.vault/init.json` existe, elle y lit les clés ;
  - une fois le fichier supprimé, elle demande chaque clé **sans écho** : 3 détenteurs saisissent
    chacun la leur, conservée dans Vaultwarden ;
  - elle n'affiche aucune clé, seulement la progression (`1/3`, `2/3`, « Vault descellé ») ;
  - si Vault est déjà descellé, elle le dit et s'arrête.

  ```sh
  vault-unseal
  vault-env true && echo OK     # vault-env refonctionne
  ```

  Testé le 20/10/2026 : Vault scellé volontairement, `vault-env` refuse, `vault-unseal`
  (3 clés), `vault-env` refonctionne.

**Conséquence pour l'application** : aucune. Les conteneurs déjà déployés gardent leurs secrets
Docker en mémoire. Un Vault scellé empêche seulement de déployer ou de faire tourner un secret.
Le descellement automatique (auto-unseal) demanderait un KMS externe ou un second Vault : c'est
hors de portée pour ce lab, et noté dans les limites.

## 5. Vaultwarden : mots de passe de l'équipe

- **Installation** : Vaultwarden n'est distribué qu'en image Docker. Or Docker dans un LXC non
  privilégié exige l'option `keyctl`, que seul `root@pam` peut activer (pas le token Terraform).
  Le rôle extrait donc le **binaire statique** et l'interface web de l'image officielle
  (variante Alpine), **épinglée par son empreinte** (`vaultwarden_image`). Il vérifie la version
  du binaire, puis le lance en natif sous systemd.
- **Configuration** : `/etc/vaultwarden/vaultwarden.env` (`0640`, groupe `vaultwarden`).
  - HTTPS sur 443, données dans `/var/lib/vaultwarden` (SQLite, `0700`).
  - **Inscription libre désactivée** : les comptes sont créés par invitation.
  - Indices de mot de passe masqués, 600 000 itérations de hachage côté serveur.
  - **Page `/admin` protégée par un token stocké haché** (Argon2id), à partir de
    `VAULTWARDEN_ADMIN_TOKEN`.
  - Journal détaillé (connexions, échecs) dans journald, donc Loki.
- **Pas de serveur mail** : une personne invitée depuis `/admin` crée ensuite son compte
  directement sur https://10.0.1.243 avec l'adresse invitée.
- **Clients** : extension de navigateur et applications Bitwarden officielles, en indiquant le
  serveur auto-hébergé `https://10.0.1.243`. La CA interne doit être reconnue par le poste.

### Ce qu'on y range

| Élément | Pourquoi ici |
|---|---|
| Les 5 clés de descellement de Vault, réparties entre plusieurs membres de l'équipe | Si elles sont dans Vault, on ne peut pas desceller Vault |
| Le token root de Vault, jusqu'à sa révocation | Même raison |
| Comptes de secours : `root@pam` Proxmox, admin local Grafana, admin `master` de Keycloak, `breakglass` Vault | Ils doivent fonctionner quand le SSO est en panne |
| Comptes externes : portail S3, Discord, healthchecks.io, GitHub | Services hors de notre SSO |

Contenu au 20/10/2026 :

| Dossier | Éléments |
|---|---|
| Vault (vault01) | Les 5 clés de descellement, le token root |
| Infra - Proxmox | `root@pam` |
| Infra - Keycloak | Admin du realm `master` |
| Infra - Vault | `breakglass` |
| Infra - Vaultwarden | Token de la page `/admin` |
| Infra - Supervision | Admin local Grafana ; Basic auth `monitoring` de VictoriaMetrics, d'Alertmanager et de Loki |

Soit 8 comptes, plus les 6 éléments de Vault. **Chaque élément indique dans ses notes sa source
de vérité dans Vault** (ex. `secret/infra/monitoring`, clé `LOKI_AUTH_PASSWORD`) : après une
rotation, c'est Vault qui fait foi, et Vaultwarden est mis à jour à la main
([comptes-et-rotation.md](comptes-et-rotation.md)).

Import initial : un CSV au format Bitwarden, généré sur .110 (`0600`) à partir de Vault et de
`init.json`, importé dans Vaultwarden, puis détruit (`shred`).

## 6. Supervision

| Élément | Détail |
|---|---|
| Job `keycloak` | `https://10.0.1.241:9000/metrics` |
| Job `vault` | `https://10.0.1.242:8200/v1/sys/metrics?format=prometheus` (métrique clé : `vault_core_unsealed`) |
| Job `node` | Les 3 machines |
| `TargetDown` | Keycloak, Vault ou une machine injoignable |
| `VaultSealed` | Cible `vault` joignable sans `vault_core_unsealed == 1` pendant 1 min, critique (`monitoring/vmalert/rules/identity.yml`). Un Vault scellé n'expose plus cette métrique : tester `== 0` ne suffit pas (constaté le 20/10 après le redémarrage du cluster) |
| Logs | `{host=~"iam01|vault01|vaultwarden01"}` ; audit Vault : `{identifier="vault-audit"}` ; PostgreSQL de Keycloak : `{job="postgresql"}` (fichier, lu par ACL) |

Vaultwarden n'expose pas de métriques : seule la machine est supervisée. Sa disponibilité se
teste par `https://10.0.1.243/alive`.

## 7. Secrets d'amorçage

Keycloak, Vault et Vaultwarden ont besoin de quelques secrets pour démarrer. Ils étaient dans
`/root/.iam-env` jusqu'au 20/10/2026. Ce fichier, comme `/root/.monitoring-env`,
`/root/.proxmox-env` et `/terraform/.env`, est **détruit** : les valeurs sont dans
`secret/infra/identity` (§4) et arrivent dans l'environnement par `vault-env`.

```sh
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook identity.yml
```

`identity.yml` refuse de démarrer si un secret est absent ou trop court (lancement sans
`vault-env`, par exemple).

**Poule et œuf** : Vault ne peut pas fournir les secrets dont il a besoin pour être installé. Une
réinstallation complète de vault01 se fait donc avec un environnement fourni à la main (valeurs
reprises de Vaultwarden), puis les secrets sont réécrits dans le nouveau Vault.

Fichiers sensibles restant sur .110, hors du dépôt :

| Fichier sur .110 | Contenu | Devenir |
|---|---|---|
| `/root/.vault/init.json` | 5 clés de descellement et token root | Copié dans Vaultwarden. **Gardé jusqu'après la démo du 23/10** pour le descellement sans saisie, puis supprimé et token root révoqué (§8) |
| `/root/.vault/approle-ansible.json` | `role_id` et `secret_id` de l'AppRole `ansible` (`0600`) | Reste : seul accès d'Ansible et de Terraform aux secrets, limité à 10.0.1.110 |
| `/root/.pki/ca.key` | Clé de la CA interne | Reste sur .110 (`0600`). Dans une version industrielle : CA hors ligne ou moteur PKI de Vault |

## 8. Feuille de route

| Étape | État |
|---|---|
| Déployer Keycloak, Vault et Vaultwarden en HTTPS, sous HA, supervisés | **fait** |
| Keycloak : realm `epsi`, double authentification obligatoire, groupes `infra-admins` et `viewers` | **fait** (20/10) |
| OIDC vers Grafana (groupe → rôle) et Proxmox (realm OpenID, groupes → ACL) | **fait** (20/10) |
| Vault : politiques `ansible-read` et `admin`, AppRole `ansible`, compte `breakglass` ; migration de tous les secrets des fichiers `.env`, fichiers détruits ; `vault-env` et `vault-unseal` | **fait** (20/10) |
| Rotation de tous les secrets renouvelables par nous ; inventaire des comptes ([comptes-et-rotation.md](comptes-et-rotation.md)) | **fait** (20/10) |
| Vaultwarden : comptes créés, clés de descellement, token root et 8 comptes de secours rangés | **fait** (20/10) |
| OIDC vers Vault pour les humains (méthode `oidc`, groupe `infra-admins` → politique `admin`) | à faire |
| OIDC vers PBS (realm OpenID, une fois PBS installé) | à faire |
| **Révoquer le token root et supprimer `init.json`** | **planifié après la démo du vendredi 23/10** : d'ici là, `init.json` permet à `vault-unseal` de desceller sans saisie chaque matin |

## 9. Vérifier

Depuis .110 :

```sh
# HTTPS avec la CA interne (200 attendu, sans -k)
curl -s -o /dev/null -w '%{http_code}\n' https://10.0.1.241/realms/master/.well-known/openid-configuration
curl -s -o /dev/null -w '%{http_code}\n' https://10.0.1.242:8200/v1/sys/health
curl -s -o /dev/null -w '%{http_code}\n' https://10.0.1.243/alive

# Vault : initialisé, descellé ("sealed": false)
curl -s https://10.0.1.242:8200/v1/sys/seal-status

# vault-env : connexion AppRole et lecture des secrets
vault-env true && echo OK

# Keycloak : jeton admin obtenu (200), sans afficher le jeton
vault-env sh -c 'curl -s -o /dev/null -w "%{http_code}\n" -d client_id=admin-cli -d username=admin \
  --data-urlencode "password=$KEYCLOAK_ADMIN_PASSWORD" -d grant_type=password \
  https://10.0.1.241/realms/master/protocol/openid-connect/token'

# Vaultwarden : /admin refuse un mauvais token (401)
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://10.0.1.243/admin -d token=faux

# SSO Grafana : redirection vers Keycloak avec PKCE (302, Location vers .../realms/epsi/...)
curl -s -o /dev/null -D - http://10.0.1.233:3000/login/generic_oauth | grep -i '^location' | cut -c1-90

# SSO Proxmox : realm présent, et découverte OIDC + TLS vérifiés depuis le nœud
ssh -i /root/.ssh/id_ed25519_proxmox root@10.0.1.100 \
  'pveum realm list; pveum acl list; pvesh create /access/openid/auth-url --realm keycloak --redirect-url https://10.0.1.100:8006 | cut -c1-60'
```

**Droits de l'AppRole** (le jeton reste dans une variable, jamais affiché, puis est révoqué) :

```sh
V=https://10.0.1.242:8200/v1
T=$(curl -s --data @/root/.vault/approle-ansible.json $V/auth/approle/login \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])')
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Vault-Token: $T" $V/secret/data/infra/monitoring        # 200
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Vault-Token: $T" $V/secret/data/breakglass/vault-admin  # 403
curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "X-Vault-Token: $T" $V/auth/token/revoke-self      # 204
unset T
```

**Token admin pour `identity.yml`**, une fois le token root révoqué (mot de passe de
`breakglass` saisi sans écho, depuis Vaultwarden) :

```sh
read -rs P && export VAULT_TOKEN=$(python3 -c 'import json,sys; print(json.dumps({"password": sys.argv[1]}))' "$P" \
  | curl -s --data @- https://10.0.1.242:8200/v1/auth/userpass/login/breakglass \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["auth"]["client_token"])'); unset P
vault-env ansible-playbook identity.yml --limit vault_servers
```

État au 20/10/2026 (secrets) : `vault-env` charge les 4 chemins de `secret/infra/*`. L'AppRole lit
`secret/infra/*` (200) mais pas `secret/breakglass/*` (403), et sa connexion depuis monitoring01
est refusée (400). Après la rotation, `site.yml` passe deux fois, le second sans changement ;
0 cible down, seule l'alerte `Watchdog` est active, les sources Grafana répondent `OK`.

État au 20/10/2026 (SSO) : les clients `grafana` et `proxmox` sont conformes (flux code seul,
PKCE S256, redirections exactes, claim `groups`). Grafana redirige vers Keycloak avec PKCE et
affiche le bouton Keycloak. Proxmox génère l'URL d'autorisation depuis les 3 nœuds. Les ACL
existantes sont intactes. Le second passage de `identity.yml` ne change rien.

État au 19/10/2026 : les 3 contrôles HTTPS répondent 200, un jeton admin Keycloak est obtenu,
Vault est initialisé et descellé (seuil 3 sur 5) avec `secret/` et l'audit actifs, `/admin`
répond 401 avec un mauvais token et 200 avec le bon. Les 5 cibles de métriques sont à `up = 1`,
les logs des 3 machines arrivent dans Loki, et `site.yml` relancé ne change rien sur les 12
machines.

## 10. Limites

| Limite | Risque | En production |
|---|---|---|
| Un seul nœud par service | Indisponibilité pendant une bascule HA (quelques minutes) | Keycloak en cluster (2 nœuds ou plus, base répliquée), Vault Raft à 3 nœuds |
| Pas de descellement automatique de Vault | Intervention humaine (`vault-unseal`) après chaque redémarrage ; tant que Vault est scellé, ni Ansible ni Terraform ne peuvent tourner | Auto-unseal par KMS ou HSM |
| Clés de descellement et token root encore sur .110 (`init.json`), **gardés volontairement jusqu'après la démo du 23/10** pour le descellement sans saisie | Accès root à .110 = accès à tous les secrets | Fichier supprimé et token root révoqué après la démo (planifié) ; clés réparties entre plusieurs personnes |
| Identifiants de l'AppRole sur .110, `secret_id` sans expiration | Accès root à .110 = lecture de `secret/infra/*` (restreinte à l'adresse de .110) | `secret_id` à durée de vie courte (response wrapping), ou Vault Agent |
| Les secrets passent par l'environnement d'Ansible et de Terraform | Lisibles par root dans `/proc/<pid>/environ` pendant l'exécution | Lookup `community.hashi_vault` au plus près de chaque tâche |
| Rotation manuelle (procédure écrite, pas planifiée) | Un secret peut vieillir sans que personne ne le voie | Moteurs de secrets dynamiques de Vault, rotation planifiée |
| Clé de la CA sur le poste de contrôle | Compromission de .110 = possibilité d'émettre des certificats valides | CA racine hors ligne, CA intermédiaire dans Vault (moteur PKI) |
| Adresses IP dans les URL (pas de DNS interne) | Renommage ou changement d'IP = nouveaux certificats et nouvelles URL OIDC | DNS interne, noms stables |
| Vaultwarden sans serveur mail | Pas de récupération de compte par e-mail, invitations manuelles | Relais SMTP interne |
| Signature GPG des binaires Vault non vérifiée | Seule l'intégrité du téléchargement est contrôlée | Vérification GPG de la liste d'empreintes |
| Grafana en HTTP (port 3000) | Le cookie de session Grafana et le code d'autorisation OIDC passent en clair sur le LAN du lab (le mot de passe et le TOTP, eux, sont saisis sur Keycloak en HTTPS) | Grafana en HTTPS (certificat de la CA interne ou proxy TLS), cookies `Secure` |
| Secrets des clients OIDC chez les outils (`oidc.env`, `domains.cfg`) | Un accès root à monitoring01 ou à un hyperviseur expose le secret de son client | Secrets lus dans Vault au démarrage (Vault Agent), rotation régulière |

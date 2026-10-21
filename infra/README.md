# Infrastructure : PROJECT RESILIENCE-ALPHA

Socle d'hébergement et d'observabilité de la plateforme de paiement fictive. Tout est décrit en
code et se redéploie depuis ce dossier :

- un cluster **Docker Swarm** de 6 VM sur un cluster **Proxmox VE 9 / Ceph** de 3 nœuds ;
- une stack de supervision compatible Prometheus : **VictoriaMetrics**, vmalert, Alertmanager,
  **Loki**, **Grafana** ;
- la **haute disponibilité Proxmox** sur toutes les machines ;
- les **identités et secrets** : Keycloak (SSO), HashiCorp Vault, Vaultwarden, avec une CA interne.

```
infra/
├── packer/debian13-docker/   Template VM Debian 13 + Docker (9100), cloné pour les nœuds Swarm
├── terraform/                Template cloud (9000), VM Swarm, LXC de supervision et d'identité, HA
│   └── scripts/tf            Wrapper : secrets lus dans Vault (vault-env), verrou local (flock)
├── ansible/                  Configuration : cluster Swarm, firewall, stack d'observabilité
│   ├── swarm.yml             Docker, firewall, Swarm, Alloy, cAdvisor
│   ├── monitoring.yml        vmagent x2, VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana
│   ├── identity.yml          CA interne, Keycloak, Vault, Vaultwarden
│   ├── site.yml              Les trois
│   └── roles/                Un rôle par composant (installation, service, secrets)
├── monitoring/               Configurations de la supervision, déployées par les rôles Ansible
│   ├── vmagent/              scrape.yml.j2 (équivalent prometheus.yml)
│   ├── vmalert/rules/        Règles d'alerte
│   ├── alertmanager/         alertmanager.yml.j2 (routage Discord / healthchecks.io)
│   ├── loki/                 config.yml.j2, reverse proxy nginx
│   ├── alloy/                Agent de logs (journald -> Loki)
│   ├── grafana/              Sources de données, dashboards JSON, scripts de génération
│   └── swarm/                vmagent dans le Swarm : métriques des services applicatifs
├── remediation/              Stack de démo (exemple de référence) et test de la passerelle
├── scripts/
│   ├── vault-env             Lance une commande avec les secrets de Vault dans son environnement
│   └── vault-unseal          Descelle Vault après un redémarrage (indépendant d'Ansible)
├── pki/ca.crt                Certificat public de la CA interne (à importer dans les navigateurs)
└── docs/
    ├── architecture.md       Architecture, plan d'adressage, choix techniques et limites
    ├── deploiement.md        Déploiement pas à pas, opérations courantes, dépannage
    ├── supervision.md        Métriques, logs, alertes, dashboards, sécurité de la stack
    ├── contrat-deploiement.md  Règles de déploiement des applications (pour les développeurs)
    ├── remediation.md        Passerelle de remédiation : actions, garde-fous, tests
    ├── identites.md          Keycloak, Vault, Vaultwarden, CA interne : usage, exploitation, limites
    └── comptes-et-rotation.md  Inventaire des comptes et secrets, procédure de rotation
```

## Vue d'ensemble

| Machine | Type | IP | Rôle |
|---|---|---|---|
| ceph01-03 | Proxmox VE 9 + Ceph | 10.0.1.100-102 | Hyperviseurs, stockage Ceph partagé |
| dockermgr01-03 | VM 2 vCPU / 4 Go | 10.30.1.211-213 (VLAN 301) | Managers Swarm (Raft), drainés |
| dockerwrk01-03 | VM 4 vCPU / 12 Go | 10.30.1.221-223 (VLAN 301) | Workers Swarm : conteneurs applicatifs |
| vmagent01-02 | LXC 1 vCPU / 1 Go | 10.0.1.231-232 | Collecteurs de métriques redondants |
| monitoring01 | LXC 4 vCPU / 8 Go | 10.0.1.233 | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana |
| iam01 | LXC 2 vCPU / 3 Go | 10.0.1.241 | Keycloak (SSO), PostgreSQL |
| vault01 | LXC 1 vCPU / 1 Go | 10.0.1.242 | HashiCorp Vault |
| vaultwarden01 | LXC 1 vCPU / 1 Go | 10.0.1.243 | Vaultwarden (mots de passe de l'équipe) |
| waf01 | VM (équipe cyber) | 10.30.2.251 (RA-DMZ) | WAF ; VM importée dans Terraform, seul l'envoi des logs y est géré par Ansible ([docs/waf.md](docs/waf.md)) |

Le Swarm est isolé dans le VLAN `RA-APP` ; le reste est sur `MANAGEMENT` (10.0.1.0/24). Flux autorisés
et procédure : [docs/reseau.md](docs/reseau.md).

Chaque hyperviseur porte un manager et un worker : la perte d'un hôte ne coûte qu'un nœud de
chaque type, et la HA Proxmox redémarre ses machines sur les deux autres.

## Déploiement rapide

Depuis le poste de contrôle (10.0.1.110). Les secrets sont dans Vault et chargés par `vault-env`
(voir [deploiement.md](docs/deploiement.md#2-secrets)) :

```sh
# tf = infra/terraform/scripts/tf (installé dans /usr/local/bin) : lit les secrets dans Vault
# (vault-env), se place dans /terraform et empêche deux exécutions simultanées

# 1. Template cloud Debian 13 (VM 9000) puis template Docker (VM 9100)
tf init -backend-config=backend.hcl
tf apply -target=proxmox_virtual_environment_vm.debian13_cloud
cd /srv/M2-EPSI-Workshop/infra/packer/debian13-docker && packer init . && vault-env packer build .

# 2. VM Swarm, LXC de supervision et d'identité, HA
tf apply

# 3. Configuration
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook site.yml
```

**Chaque matin** (le lab est éteint la nuit) **et avant la démo** : `vault-unseal`, puis la
check-list de [deploiement.md](docs/deploiement.md#démarrage-du-lab).

Les playbooks sont idempotents : les relancer ne change rien si l'état est conforme.
Le détail, les vérifications et le dépannage sont dans [docs/deploiement.md](docs/deploiement.md).

## Où trouver les configurations de supervision

| Fichier | Emplacement |
|---|---|
| Scrape (équivalent `prometheus.yml`) | `monitoring/vmagent/scrape.yml.j2` |
| Règles d'alerte | `monitoring/vmalert/rules/` |
| `alertmanager.yml` | `monitoring/alertmanager/alertmanager.yml.j2` |
| `loki.yml` | `monitoring/loki/config.yml.j2` |
| Dashboards Grafana | `monitoring/grafana/dashboards/` |

Table complète dans [docs/supervision.md](docs/supervision.md#2-où-sont-les-fichiers-de-configuration).

## Accès

| Service | URL | Authentification |
|---|---|---|
| Grafana | http://10.0.1.233:3000 | Keycloak (SSO, TOTP) ; secours : `admin` |
| VictoriaMetrics (vmui) | http://10.0.1.233:8428/vmui | Basic : `monitoring` |
| vmalert | http://10.0.1.233:8880 | Basic : `monitoring` |
| Alertmanager | http://10.0.1.233:9093 | Basic : `monitoring` |
| Loki (API) | http://10.0.1.233:3100 | Basic : `monitoring` (nginx) |
| Proxmox | https://10.0.1.100:8006 | Keycloak (realm « Keycloak ») ; secours : `root@pam` |
| Keycloak | https://10.0.1.241/realms/epsi/account (comptes), https://10.0.1.241/admin | realm `epsi` ; secours : `admin` du realm `master` |
| Vault | https://10.0.1.242:8200 | `breakglass` (userpass) ; machines : AppRole `ansible` (voir [identites.md](docs/identites.md#4-vault--secrets-des-machines)) |
| Vaultwarden | https://10.0.1.243 | compte personnel ; `/admin` par token |

Les secrets des machines sont dans Vault, les comptes de secours dans Vaultwarden, **jamais dans
ce dépôt**. Les services HTTPS utilisent la CA interne : importer
[`pki/ca.crt`](pki/ca.crt) dans le navigateur. Les alertes arrivent sur Discord ; le Watchdog est surveillé par healthchecks.io.

## Secrets

Aucun secret n'est versionné. Depuis le 20/10/2026, ils sont tous dans **HashiCorp Vault**
(`secret/infra/*`) : `vault-env` les lit avec l'AppRole `ansible` et les passe en variables
d'environnement à Ansible, Terraform et Packer. Les anciens fichiers `.env` du poste de contrôle
sont détruits. Sur les serveurs, les secrets sont écrits dans des fichiers séparés (droits `0640`,
groupe du seul service qui les lit), avec `no_log` côté Ansible. Le diff sortant est passé au
scanner de secrets avant chaque push.

- Fonctionnement de Vault, arborescence des secrets, descellement : [docs/identites.md](docs/identites.md)
- Inventaire de tous les comptes et procédure de rotation : [docs/comptes-et-rotation.md](docs/comptes-et-rotation.md)

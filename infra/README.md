# Infrastructure : PROJECT RESILIENCE-ALPHA

Socle d'hébergement et d'observabilité de la plateforme de paiement fictive. Tout est décrit en
code et se redéploie depuis ce dossier :

- un cluster **Docker Swarm** de 6 VM sur un cluster **Proxmox VE 9 / Ceph** de 3 nœuds ;
- une stack de supervision compatible Prometheus : **VictoriaMetrics**, vmalert, Alertmanager,
  **Loki**, **Grafana** ;
- la **haute disponibilité Proxmox** sur toutes les machines.

```
infra/
├── packer/debian13-docker/   Template VM Debian 13 + Docker (9100), cloné pour les nœuds Swarm
├── terraform/                Template cloud (9000), VM Swarm, LXC de supervision, HA Proxmox
│   └── scripts/tf            Wrapper : charge les secrets et pose un verrou local (flock)
├── ansible/                  Configuration : cluster Swarm, firewall, stack d'observabilité
│   ├── swarm.yml             Docker, firewall, Swarm, Alloy, cAdvisor
│   ├── monitoring.yml        vmagent x2, VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana
│   ├── site.yml              Les deux
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
└── docs/
    ├── architecture.md       Architecture, plan d'adressage, choix techniques et limites
    ├── deploiement.md        Déploiement pas à pas, opérations courantes, dépannage
    ├── supervision.md        Métriques, logs, alertes, dashboards, sécurité de la stack
    ├── contrat-deploiement.md  Règles de déploiement des applications (pour les développeurs)
    └── remediation.md        Passerelle de remédiation : actions, garde-fous, tests
```

## Vue d'ensemble

| Machine | Type | IP | Rôle |
|---|---|---|---|
| ceph01-03 | Proxmox VE 9 + Ceph | 10.0.1.100-102 | Hyperviseurs, stockage Ceph partagé |
| dockermgr01-03 | VM 2 vCPU / 4 Go | 10.0.1.211-213 | Managers Swarm (Raft), drainés |
| dockerwrk01-03 | VM 4 vCPU / 12 Go | 10.0.1.221-223 | Workers Swarm : conteneurs applicatifs |
| vmagent01-02 | LXC 1 vCPU / 1 Go | 10.0.1.231-232 | Collecteurs de métriques redondants |
| monitoring01 | LXC 4 vCPU / 8 Go | 10.0.1.233 | VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana |

Chaque hyperviseur porte un manager et un worker : la perte d'un hôte ne coûte qu'un nœud de
chaque type, et la HA Proxmox redémarre ses machines sur les deux autres.

## Déploiement rapide

Depuis le poste de contrôle (10.0.1.110), secrets en place (voir [deploiement.md](docs/deploiement.md#2-secrets)) :

```sh
# tf = infra/terraform/scripts/tf (installé dans /usr/local/bin) : charge /root/.proxmox-env,
# se place dans /terraform (lien vers infra/terraform) et empêche deux exécutions simultanées

# 1. Template cloud Debian 13 (VM 9000) puis template Docker (VM 9100)
tf init -backend-config=backend.hcl
tf apply -target=proxmox_virtual_environment_vm.debian13_cloud
source /root/.proxmox-env
cd /srv/M2-EPSI-Workshop/infra/packer/debian13-docker && packer init . && packer build .

# 2. VM Swarm, LXC de supervision, HA
tf apply

# 3. Configuration
cd /srv/M2-EPSI-Workshop/infra/ansible
source /root/.monitoring-env
ansible-playbook site.yml
```

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
| Grafana | http://10.0.1.233:3000 | admin |
| VictoriaMetrics (vmui) | http://10.0.1.233:8428/vmui | Basic : `monitoring` |
| vmalert | http://10.0.1.233:8880 | Basic : `monitoring` |
| Alertmanager | http://10.0.1.233:9093 | Basic : `monitoring` |
| Loki (API) | http://10.0.1.233:3100 | Basic : `monitoring` (nginx) |

Les mots de passe sont dans `/root/.monitoring-env` sur le poste de contrôle, **jamais dans ce
dépôt**. Les alertes arrivent sur Discord ; le Watchdog est surveillé par healthchecks.io.

## Secrets

Aucun secret n'est versionné. Ils sont lus depuis l'environnement (`/terraform/.env`,
`/root/.proxmox-env`, `/root/.monitoring-env`, `backend.hcl`), tous exclus par `.gitignore`. Sur les
serveurs, ils sont écrits dans des fichiers séparés (droits `0640`, groupe du seul service qui les lit),
avec `no_log` côté Ansible. Le diff sortant est passé au scanner de secrets avant chaque push.

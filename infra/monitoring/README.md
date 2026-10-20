# Configurations de la supervision

Fichiers de configuration de la stack d'observabilité. Ils sont **déployés par les rôles Ansible**
(`infra/ansible/roles/*`, variable `monitoring_config_dir`) : on modifie ici, puis on applique avec

```sh
cd /srv/M2-EPSI-Workshop/infra/ansible
vault-env ansible-playbook monitoring.yml   # alloy/ concerne toutes les machines : vault-env ansible-playbook site.yml
```

Les fichiers `.j2` sont des templates Jinja2 : cibles, IP et ports viennent de l'inventaire
(`infra/ansible/inventory/hosts.yml`). Aucun secret ici : les mots de passe viennent de Vault
(`vault-env`) et sont lus depuis des fichiers posés par Ansible sur les serveurs.

| Dossier | Contenu | Équivalent classique | Déployé sur |
|---|---|---|---|
| `vmagent/scrape.yml.j2` | Jobs de scrape (stack, nœuds, Proxmox, Ceph, Docker, cAdvisor) | `prometheus.yml` | vmagent01-02 |
| `vmalert/rules/*.yml` | Règles d'alerte (format Prometheus) ; tout fichier ajouté est déployé | `rules/*.yml` | monitoring01 |
| `alertmanager/alertmanager.yml.j2` | Routage : Discord par défaut, Watchdog vers healthchecks.io | `alertmanager.yml` | monitoring01 |
| `loki/config.yml.j2` | Loki monolithique, stockage local, rétention 14 j | `loki.yml` | monitoring01 |
| `loki/nginx-loki.conf.j2` | Reverse proxy authentifiant devant Loki | | monitoring01 |
| `alloy/config.alloy.j2` | Lecture de journald (hôte + conteneurs) et des fichiers `alloy_log_files`, envoi vers Loki | promtail | les 17 machines (dont hyperviseurs, .110, WAF) |
| `grafana/datasources.yml.j2` | Sources VictoriaMetrics, Loki, Alertmanager | | monitoring01 |
| `grafana/dashboards/<Dossier>/` | Dashboards JSON ; un dossier = un dossier Grafana | | monitoring01 |
| `grafana/scripts/` | Génération (`gen-*.py`) et import figé (`fetch-dashboards.py`) des dashboards | | poste de contrôle |
| `swarm/stack.yml.j2`, `swarm/scrape.yml.j2` | vmagent dans le Swarm : `/metrics` des services applicatifs (cibles : `swarm_scrape_targets`) | | stack Swarm `monitoring` |

Documentation : [../docs/supervision.md](../docs/supervision.md).

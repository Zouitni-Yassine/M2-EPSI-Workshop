#!/usr/bin/env python3
"""Génère le dashboard Grafana « Plateforme - vue centrale » (uid central).

Un seul écran pour l'état de santé de toute la plateforme : en haut, un voyant par
brique (application, base répliquée, WAF, identités, assistant, sauvegardes, Proxmox,
Ceph, Swarm, supervision), chacun relié à son dashboard détaillé, puis les alertes.
Le détail est rangé dans des sections repliées (ouvertes à la demande : leurs requêtes
ne partent qu'à l'ouverture).

Usage (depuis infra/monitoring/grafana) : python3 scripts/gen-central-dashboard.py
Sortie : dashboards/Vue centrale/central.json

Toutes les requêtes sont en MetricsQL/PromQL (VictoriaMetrics) ou LogQL (Loki).
Les voyants « en panne / alertes » utilisent `or vector(0)` / `or label_set(...)`
pour afficher 0 ou « Aucune » plutôt que « No data » quand tout va bien.
"""
import json
import pathlib

OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "dashboards/Vue centrale/central.json")

VM = {"type": "prometheus", "uid": "victoriametrics"}
LOKI = {"type": "loki", "uid": "loki"}

# Taille nominale de la plateforme (affichée en suffixe « / N » sur les voyants).
NB_PVE = 3          # hyperviseurs ceph01-03
NB_OSD = 3
NB_MON = 3
NB_SWARM = 6        # 3 managers + 3 workers
NB_MANAGERS = 3
NB_VMAGENT = 2
NB_FRONTEND = 3     # frontal : une réplique par worker
NB_DB = 3           # nœuds Patroni db1-3 (un par worker) : 1 primaire + 2 réplicas
# Services de la stack paiement (db1-3, etcd1-3, auth, payment-api, detector,
# remediation, frontend, mailpit)
NB_PAIEMENT_SERVICES = 12
STACK_JOBS = ["victoriametrics", "vmalert", "alertmanager", "loki", "grafana"]
RAG_UNITS = ["ollama.service", "ollama-index.service", "rag-api.service",
             "rag-mcp.service", "discord-bot.service", "nginx.service"]
PAIEMENT = 'stack="paiement"'
DB_SVC = 'container_label_com_docker_swarm_service_name=~"paiement_db[0-9]+"'
WAF_ACCESS = ('{host="waf01", container="resilience-waf"} | json | __error__="" '
              '| event_type="http_access"')
WAF_BAN = '{host="waf01", identifier="waf-ban"}'
# pg_dump : une ligne par base, écrite deux fois dans le journal (logger -> notice,
# sortie du service -> info) : on ne garde que celle de logger
PGDUMP = '{host="control01", identifier="paiement-db-backup", level="notice"}'
PBS = '{host=~"ceph0[1-3]"}'
NOTIFY = ('{job="alertmanager-notify"} | json body | line_format "{{.body}}" '
          '| json status="status", alertname="alerts[0].labels.alertname", '
          'severity="alerts[0].labels.severity" | __error__=""')
GATEWAY = ('{identifier="remediate"} |= "code=" '
           '| regexp "code=(?P<code>[0-9]+) (?P<payload>.*)" | line_format "{{.payload}}" '
           '| json action, svc="service", duration_s, error')
BOT = '{host="rag01", unit="discord-bot.service"} |= "question" | logfmt | __error__=""'

# Niveaux journald considérés comme warning/erreur dans Loki.
LOG_LEVELS = "warning|warn|err|error|crit|alert|emerg"
LOG_SELECTOR = ('{job=~".+", host=~"$log_host", service=~"$log_service", '
                f'level=~"{LOG_LEVELS}"}}')

# Libellé de service Swarm : nom du service si le conteneur est une tâche Swarm,
# sinon nom du conteneur (ex. cadvisor, lancé hors Swarm).
def by_service(expr: str) -> str:
    inner = f'label_replace({expr}, "svc", "$1", "name", "(.*)")'
    return (f'label_replace({inner}, "svc", "$1", '
            '"container_label_com_docker_swarm_service_name", "(.+)")')


# --------------------------------------------------------------------------- #
# Briques de base
# --------------------------------------------------------------------------- #
_ids = iter(range(1, 1000))


def tgt(expr, legend="", ref="A", instant=False, fmt="time_series", ds=VM):
    t = {"datasource": ds, "refId": ref, "expr": expr, "legendFormat": legend}
    if ds is VM:
        t.update({"range": not instant, "instant": instant, "format": fmt,
                  "editorMode": "code"})
    else:
        t.update({"queryType": "instant" if instant else "range", "editorMode": "code"})
    return t


def steps(*pairs):
    """steps(("red", None), ("orange", 2), ("green", 3))"""
    return {"mode": "absolute",
            "steps": [{"color": c, "value": v} for c, v in pairs]}


GREEN_ONLY = steps(("green", None))
OK_IF_ZERO = steps(("green", None), ("orange", 1), ("red", 3))


def full_nominal(n, warn=None):
    """Vert si n, orange à partir de warn (défaut n-1), rouge en dessous."""
    warn = n - 1 if warn is None else warn
    if warn >= n:
        return steps(("red", None), ("green", n))
    return steps(("red", None), ("orange", warn), ("green", n))


def link(title, uid, params=""):
    return {"title": title, "url": f"/d/{uid}?${{__url_time_range}}{params}",
            "targetBlank": False}


def node_link(host):
    return link(f"Machine {host}", "node-exporter-full", f"&var-job=node&var-host={host}")


def panel(ptype, title, targets, pos, *, unit=None, thresholds=None,
          mappings=None, options=None, custom=None, overrides=None,
          links=None, desc="", decimals=None, minv=None, maxv=None,
          no_value=None, color=None, transformations=None, ds=VM,
          interval=None):
    x, y, w, h = pos
    defaults = {"mappings": mappings or [],
                "thresholds": thresholds or GREEN_ONLY}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if minv is not None:
        defaults["min"] = minv
    if maxv is not None:
        defaults["max"] = maxv
    if no_value is not None:
        defaults["noValue"] = no_value
    defaults["color"] = color or {"mode": "thresholds"}
    if custom is not None:
        defaults["custom"] = custom
    p = {"id": next(_ids), "type": ptype, "title": title, "description": desc,
         "datasource": ds, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": targets,
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if links:
        p["links"] = links
    if transformations:
        p["transformations"] = transformations
    if interval:
        p["interval"] = interval
    return p


def row(title, y):
    return {"id": next(_ids), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(title, targets, pos, *, text_mode="value", color_mode="background",
         orientation="auto", **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                              "values": False},
            "colorMode": color_mode, "graphMode": "none", "justifyMode": "center",
            "textMode": text_mode, "orientation": orientation,
            "wideLayout": True, "showPercentChange": False}
    return panel("stat", title, targets, pos, options=opts, **kw)


def timeseries(title, targets, pos, *, unit=None, stack=False, fill=10,
               legend="list", draw="line", soft_min=True, **kw):
    custom = {"drawStyle": draw, "lineWidth": 2, "fillOpacity": fill,
              "gradientMode": "opacity", "showPoints": "never",
              "spanNulls": False, "axisSoftMin": 0 if soft_min else None,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    custom = {k: v for k, v in custom.items() if v is not None}
    opts = {"legend": {"displayMode": "list" if legend == "hidden" else legend,
                       "placement": "bottom", "showLegend": legend != "hidden",
                       "calcs": ["lastNotNull", "max"] if legend == "table" else []},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    kw.setdefault("color", {"mode": "palette-classic"})
    return panel("timeseries", title, targets, pos, unit=unit, custom=custom,
                 options=opts, **kw)


def bargauge(title, targets, pos, *, unit=None, **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                              "values": False},
            "orientation": "horizontal", "displayMode": "gradient",
            "valueMode": "color", "showUnfilled": True, "namePlacement": "left",
            "sizing": "auto", "minVizHeight": 16, "maxVizHeight": 40}
    return panel("bargauge", title, targets, pos, unit=unit, options=opts, **kw)


def table(title, targets, pos, *, transformations=None, **kw):
    opts = {"showHeader": True, "cellHeight": "sm",
            "footer": {"show": False, "reducer": ["sum"], "fields": ""}}
    kw.setdefault("custom", {"align": "auto", "cellOptions": {"type": "auto"},
                             "inspect": False})
    return panel("table", title, targets, pos, options=opts,
                 transformations=transformations, **kw)


def override_name(name, props):
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def override_regex(regex, props):
    return {"matcher": {"id": "byRegexp", "options": regex}, "properties": props}


def fixed(color):
    return {"id": "color", "value": {"mode": "fixed", "fixedColor": color}}


def text_map(value, text, color):
    return {"type": "value",
            "options": {str(value): {"text": text, "color": color, "index": 0}}}


# --------------------------------------------------------------------------- #
# Panels
# --------------------------------------------------------------------------- #
panels = []
y = 0
V = 4  # hauteur d'un voyant


def tile(title, targets, x, *, uid, label=None, w=3, **kw):
    """Voyant d'une brique (3 colonnes sur 24 : 8 par ligne), relié à son dashboard."""
    kw.setdefault("links", [link(label or "Détail", uid)])
    return stat(title, targets, (x, y, w, V), **kw)


def ok_map(ok="OK", ko="KO", unknown=None):
    maps = [text_map(1, ok, "green"), text_map(0, ko, "red")]
    if unknown:
        maps.append(text_map(-1, unknown, "orange"))
    return maps


# ---- Briques : application et base répliquée ------------------------------------
db_primary = (
    'max by (name, host) (label_replace(max by (host, container_label_com_docker_swarm_service_name) '
    f'(container_last_seen{{{DB_SVC}}}), "service", "$1", '
    '"container_label_com_docker_swarm_service_name", "(.*)") '
    f'* on (service) group_left (name) max by (service, name) (patroni_primary{{{PAIEMENT}}} == 1)) '
    'or on() label_set(vector(0), "name", "AUCUN", "host", "-")')
panels += [
    tile("Paiements (sonde)",
         [tgt('min(paiement_probe_up) or vector(-1)', instant=True)], 0,
         uid="demo-remediation", label="Démo / Remédiation",
         mappings=ok_map("OK", "EN PANNE", "SONDE MUETTE"),
         thresholds=steps(("orange", None), ("red", 0), ("green", 1)),
         desc="Sonde de transaction (stack probe) : un client réel par l'adresse virtuelle, "
              "/api/health toutes les 5 s et un paiement de test toutes les 30 s."),
    tile("Entrée 10.30.1.200",
         [tgt('max by (host) (app_vip_master == 1) '
              'or on() label_set(vector(0), "host", "PERSONNE")', "{{host}}", instant=True)], 3,
         uid="swarm-overview", label="Swarm", text_mode="name",
         thresholds=steps(("red", None), ("green", 1)),
         desc="Worker qui porte l'adresse virtuelle de l'application (keepalived sur les 3 "
              "workers, métrique app_vip_master). Deux noms = conflit."),
    tile("Frontal",
         [tgt('count(container_last_seen{container_label_com_docker_swarm_service_name='
              '"paiement_frontend"}) or vector(0)', instant=True)], 6,
         uid="swarm-overview", label="Swarm", unit=f"suffix: / {NB_FRONTEND}",
         thresholds=full_nominal(NB_FRONTEND, warn=1),
         desc="Répliques du frontal (une par worker) vues par cAdvisor."),
    tile("Services paiement",
         [tgt('count(count by (container_label_com_docker_swarm_service_name) '
              f'(container_last_seen{{container_label_com_docker_stack_namespace="paiement"}})) '
              'or vector(0)', instant=True)], 9,
         uid="docker-containers", label="Conteneurs", unit=f"suffix: / {NB_PAIEMENT_SERVICES}",
         thresholds=full_nominal(NB_PAIEMENT_SERVICES, warn=10),
         desc="Services de la stack paiement ayant au moins un conteneur en marche : db1-3, "
              "etcd1-3, auth, payment-api, detector, remediation, frontend, mailpit."),
    tile("Base : primaire",
         [tgt(db_primary, "{{name}} · {{host}}", instant=True)], 12,
         uid="swarm-overview", label="Swarm : base répliquée", text_mode="name",
         thresholds=steps(("red", None), ("green", 1)),
         desc="Nœud Patroni primaire et le worker qui le fait tourner (bascule automatique "
              "si ce worker tombe). Deux noms = double primaire."),
    tile("Réplicas en flux",
         [tgt(f'count(patroni_replica{{{PAIEMENT}}} == 1 and on (instance) '
              f'patroni_postgres_streaming{{{PAIEMENT}}} == 1) or vector(0)', instant=True)], 15,
         uid="swarm-overview", label="Swarm : base répliquée", unit=f"suffix: / {NB_DB - 1}",
         thresholds=full_nominal(NB_DB - 1, warn=1),
         desc="Réplicas PostgreSQL qui reçoivent le flux de réplication du primaire."),
    tile("Détecteur ML",
         [tgt('max(detector_ready) or vector(-1)', instant=True)], 18,
         uid="ml-detecteur", label="Modèle ML",
         mappings=[text_map(1, "PRÊT", "green"), text_map(0, "APPRENTISSAGE", "orange"),
                   text_map(-1, "MUET", "red")],
         thresholds=steps(("red", None), ("orange", 0), ("green", 1)),
         desc="Détecteur d'anomalies (IsolationForest) : modèle entraîné et /metrics joignable."),
    tile("Moteur de remédiation",
         [tgt('max(paiement_probe_remediation_in_progress) or vector(-1)', instant=True)], 21,
         uid="demo-remediation", label="Démo / Remédiation",
         mappings=[text_map(0, "VEILLE", "green"), text_map(1, "EN ACTION", "orange"),
                   text_map(-1, "INCONNU", "red")],
         thresholds=steps(("red", None), ("green", 0), ("orange", 1)),
         desc="État du moteur (/remediation/state, relu par la sonde) : EN ACTION entre la "
              "décision et la reprise. Il agit par la passerelle remediate des managers."),
]
y += V

# ---- Briques : sécurité, identités, assistant, sauvegardes ------------------------
rag_re = "|".join(RAG_UNITS)
panels += [
    tile("WAF (waf01)",
         [tgt('max(pve_up * on (id) group_left (name) pve_guest_info{name="waf01"}) '
              'or vector(0)', instant=True)], 0,
         uid="resilience-cyber", label="Cyber", mappings=ok_map("EN MARCHE", "ARRÊTÉ"),
         thresholds=steps(("red", None), ("green", 1)),
         desc="VM du WAF (RA-DMZ 10.30.2.251) : NPM -> WAF -> adresse virtuelle."),
    tile("IP bannies au WAF",
         [tgt(f'max(last_over_time({WAF_BAN} |~ "^(ban|expiration) " | logfmt '
              '| unwrap actifs [20m]) by (host)) or vector(0)', ds=LOKI, instant=True)], 3,
         uid="resilience-cyber", label="Cyber", ds=LOKI, decimals=0,
         thresholds=steps(("green", None), ("orange", 1)), color_mode="value",
         desc="Bannissements actifs (15 min) posés par le récepteur waf-ban sur alerte Loki "
              "(rafale, force brute, attaques bloquées). Liste : sudo waf-ban list sur waf01."),
    tile("Vault",
         [tgt('max(vault_core_unsealed) or vector(0)', instant=True)], 6,
         uid="node-exporter-full", links=[node_link("vault01")],
         mappings=[text_map(1, "DESCELLÉ", "green"), text_map(0, "SCELLÉ", "red")],
         thresholds=steps(("red", None), ("green", 1)),
         desc="Coffre des secrets d'infrastructure. Scellé après un redémarrage : vault-unseal."),
    tile("Keycloak (SSO)",
         [tgt('max(up{job="keycloak"}) or vector(0)', instant=True)], 9,
         uid="node-exporter-full", links=[node_link("iam01")], mappings=ok_map(),
         thresholds=steps(("red", None), ("green", 1)),
         desc="Fournisseur d'identité (realm epsi, TOTP) : SSO de Grafana et Proxmox."),
    tile("Vaultwarden",
         [tgt('max(node_systemd_unit_state{host="vaultwarden01", name="vaultwarden.service", '
              'state="active"}) or vector(0)', instant=True)], 12,
         uid="node-exporter-full", links=[node_link("vaultwarden01")], mappings=ok_map(),
         thresholds=steps(("red", None), ("green", 1)),
         desc="Coffre des comptes de secours (service systemd vaultwarden)."),
    tile("Assistant (rag01)",
         [tgt(f'sum(node_systemd_unit_state{{host="rag01", state="active", name=~"{rag_re}"}}) '
              'or vector(0)', instant=True)], 15,
         uid="node-exporter-full", links=[node_link("rag01")], unit=f"suffix: / {len(RAG_UNITS)}",
         thresholds=full_nominal(len(RAG_UNITS), warn=4),
         desc="Services actifs sur rag01 : " + ", ".join(RAG_UNITS) + "."),
    tile("pg_dump (1 h)",
         [tgt(f'sum(count_over_time({PGDUMP} |= "ok base=payments" [1h])) or vector(0)',
              ds=LOKI, instant=True)], 18,
         uid="proxmox", label="Proxmox", ds=LOKI, unit="suffix: / 4", decimals=0,
         thresholds=steps(("red", None), ("orange", 1), ("green", 3)),
         desc="Sauvegardes logiques réussies de la base payments depuis une heure (pg_dump "
              "toutes les 15 min sur le poste de contrôle, sur le primaire courant)."),
    tile("Sauvegardes PBS (24 h)",
         [tgt(f'sum(count_over_time({PBS} |= "INFO: Finished Backup of VM" [24h])) '
              'or vector(0)', "réussies", ds=LOKI, instant=True),
          tgt(f'sum(count_over_time({PBS} |~ "ERROR: Backup of VM|ERROR: job failed" [24h])) '
              'or vector(0)', "erreurs", "B", ds=LOKI, instant=True)], 21,
         uid="proxmox", label="Proxmox", ds=LOKI, decimals=0,
         text_mode="value_and_name", color_mode="value",
         thresholds=steps(("green", None), ("red", 1)),
         overrides=[override_name("réussies", [fixed("blue")])],
         desc="Sauvegardes de VM/LXC vers Proxmox Backup Server (jobs 13h00 et 21h00) "
              "terminées ou en erreur, d'après le journal des hyperviseurs."),
]
y += V

# ---- Voyants ---------------------------------------------------------------
panels += [
    stat("Alertes actives",
         [tgt('count(ALERTS{alertstate="firing", alertname!="Watchdog"}) or vector(0)',
              instant=True)],
         (0, y, 4, V), thresholds=OK_IF_ZERO,
         desc="Alertes vmalert en état firing (hors Watchdog, toujours active par conception).",
         links=[link("vmalert", "vmalert")]),
    stat("Hyperviseurs Proxmox",
         [tgt('sum(pve_up{id=~"node/.+"}) or vector(0)', instant=True)],
         (4, y, 4, V), unit=f"suffix: / {NB_PVE}", thresholds=full_nominal(NB_PVE),
         desc="Nœuds Proxmox en ligne vus par l'API du cluster (pve-exporter).",
         links=[link("Proxmox", "proxmox")]),
    stat("Ceph santé",
         [tgt('max(ceph_health_status) or vector(-1)', instant=True)],
         (8, y, 4, V),
         thresholds=steps(("red", None), ("green", 0), ("orange", 1), ("red", 2)),
         mappings=[text_map(-1, "INCONNU", "red"), text_map(0, "HEALTH_OK", "green"),
                   text_map(1, "HEALTH_WARN", "orange"), text_map(2, "HEALTH_ERR", "red")],
         desc="ceph_health_status du mgr actif (INCONNU = métriques Ceph absentes).",
         links=[link("Ceph", "proxmox")]),
    stat("OSD up / in",
         [tgt('sum(ceph_osd_up) or vector(0)', "up", instant=True),
          tgt('sum(ceph_osd_in) or vector(0)', "in", "B", instant=True)],
         (12, y, 4, V), text_mode="value_and_name", unit=f"suffix: / {NB_OSD}",
         thresholds=full_nominal(NB_OSD),
         desc="OSD démarrés (up) et intégrés au placement des données (in).",
         links=[link("Ceph", "proxmox")]),
    stat("Quorum MON Ceph",
         [tgt('sum(max by (ceph_daemon) (ceph_mon_quorum_status)) or vector(0)',
              instant=True)],
         (16, y, 4, V), unit=f"suffix: / {NB_MON}",
         thresholds=full_nominal(NB_MON, warn=2),
         desc="Moniteurs dans le quorum (2/3 suffisent pour garder le cluster disponible).",
         links=[link("Ceph", "proxmox")]),
    stat("PG Ceph active+clean",
         [tgt('(sum(ceph_pg_clean) / sum(ceph_pg_total)) or vector(0)', instant=True)],
         (20, y, 4, V), unit="percentunit", decimals=0,
         thresholds=steps(("red", None), ("orange", 0.9), ("green", 1)),
         desc="Part des placement groups propres. < 100 % = réplication/reconstruction en cours.",
         links=[link("Ceph", "proxmox")]),
]
y += V
panels += [
    stat("Nœuds Swarm ready",
         [tgt('max(swarm_manager_nodes{state="ready"}) or vector(0)', instant=True)],
         (0, y, 4, V), unit=f"suffix: / {NB_SWARM}",
         thresholds=full_nominal(NB_SWARM, warn=4),
         desc="Nœuds du cluster Swarm à l'état ready (vu par les managers).",
         links=[link("Swarm", "swarm-overview")]),
    stat("Managers joignables",
         [tgt('count(up{job="docker", role="swarm_manager"} == 1) or vector(0)',
              instant=True)],
         (4, y, 4, V), unit=f"suffix: / {NB_MANAGERS}",
         thresholds=full_nominal(NB_MANAGERS, warn=2),
         desc="Managers Swarm qui répondent. 2/3 = quorum Raft conservé ; < 2 = quorum perdu.",
         links=[link("Swarm", "swarm-overview")]),
    stat("Leader Swarm",
         [tgt('max by (host) (swarm_manager_leader == 1) '
              'or on() label_set(vector(0), "host", "AUCUN")', "{{host}}", instant=True)],
         (8, y, 4, V), text_mode="name",
         thresholds=steps(("red", None), ("green", 1)),
         desc="Manager actuellement leader Raft (change lors d'une bascule).",
         links=[link("Swarm", "swarm-overview")]),
    stat("Tâches Swarm",
         [tgt('max(swarm_manager_tasks_total{state="running"}) or vector(0)',
              "running", instant=True),
          tgt('max(swarm_manager_tasks_total{state=~"failed|rejected"}) or vector(0)',
              "échec", "B", instant=True)],
         (12, y, 4, V), text_mode="value_and_name", color_mode="value",
         thresholds=steps(("green", None), ("orange", 1)),
         overrides=[override_name("running", [fixed("blue")])],
         desc="Tâches running / en échec (failed+rejected, conservées dans l'historique Swarm).",
         links=[link("Swarm", "swarm-overview")]),
    stat("Cibles supervisées",
         [tgt('count(up == 1) or vector(0)', "en ligne", instant=True),
          tgt('count(up == 0) or vector(0)', "en panne", "B", instant=True)],
         (16, y, 4, V), text_mode="value_and_name", color_mode="value",
         thresholds=steps(("green", None), ("red", 1)),
         overrides=[override_name("en ligne", [fixed("blue")])],
         desc="Cibles scrapées par les vmagents (toutes les jobs).",
         links=[link("vmagent", "vmagent")]),
    stat("Redondance vmagent",
         [tgt('count(up{job="vmagent"} == 1) or vector(0)', instant=True)],
         (20, y, 4, V), unit=f"suffix: / {NB_VMAGENT}",
         thresholds=full_nominal(NB_VMAGENT),
         desc="Collecteurs actifs (2 vmagents redondants, dédupliqués par VictoriaMetrics).",
         links=[link("vmagent", "vmagent")]),
]
y += V

# ---- Alertes ---------------------------------------------------------------
panels.append(row("Alertes", y)); y += 1
panels += [
    panel("state-timeline", "Historique des alertes",
          [tgt('count by (alertname) (ALERTS{alertstate="firing"})', "{{alertname}}")],
          (0, y, 14, 8),
          thresholds=steps(("red", None)),
          mappings=[{"type": "range",
                     "options": {"from": 1, "to": 1e9,
                                 "result": {"text": "FIRING", "color": "red"}}}],
          overrides=[override_name("Watchdog", [
              {"id": "mappings", "value": [{"type": "range", "options": {
                  "from": 1, "to": 1e9,
                  "result": {"text": "chaîne d'alerte OK", "color": "green"}}}]}])],
          custom={"fillOpacity": 80, "lineWidth": 0, "spanNulls": False,
                  "insertNulls": 90000, "hideFrom": {"legend": False,
                                                    "tooltip": False, "viz": False}},
          options={"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                   "alignValue": "left", "legend": {"showLegend": False,
                                                    "displayMode": "list",
                                                    "placement": "bottom"},
                   "tooltip": {"mode": "single", "sort": "none"}},
          desc="Périodes de déclenchement de chaque alerte. Watchdog (vert) prouve que "
               "la chaîne vmalert -> Alertmanager fonctionne.",
          links=[link("vmalert", "vmalert")]),
    table("Alertes en cours",
          [tgt('ALERTS{alertstate="firing", alertname!="Watchdog"} '
               'or on() label_set(vector(0), "alertname", "Aucune alerte active")',
               instant=True, fmt="table")],
          (14, y, 10, 8),
          transformations=[{"id": "organize", "options": {
              "excludeByName": {"Time": True, "Value": True, "__name__": True,
                                "alertstate": True, "alertgroup": True},
              "indexByName": {"alertname": 0, "severity": 1, "host": 2, "job": 3,
                              "instance": 4},
              "renameByName": {"alertname": "Alerte", "severity": "Sévérité",
                               "host": "Hôte", "job": "Job",
                               "instance": "Instance"}}}],
          overrides=[override_name("Sévérité", [
              {"id": "custom.cellOptions", "value": {"type": "color-background"}},
              {"id": "mappings", "value": [{"type": "value", "options": {
                  "critical": {"color": "red", "index": 0},
                  "warning": {"color": "orange", "index": 1},
                  "info": {"color": "blue", "index": 2}}}]}])],
          desc="Alertes firing (série ALERTS écrite par vmalert)."),
]
y += 8

# Sections de détail : repliées à l'ouverture (voir COLLAPSED en fin de script)
LOGS_OPTS = {"showTime": True, "showLabels": False, "showCommonLabels": False,
             "wrapLogMessage": True, "prettifyLogMessage": False,
             "enableLogDetails": True, "enableInfiniteScrolling": False,
             "dedupStrategy": "none", "sortOrder": "Descending"}


def logs(title, expr, pos, desc="", **kw):
    return panel("logs", title, [tgt(expr, ds=LOKI)], pos, ds=LOKI, options=LOGS_OPTS,
                 desc=desc, **kw)


def timeline(title, targets, pos, mappings, **kw):
    kw.setdefault("thresholds", steps(("red", None), ("green", 1)))
    return panel("state-timeline", title, targets, pos, mappings=mappings,
                 custom={"lineWidth": 0, "fillOpacity": 85},
                 options={"showValue": "auto", "mergeValues": True, "rowHeight": 0.85,
                          "alignValue": "center", "legend": {"showLegend": False,
                                                             "displayMode": "list",
                                                             "placement": "bottom"},
                          "tooltip": {"mode": "single", "sort": "none"}}, **kw)


# ---- Application : stack paiement -------------------------------------------
API_BUSINESS = 'service="paiement_payment-api", route!~"/api/(status|health)"'
panels.append(row("Application : stack paiement", y)); y += 1
panels += [
    table("Placement des services",
          [tgt('count by (container_label_com_docker_stack_namespace, '
               'container_label_com_docker_swarm_service_name, host) (container_last_seen'
               '{container_label_com_docker_stack_namespace=~"paiement|probe|registry|monitoring"})',
               instant=True, fmt="table")],
          (0, y, 8, 13),
          transformations=[
              {"id": "organize", "options": {
                  "excludeByName": {"Time": True},
                  "indexByName": {"container_label_com_docker_stack_namespace": 0,
                                  "container_label_com_docker_swarm_service_name": 1,
                                  "host": 2, "Value": 3},
                  "renameByName": {"container_label_com_docker_stack_namespace": "Stack",
                                   "container_label_com_docker_swarm_service_name": "Service",
                                   "host": "Worker", "Value": "Conteneurs"}}},
              {"id": "sortBy", "options": {"sort": [{"field": "Service"}]}}],
          overrides=[override_name("Worker", [
              {"id": "custom.cellOptions", "value": {"type": "color-text"}},
              {"id": "color", "value": {"mode": "palette-classic-by-name"}}])],
          desc="Conteneurs en marche par service et par worker (cAdvisor) : stack paiement, "
               "sonde, registre privé 10.30.1.221:5000, vmagent du Swarm.",
          links=[link("Conteneurs", "docker-containers")]),
    timeline("Porteur de l'adresse virtuelle 10.30.1.200",
             [tgt('max by (host) (app_vip_master)', "{{host}}")], (8, y, 8, 5),
             mappings=[text_map(1, "PORTEUR", "green"), text_map(0, "secours", "transparent")],
             desc="keepalived (unicast, nopreempt) sur les 3 workers : l'adresse change de "
                  "worker quand son porteur tombe.",
             links=[link("Swarm", "swarm-overview")]),
    stat("Dépendances de payment-api",
         [tgt('max by (dependency) (payment_api_dependency_up)', "{{dependency}}",
              instant=True)],
         (8, y + 5, 8, 4), text_mode="value_and_name", mappings=ok_map(),
         thresholds=steps(("red", None), ("green", 1)),
         desc="Base de données et prestataires de paiement (Stripe, PayPal en mode test) vus "
              "par payment-api."),
    timeseries("payment-api : requêtes et erreurs",
               [tgt(f'sum(rate(http_requests_total{{{API_BUSINESS}}}[$__rate_interval]))',
                    "requêtes/s"),
                tgt('sum(rate(http_requests_total{service="paiement_payment-api", '
                    'code=~"5.."}[$__rate_interval])) or vector(0)', "5xx/s", "B")],
               (16, y, 8, 9), unit="reqps",
               overrides=[override_name("5xx/s", [fixed("red")])],
               desc="Requêtes métier (hors /api/status et /api/health) et réponses 5xx.",
               links=[link("Démo / Remédiation", "demo-remediation")]),
    timeseries("payment-api : latence p95",
               [tgt('histogram_quantile(0.95, sum by (le) (rate('
                    f'http_request_duration_seconds_bucket{{{API_BUSINESS}}}[$__rate_interval])))',
                    "p95")],
               (8, y + 9, 8, 4), unit="s", legend="hidden",
               links=[link("Démo / Remédiation", "demo-remediation")]),
    timeseries("Sonde : durée des étapes",
               [tgt('max by (step) (paiement_probe_step_duration_seconds)', "{{step}}")],
               (16, y + 9, 8, 4), unit="s", legend="hidden",
               desc="Dernière transaction de la sonde : frontal, santé, connexion, création, "
                    "confirmation (Stripe en mode test).",
               links=[link("Démo / Remédiation", "demo-remediation")]),
]
y += 13
panels += [
    timeseries("Connexions et reconnaissance faciale",
               [tgt('sum by (result) (increase(auth_login_total[$__rate_interval]))',
                    "connexion {{result}}"),
                tgt('sum by (result) (increase(auth_face_total{result!="enrolled"}'
                    '[$__rate_interval]))', "visage {{result}}", "B")],
               (0, y, 8, 8), draw="bars", fill=80, stack=True, decimals=0,
               overrides=[override_regex(".*(failure|locked|rejected)", [fixed("red")])],
               desc="Service auth : connexions (succès, échec, blocage) et identification des "
                    "opérateurs par la caméra (reconnus, refusés, bloqués).",
               links=[link("Démo / Remédiation", "demo-remediation"),
                      link("Cyber", "resilience-cyber")]),
    timeseries("Détecteur : score d'anomalie",
               [tgt('max(detector_anomaly_score)', "score"),
                tgt('max(detector_threshold)', "seuil", "B")],
               (8, y, 8, 8), decimals=2,
               overrides=[override_name("seuil", [
                   fixed("red"), {"id": "custom.fillOpacity", "value": 0},
                   {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}])],
               desc="Score du détecteur (IsolationForest, /metrics, à 30 s près). Détail du "
                    "modèle dans le dashboard Modèle ML.",
               links=[link("Modèle ML", "ml-detecteur")]),
    logs("Passerelle remediate : actions du moteur",
         GATEWAY + ' | line_format "{{.action}} {{.svc}} : {{if .duration_s}}{{.duration_s}} s'
                   '{{else}}{{.error}}{{end}} (code {{.code}})"',
         (16, y, 8, 8),
         desc="Actions demandées par le moteur de remédiation à la passerelle des managers "
              "(SSH, commande forcée remediate) : durée du redémarrage ou refus (limites : "
              "60 s entre deux actions sur un service, 10 actions / 10 min).",
         links=[link("Démo / Remédiation", "demo-remediation")]),
]
y += 8

# ---- Base PostgreSQL répliquée (Patroni + etcd) ---------------------------------
db_role = (f'max by (name) (3 * patroni_primary{{{PAIEMENT}}} + patroni_replica{{{PAIEMENT}}} '
           f'* (1 + patroni_postgres_streaming{{{PAIEMENT}}}))')
primary_lsn = (f'scalar(max(patroni_xlog_location{{{PAIEMENT}}} and on (instance) '
               f'patroni_primary{{{PAIEMENT}}} == 1))')
replica = f'on (instance) patroni_replica{{{PAIEMENT}}} == 1'
panels.append(row("Base PostgreSQL répliquée (Patroni)", y)); y += 1
panels += [
    stat("Primaire", [tgt(db_primary, "{{name}} · {{host}}", instant=True)],
         (0, y, 4, 4), text_mode="name", thresholds=steps(("red", None), ("green", 1)),
         desc="Nœud primaire et worker qui l'héberge."),
    stat("Nœuds Patroni joignables",
         [tgt('count(up{job=~"paiement_db[0-9]+"} == 1) or vector(0)', instant=True)],
         (4, y, 4, 4), unit=f"suffix: / {NB_DB}", thresholds=full_nominal(NB_DB, warn=2),
         desc="API Patroni (/metrics, port 8008) de db1, db2, db3."),
    stat("Timeline PostgreSQL",
         [tgt(f'max(patroni_postgres_timeline{{{PAIEMENT}}})', instant=True)],
         (8, y, 4, 4), color_mode="value", thresholds=steps(("blue", None)),
         desc="Augmente de 1 à chaque bascule (promotion d'un réplica)."),
    stat("etcd vu il y a",
         [tgt(f'max(time() - patroni_dcs_last_seen{{{PAIEMENT}}})', instant=True)],
         (12, y, 4, 4), unit="s", decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("orange", 30), ("red", 60)),
         desc="Dernier contact de Patroni avec etcd (etcd1-3, magasin du verrou de leader). "
              "Au-delà de 60 s : alerte PaiementDbEtcdInjoignable."),
    timeline("Rôle des nœuds", [tgt(db_role, "{{name}}")], (16, y, 8, 8),
             mappings=[text_map(3, "PRIMAIRE", "blue"), text_map(2, "réplica en flux", "green"),
                       text_map(1, "réplica sans flux", "orange")],
             thresholds=steps(("orange", None)),
             desc="Primaire, réplicas qui reçoivent le flux, réplicas décrochés. Une bascule "
                  "se voit au changement de couleur."),
    timeseries("Retard de réplication",
               [tgt(f'clamp_min({primary_lsn} - (patroni_xlog_received_location{{{PAIEMENT}}} '
                    f'and {replica}), 0)', "{{name}} reçu"),
                tgt(f'clamp_min(patroni_xlog_received_location{{{PAIEMENT}}} - '
                    f'patroni_xlog_replayed_location{{{PAIEMENT}}}, 0) and {replica}',
                    "{{name}} rejoué", "B")],
               (0, y + 4, 16, 4), unit="bytes", legend="hidden",
               desc="Octets de WAL en retard sur le primaire (reçus, puis rejoués). Alerte "
                    "PaiementDbReplicationRetard au-delà de 16 Mo."),
]
y += 8

# ---- Sécurité : WAF et bannissements --------------------------------------------
panels.append(row("Sécurité : WAF et bannissements", y)); y += 1
panels += [
    timeseries("Requêtes au WAF par statut",
               [tgt(f'sum by (status) (count_over_time({WAF_ACCESS} [$__auto]))', "{{status}}",
                    ds=LOKI)],
               (0, y, 10, 8), ds=LOKI, draw="bars", fill=80, stack=True, unit="short",
               overrides=[override_regex("4..", [fixed("orange")]),
                          override_regex("403", [fixed("red")]),
                          override_regex("5..", [fixed("dark-red")])],
               desc="Requêtes publiques (NPM -> waf01) par code HTTP. 403 = bloquée par "
                    "ModSecurity ou par la liste des IP bannies.",
               links=[link("Cyber", "resilience-cyber")]),
    bargauge("IP les plus bloquées (403)",
             [tgt(f'topk(10, sum by (source_ip) (count_over_time({WAF_ACCESS} | status="403" '
                  '[$__range])))', "{{source_ip}}", ds=LOKI, instant=True)],
             (10, y, 5, 8), ds=LOKI, decimals=0, minv=0, no_value="aucune",
             thresholds=steps(("orange", None), ("red", 10)),
             desc="Sur la période affichée (IP réelle du client, transmise par NPM).",
          links=[link("Cyber", "resilience-cyber")]),
    logs("Bannissements (waf-ban)", WAF_BAN + ' |~ "^(ban|expiration|refus|erreur)"',
         (15, y, 9, 8),
         desc="Récepteur waf-ban de waf01 : bannissement 15 min sur alerte Loki (WafSourceFlood, "
              "WafSourceBruteForce, WafSourceAttacks) via Alertmanager, expiration, refus "
              "(liste blanche, plafonds).",
         links=[link("Cyber", "resilience-cyber")]),
]
y += 8

# ---- Assistant RAG (rag01) ------------------------------------------------------
panels.append(row("Assistant (rag01) et bot Discord", y)); y += 1
panels += [
    timeline("Services de rag01",
             [tgt(f'max by (name) (node_systemd_unit_state{{host="rag01", state="active", '
                  f'name=~"{rag_re}"}})', "{{name}}")], (0, y, 8, 8),
             mappings=[text_map(1, "actif", "green"), text_map(0, "arrêté", "red")],
             desc="Ollama (modèle et index), API rag-api (:8600), serveur MCP supervision "
                  "(lecture seule), bot Discord, relais nginx GPU/CPU.",
             links=[node_link("rag01")]),
    timeseries("Bot Discord : temps de réponse",
               [tgt(f'max by (statut) (max_over_time({BOT} | unwrap duration(total) '
                    '[$__interval]))', "{{statut}}", ds=LOKI)],
               (8, y, 8, 8), ds=LOKI, unit="s", interval="2m",
               overrides=[override_regex("ok", [fixed("green")])],
               desc="Durée totale de chaque question posée au bot (#assistance-rag), par statut "
                    "(ok, http_504 = délai de l'API dépassé)."),
    timeseries("rag01 : CPU et mémoire",
               [tgt('1 - avg(rate(node_cpu_seconds_total{host="rag01", mode="idle"}'
                    '[$__rate_interval]))', "CPU"),
                tgt('1 - node_memory_MemAvailable_bytes{host="rag01"} '
                    '/ node_memory_MemTotal_bytes{host="rag01"}', "mémoire", "B")],
               (16, y, 8, 8), unit="percentunit", minv=0, maxv=1,
               desc="Le modèle tourne sur le GPU de délestage quand le tunnel est ouvert, "
                    "sinon sur le CPU de rag01 (repli).",
               links=[node_link("rag01")]),
]
y += 8
panels.append(logs("Questions au bot (sans le nom de l'auteur)",
                   BOT + ' | line_format "statut={{.statut}} outils={{.outils}} '
                         'api={{.duree_api}} total={{.total}}"',
                   (0, y, 24, 6)))
y += 6

# ---- Sauvegardes ----------------------------------------------------------------
panels.append(row("Sauvegardes", y)); y += 1
panels += [
    stat("pg_dump réussis (période)",
         [tgt(f'sum(count_over_time({PGDUMP} |= "ok base=" [$__range])) or vector(0)',
              ds=LOKI, instant=True)],
         (0, y, 4, 4), ds=LOKI, decimals=0, color_mode="value",
         thresholds=steps(("red", None), ("green", 1)),
         desc="Dumps réussis (une ligne par base : auth, payments) sur la période affichée."),
    stat("pg_dump en échec (période)",
         [tgt(f'sum(count_over_time({PGDUMP} |= "echec" [$__range])) or vector(0)',
              ds=LOKI, instant=True)],
         (0, y + 4, 4, 4), ds=LOKI, decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("red", 1))),
    timeseries("Taille des dumps",
               [tgt(f'max by (base) (max_over_time({PGDUMP} |= "ok base=" | logfmt '
                    '| unwrap taille [$__interval]))', "{{base}}", ds=LOKI)],
               (4, y, 8, 8), ds=LOKI, unit="bytes", interval="15m",
               desc="Taille de chaque dump (format custom pg_dump) dans /var/backups/paiement "
                    "sur le poste de contrôle."),
    stat("Invités hors sauvegarde",
         [tgt('max(pve_not_backed_up_total) or vector(0)', instant=True)],
         (12, y, 4, 4), color_mode="value", thresholds=steps(("green", None), ("orange", 1)),
         desc="VM/LXC qu'aucun job de sauvegarde Proxmox ne couvre.",
         links=[link("Proxmox", "proxmox")]),
    stat("PBS (période)",
         [tgt(f'sum(count_over_time({PBS} |= "INFO: Finished Backup of VM" [$__range])) '
              'or vector(0)', "réussies", ds=LOKI, instant=True),
          tgt(f'sum(count_over_time({PBS} |~ "ERROR: Backup of VM|ERROR: job failed" '
              '[$__range])) or vector(0)', "erreurs", "B", ds=LOKI, instant=True)],
         (12, y + 4, 4, 4), ds=LOKI, decimals=0, text_mode="value_and_name",
         color_mode="value", thresholds=steps(("green", None), ("red", 1)),
         overrides=[override_name("réussies", [fixed("blue")])]),
    logs("Journal des sauvegardes (pg_dump et PBS)",
         '{host=~"control01|ceph0[1-3]"} |~ "^(ok|echec) base=|restauration-test|'
         'starting new backup job|Finished Backup of VM|ERROR: Backup of VM|Backup job finished" '
         '| level!="info" or host!="control01"',
         (16, y, 8, 8),
         desc="pg_dump toutes les 15 min (paiement-db-backup) et jobs vzdump vers Proxmox "
              "Backup Server (13h00, 21h00 ; une sauvegarde gèle les VM ~45 s)."),
]
y += 8

# ---- Notifications Discord -------------------------------------------------------
panels.append(row("Notifications Discord (Alertmanager)", y)); y += 1
panels += [
    stat("Notifications envoyées (période)",
         [tgt(f'sum by (status) (count_over_time({NOTIFY} [$__range]))', "{{status}}",
              ds=LOKI, instant=True)],
         (0, y, 6, 6), ds=LOKI, decimals=0, text_mode="value_and_name", color_mode="value",
         orientation="horizontal", thresholds=steps(("blue", None)),
         overrides=[override_name("firing", [fixed("red")]),
                    override_name("resolved", [fixed("green")])],
         desc="Copie de chaque notification envoyée au salon Discord (récepteur webhook "
              "journalisé sur monitoring01, job alertmanager-notify)."),
    logs("Dernières notifications",
         NOTIFY + ' | line_format "{{.status}} {{.alertname}} ({{.severity}})"',
         (6, y, 18, 6),
         desc="Mêmes notifications que sur Discord et dans la page Supervision du back-office."),
]
y += 6

# ---- Proxmox ---------------------------------------------------------------
panels.append(row("Proxmox", y)); y += 1
node_lbl = '"node", "$1", "id", "node/(.+)"'
panels += [
    timeseries("CPU par hyperviseur",
               [tgt(f'label_replace(pve_cpu_usage_ratio{{id=~"node/.+"}}, {node_lbl})',
                    "{{node}}")],
               (0, y, 8, 7), unit="percentunit", minv=0, maxv=1,
               links=[link("Proxmox", "proxmox")]),
    timeseries("RAM par hyperviseur",
               [tgt(f'label_replace(pve_memory_usage_bytes{{id=~"node/.+"}} '
                    f'/ pve_memory_size_bytes{{id=~"node/.+"}}, {node_lbl})', "{{node}}")],
               (8, y, 8, 7), unit="percentunit", minv=0, maxv=1,
               links=[link("Proxmox", "proxmox")]),
    bargauge("Stockages Proxmox",
             [tgt('max by (storage) ((pve_disk_usage_bytes / pve_disk_size_bytes) '
                  '* on(id) group_left(storage) pve_storage_info{plugintype="rbd"})',
                  "Ceph RBD {{storage}}", instant=True),
              tgt('(pve_disk_usage_bytes / pve_disk_size_bytes) * on(id) '
                  'group_left(node, storage) pve_storage_info{plugintype=~"dir|lvmthin"}',
                  "{{node}} {{storage}}", "B", instant=True)],
             (16, y, 8, 7), unit="percentunit", minv=0, maxv=1, decimals=1,
             thresholds=steps(("green", None), ("orange", 0.75), ("red", 0.9)),
             desc="Taux d'occupation des stockages (RBD partagés sur Ceph + disque local).",
             links=[link("Proxmox", "proxmox")]),
]
y += 7
guest_sel = '{id=~"(qemu|lxc)/.+"}'
panels += [
    table("Invités (VM / LXC)",
          [tgt('pve_guest_info{template="0"}', ref="A", instant=True, fmt="table"),
           tgt(f'pve_up{guest_sel}', ref="B", instant=True, fmt="table"),
           tgt(f'pve_cpu_usage_ratio{guest_sel}', ref="C", instant=True, fmt="table"),
           tgt(f'pve_memory_usage_bytes{guest_sel} / pve_memory_size_bytes{guest_sel}',
               ref="D", instant=True, fmt="table"),
           tgt(f'max by (id, state) (pve_ha_state{guest_sel} == 1)', ref="E",
               instant=True, fmt="table")],
          (0, y, 16, 9),
          transformations=[
              {"id": "merge", "options": {}},
              {"id": "filterByValue", "options": {
                  "type": "exclude", "match": "any",
                  "filters": [{"fieldName": "name",
                               "config": {"id": "isNull", "options": {}}}]}},
              {"id": "organize", "options": {
                  "excludeByName": {"Time": True, "__name__": True, "instance": True,
                                    "job": True, "tags": True, "template": True,
                                    "Value #A": True, "Value #E": True},
                  "indexByName": {"name": 0, "type": 1, "node": 2, "Value #B": 3,
                                  "state": 4, "Value #C": 5, "Value #D": 6, "id": 7},
                  "renameByName": {"name": "Nom", "type": "Type",
                                   "node": "Hyperviseur", "Value #B": "État",
                                   "state": "HA", "Value #C": "CPU",
                                   "Value #D": "RAM", "id": "ID"}}},
              {"id": "sortBy", "options": {"sort": [{"field": "Nom"}]}}],
          overrides=[
              override_name("État", [
                  {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                  {"id": "mappings", "value": [{"type": "value", "options": {
                      "0": {"text": "ARRÊTÉ", "color": "red", "index": 0},
                      "1": {"text": "EN MARCHE", "color": "green", "index": 1}}}]}]),
              override_name("CPU", [{"id": "unit", "value": "percentunit"},
                                    {"id": "decimals", "value": 1},
                                    {"id": "custom.cellOptions",
                                     "value": {"type": "gauge", "mode": "basic"}},
                                    {"id": "max", "value": 1}]),
              override_name("RAM", [{"id": "unit", "value": "percentunit"},
                                    {"id": "decimals", "value": 1},
                                    {"id": "custom.cellOptions",
                                     "value": {"type": "gauge", "mode": "basic"}},
                                    {"id": "max", "value": 1}]),
              override_name("Hyperviseur", [
                  {"id": "custom.cellOptions", "value": {"type": "color-text"}},
                  {"id": "color", "value": {"mode": "palette-classic-by-name"}}])],
          thresholds=steps(("green", None), ("orange", 0.75), ("red", 0.9)),
          desc="Placement et état des invités : permet de voir une VM redémarrer "
               "ou migrer sur un autre hyperviseur (colonne HA = ressource gérée par le HA Proxmox).",
          links=[link("Proxmox", "proxmox")]),
    stat("Invités en marche",
         [tgt('sum(pve_up{id=~"(qemu|lxc)/.+"} * on(id) group_left() '
              'pve_guest_info{template="0"}) or vector(0)', instant=True)],
         (16, y, 4, 9), thresholds=steps(("red", None), ("orange", 1)),
         desc="VM et conteneurs LXC démarrés (templates exclus).",
         color_mode="value",
         links=[link("Proxmox", "proxmox")]),
    stat("Ressources HA",
         [tgt('count(pve_ha_state{id=~"(qemu|lxc)/.+", state="started"} == 1) or vector(0)',
              "démarrées", instant=True),
          tgt('count(pve_ha_state{id=~"(qemu|lxc)/.+", '
              'state=~"recovery|fence|migrate|relocate|error|freeze"} == 1) or vector(0)',
              "en bascule / erreur", "B", instant=True)],
         (20, y, 4, 9), text_mode="value_and_name", color_mode="value",
         orientation="horizontal",
         thresholds=steps(("green", None), ("orange", 1)),
         overrides=[override_name("démarrées", [fixed("blue")])],
         desc="Ressources du HA Proxmox : en bascule = recovery/fence/migrate/relocate/error.",
         links=[link("Proxmox", "proxmox")]),
]
y += 9

# ---- Ceph ------------------------------------------------------------------
panels.append(row("Ceph", y)); y += 1
panels += [
    panel("gauge", "Capacité Ceph utilisée",
          [tgt('max(ceph_cluster_total_used_bytes) / max(ceph_cluster_total_bytes)',
               instant=True)],
          (0, y, 4, 8), unit="percentunit", minv=0, maxv=1, decimals=1,
          thresholds=steps(("green", None), ("orange", 0.7), ("red", 0.85)),
          options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                     "values": False},
                   "showThresholdMarkers": True, "showThresholdLabels": False,
                   "orientation": "auto", "sizing": "auto"},
          links=[link("Ceph", "proxmox")]),
    stat("Volume brut",
         [tgt('max(ceph_cluster_total_used_bytes)', "utilisé", instant=True),
          tgt('max(ceph_cluster_total_bytes)', "total", "B", instant=True)],
         (4, y, 4, 4), text_mode="value_and_name", color_mode="value", unit="bytes",
         color={"mode": "fixed", "fixedColor": "blue"}, decimals=1,
         links=[link("Ceph", "proxmox")]),
    stat("PG dégradés / non actifs",
         [tgt('sum(ceph_pg_degraded) or vector(0)', "dégradés", instant=True),
          tgt('(sum(ceph_pg_total) - sum(ceph_pg_active)) or vector(0)', "non actifs",
              "B", instant=True)],
         (4, y + 4, 4, 4), text_mode="value_and_name", color_mode="value",
         thresholds=steps(("green", None), ("orange", 1)),
         desc="PG dégradés = copies manquantes (OSD perdu), reconstruction automatique en cours.",
         links=[link("Ceph", "proxmox")]),
    timeseries("IOPS client",
               [tgt('sum(rate(ceph_pool_rd[$__rate_interval]))', "lecture"),
                tgt('sum(rate(ceph_pool_wr[$__rate_interval]))', "écriture", "B")],
               (8, y, 5, 8), unit="iops", links=[link("Ceph", "proxmox")]),
    timeseries("Débit client",
               [tgt('sum(rate(ceph_pool_rd_bytes[$__rate_interval]))', "lecture"),
                tgt('sum(rate(ceph_pool_wr_bytes[$__rate_interval]))', "écriture", "B")],
               (13, y, 5, 8), unit="Bps", links=[link("Ceph", "proxmox")]),
    timeseries("Latence OSD",
               [tgt('max by (ceph_daemon) (ceph_osd_commit_latency_ms)',
                    "commit {{ceph_daemon}}"),
                tgt('max by (ceph_daemon) (ceph_osd_apply_latency_ms)',
                    "apply {{ceph_daemon}}", "B")],
               (18, y, 6, 8), unit="ms",
               thresholds=steps(("green", None), ("orange", 50), ("red", 200)),
               links=[link("Ceph", "proxmox")]),
]
y += 8

# ---- Docker Swarm ----------------------------------------------------------
panels.append(row("Docker Swarm", y)); y += 1
panels += [
    timeseries("CPU par nœud Swarm",
               [tgt('1 - avg by (host) (rate(node_cpu_seconds_total{role=~"swarm_.+", '
                    'mode="idle"}[$__rate_interval]))', "{{host}}")],
               (0, y, 8, 7), unit="percentunit", minv=0, maxv=1,
               links=[link("Node Exporter", "node-exporter-full")]),
    timeseries("RAM par nœud Swarm",
               [tgt('1 - node_memory_MemAvailable_bytes{role=~"swarm_.+"} '
                    '/ node_memory_MemTotal_bytes{role=~"swarm_.+"}', "{{host}}")],
               (8, y, 8, 7), unit="percentunit", minv=0, maxv=1,
               links=[link("Node Exporter", "node-exporter-full")]),
    bargauge("Conteneurs running par nœud",
             [tgt('max by (host) (engine_daemon_container_states_containers'
                  '{state="running"})', "{{host}}", instant=True)],
             (16, y, 8, 7), thresholds=steps(("blue", None)), decimals=0, minv=0,
             desc="Nombre de conteneurs en cours d'exécution par nœud (Docker engine).",
             links=[link("Swarm", "swarm-overview")]),
]
y += 7
panels += [
    timeseries("CPU par service",
               [tgt('sum by (svc) (' + by_service(
                   'rate(container_cpu_usage_seconds_total{name!=""}[$__rate_interval])')
                    + ')', "{{svc}}")],
               (0, y, 8, 7), unit="percentunit",
               desc="CPU consommé par service Swarm (1 = 100 % d'un cœur), toutes "
                    "réplicas confondues. Source cAdvisor (workers).",
               links=[link("Conteneurs", "docker-containers")]),
    timeseries("Mémoire par service",
               [tgt('sum by (svc) (' + by_service(
                   'container_memory_working_set_bytes{name!=""}') + ')', "{{svc}}")],
               (8, y, 8, 7), unit="bytes",
               links=[link("Conteneurs", "docker-containers")]),
    bargauge("Réplicas par service",
             [tgt('count by (svc) (' + by_service(
                 'container_memory_working_set_bytes{name!=""}') + ')', "{{svc}}",
                  instant=True)],
             (16, y, 8, 7), thresholds=steps(("blue", None)), decimals=0, minv=0,
             desc="Conteneurs vus par cAdvisor sur les workers, regroupés par service Swarm.",
             links=[link("Swarm", "swarm-overview")]),
]
y += 7

# ---- Réseau des hyperviseurs ----------------------------------------------
panels.append(row("Réseau des hyperviseurs", y)); y += 1
for i, host in enumerate(["ceph01", "ceph02", "ceph03"]):
    sel = f'{{role="pve", host="{host}", device=~"nic[0-9]+|vmbr[0-9]+"}}'
    panels.append(timeseries(
        f"Trafic {host}",
        [tgt(f'rate(node_network_receive_bytes_total{sel}[$__rate_interval]) * 8',
             "{{device}} rx"),
         tgt(f'rate(node_network_transmit_bytes_total{sel}[$__rate_interval]) * 8',
             "{{device}} tx", "B")],
        (8 * i, y, 8, 8), unit="bps", fill=0, soft_min=False,
        overrides=[override_regex(".* tx", [
            {"id": "custom.transform", "value": "negative-Y"}])],
        desc="Interfaces physiques (nicX) et bridge vmbr0. Réception au-dessus, "
             "émission en dessous de l'axe.",
        links=[link("Node Exporter", "node-exporter-full")]))
y += 8

# ---- Supervision -----------------------------------------------------------
panels.append(row("Supervision", y)); y += 1
stack_re = "|".join(STACK_JOBS)
panels += [
    stat("Services de la stack",
         [tgt(f'count(up{{job=~"{stack_re}"}} == 1) or vector(0)', instant=True)],
         (0, y, 4, 4), unit=f"suffix: / {len(STACK_JOBS)}",
         thresholds=full_nominal(len(STACK_JOBS)),
         desc="VictoriaMetrics, vmalert, Alertmanager, Loki, Grafana."),
    stat("Chaîne d'alerte",
         [tgt('count(ALERTS{alertname="Watchdog", alertstate="firing"}) or vector(0)',
              instant=True)],
         (0, y + 4, 4, 4),
         thresholds=steps(("red", None), ("green", 1)),
         mappings=[text_map(0, "KO", "red"), text_map(1, "OK", "green")],
         desc="L'alerte Watchdog doit toujours être active : son absence signale une "
              "chaîne vmalert -> Alertmanager cassée.",
         links=[link("vmalert", "vmalert")]),
    table("Cibles en panne",
          [tgt('up == 0 or on() label_set(vector(1), "job", '
               '"Toutes les cibles répondent")', instant=True, fmt="table")],
          (4, y, 6, 8),
          transformations=[{"id": "organize", "options": {
              "excludeByName": {"Time": True, "Value": True, "__name__": True,
                                "pve_node": True},
              "indexByName": {"job": 0, "host": 1, "instance": 2, "role": 3},
              "renameByName": {"job": "Job", "host": "Hôte",
                               "instance": "Instance", "role": "Rôle"}}}],
          desc="Cibles dont le dernier scrape a échoué (up == 0).",
          links=[link("vmagent", "vmagent")]),
    timeseries("Buffer disque vmagent",
               [tgt('sum by (host) (vmagent_remotewrite_pending_data_bytes)', "{{host}}")],
               (10, y, 7, 8), unit="bytes",
               thresholds=steps(("green", None), ("red", 100e6)),
               desc="Données en attente d'envoi vers VictoriaMetrics. Monte si "
                    "VictoriaMetrics est injoignable, se vide à la reprise (aucune perte).",
               links=[link("vmagent", "vmagent")]),
    timeseries("Ingestion",
               [tgt('sum(rate(vm_rows_inserted_total[$__rate_interval]))',
                    "VictoriaMetrics (échantillons/s)"),
                tgt('sum(rate(loki_distributor_lines_received_total[$__rate_interval]))',
                    "Loki (lignes/s)", "B")],
               (17, y, 7, 8), unit="short",
               overrides=[override_name("Loki (lignes/s)", [
                   {"id": "custom.axisPlacement", "value": "right"}])],
               desc="Débit d'écriture dans les bases de métriques et de logs.",
               links=[link("VictoriaMetrics", "victoriametrics")]),
]
y += 8

# ---- Logs ------------------------------------------------------------------
panels.append(row("Logs warning / erreur", y)); y += 1
panels += [
    timeseries("Volume de logs warning/erreur par hôte",
               [tgt(f'sum by (host) (count_over_time({LOG_SELECTOR} [$__auto]))',
                    "{{host}}", ds=LOKI)],
               (0, y, 24, 6), draw="bars", fill=80, stack=True, ds=LOKI, unit="short",
               desc="Logs journald de niveau warning à emerg (toutes les machines : "
                    "hyperviseurs, Swarm, supervision, identités, rag01, waf01, poste de contrôle)."),
]
y += 6
panels.append(panel(
    "logs", "Logs récents (warning et plus grave)",
    [tgt(LOG_SELECTOR, ds=LOKI)],
    (0, y, 24, 12), ds=LOKI,
    options={"showTime": True, "showLabels": False, "showCommonLabels": False,
             "wrapLogMessage": True, "prettifyLogMessage": False,
             "enableLogDetails": True, "enableInfiniteScrolling": False,
             "dedupStrategy": "none", "sortOrder": "Descending"},
    desc="Filtrer par hôte / service avec les variables en haut du dashboard."))
y += 12

# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
def loki_var(name, label, lbl):
    return {"name": name, "label": label, "type": "query", "datasource": LOKI,
            "query": {"type": 1, "label": lbl, "stream": "", "refId": "LokiVariableQueryEditor-VariableQuery"},
            "definition": f"label_values({lbl})", "refresh": 2, "includeAll": True,
            "allValue": ".*", "multi": True, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "options": [], "hide": 0}


DETAIL = [("Démo / Remédiation", "demo-remediation"), ("Modèle ML", "ml-detecteur"),
          ("Cyber", "resilience-cyber"), ("Proxmox & Ceph", "proxmox"),
          ("Swarm", "swarm-overview"), ("Conteneurs", "docker-containers"),
          ("Node Exporter", "node-exporter-full"),
          ("VictoriaMetrics", "victoriametrics"), ("vmagent", "vmagent"),
          ("vmalert", "vmalert")]

dashboard = {
    "id": None,
    "uid": "central",
    "title": "Plateforme - vue centrale",
    "description": "État de santé de toute la plateforme en un écran : application, base "
                   "répliquée, WAF, identités, assistant, sauvegardes, Proxmox, Ceph, Swarm, "
                   "supervision, alertes et logs.",
    "tags": ["central", "plateforme"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
    "fiscalYearStartMonth": 0,
    "liveNow": False,
    "schemaVersion": 39,
    "version": 1,
    "links": [{"title": t, "type": "link", "url": f"/d/{u}", "icon": "dashboard",
               "keepTime": True, "includeVars": False, "targetBlank": False,
               "asDropdown": False, "tags": [], "tooltip": f"Dashboard détaillé {t}"}
              for t, u in DETAIL],
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
         "name": "Annotations & Alerts", "type": "dashboard"},
        {"name": "Alertes", "enable": True, "hide": False, "iconColor": "red",
         "datasource": VM,
         "expr": 'ALERTS{alertstate="firing", alertname!="Watchdog"}',
         "step": "30s", "titleFormat": "{{alertname}}",
         "textFormat": "{{host}} {{instance}}", "tagKeys": "severity",
         "useValueForTime": False}]},
    "templating": {"list": [loki_var("log_host", "Hôte (logs)", "host"),
                            loki_var("log_service", "Service (logs)", "service")]},
    "panels": panels,
}

# Sections de détail repliées : chaque rangée emporte ses panneaux jusqu'à la suivante.
# Les rangées repliées s'empilent (une ligne chacune) sous les voyants et les alertes.
OPEN_ROWS = {"Alertes"}
folded, current, ry = [], None, None
for p in panels:
    if p["type"] == "row":
        current = None
        if p["title"] not in OPEN_ROWS:
            p["collapsed"] = True
            current = p
        folded.append(p)
    elif current is not None:
        current["panels"].append(p)
    else:
        folded.append(p)
# positions : panneaux ouverts inchangés, rangées repliées les unes sous les autres
bottom = max(p["gridPos"]["y"] + p["gridPos"]["h"] for p in folded if not p.get("collapsed"))
for p in folded:
    if p.get("collapsed"):
        offset = bottom - p["gridPos"]["y"]
        p["gridPos"]["y"] = bottom
        for q in p["panels"]:
            q["gridPos"]["y"] += offset
        bottom += 1
dashboard["panels"] = folded

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n",
               encoding="utf-8")
print(f"{OUT} : {len(panels)} panneaux, {len(folded)} au premier niveau")

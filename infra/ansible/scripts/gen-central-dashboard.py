#!/usr/bin/env python3
"""Génère le dashboard Grafana « Plateforme - vue centrale » (uid central).

Un seul écran pour l'état de santé de toute la plateforme : Proxmox, Ceph,
Docker Swarm, chaîne de supervision, alertes et logs. Conçu pour être lisible
de loin (démo incident -> reprise automatique).

Usage (depuis infra/ansible) : python3 scripts/gen-central-dashboard.py
Sortie : roles/grafana/files/dashboards/Vue centrale/central.json

Toutes les requêtes sont en MetricsQL/PromQL (VictoriaMetrics) ou LogQL (Loki).
Les voyants « en panne / alertes » utilisent `or vector(0)` / `or label_set(...)`
pour afficher 0 ou « Aucune » plutôt que « No data » quand tout va bien.
"""
import json
import pathlib

OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "roles/grafana/files/dashboards/Vue centrale/central.json")

VM = {"type": "prometheus", "uid": "victoriametrics"}
LOKI = {"type": "loki", "uid": "loki"}

# Taille nominale de la plateforme (affichée en suffixe « / N » sur les voyants).
NB_PVE = 3          # hyperviseurs ceph01-03
NB_OSD = 3
NB_MON = 3
NB_SWARM = 6        # 3 managers + 3 workers
NB_MANAGERS = 3
NB_VMAGENT = 2
STACK_JOBS = ["victoriametrics", "vmalert", "alertmanager", "loki", "grafana"]

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
        t.update({"queryType": "range", "editorMode": "code"})
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


def link(title, uid):
    return {"title": title, "url": f"/d/{uid}?${{__url_time_range}}",
            "targetBlank": False}


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
    opts = {"legend": {"displayMode": legend, "placement": "bottom",
                       "showLegend": True,
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

# ---- Voyants ---------------------------------------------------------------
V = 4  # hauteur d'un voyant
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
               desc="Logs journald de niveau warning à emerg (machines Swarm et supervision)."),
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


DETAIL = [("Proxmox & Ceph", "proxmox"),
          ("Swarm", "swarm-overview"), ("Conteneurs", "docker-containers"),
          ("Node Exporter", "node-exporter-full"),
          ("VictoriaMetrics", "victoriametrics"), ("vmagent", "vmagent"),
          ("vmalert", "vmalert")]

dashboard = {
    "id": None,
    "uid": "central",
    "title": "Plateforme - vue centrale",
    "description": "État de santé de toute la plateforme en un écran : Proxmox, Ceph, "
                   "Docker Swarm, supervision, alertes et logs.",
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

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n",
               encoding="utf-8")
print(f"{OUT} : {len(panels)} panels")

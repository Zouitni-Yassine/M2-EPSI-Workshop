#!/usr/bin/env python3
"""Génère le dashboard "Proxmox & Ceph" (uid proxmox) à partir des métriques collectées :
pve-exporter (job pve), module prometheus du mgr Ceph (job ceph), node_exporter des
hyperviseurs (job node, role=pve).

Usage (depuis infra/monitoring/grafana) : python3 scripts/gen-proxmox-dashboard.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "dashboards/Infrastructure/proxmox.json"
DS = {"type": "prometheus", "uid": "victoriametrics"}

# Filtres réutilisés
NODE = 'id=~"node/$node"'
GUEST = 'id=~"(qemu|lxc)/.+"'
HOST = 'role="pve", host=~"$node"'
# Nom lisible d'un nœud PVE à partir de id="node/ceph01"
def node_name(expr):
    return f'label_replace({expr}, "node", "$1", "id", "node/(.+)")'


# Tableaux : chaque requête ne garde que la clé de jointure (et les colonnes d'info),
# sinon instance/job/host diffèrent entre requêtes et la fusion Grafana duplique les lignes
def by(keys, expr):
    return f"max by ({keys}) ({expr})"
# Ajoute name/type/node d'un invité (exclut les templates)
def with_guest(expr, labels="name, type, node"):
    return f'({expr}) * on (id) group_left ({labels}) pve_guest_info{{template="0", node=~"$node"}}'
# Ajoute le nom d'un pool Ceph
def with_pool(expr):
    return f'({expr}) * on (pool_id) group_left (name) ceph_pool_metadata'
# Ajoute l'hôte d'un OSD
def with_osd(expr):
    return f'({expr}) * on (ceph_daemon) group_left (hostname) ceph_osd_metadata'

panels = []
_id = 0
_y = 0


def _add(p, x, w, h):
    global _id
    _id += 1
    p.update(id=_id, gridPos={"x": x, "y": _y, "w": w, "h": h})
    panels.append(p)
    return p


def next_row(h):
    global _y
    _y += h


def row(title):
    global _id, _y
    _id += 1
    panels.append({"type": "row", "title": title, "id": _id, "collapsed": False,
                   "gridPos": {"x": 0, "y": _y, "w": 24, "h": 1}, "panels": []})
    _y += 1


def target(expr, legend="", ref="A", instant=False, fmt="time_series"):
    t = {"refId": ref, "datasource": DS, "expr": expr, "legendFormat": legend}
    if instant:
        t.update(instant=True, range=False, format=fmt)
    return t


def steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in pairs]}


GREEN = steps((None, "green"))
HIGH_BAD = steps((None, "green"), (0.75, "orange"), (0.9, "red"))      # ratio 0-1
HIGH_BAD_PCT = steps((None, "green"), (75, "orange"), (90, "red"))     # %


def stat(title, expr, x, w=4, h=4, unit="none", thresholds=GREEN, mappings=None,
         text_mode="value", legend="", desc="", decimals=None):
    fc = {"unit": unit, "thresholds": thresholds, "mappings": mappings or []}
    if decimals is not None:
        fc["decimals"] = decimals
    return _add({"type": "stat", "title": title, "description": desc, "datasource": DS,
                 "targets": [target(expr, legend, instant=True)],
                 "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": ""},
                             "colorMode": "background", "graphMode": "none",
                             "textMode": text_mode, "justifyMode": "center"},
                 "fieldConfig": {"defaults": fc, "overrides": []}}, x, w, h)


def ts(title, targets, x, w=12, h=8, unit="short", stack=False, desc="", minv=None,
       maxv=None, overrides=None, fill=10):
    custom = {"fillOpacity": fill, "lineWidth": 1, "showPoints": "never",
              "stacking": {"mode": "normal" if stack else "none"}}
    d = {"unit": unit, "custom": custom}
    if minv is not None:
        d["min"] = minv
    if maxv is not None:
        d["max"] = maxv
    return _add({"type": "timeseries", "title": title, "description": desc, "datasource": DS,
                 "targets": targets,
                 "fieldConfig": {"defaults": d, "overrides": overrides or []},
                 "options": {"legend": {"displayMode": "table", "placement": "right",
                                        "calcs": ["lastNotNull", "max"], "sortBy": "Last *", "sortDesc": True},
                             "tooltip": {"mode": "multi", "sort": "desc"}}}, x, w, h)


def table(title, queries, columns, x, w=24, h=8, desc="", sort=None, hide=(), keys="id", info=None):
    """queries : [(refId, expr)] instantanées au format table, fusionnées sur leurs labels communs.
    columns : {nom_source: (nom_affiché, unité|None, options)}"""
    rename, order, overrides = {}, {}, []
    exclude = {"Time": True, "__name__": True, "job": True, "instance": True, "host": True}
    exclude.update({h_: True for h_ in hide})
    for i, (src, (label, unit, opts)) in enumerate(columns.items()):
        rename[src] = label
        order[src] = i
        props = []
        if unit:
            props.append({"id": "unit", "value": unit})
        for k, v in (opts or {}).items():
            props.append({"id": k, "value": v})
        if props:
            overrides.append({"matcher": {"id": "byName", "options": label}, "properties": props})
    return _add({"type": "table", "title": title, "description": desc, "datasource": DS,
                 "targets": [target(by(", ".join(filter(None, [keys, (info or {}).get(r)])), e), ref=r, instant=True, fmt="table")
                             for r, e in queries],
                 "transformations": [
                     {"id": "merge", "options": {}},
                     {"id": "organize", "options": {"excludeByName": exclude, "indexByName": order,
                                                    "renameByName": rename}}],
                 "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": False},
                                              "thresholds": GREEN},
                                 "overrides": overrides},
                 "options": {"showHeader": True, "cellHeight": "sm",
                             "sortBy": [{"displayName": sort, "desc": False}] if sort else []}}, x, w, h)


def bargauge(title, expr, legend, x, w=12, h=8, unit="percentunit", thresholds=HIGH_BAD,
             maxv=1, desc=""):
    return _add({"type": "bargauge", "title": title, "description": desc, "datasource": DS,
                 "targets": [target(expr, legend, instant=True)],
                 "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": maxv,
                                              "thresholds": thresholds}, "overrides": []},
                 "options": {"orientation": "horizontal", "displayMode": "gradient",
                             "showUnfilled": True, "valueMode": "color",
                             "reduceOptions": {"calcs": ["lastNotNull"]}}}, x, w, h)


def gauge(title, expr, x, w=4, h=7, unit="percentunit", thresholds=HIGH_BAD, maxv=1, desc=""):
    return _add({"type": "gauge", "title": title, "description": desc, "datasource": DS,
                 "targets": [target(expr, instant=True)],
                 "fieldConfig": {"defaults": {"unit": unit, "min": 0, "max": maxv,
                                              "thresholds": thresholds}, "overrides": []},
                 "options": {"reduceOptions": {"calcs": ["lastNotNull"]},
                             "showThresholdLabels": False, "showThresholdMarkers": True}}, x, w, h)


def vmap(*items):
    """Mappings valeur -> texte/couleur : vmap((0, "OK", "green"), ...)"""
    return [{"type": "value", "options": {str(v): {"text": t, "color": c, "index": i}}}
            for i, (v, t, c) in enumerate(items)]


def colored_text(mapping_items):
    return {"custom.cellOptions": {"type": "color-background"}, "mappings": vmap(*mapping_items)}


UP_DOWN = [(1, "en marche", "green"), (0, "arrêté", "red")]
YES_NO = [(1, "oui", "green"), (0, "non", "red")]

# ============================================================================
# Vue d'ensemble
# ============================================================================
row("Vue d'ensemble")
stat("Quorum Proxmox", 'label_value(pve_cluster_info, "quorate")', 0,
     mappings=vmap((1, "OK", "green"), (0, "PERDU", "red")),
     desc="Quorum corosync du cluster Proxmox (pve_cluster_info)")
stat("Nœuds en ligne", 'sum(pve_up{id=~"node/.+"})', 4,
     thresholds=steps((None, "red"), (2, "orange"), (3, "green")),
     desc="Hyperviseurs vus en ligne par l'API Proxmox (sur 3)")
stat("Invités en marche", f'sum({with_guest(f"pve_up{{{GUEST}}}", "name")})', 8,
     desc="VM et LXC en marche (hors templates)")
stat("Invités arrêtés",
     f'count(pve_guest_info{{template="0", node=~"$node"}}) - sum({with_guest(f"pve_up{{{GUEST}}}", "name")})',
     12, thresholds=steps((None, "green"), (1, "orange")),
     desc="VM et LXC arrêtés (hors templates)")
stat("CPU cluster",
     'sum(pve_cpu_usage_ratio{id=~"node/.+"} * pve_cpu_usage_limit{id=~"node/.+"}) / sum(pve_cpu_usage_limit{id=~"node/.+"})',
     16, unit="percentunit", thresholds=HIGH_BAD, decimals=1)
stat("RAM cluster",
     'sum(pve_memory_usage_bytes{id=~"node/.+"}) / sum(pve_memory_size_bytes{id=~"node/.+"})',
     20, unit="percentunit", thresholds=HIGH_BAD, decimals=1)
next_row(4)
stat("Santé Ceph", "max(ceph_health_status) or vector(-1)", 0,
     mappings=vmap((0, "HEALTH_OK", "green"), (1, "HEALTH_WARN", "orange"),
                   (2, "HEALTH_ERR", "red"), (-1, "INCONNU", "purple")))
stat("OSD up", "sum(ceph_osd_up)", 4,
     thresholds=steps((None, "red"), (2, "orange"), (3, "green")),
     desc="OSD up (sur 3, un par hyperviseur)")
stat("Quorum MON", "sum(ceph_mon_quorum_status)", 8,
     thresholds=steps((None, "red"), (2, "orange"), (3, "green")),
     desc="Moniteurs Ceph dans le quorum (sur 3)")
stat("Mgr actif", 'max by (ceph_daemon) (ceph_mgr_status) == 1', 12, text_mode="name",
     legend="{{ceph_daemon}}", desc="Manager Ceph actif (les autres sont en standby)")
stat("PG active+clean", "sum(ceph_pg_clean) / sum(ceph_pg_total)", 16, unit="percentunit",
     thresholds=steps((None, "red"), (0.95, "orange"), (1, "green")), decimals=1)
stat("Ceph utilisé (brut)", "sum(ceph_cluster_total_used_raw_bytes) / sum(ceph_cluster_total_bytes)",
     20, unit="percentunit", thresholds=HIGH_BAD, decimals=1)
next_row(4)
stat("Invités sans sauvegarde", "max(pve_not_backed_up_total) or vector(0)", 0,
     thresholds=steps((None, "green"), (1, "orange")),
     desc="Invités non couverts par une tâche de sauvegarde Proxmox (pve_not_backed_up_total)")
stat("Ressources HA démarrées", 'count(pve_ha_state{id=~"(qemu|lxc)/.+", state="started"} == 1) or vector(0)',
     4, desc="Invités gérés par la HA Proxmox et démarrés")
stat("Invités verrouillés", "count(pve_lock_state == 1) or vector(0)", 8,
     thresholds=steps((None, "green"), (1, "orange")),
     desc="Invités avec un verrou en cours (backup, migration, snapshot...)")
stat("Objets dégradés", "max(ceph_num_objects_degraded) or vector(0)", 12,
     thresholds=steps((None, "green"), (1, "orange")))
stat("Opérations lentes", "max(ceph_healthcheck_slow_ops) or vector(0)", 16,
     thresholds=steps((None, "green"), (1, "red")), desc="Slow ops signalées par Ceph")
stat("Flags OSD actifs", 'count({__name__=~"ceph_osd_flag_.+"} == 1) or vector(0)', 20,
     thresholds=steps((None, "green"), (1, "orange")),
     desc="noout, norebalance, noscrub... (maintenance en cours ?)")
next_row(4)

# ============================================================================
# Hyperviseurs
# ============================================================================
row("Hyperviseurs")
table("Nœuds", [
    ("A", node_name(f"pve_up{{{NODE}}}")),
    ("B", node_name(f"pve_uptime_seconds{{{NODE}}}")),
    ("C", node_name(f"pve_cpu_usage_ratio{{{NODE}}}")),
    ("D", node_name(f"pve_cpu_usage_limit{{{NODE}}}")),
    ("E", node_name(f"pve_memory_usage_bytes{{{NODE}}} / pve_memory_size_bytes{{{NODE}}}")),
    ("F", node_name(f"pve_memory_size_bytes{{{NODE}}}")),
    ("G", node_name(f"pve_disk_usage_bytes{{{NODE}}} / pve_disk_size_bytes{{{NODE}}}")),
    ("H", f'label_replace(count by (node) (pve_up{{{GUEST}}} * on (id) group_left (node) pve_guest_info{{template="0", node=~"$node"}} == 1), "id", "node/$1", "node", "(.+)")'),
], {
    "node": ("Nœud", None, None),
    "Value #A": ("État", None, colored_text([(1, "en ligne", "green"), (0, "hors ligne", "red")])),
    "Value #B": ("Uptime", "s", None),
    "Value #C": ("CPU", "percentunit", {"custom.cellOptions": {"type": "gauge", "mode": "basic"},
                                        "max": 1, "thresholds": HIGH_BAD}),
    "Value #D": ("Cœurs", "short", None),
    "Value #E": ("RAM", "percentunit", {"custom.cellOptions": {"type": "gauge", "mode": "basic"},
                                        "max": 1, "thresholds": HIGH_BAD}),
    "Value #F": ("RAM totale", "bytes", None),
    "Value #G": ("Disque système", "percentunit", {"custom.cellOptions": {"type": "gauge", "mode": "basic"},
                                                   "max": 1, "thresholds": HIGH_BAD}),
    "Value #H": ("Invités en marche", "short", None),
}, 0, h=6, sort="Nœud", hide=("id",), keys="id, node")
next_row(6)
ts("CPU par nœud", [target(node_name(f"pve_cpu_usage_ratio{{{NODE}}}"), "{{node}}")], 0,
   unit="percentunit", minv=0, maxv=1)
ts("RAM par nœud", [target(node_name(f"pve_memory_usage_bytes{{{NODE}}} / pve_memory_size_bytes{{{NODE}}}"), "{{node}}")],
   12, unit="percentunit", minv=0, maxv=1)
next_row(8)
ts("Charge système (load 1 min / cœurs)",
   [target(f'node_load1{{{HOST}}} / on (host) count by (host) (node_cpu_seconds_total{{{HOST}, mode="idle"}})', "{{host}}")],
   0, w=8, unit="percentunit", minv=0,
   desc="Load average rapporté au nombre de cœurs : au-delà de 100 %, des processus attendent le CPU")
ts("Pression CPU / IO (PSI)", [
    target(f'rate(node_pressure_cpu_waiting_seconds_total{{{HOST}}}[$__rate_interval])', "CPU {{host}}"),
    target(f'rate(node_pressure_io_waiting_seconds_total{{{HOST}}}[$__rate_interval])', "IO {{host}}", ref="B"),
], 8, w=8, unit="percentunit", minv=0,
   desc="Part du temps où des tâches attendent le CPU ou les entrées/sorties")
ts("Disques physiques : occupation (sda, sdb)",
   [target(f'rate(node_disk_io_time_seconds_total{{{HOST}, device=~"sd[a-z]+"}}[$__rate_interval])', "{{host}} {{device}}")],
   16, w=8, unit="percentunit", minv=0, maxv=1,
   desc="Temps pendant lequel le disque est occupé (100 % = saturé)")
next_row(8)


def net_panel(title, dev, x, desc):
    return ts(title, [
        target(f'rate(node_network_receive_bytes_total{{{HOST}, device="{dev}"}}[$__rate_interval]) * 8', "{{host}} reçu"),
        target(f'-rate(node_network_transmit_bytes_total{{{HOST}, device="{dev}"}}[$__rate_interval]) * 8', "{{host}} émis", ref="B"),
    ], x, w=8, unit="bps", desc=desc)


net_panel("Réseau LAN / VM (nic0)", "nic0", 0, "Interface du bridge vmbr0 : management et trafic des invités. Émission sous l'axe.")
net_panel("Réseau cluster corosync (nic1)", "nic1", 8, "172.16.0.0/24 : communication du cluster Proxmox. Émission sous l'axe.")
net_panel("Réseau Ceph (nic2)", "nic2", 16, "172.16.1.0/24 : réplication et accès Ceph. Sa saturation ralentit tout le stockage. Émission sous l'axe.")
next_row(8)

# ============================================================================
# Invités
# ============================================================================
row("Invités (VM et LXC)")
table("Invités", [
    ("A", f'pve_guest_info{{template="0", node=~"$node"}}'),
    ("B", f"sum by (id) (pve_up{{{GUEST}}})"),
    ("C", f"sum by (id) (pve_cpu_usage_ratio{{{GUEST}}})"),
    ("D", f"sum by (id) (pve_cpu_usage_limit{{{GUEST}}})"),
    ("E", f"sum by (id) (pve_memory_usage_bytes{{{GUEST}}})"),
    ("F", f"sum by (id) (pve_memory_size_bytes{{{GUEST}}})"),
    ("G", f"sum by (id) (rate(pve_network_receive_bytes_total{{{GUEST}}}[5m]) + rate(pve_network_transmit_bytes_total{{{GUEST}}}[5m]))"),
    ("H", f"sum by (id) (rate(pve_disk_read_bytes_total{{{GUEST}}}[5m]) + rate(pve_disk_written_bytes_total{{{GUEST}}}[5m]))"),
    ("I", f"sum by (id) (pve_uptime_seconds{{{GUEST}}})"),
    ("J", f'sum by (id) (pve_onboot_status{{{GUEST}}})'),
], {
    "id": ("ID", None, None),
    "name": ("Nom", None, None),
    "type": ("Type", None, None),
    "node": ("Nœud", None, None),
    "Value #B": ("État", None, colored_text(UP_DOWN)),
    "Value #C": ("CPU", "percentunit", {"custom.cellOptions": {"type": "gauge", "mode": "basic"},
                                        "max": 1, "thresholds": HIGH_BAD}),
    "Value #D": ("vCPU", "short", None),
    "Value #E": ("RAM utilisée", "bytes", None),
    "Value #F": ("RAM allouée", "bytes", None),
    "Value #G": ("Réseau", "Bps", None),
    "Value #H": ("Disque", "Bps", None),
    "Value #I": ("Uptime", "s", None),
    "Value #J": ("Démarrage auto", None, {"mappings": vmap((1, "oui", "green"), (0, "non", "text"))}),
    "tags": ("Tags", None, None),
}, 0, h=9, sort="ID", hide=("Value #A", "template"), info={"A": "name, type, node, tags"},
   desc="Hors templates. Réseau et disque : moyenne sur 5 min (lecture + écriture, réception + émission).")
next_row(9)
ts("CPU par invité (cœurs utilisés)",
   [target(with_guest(f"pve_cpu_usage_ratio{{{GUEST}}} * pve_cpu_usage_limit{{{GUEST}}}", "name"), "{{name}}")],
   0, unit="short", minv=0)
ts("RAM par invité", [target(with_guest(f"pve_memory_usage_bytes{{{GUEST}}}", "name"), "{{name}}")],
   12, unit="bytes", minv=0)
next_row(8)
ts("Réseau par invité", [
    target(with_guest(f"rate(pve_network_receive_bytes_total{{{GUEST}}}[$__rate_interval])", "name"), "{{name}} reçu"),
    target(with_guest(f"-rate(pve_network_transmit_bytes_total{{{GUEST}}}[$__rate_interval])", "name"), "{{name}} émis", ref="B"),
], 0, unit="Bps", desc="Émission sous l'axe")
ts("Disque par invité", [
    target(with_guest(f"rate(pve_disk_read_bytes_total{{{GUEST}}}[$__rate_interval])", "name"), "{{name}} lecture"),
    target(with_guest(f"-rate(pve_disk_written_bytes_total{{{GUEST}}}[$__rate_interval])", "name"), "{{name}} écriture", ref="B"),
], 12, unit="Bps", desc="Écriture sous l'axe")
next_row(8)

# ============================================================================
# Stockages Proxmox
# ============================================================================
row("Stockages Proxmox")
bargauge("Stockages partagés (Ceph RBD)",
         'max by (storage) ((pve_disk_usage_bytes{id=~"storage/.+"} / pve_disk_size_bytes{id=~"storage/.+"}) '
         '* on (id) group_left (storage) pve_storage_info * on (id) group_left () (pve_storage_shared == 1))',
         "{{storage}}", 0, w=8, h=6, desc="Vus identiquement depuis chaque nœud : une seule valeur par stockage")
bargauge("Stockages locaux",
         '(pve_disk_usage_bytes{id=~"storage/.+"} / pve_disk_size_bytes{id=~"storage/.+"}) '
         '* on (id) group_left (storage, node) pve_storage_info{node=~"$node"} * on (id) group_left () (pve_storage_shared == 0)',
         "{{node}} / {{storage}}", 8, w=16, h=6)
next_row(6)

# ============================================================================
# Ceph
# ============================================================================
row("Ceph : capacité et pools")
gauge("Capacité brute utilisée", "sum(ceph_cluster_total_used_raw_bytes) / sum(ceph_cluster_total_bytes)", 0,
      desc="Seuils Ceph par défaut : nearfull 85 %, full 95 % (par OSD)")
stat("Brut utilisé", "sum(ceph_cluster_total_used_raw_bytes)", 4, w=4, h=3, unit="bytes")
stat("Brut total", "sum(ceph_cluster_total_bytes)", 8, w=4, h=3, unit="bytes")
ts("Capacité dans le temps", [
    target("sum(ceph_cluster_total_used_raw_bytes)", "brut utilisé"),
    target("sum(ceph_cluster_total_bytes)", "brut total", ref="B"),
], 12, h=7, unit="bytes", minv=0)
_y += 3
stat("Objets", "sum(ceph_pool_objects)", 4, w=4, h=4, unit="short")
stat("Pools", "count(ceph_pool_metadata)", 8, w=4, h=4)
_y -= 3
next_row(7)
table("Pools", [
    ("A", "ceph_pool_metadata"),
    ("B", "sum by (pool_id) (ceph_pool_stored)"),
    ("C", "sum by (pool_id) (ceph_pool_bytes_used)"),
    ("D", "sum by (pool_id) (ceph_pool_percent_used)"),
    ("E", "sum by (pool_id) (ceph_pool_max_avail)"),
    ("F", "sum by (pool_id) (ceph_pool_objects)"),
    ("G", "sum by (pool_id) (rate(ceph_pool_rd[5m]) + rate(ceph_pool_wr[5m]))"),
], {
    "name": ("Pool", None, None),
    "description": ("Protection", None, None),
    "application": ("Usage", None, None),
    "Value #B": ("Données stockées", "bytes", None),
    "Value #C": ("Espace brut consommé", "bytes", None),
    "Value #D": ("Utilisation", "percentunit", {"custom.cellOptions": {"type": "gauge", "mode": "basic"},
                                                "max": 1, "thresholds": HIGH_BAD}),
    "Value #E": ("Disponible", "bytes", None),
    "Value #F": ("Objets", "short", None),
    "Value #G": ("IOPS (5 min)", "iops", None),
}, 0, h=6, sort="Pool", hide=("pool_id", "type", "compression_mode", "Value #A"),
   keys="pool_id", info={"A": "name, description, application"},
   desc="Protection : replica:N = N copies ; ec:k+m = erasure coding (k données + m parités)")
next_row(6)

row("Ceph : activité")
ts("IOPS client par pool", [
    target(with_pool("sum by (pool_id) (rate(ceph_pool_rd[$__rate_interval]))"), "{{name}} lecture"),
    target(with_pool("-sum by (pool_id) (rate(ceph_pool_wr[$__rate_interval]))"), "{{name}} écriture", ref="B"),
], 0, unit="iops", desc="Écriture sous l'axe")
ts("Débit client par pool", [
    target(with_pool("sum by (pool_id) (rate(ceph_pool_rd_bytes[$__rate_interval]))"), "{{name}} lecture"),
    target(with_pool("-sum by (pool_id) (rate(ceph_pool_wr_bytes[$__rate_interval]))"), "{{name}} écriture", ref="B"),
], 12, unit="Bps", desc="Écriture sous l'axe")
next_row(8)
ts("Récupération / rééquilibrage", [
    target("sum(ceph_pool_recovering_bytes_per_sec)", "débit de récupération"),
], 0, w=8, unit="Bps", minv=0, desc="Non nul après la perte ou le retour d'un OSD")
ts("Objets dégradés / mal placés / introuvables", [
    target("max(ceph_num_objects_degraded)", "dégradés"),
    target("max(ceph_num_objects_misplaced)", "mal placés", ref="B"),
    target("max(ceph_num_objects_unfound)", "introuvables", ref="C"),
], 8, w=8, unit="short", minv=0)
ts("PG hors état nominal", [
    target(f"sum(ceph_pg_{s})", s, ref=chr(65 + i)) for i, s in enumerate(
        ["degraded", "undersized", "recovering", "recovery_wait", "backfilling", "backfill_wait",
         "peering", "remapped", "stale", "inconsistent", "down", "incomplete"])
] + [target("sum(ceph_pg_total) - sum(ceph_pg_clean)", "non clean", ref="Z")],
   16, w=8, unit="short", minv=0, desc="Placement groups : tout doit rester à 0 en régime normal")
next_row(8)

row("Ceph : OSD et démons")
table("OSD", [
    ("A", "ceph_osd_metadata"),
    ("B", "sum by (ceph_daemon) (ceph_osd_up)"),
    ("C", "sum by (ceph_daemon) (ceph_osd_in)"),
    ("D", "sum by (ceph_daemon) (ceph_osd_weight)"),
    ("E", "sum by (ceph_daemon) (ceph_osd_apply_latency_ms)"),
    ("F", "sum by (ceph_daemon) (ceph_osd_commit_latency_ms)"),
], {
    "ceph_daemon": ("OSD", None, None),
    "hostname": ("Hôte", None, None),
    "device_class": ("Classe", None, None),
    "objectstore": ("Backend", None, None),
    "Value #B": ("Up", None, colored_text(YES_NO)),
    "Value #C": ("In", None, colored_text(YES_NO)),
    "Value #D": ("Poids", "short", None),
    "Value #E": ("Latence apply", "ms", None),
    "Value #F": ("Latence commit", "ms", None),
    "cluster_addr": ("Adresse cluster", None, None),
}, 0, w=14, h=6, sort="OSD", hide=("ceph_version", "public_addr", "Value #A"),
   keys="ceph_daemon", info={"A": "hostname, device_class, objectstore, cluster_addr"})
table("Moniteurs", [
    ("A", "ceph_mon_metadata"),
    ("B", "sum by (ceph_daemon) (ceph_mon_quorum_status)"),
], {
    "ceph_daemon": ("MON", None, None),
    "hostname": ("Hôte", None, None),
    "rank": ("Rang", None, None),
    "Value #B": ("Quorum", None, colored_text(YES_NO)),
}, 14, w=5, h=6, sort="MON", hide=("ceph_version", "public_addr", "Value #A"),
   keys="ceph_daemon", info={"A": "hostname, rank"})
table("Managers", [
    ("A", "sum by (ceph_daemon) (ceph_mgr_status)"),
], {
    "ceph_daemon": ("MGR", None, None),
    "Value #A": ("Statut", None, colored_text([(1, "actif", "green"), (0, "standby", "blue")])),
}, 19, w=5, h=6, sort="MGR", keys="ceph_daemon")
next_row(6)
ts("Latence des OSD", [
    target(with_osd("ceph_osd_apply_latency_ms"), "{{ceph_daemon}} ({{hostname}}) apply"),
    target(with_osd("ceph_osd_commit_latency_ms"), "{{ceph_daemon}} ({{hostname}}) commit", ref="B"),
], 0, unit="ms", minv=0, desc="Latences moyennes remontées par le mgr (pas d'histogramme par opération)")
ts("Disques des OSD : occupation (dm-0)",
   [target(f'rate(node_disk_io_time_seconds_total{{{HOST}, device="dm-0"}}[$__rate_interval])', "{{host}}")],
   12, unit="percentunit", minv=0, maxv=1,
   desc="Volume LVM des OSD (ceph_disk_occupation_human : /dev/dm-0 sur chaque hôte)")
next_row(8)

# ============================================================================
dashboard = {
    "uid": "proxmox",
    "title": "Proxmox & Ceph",
    "description": "Cluster Proxmox VE et stockage Ceph : nœuds, invités, stockages, pools, OSD.",
    "tags": ["infrastructure", "proxmox", "ceph"],
    "timezone": "browser",
    "refresh": "30s",
    "time": {"from": "now-1h", "to": "now"},
    "schemaVersion": 39,
    "editable": False,
    "graphTooltip": 1,
    "links": [
        {"title": "Vue centrale", "type": "link", "url": "/d/central", "icon": "dashboard",
         "keepTime": True, "includeVars": False, "targetBlank": False},
        {"title": "Nœuds (node_exporter)", "type": "link", "url": "/d/node-exporter-full?var-role=pve",
         "icon": "dashboard", "keepTime": True},
    ],
    "templating": {"list": [{
        "name": "node", "label": "Hyperviseur", "type": "query", "datasource": DS,
        "query": {"query": "label_values(pve_node_info, name)", "refId": "V"},
        "refresh": 1, "includeAll": True, "multi": True, "allValue": ".*",
        "current": {"text": "All", "value": "$__all"}, "sort": 1,
    }]},
    "panels": panels,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{OUT} : {len([p for p in panels if p['type'] != 'row'])} panels")

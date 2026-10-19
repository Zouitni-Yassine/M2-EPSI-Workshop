#!/usr/bin/env python3
"""Télécharge les dashboards publics de grafana.com (révisions figées), les adapte
aux sources de données provisionnées et à nos métriques/labels, puis les écrit dans
roles/grafana/files/dashboards/<Dossier>/<uid>.json. Le résultat est versionné dans
le dépôt : le déploiement Ansible ne dépend donc pas de grafana.com.

Les corrections propres à notre stack (labels host/role, métriques non collectées,
variables, harmonisation titre/tags/refresh...) sont appliquées en post-traitement
par les fonctions patch_<uid>() ci-dessous : ne pas éditer les JSON générés à la main,
modifier ce script et le relancer.

Dashboards maintenus à la main (absents de la liste, à éditer directement) :
  - Docker Swarm/swarm-overview.json   (vue d'ensemble Swarm)
  - Docker Swarm/docker-containers.json (conteneurs cAdvisor)

Usage (depuis infra/ansible) : python3 scripts/fetch-dashboards.py
"""
import json
import pathlib
import re
import urllib.request

# Type de source -> uid provisionné (roles/grafana/templates/datasources.yml.j2)
DATASOURCE_UIDS = {"prometheus": "victoriametrics", "loki": "loki"}
DS_VM = {"type": "prometheus", "uid": "victoriametrics"}

# (id grafana.com, révision, dossier Grafana, uid stable)
DASHBOARDS = [
    (1860, 45, "Infrastructure", "node-exporter-full"),
    (10347, 5, "Infrastructure", "proxmox"),
    (2842, 18, "Infrastructure", "ceph-cluster"),
    (10229, 60, "Supervision", "victoriametrics"),
    (12683, 42, "Supervision", "vmagent"),
    (14950, 22, "Supervision", "vmalert"),
]

OUT = pathlib.Path(__file__).resolve().parent.parent / "roles/grafana/files/dashboards"


def fetch(gid: int, rev: int) -> str:
    url = f"https://grafana.com/api/dashboards/{gid}/revisions/{rev}/download"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode()


# --------------------------------------------------------------------------- helpers


def iter_panels(panels):
    for p in panels:
        yield p
        yield from iter_panels(p.get("panels", []))


def all_panels(dash):
    return list(iter_panels(dash.get("panels", [])))


def remove_panels(dash, ids):
    """Supprime des panels par id. Un row supprimé emporte ses panels (row replié :
    panels imbriqués ; row déplié : panels suivants jusqu'au prochain row)."""
    ids = set(ids)

    def clean(panels):
        out, skipping = [], False
        for p in panels:
            if p.get("type") == "row":
                skipping = p["id"] in ids and not p.get("collapsed")
                if p["id"] in ids:
                    continue
            elif skipping or p.get("id") in ids:
                continue
            if "panels" in p:
                p["panels"] = clean(p["panels"])
            out.append(p)
        return out

    dash["panels"] = clean(dash["panels"])


def drop_targets(dash, patterns):
    """Retire les requêtes dont l'expression contient un des motifs ; un panel
    qui n'a plus de requête est supprimé."""
    empty = []
    for p in all_panels(dash):
        tg = p.get("targets")
        if not tg:
            continue
        kept = [t for t in tg if not any(s in (t.get("expr") or "") for s in patterns)]
        if len(kept) != len(tg):
            p["targets"] = kept
            if not kept:
                empty.append(p["id"])
    remove_panels(dash, empty)


def drop_empty_rows(dash):
    remove_panels(dash, [p["id"] for p in dash["panels"]
                         if p.get("type") == "row" and p.get("collapsed") and not p.get("panels")])


def sub_exprs(dash, repl, regex=False):
    """Remplacements dans les expressions des requêtes et des variables."""
    def do(s):
        for a, b in repl:
            s = re.sub(a, b, s) if regex else s.replace(a, b)
        return s

    for p in all_panels(dash):
        for t in p.get("targets", []) or []:
            if t.get("expr"):
                t["expr"] = do(t["expr"])
    for v in dash.get("templating", {}).get("list", []):
        for k in ("definition", "query"):
            if isinstance(v.get(k), str):
                v[k] = do(v[k])
            elif isinstance(v.get(k), dict) and isinstance(v[k].get("query"), str):
                v[k]["query"] = do(v[k]["query"])


def set_targets(dash, pid, targets, title=None, unit=None):
    """Remplace les requêtes d'un panel : targets = [(expr, legend), ...]."""
    for p in all_panels(dash):
        if p.get("id") == pid:
            p["targets"] = [{"datasource": DS_VM, "expr": e, "legendFormat": l,
                             "refId": chr(65 + i), "range": True}
                            for i, (e, l) in enumerate(targets)]
            if title is not None:
                p["title"] = title
            if unit is not None:
                p.setdefault("fieldConfig", {}).setdefault("defaults", {})["unit"] = unit
            return
    raise KeyError(pid)


def set_title(dash, pid, title):
    for p in all_panels(dash):
        if p.get("id") == pid:
            p["title"] = title
            return
    raise KeyError(pid)


def query_var(name, label, query, hide=0, include_all=False, multi=False, sort=1):
    v = {"name": name, "label": label, "type": "query", "datasource": DS_VM,
         "definition": query, "query": {"query": query, "refId": f"{name}-var"},
         "refresh": 2, "regex": "", "sort": sort, "hide": hide,
         "includeAll": include_all, "multi": multi, "current": {}, "options": []}
    if include_all:
        v["allValue"] = ".*"
        v["current"] = {"text": "All", "value": "$__all"}
    return v


def fix_ds_vars(dash):
    """Variables de type datasource : figées sur VictoriaMetrics et masquées."""
    for v in dash.get("templating", {}).get("list", []):
        if v.get("type") == "datasource" and v.get("query") == "prometheus":
            v["current"] = {"text": "VictoriaMetrics", "value": "victoriametrics"}
            v["hide"] = 2


def harmonize(dash, title, tags, time_from="now-1h"):
    dash["title"] = title
    dash["tags"] = tags
    dash["refresh"] = "30s"
    dash["time"] = {"from": time_from, "to": "now"}
    dash["timezone"] = "browser"
    dash["editable"] = False
    fix_ds_vars(dash)


# --------------------------------------------------------------------------- patches


def patch_node_exporter_full(d):
    # Sélection par rôle puis par nom d'hôte lisible (label host ajouté par vmagent)
    # au lieu de nodename/instance ; job et instance deviennent des variables masquées.
    tl = d["templating"]["list"]
    ds = next(v for v in tl if v["type"] == "datasource")
    job = next(v for v in tl if v["name"] == "job")
    job["hide"] = 2
    job["datasource"] = DS_VM
    d["templating"]["list"] = [
        ds, job,
        query_var("role", "Rôle", 'label_values(node_uname_info{job="$job"}, role)',
                  include_all=True, multi=True),
        query_var("host", "Hôte", 'label_values(node_uname_info{job="$job", role=~"$role"}, host)'),
        query_var("node", "Instance", 'label_values(node_uname_info{job="$job", host="$host"}, instance)',
                  hide=2),
    ]
    raw = json.dumps(d["panels"]).replace("$nodename", "$host")
    d["panels"] = json.loads(raw)
    # Collecteurs node_exporter non activés chez nous (processes, tcpstat, interrupts,
    # cpufreq, hwmon, powersupply) ou sans objet en VM/LXC (cooling device).
    drop_targets(d, [
        "node_pressure_irq_stalled_seconds_total", "node_processes_", "node_cpu_scaling_frequency",
        "node_interrupts_total", "node_hwmon_", "node_cooling_device_", "node_power_supply_",
        "node_netstat_Tcp_MaxConn", "node_tcp_connection_states",
    ])
    # node_network_up n'a plus de label operstate (désormais dans node_network_info).
    sub_exprs(d, [('node_network_up{operstate="up",', "node_network_up{")])
    drop_empty_rows(d)
    harmonize(d, "Nœuds - Node Exporter Full", ["infrastructure", "node-exporter"])


def patch_proxmox(d):
    # Une seule cible pve-exporter : la variable instance est masquée.
    for v in d["templating"]["list"]:
        if v["name"] == "instance":
            v["hide"] = 2
            v["refresh"] = 2
    for p in all_panels(d):
        for t in p.get("targets", []) or []:
            if t.get("expr"):
                # Filtre instance manquant sur la 2e moitié de la requête Disk IO
                t["expr"] = t["expr"].replace("rate(pve_disk_read_bytes[5m])",
                                              'rate(pve_disk_read_bytes{instance="$instance"}[5m])')
                t["expr"] = t["expr"].replace("[5m]", "[$__rate_interval]")
    harmonize(d, "Proxmox - cluster", ["infrastructure", "proxmox"])


def patch_ceph_cluster(d):
    # Révision sans __inputs : les panels pointent sur ${DS_PROMETHEUS}.
    raw = json.dumps(d).replace('"${DS_PROMETHEUS}"', json.dumps(DS_VM))
    raw = raw.replace('"$DS_PROMETHEUS"', json.dumps(DS_VM))
    d.clear()
    d.update(json.loads(raw))
    d["templating"]["list"] = []  # DS_PROMETHEUS et $interval (5s par défaut : trop court)
    for p in all_panels(d):
        for obj in [p] + (p.get("targets") or []):
            if obj.get("interval") == "$interval":
                del obj["interval"]
    sub_exprs(d, [("[$interval]", "[$__rate_interval]"), ("irate(", "rate("), ("[5m]", "[$__rate_interval]")])
    # Ceph >= Reef/Squid : les compteurs de perf OSD (ceph_osd_op_*) ne sont plus
    # exposés par le module prometheus du mgr (ils passent par ceph-exporter, non
    # déployé). On utilise les compteurs par pool équivalents.
    sub_exprs(d, [
        ("ceph_osd_op_w_in_bytes", "ceph_pool_wr_bytes"),
        ("ceph_osd_op_r_out_bytes", "ceph_pool_rd_bytes"),
        ("ceph_osd_op_w{", "ceph_pool_wr{"),
        ("ceph_osd_op_r{", "ceph_pool_rd{"),
        ("ceph_pg_wait_backfill{", "ceph_pg_backfill_wait{"),
        ("ceph_pg_backfill{", "ceph_pg_backfilling{"),
        ("sum(ceph_unclean_pgs{})", "sum(ceph_pg_total{}) - sum(ceph_pg_clean{})"),
    ])
    for pid, t in [(4, "Débit écriture (pools)"), (5, "Débit lecture (pools)"),
                   (9, "Octets écrits (cumul pools)"), (10, "Octets lus (cumul pools)"),
                   (12, "IOPS écriture (pools)"), (13, "IOPS lecture (pools)"),
                   (30, "IOPS (pools)"), (31, "Débit cluster (pools)"), (49, "Objets (total)")]:
        set_title(d, pid, t)
    set_targets(d, 23, [("sum(ceph_pg_total{})", "")], title="PGs (total)")
    set_targets(d, 37, [("count by (objectstore) (ceph_osd_metadata{})", "{{objectstore}}")],
                title="OSD par type de stockage")
    set_targets(d, 52, [("sum(ceph_pool_recovering_objects_per_sec{})", "objets/s")],
                title="Récupération (objets/s)")
    # Débits : unité par seconde
    for pid in (31,):
        for p in all_panels(d):
            if p["id"] == pid:
                p["fieldConfig"]["defaults"]["unit"] = "Bps"
    # Panneaux node_exporter : limités aux hyperviseurs Ceph, légende par host.
    set_targets(d, 43, [('node_memory_MemTotal_bytes{role="pve"} - node_memory_MemAvailable_bytes{role="pve"}', "{{host}}")],
                title="Mémoire utilisée des nœuds Ceph")
    set_targets(d, 44, [('100 * (1 - avg by (host) (rate(node_cpu_seconds_total{role="pve", mode="idle"}[$__rate_interval])))', "{{host}}")],
                title="CPU des nœuds Ceph")
    set_targets(d, 45, [('sum by (host) (rate(node_disk_read_bytes_total{role="pve"}[$__rate_interval]))', "{{host}}")],
                title="Lecture disque des nœuds Ceph", unit="Bps")
    set_targets(d, 46, [('sum by (host) (rate(node_disk_written_bytes_total{role="pve"}[$__rate_interval]))', "{{host}}")],
                title="Écriture disque des nœuds Ceph", unit="Bps")
    set_targets(d, 47, [('100 * node_filesystem_avail_bytes{role="pve", mountpoint="/"} / node_filesystem_size_bytes{role="pve", mountpoint="/"}', "{{host}}")],
                title="Espace libre / des nœuds Ceph")
    set_title(d, 42, "Nœuds Ceph (node_exporter)")
    # Métriques non disponibles : sessions mon, latences par op OSD, MDS/RGW absents.
    remove_panels(d, [16, 26, 27, 56, 57, 58, 63, 64])
    harmonize(d, "Ceph - cluster", ["infrastructure", "ceph"])


def patch_victoriametrics(d):
    harmonize(d, "Supervision - VictoriaMetrics", ["supervision", "victoriametrics"], "now-3h")


def patch_vmagent(d):
    # Pas de streaming aggregation, pas de Kafka (Enterprise), pas d'ingestion push
    # (vmagent ne fait que scraper), pas de limite de séries configurée.
    remove_panels(d, [136, 163, 71, 88, 90])
    harmonize(d, "Supervision - vmagent", ["supervision", "victoriametrics", "vmagent"], "now-3h")


def patch_vmalert(d):
    # Aucune règle d'enregistrement définie : les métriques vmalert_recording_* ne
    # sont pas exposées, la section correspondante resterait vide.
    remove_panels(d, [28])
    harmonize(d, "Supervision - vmalert", ["supervision", "victoriametrics", "vmalert"], "now-3h")


PATCHES = {
    "node-exporter-full": patch_node_exporter_full,
    "proxmox": patch_proxmox,
    "ceph-cluster": patch_ceph_cluster,
    "victoriametrics": patch_victoriametrics,
    "vmagent": patch_vmagent,
    "vmalert": patch_vmalert,
}


def main() -> None:
    for gid, rev, folder, uid in DASHBOARDS:
        raw = fetch(gid, rev)
        # Les dashboards exportés référencent leurs sources par des variables ${DS_...}
        # résolues à l'import manuel ; en provisioning fichier, on les remplace ici.
        for inp in json.loads(raw).get("__inputs", []):
            placeholder = "${%s}" % inp["name"]
            if inp.get("type") == "datasource":
                raw = raw.replace(placeholder, DATASOURCE_UIDS[inp["pluginId"]])
            elif inp.get("type") == "constant":
                raw = raw.replace(placeholder, inp.get("value", ""))
        dash = json.loads(raw)
        dash.pop("__inputs", None)
        dash.pop("__requires", None)
        dash.pop("__elements", None)
        dash["id"] = None
        dash["uid"] = uid
        PATCHES[uid](dash)
        dest = OUT / folder / f"{uid}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n")
        print(f"{gid} rev {rev} -> {dest.relative_to(OUT)} ({dash.get('title')})")


if __name__ == "__main__":
    main()

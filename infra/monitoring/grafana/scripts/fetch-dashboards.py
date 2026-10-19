#!/usr/bin/env python3
"""Télécharge les dashboards publics de grafana.com (révisions figées), les adapte
aux sources de données provisionnées et à nos métriques/labels, puis les écrit dans
dashboards/<Dossier>/<uid>.json. Le résultat est versionné dans
le dépôt : le déploiement Ansible ne dépend donc pas de grafana.com.

Les corrections propres à notre stack (labels host/role, métriques non collectées,
variables, harmonisation titre/tags/refresh...) sont appliquées en post-traitement
par les fonctions patch_<uid>() ci-dessous : ne pas éditer les JSON générés à la main,
modifier ce script et le relancer.

Dashboards maintenus à la main (absents de la liste, à éditer directement) :
  - Docker Swarm/swarm-overview.json   (vue d'ensemble Swarm)
  - Docker Swarm/docker-containers.json (conteneurs cAdvisor)

Usage (depuis infra/monitoring/grafana) : python3 scripts/fetch-dashboards.py
"""
import json
import pathlib
import re
import urllib.request

# Type de source -> uid provisionné (datasources.yml.j2)
DATASOURCE_UIDS = {"prometheus": "victoriametrics", "loki": "loki"}
DS_VM = {"type": "prometheus", "uid": "victoriametrics"}

# (id grafana.com, révision, dossier Grafana, uid stable)
# Proxmox & Ceph : dashboard maison, voir gen-proxmox-dashboard.py
DASHBOARDS = [
    (1860, 45, "Infrastructure", "node-exporter-full"),
    (10229, 60, "Supervision", "victoriametrics"),
    (12683, 42, "Supervision", "vmagent"),
    (14950, 22, "Supervision", "vmalert"),
]

OUT = pathlib.Path(__file__).resolve().parent.parent / "dashboards"


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

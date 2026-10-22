#!/usr/bin/env python3
"""Génère le dashboard Grafana « Démo / Remédiation » (uid demo-remediation).

Écran de la démonstration (clip de 60 s, jury) : un incident sur Resilience Pay, sa
détection par le détecteur ML, l'action du moteur de remédiation et le retour des paiements,
sans intervention humaine. Gros voyants, rafraîchissement 5 s, 15 dernières minutes.

Usage (depuis infra/monitoring/grafana) : python3 scripts/gen-demo-dashboard.py
Sortie : dashboards/Démo/demo-remediation.json

Sources :
- la sonde de transaction (stack probe, infra/monitoring/probe) : un client réel par le
  relais public. Elle écrit une ligne logfmt toutes les 5 s (type=etat : paiements, score du
  détecteur, état du moteur), une par transaction (type=transaction), une par début ou fin de
  panne (type=incident) et recopie chaque événement du moteur (type=evenement), que le moteur
  ne journalise pas lui-même. VictoriaMetrics ne garde qu'un échantillon par 30 s
  (déduplication) : l'état à 5 s près se lit donc dans Loki ; les métriques de la sonde
  (paiement_probe_*) servent aux alertes et aux valeurs durables ;
- les métriques de payment-api (vmagent du Swarm) et les alertes (série ALERTS de vmalert,
  les mêmes que celles envoyées à Alertmanager).
"""
import json
import pathlib

OUT = (pathlib.Path(__file__).resolve().parent.parent
       / "dashboards/Démo/demo-remediation.json")

VM = {"type": "prometheus", "uid": "victoriametrics"}
LOKI = {"type": "loki", "uid": "loki"}

PROBE = '{stack="probe", service="probe_transactions"}'
ETAT = PROBE + ' |= "type=etat"'
API = 'service="paiement_payment-api"'
API_BUSINESS = API + ', route!~"/api/(status|health)"'  # hors sondes (détecteur, moteur, canary)
THRESHOLD = 0.55  # seuil du détecteur (THRESHOLD de la stack paiement)


def unwrap(field, fn="last_over_time", window="15s", selector=ETAT):
    """Valeur numérique d'un champ logfmt des lignes de la sonde, agrégée sur une fenêtre."""
    return (f'max({fn}({selector} | logfmt {field} | __error__="" '
            f'| unwrap {field} [{window}]))')


# --------------------------------------------------------------------------- #
# Briques de base (mêmes conventions que gen-central-dashboard.py)
# --------------------------------------------------------------------------- #
_ids = iter(range(1, 1000))


def tgt(expr, legend="", ref="A", instant=False, fmt="time_series", ds=VM):
    t = {"datasource": ds, "refId": ref, "expr": expr, "legendFormat": legend,
         "editorMode": "code"}
    if ds is VM:
        t.update({"range": not instant, "instant": instant, "format": fmt})
    else:
        t.update({"queryType": "instant" if instant else "range"})
    return t


def steps(*pairs):
    return {"mode": "absolute",
            "steps": [{"color": c, "value": v} for c, v in pairs]}


def text_map(value, text, color):
    return {"type": "value",
            "options": {str(value): {"text": text, "color": color, "index": 0}}}


def range_map(lo, hi, text, color):
    return {"type": "range",
            "options": {"from": lo, "to": hi, "result": {"text": text, "color": color, "index": 0}}}


def panel(ptype, title, targets, pos, *, unit=None, thresholds=None, mappings=None,
          options=None, custom=None, overrides=None, desc="", decimals=None, minv=None,
          maxv=None, no_value=None, color=None, transformations=None, ds=VM,
          interval=None):
    x, y, w, h = pos
    defaults = {"mappings": mappings or [],
                "thresholds": thresholds or steps(("green", None))}
    for key, val in (("unit", unit), ("decimals", decimals), ("min", minv),
                     ("max", maxv), ("noValue", no_value)):
        if val is not None:
            defaults[key] = val
    defaults["color"] = color or {"mode": "thresholds"}
    if custom is not None:
        defaults["custom"] = custom
    p = {"id": next(_ids), "type": ptype, "title": title, "description": desc,
         "datasource": ds, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": targets,
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if transformations:
        p["transformations"] = transformations
    if interval:
        p["interval"] = interval
    return p


def stat(title, targets, pos, *, text_mode="value", color_mode="background", **kw):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": "none", "justifyMode": "center",
            "textMode": text_mode, "orientation": "auto", "wideLayout": True,
            "showPercentChange": False, "text": {}}
    return panel("stat", title, targets, pos, options=opts, **kw)


def timeseries(title, targets, pos, *, unit=None, fill=15, draw="line", legend=True, **kw):
    custom = {"drawStyle": draw, "lineWidth": 3, "fillOpacity": fill,
              "gradientMode": "opacity", "showPoints": "never", "spanNulls": False,
              "axisSoftMin": 0, "barAlignment": 0,
              "stacking": {"mode": "none", "group": "A"}}
    opts = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": legend,
                       "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    kw.setdefault("color", {"mode": "palette-classic"})
    return panel("timeseries", title, targets, pos, unit=unit, custom=custom,
                 options=opts, **kw)


def override_name(name, props):
    return {"matcher": {"id": "byName", "options": name}, "properties": props}


def fixed(color):
    return {"id": "color", "value": {"mode": "fixed", "fixedColor": color}}


# --------------------------------------------------------------------------- #
# Panneaux
# --------------------------------------------------------------------------- #
panels = []
y = 0

# ---- Bandeau : l'état en un coup d'œil (lisible de loin) ---------------------
H = 7
panels += [
    stat("Paiements",
         # last_over_time [15s] : l'état de la dernière ligne (une toutes les 5 s) ;
         # plus aucune ligne depuis 15 s = sonde muette (valeur 2)
         [tgt(unwrap("panne") + " or vector(2)", ds=LOKI)],
         (0, y, 8, H), ds=LOKI, interval="5s",
         mappings=[text_map(0, "OK", "green"), text_map(1, "EN PANNE", "red"),
                   text_map(2, "SONDE MUETTE", "orange")],
         thresholds=steps(("green", None), ("red", 1), ("orange", 2)),
         desc="Vu par la sonde de transaction, comme un client : EN PANNE dès que le frontal "
              "ou /api/health échoue, ou que la dernière transaction de test a échoué. "
              "Précision 5 s (journal de la sonde dans Loki)."),
    stat("Depuis la dernière transaction réussie",
         [tgt(unwrap("depuis_succes_s"), ds=LOKI)],
         (8, y, 4, H), ds=LOKI, interval="5s", unit="s", decimals=0,
         thresholds=steps(("green", None), ("orange", 45), ("red", 90)),
         desc="Une transaction complète (connexion, création, confirmation carte de test "
              "4242…) toutes les 30 s : la valeur va normalement de 0 à 30 s. Au-delà de "
              "90 s, l'alerte PaiementTransactionProbeFailing se déclenche."),
    stat("Score d'anomalie",
         [tgt(unwrap("score"), ds=LOKI)],
         (12, y, 4, H), ds=LOKI, interval="5s", decimals=2, minv=0,
         thresholds=steps(("green", None), ("red", THRESHOLD)),
         desc=f"Score courant du détecteur ML (IsolationForest), seuil {THRESHOLD}. Le détecteur "
              "n'expose pas de /metrics : la sonde lit /detector/score (session opérateur, "
              "lecture seule) toutes les 5 s et le recopie tel quel."),
    stat("Moteur de remédiation",
         [tgt(unwrap("remediation") + " or vector(2)", ds=LOKI)],
         (16, y, 4, H), ds=LOKI, interval="5s",
         mappings=[text_map(0, "EN VEILLE", "green"), text_map(1, "EN ACTION", "orange"),
                   text_map(2, "INCONNU", "text")],
         thresholds=steps(("green", None), ("orange", 1), ("text", 2)),
         desc="État du moteur (/remediation/state) : EN ACTION entre la décision et la "
              "déclaration de reprise."),
    stat("Dernier temps de reprise",
         [tgt(unwrap("duree_s", window="24h",
                     selector=PROBE + ' |= "type=incident" |= "phase=fin"'),
              "vu par la sonde", ds=LOKI, instant=True),
          tgt('max(paiement_probe_remediation_last_recovery_seconds) > 0', "mesuré par le moteur",
              "B", instant=True)],
         (20, y, 4, H), ds=LOKI, unit="s", decimals=0, text_mode="value_and_name",
         color_mode="value", no_value="aucun incident",
         thresholds=steps(("green", None), ("orange", 60), ("red", 120)),
         desc="Sonde : durée de la dernière panne vue par un client (du premier échec au "
              "premier succès, à 5 s près, dernières 24 h). Moteur : de la décision à la "
              "reprise qu'il déclare (lastRecoverySeconds)."),
]
panels[-1]["targets"][1]["datasource"] = VM
panels[-1]["datasource"] = {"type": "datasource", "uid": "-- Mixed --"}
y += H

# ---- Chronologie en couloirs : panne, détection, action ------------------------
lanes = [("Paiements", "panne", text_map(0, "OK", "green"), text_map(1, "EN PANNE", "red")),
         ("Anomalie détectée", "anomalie", text_map(0, "non", "green"), text_map(1, "ANOMALIE", "red")),
         ("Moteur", "remediation", text_map(0, "veille", "green"), text_map(1, "EN ACTION", "orange"))]
panels.append(panel(
    "state-timeline", "Avant / pendant / après",
    [tgt(unwrap(field, fn="max_over_time", window="$__interval"), name, chr(65 + i), ds=LOKI)
     for i, (name, field, *_m) in enumerate(lanes)],
    (0, y, 24, 6), ds=LOKI, interval="5s",
    mappings=[text_map(0, "OK", "green"), text_map(1, "PANNE", "red")],
    custom={"lineWidth": 0, "fillOpacity": 85},
    overrides=[override_name(name, [{"id": "mappings", "value": list(maps)}])
               for name, _f, *maps in lanes],
    options={"showValue": "auto", "mergeValues": True, "rowHeight": 0.85,
             "alignValue": "center", "legend": {"showLegend": False},
             "tooltip": {"mode": "single"}},
    desc="Trois couloirs à 5 s près : paiements vus par la sonde, verdict du détecteur, "
         "moteur de remédiation. Les traits verticaux sont les événements du moteur."))
y += 6

# ---- Détecteur et transactions --------------------------------------------------
H = 9
panels += [
    timeseries("Score d'anomalie du détecteur",
               [tgt(unwrap("score", fn="max_over_time", window="$__interval"), "score", ds=LOKI),
                tgt(unwrap("seuil", fn="max_over_time", window="$__interval"), "seuil", "B",
                    ds=LOKI)],
               (0, y, 12, H), ds=LOKI, interval="5s", decimals=2, minv=0,
               overrides=[override_name("score", [fixed("purple")]),
                          override_name("seuil", [fixed("red"),
                                                  {"id": "custom.lineStyle",
                                                   "value": {"fill": "dash", "dash": [10, 10]}},
                                                  {"id": "custom.fillOpacity", "value": 0}])],
               desc="Au-dessus du seuil pendant 3 s de suite : anomalie confirmée, le moteur "
                    "agit. Valeurs recopiées de /detector/score par la sonde."),
    timeseries("Transactions de test (client « Sonde », 1,00 €)",
               [tgt(f'sum(count_over_time({PROBE} |= "type=transaction" |= "result=ok" [$__interval]))',
                    "réussies", ds=LOKI),
                tgt(f'sum(count_over_time({PROBE} |= "type=transaction" |= "result=echec" [$__interval]))',
                    "échouées", "B", ds=LOKI),
                tgt(unwrap("duree_ms", fn="max_over_time", window="$__interval",
                           selector=PROBE + ' |= "type=transaction" |= "result=ok"') + " / 1000",
                    "durée (s)", "C", ds=LOKI)],
               (12, y, 12, H), ds=LOKI, interval="30s", draw="bars", fill=80,
               overrides=[override_name("réussies", [fixed("green")]),
                          override_name("échouées", [fixed("red")]),
                          override_name("durée (s)", [
                              fixed("blue"), {"id": "unit", "value": "s"},
                              {"id": "custom.drawStyle", "value": "line"},
                              {"id": "custom.showPoints", "value": "always"},
                              {"id": "custom.pointSize", "value": 8},
                              {"id": "custom.fillOpacity", "value": 0},
                              {"id": "custom.axisPlacement", "value": "right"}])],
               desc="Une transaction complète toutes les 30 s (et aussitôt que l'API "
                    "répond de nouveau après une panne) : barres vertes réussies, rouges "
                    "échouées ; points bleus : durée de bout en bout (Stripe compris)."),
]
y += H

# ---- payment-api ----------------------------------------------------------------
H = 7
panels += [
    stat("payment-api : réplicas qui répondent",
         [tgt(f'count(up{{{API}}} == 1) or vector(0)', instant=True)],
         (0, y, 4, H), unit="suffix: / 1",
         thresholds=steps(("red", None), ("green", 1)),
         desc="Réplicas dont /metrics répond (vmagent du Swarm, toutes les 30 s)."),
    timeseries("payment-api : requêtes/s (hors sondes)",
               [tgt(f'sum(rate(http_requests_total{{{API_BUSINESS}}}[$__rate_interval]))',
                    "requêtes/s")],
               (4, y, 7, H), unit="reqps", legend=False,
               overrides=[override_name("requêtes/s", [fixed("blue")])],
               desc="Requêtes métier (hors /api/status et /api/health)."),
    timeseries("payment-api : erreurs 5xx/s",
               [tgt(f'sum(rate(http_requests_total{{{API}, code=~"5.."}}[$__rate_interval])) '
                    'or vector(0)', "5xx/s")],
               (11, y, 6, H), unit="reqps", legend=False,
               overrides=[override_name("5xx/s", [fixed("red")])],
               desc="Réponses 5xx de payment-api. Quand le service est arrêté, ses métriques "
                    "disparaissent : la panne se voit alors sur la sonde, pas ici."),
    timeseries("payment-api : latence p95",
               [tgt('histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket'
                    f'{{{API_BUSINESS}}}[$__rate_interval])))', "p95")],
               (17, y, 7, H), unit="s", legend=False,
               overrides=[override_name("p95", [fixed("orange")])],
               desc="Latence p95 des requêtes métier (histogramme de payment-api)."),
]
y += H

# ---- Chronologie et alertes -----------------------------------------------------
H = 11
panels += [
    panel("logs", "Chronologie de la remédiation",
          [tgt(PROBE + ' |~ "type=(evenement|incident)" | logfmt '
               '| line_format "{{.etape}} : {{.texte}}"', ds=LOKI)],
          (0, y, 14, H), ds=LOKI,
          options={"showTime": True, "showLabels": False, "showCommonLabels": False,
                   "wrapLogMessage": True, "prettifyLogMessage": False,
                   "enableLogDetails": False, "enableInfiniteScrolling": False,
                   "dedupStrategy": "none", "sortOrder": "Ascending"},
          desc="Événements du moteur de remédiation (détection, décision, redémarrage par la "
               "passerelle, vérification, reprise) recopiés par la sonde, et début / fin de "
               "panne vus par la sonde. Heure à 5 s près (lecture de /remediation/state)."),
    panel("table", "Alertes actives",
          # last_over_time [1m] : vmalert réécrit ALERTS à chaque évaluation (30 s) ; sans
          # cela, une alerte résolue resterait affichée 5 min (fenêtre de recherche par défaut)
          [tgt('max by (alertname, severity, remediation, alertstate) '
               '(last_over_time(ALERTS{alertname!="Watchdog"}[1m])) '
               'or on() label_set(vector(0), "alertname", "Aucune alerte")',
               instant=True, fmt="table")],
          (14, y, 10, H),
          custom={"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
          options={"showHeader": True, "cellHeight": "md",
                   "footer": {"show": False, "reducer": ["sum"], "fields": ""}},
          overrides=[override_name("État", [
              {"id": "mappings", "value": [text_map("firing", "ACTIVE", "red"),
                                           text_map("pending", "en attente", "orange")]},
              {"id": "custom.cellOptions", "value": {"type": "color-text"}}])],
          transformations=[{"id": "organize", "options": {
              "excludeByName": {"Time": True, "Value": True},
              "indexByName": {"alertname": 0, "alertstate": 1, "severity": 2, "remediation": 3},
              "renameByName": {"alertname": "Alerte", "alertstate": "État",
                               "severity": "Sévérité", "remediation": "Remédiation"}}}],
          desc="Alertes vmalert en cours (série ALERTS : les mêmes que celles envoyées à "
               "Alertmanager, puis à Discord). remediation=auto : lue par le moteur ; "
               "manual : pour les humains. Délai de 1 à 3 min (scrape 30 s + durée for)."),
]
y += H

# ---- Infrastructure : ce qui encaisse les pannes sous l'application ------------------
# Pour les tests de résilience (infra/chaos/chaos.sh) : chaque test pose une annotation
# « Tests de chaos » (zone violette) sur tous les panneaux. Métriques à 30 s près.
panels.append({"id": next(_ids), "type": "row", "title": "Infrastructure",
               "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []})
y += 1
H = 5
panels += [
    stat("Adresse virtuelle 10.30.1.200",
         [tgt('max by (host) (app_vip_master) == 1', "{{host}}", instant=True)],
         (0, y, 5, H), text_mode="name", no_value="PERSONNE",
         thresholds=steps(("green", None)),
         desc="Worker qui porte l'adresse d'entrée de l'application (keepalived, métrique "
              "app_vip_master publiée à chaque changement d'état). Deux noms = conflit."),
    stat("Nœuds Swarm joignables",
         [tgt('count(up{job="docker"} == 1) or vector(0)', instant=True)],
         (5, y, 4, H), unit="suffix: / 6",
         thresholds=steps(("red", None), ("orange", 4), ("green", 6)),
         desc="Démons Docker des 3 managers et 3 workers dont les métriques répondent."),
    stat("Leader Swarm",
         [tgt('max by (host) (swarm_manager_leader) == 1', "{{host}}", instant=True)],
         (9, y, 4, H), text_mode="name", no_value="AUCUN",
         thresholds=steps(("blue", None)),
         desc="Manager leader du consensus Raft (réélu en quelques secondes s'il tombe)."),
    stat("Hyperviseurs",
         [tgt('count(up{job="node", role="pve"} == 1) or vector(0)', instant=True)],
         (13, y, 4, H), unit="suffix: / 3",
         thresholds=steps(("red", None), ("orange", 2), ("green", 3)),
         desc="Nœuds Proxmox joignables (node_exporter). Quorum du cluster : 2 sur 3."),
    stat("Ceph",
         [tgt('max(ceph_health_status)', instant=True)],
         (17, y, 4, H),
         mappings=[text_map(0, "HEALTH_OK", "green"), text_map(1, "HEALTH_WARN", "orange"),
                   text_map(2, "HEALTH_ERR", "red")],
         thresholds=steps(("green", None), ("orange", 1), ("red", 2)),
         desc="Santé du stockage distribué (module prometheus du mgr Ceph). WARN après la "
              "perte d'un nœud : données servies par les répliques restantes."),
    stat("Vault",
         [tgt('max(vault_core_unsealed) or vector(0)', instant=True)],
         (21, y, 3, H),
         mappings=[text_map(1, "DESCELLÉ", "green"), text_map(0, "SCELLÉ", "red")],
         thresholds=steps(("red", None), ("green", 1)),
         desc="Après un redémarrage, Vault revient scellé (choix de sécurité : clés hors de "
              "la machine) : vault-unseal depuis le poste de contrôle."),
]
y += H
H = 10
panels += [
    timeseries("Conteneurs de l'application par worker",
               [tgt('count by (host) (container_last_seen{'
                    'container_label_com_docker_stack_namespace="paiement"})', "{{host}}")],
               (0, y, 8, H), fill=60, decimals=0, minv=0,
               desc="Tâches de la stack paiement vues par cAdvisor sur chaque worker : quand "
                    "un worker tombe, Swarm replace ses tâches sur les autres."),
    panel("state-timeline", "Machines du lab",
          [tgt('max by (host) (up{job="node", role="pve"})', "{{host}}"),
           tgt('max by (name) (pve_up * on (id) group_left (name) pve_guest_info{template="0"})',
               "{{name}}", "B")],
          (8, y, 10, H),
          mappings=[text_map(1, "en marche", "green"), text_map(0, "arrêtée", "red")],
          thresholds=steps(("red", None), ("green", 1)),
          custom={"lineWidth": 0, "fillOpacity": 85},
          options={"showValue": "never", "mergeValues": True, "rowHeight": 0.8,
                   "alignValue": "left", "legend": {"showLegend": False},
                   "tooltip": {"mode": "single"}},
          desc="Hyperviseurs (node_exporter) puis VM et conteneurs LXC (exportateur Proxmox). "
               "La HA Proxmox relance ailleurs les machines d'un nœud perdu."),
    panel("table", "Placement (hyperviseur)",
          [tgt('max by (name, node) (pve_guest_info{template="0"})', instant=True, fmt="table")],
          (18, y, 6, H),
          custom={"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
          options={"showHeader": True, "cellHeight": "sm",
                   "sortBy": [{"displayName": "Machine", "desc": False}],
                   "footer": {"show": False, "reducer": ["sum"], "fields": ""}},
          transformations=[{"id": "organize", "options": {
              "excludeByName": {"Time": True, "Value": True},
              "indexByName": {"name": 0, "node": 1},
              "renameByName": {"name": "Machine", "node": "Hyperviseur"}}}],
          desc="Hyperviseur qui fait tourner chaque machine (change après une reprise HA)."),
]
y += H


# ---- Back-office : reconnaissance faciale des opérateurs (service auth) ------------
# Compteur auth_face_total{result} (/metrics :8300, vmagent du Swarm) : recognized, rejected,
# locked (identifiant bloqué après deux cycles ratés), enrolled. Le cas « indisponible »
# (modèles absents, réponse 503) n'est pas compté : il se lit dans les journaux JSON (Loki).
# Valeurs sur la période affichée ($__range).
AUTH = 'service="paiement_auth"'
AUTH_LOGS = '{service="paiement_auth"} | json | __error__=""'


def face_sum(result):
    return f'sum(increase(auth_face_total{{{AUTH}, result=~"{result}"}}[$__range]))'


def face_increase(result):
    return face_sum(result) + " or vector(0)"


panels.append({"id": next(_ids), "type": "row", "title": "Back-office : reconnaissance faciale",
               "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []})
y += 1
H = 4
panels += [
    stat("Visages reconnus", [tgt(face_increase("recognized"), instant=True)],
         (0, y, 5, H), decimals=0, color_mode="value",
         thresholds=steps(("green", None)),
         desc="Opérateurs reconnus par la caméra avant la saisie du mot de passe "
              "(auth_face_total{result=\"recognized\"}), sur la période affichée."),
    stat("Visages refusés", [tgt(face_increase("rejected"), instant=True)],
         (5, y, 5, H), decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("orange", 1), ("red", 5)),
         desc="Cycles d'identification ratés (visage différent du gabarit, aucun visage, "
              "plusieurs visages). Beaucoup de refus en peu de temps : alerte AuthFaceRejectBurst."),
    stat("Identifiants bloqués", [tgt(face_increase("locked"), instant=True)],
         (10, y, 4, H), decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("red", 1)),
         desc="Identifiants opérateur bloqués après deux cycles ratés (visage ou mot de passe)."),
    stat("Reconnaissance indisponible",
         [tgt(f'sum(count_over_time({AUTH_LOGS} | event="face" | result="unavailable" '
              '[$__range])) or vector(0)', instant=True, ds=LOKI)],
         (14, y, 5, H), ds=LOKI, decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("red", 1)),
         desc="Réponses 503 : modèles de reconnaissance absents ou illisibles côté serveur "
              "(journaux event=face result=unavailable). Alerte AuthFaceUnavailable."),
    stat("Taux de reconnaissance",
         [tgt(f'{face_sum("recognized")} / ({face_sum("recognized|rejected|locked")} > 0)',
              instant=True)],
         (19, y, 5, H), unit="percentunit", decimals=0, color_mode="value",
         no_value="aucune tentative", minv=0, maxv=1,
         thresholds=steps(("red", None), ("orange", 0.5), ("green", 0.8)),
         desc="Reconnus / (reconnus + refusés + bloqués) sur la période affichée."),
]
y += H

# --------------------------------------------------------------------------- #
# Annotations : événements du moteur et de la sonde, alertes
# --------------------------------------------------------------------------- #
def loki_annotation(name, color, selector):
    return {"name": name, "enable": True, "hide": False, "iconColor": color,
            "datasource": LOKI, "expr": selector, "instant": False,
            "titleFormat": "{{etape}}", "textFormat": "{{texte}}", "tagKeys": "kind"}


EVENTS = PROBE + ' |= "type=evenement" | logfmt'
dashboard = {
    "id": None,
    "uid": "demo-remediation",
    "title": "Démo / Remédiation",
    "description": "Démonstration de la reprise automatique de Resilience Pay : sonde de "
                   "transaction, détecteur ML, moteur de remédiation, alertes.",
    "tags": ["demo", "paiement", "remediation"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "5s",
    "time": {"from": "now-15m", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m"]},
    "fiscalYearStartMonth": 0,
    "liveNow": False,
    "schemaVersion": 39,
    "version": 1,
    "links": [{"title": "Vue centrale", "type": "link", "url": "/d/central", "icon": "dashboard",
               "keepTime": True, "includeVars": False, "targetBlank": False,
               "asDropdown": False, "tags": [], "tooltip": "Plateforme - vue centrale"}],
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
         "name": "Annotations & Alerts", "type": "dashboard"},
        loki_annotation("Incident détecté", "red", EVENTS + ' | kind="detect"'),
        loki_annotation("Action du moteur", "orange", EVENTS + ' | kind="act"'),
        loki_annotation("Vérification", "blue", EVENTS + ' | kind="verify"'),
        loki_annotation("Service rétabli", "green", EVENTS + ' | kind="restore"'),
        loki_annotation("Sonde : panne / reprise", "purple",
                        PROBE + ' |= "type=incident" | logfmt'),
        # Réponse à l'attaque : IP bannie au WAF par waf-ban (alerte Loki -> Alertmanager)
        {"name": "IP bannie au WAF", "enable": True, "hide": False, "iconColor": "dark-red",
         "datasource": LOKI, "instant": False,
         "expr": '{host="waf01",identifier="waf-ban"} |~ "^ban ip=" | logfmt',
         "titleFormat": "IP bannie au WAF : {{ip}}", "textFormat": "{{raison}}, {{duree_s}} s",
         "tagKeys": "raison"},
        # Posées par infra/chaos/chaos.sh (API Grafana, tag chaos) : une zone par test
        {"name": "Tests de chaos", "enable": True, "hide": False, "iconColor": "#B877D9",
         "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "target": {"type": "tags", "tags": ["chaos"], "limit": 100, "matchAny": True}},
        {"name": "Alertes paiement", "enable": True, "hide": False, "iconColor": "yellow",
         "datasource": VM,
         "expr": 'ALERTS{alertstate="firing", alertname=~"Paiement.*"}',
         "step": "30s", "titleFormat": "{{alertname}}", "textFormat": "{{service}}",
         "tagKeys": "severity", "useValueForTime": False}]},
    "templating": {"list": []},
    "panels": panels,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{OUT} : {len(panels)} panels")

#!/usr/bin/env python3
"""Génère les dashboards de lecture de logs (Loki) de l'application de paiement.

Trois dashboards du dossier Grafana « Logs », même gabarit que les autres dashboards Logs
(voyants, erreurs, événements clés, tous les logs) :
- logs-paiement     « Logs - Application paiement » : auth, payment-api, frontal nginx, mailpit ;
- logs-base         « Logs - Base de données (Patroni) » : PostgreSQL/Patroni db1-3, etcd1-3 ;
- logs-remediation  « Logs - Détection et remédiation » : détecteur, moteur, sonde de
  transaction, passerelle « remediate » des managers Swarm.

Usage (depuis infra/monitoring/grafana) : python3 -B scripts/gen-logs-application.py
Sortie : dashboards/Logs/logs-{paiement,base,remediation}.json (écriture atomique).

Particularités des journaux (constatées le 22/10/2026) :
- le label Loki « level » des conteneurs Swarm vaut « error » pour tout ce qui sort sur
  stderr (uvicorn, Patroni, PostgreSQL, etcd) : il ne dit rien de la gravité. Les erreurs
  sont donc reconnues au contenu de la ligne (niveau JSON, mots-clés, codes HTTP) ;
- auth et payment-api écrivent leurs événements métier en JSON (event, result, msg…) ;
  le parseur json renomme les champs « level » et « service » en level_extracted et
  service_extracted (conflit avec les labels du flux) ;
- le détecteur et le moteur ne journalisent pas leurs décisions : la sonde de transaction
  (stack probe) les recopie en logfmt (type=evenement), et la passerelle « remediate »
  des managers écrit chaque appel dans le journal (identifiant syslog « remediate »).
"""
import json
import os
import pathlib

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "dashboards/Logs"

LOKI = {"type": "loki", "uid": "loki"}

# Recherche libre (zone de texte, vide par défaut = tout)
SEARCH = ' |~ "(?i)$recherche"'

# Masquage défensif dans les lignes affichées : valeurs de paramètres sensibles
# (jeton, mot de passe, clé…) dans une URL ou un champ « clé=valeur ». Rien de tel n'a été
# vu dans ces journaux le 22/10, mais une requête d'attaque peut en contenir.
# Deux passes : « Bearer <jeton> », puis « clé=valeur » / « clé: valeur » / « "clé": "valeur" ».
# (chaînes brutes : « \\s » et « \" » sont les échappements des chaînes du modèle Go)
MASK = (r'{{ regexReplaceAll "(?i)(bearer\\s+)[A-Za-z0-9._~+/=-]+" '
        r'(regexReplaceAll "(?i)((token|passw[a-z]*|pwd|secret|api_?key|authorization|'
        r'session_?id|cookie)[a-z_]*\"?\\s*[=:]\\s*\"?)[^&\\s\",]+" __line__ "${1}***") '
        r'"${1}***" }}')
MASK_PATH = ('{{ regexReplaceAll "(?i)((token|passw[a-z]*|pwd|secret|api_?key|session|'
             'code)[a-z_]*=)[^&]*" .path "${1}***" }}')


# --------------------------------------------------------------------------- #
# Briques de base (mêmes conventions que gen-demo-dashboard.py)
# --------------------------------------------------------------------------- #
class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def tgt(expr, legend="", ref="A", instant=False, max_lines=None):
    t = {"datasource": LOKI, "refId": ref, "expr": expr, "legendFormat": legend,
         "editorMode": "code", "queryType": "instant" if instant else "range"}
    if max_lines:
        t["maxLines"] = max_lines
    return t


def steps(*pairs):
    return {"mode": "absolute",
            "steps": [{"color": c, "value": v} for c, v in pairs]}


def panel(ids, ptype, title, targets, pos, *, desc="", unit=None, thresholds=None,
          mappings=None, options=None, custom=None, overrides=None, decimals=None,
          no_value=None, color=None, transformations=None, interval=None):
    x, y, w, h = pos
    if no_value is None:
        no_value = NO_DATA
    defaults = {"mappings": mappings or [],
                "thresholds": thresholds or steps(("green", None))}
    for key, val in (("unit", unit), ("decimals", decimals), ("noValue", no_value)):
        if val is not None:
            defaults[key] = val
    defaults["color"] = color or {"mode": "thresholds"}
    if custom is not None:
        defaults["custom"] = custom
    p = {"id": ids(), "type": ptype, "title": title, "description": desc,
         "datasource": LOKI, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": targets,
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if transformations:
        p["transformations"] = transformations
    if interval:
        p["interval"] = interval
    return p


NO_DATA = "Aucun événement sur la période (normal hors incident)"
# Plage propre aux panneaux d'événements rares : le dashboard s'ouvre sur 1 h, période
# sur laquelle une bascule, une remédiation ou un échec de connexion est souvent absent.
RARE_RANGE, RARE_LABEL = "24h", " (24 h)"
# Événements qu'on peut ne pas voir pendant plus d'une journée (le lab est éteint la nuit) :
# une semaine, pour que la démo montre la dernière bascule ou reconnaissance faciale.
WEEK_RANGE, WEEK_LABEL = "7d", " (7 j)"
WEEK = {"Back-office : reconnaissance faciale et administration (auth)",
        "Élection du primaire et bascules (Patroni)"}


def row(ids, title, y):
    return {"id": ids(), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(ids, title, expr, pos, *, desc, thresholds=None, unit="none", text_mode="value",
         no_value="0", color_mode="background", legend=""):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": "none", "justifyMode": "center",
            "textMode": text_mode, "orientation": "auto", "wideLayout": True,
            "showPercentChange": False, "text": {}}
    if text_mode == "value":  # comptage : 0 plutôt que « No data »
        expr = f"({expr}) or vector(0)"
    return panel(ids, "stat", title, [tgt(expr, legend, instant=True)], pos, desc=desc, unit=unit,
                 decimals=0, thresholds=thresholds or steps(("blue", None)),
                 no_value=no_value, options=opts)


def bars(ids, title, targets, pos, *, desc, interval="1m"):
    """Histogramme empilé (volume de logs, comptages d'événements)."""
    custom = {"drawStyle": "bars", "lineWidth": 1, "fillOpacity": 80,
              "gradientMode": "none", "showPoints": "never", "spanNulls": False,
              "axisSoftMin": 0, "barAlignment": 0,
              "stacking": {"mode": "normal", "group": "A"}}
    opts = {"legend": {"displayMode": "list", "placement": "right", "showLegend": True,
                       "calcs": ["sum"]},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel(ids, "timeseries", title, targets, pos, desc=desc, unit="short",
                 custom=custom, options=opts, color={"mode": "palette-classic"},
                 interval=interval)


LOGS_OPTS = {"showTime": True, "showLabels": False, "showCommonLabels": False,
             "wrapLogMessage": True, "prettifyLogMessage": False,
             "enableLogDetails": True, "enableInfiniteScrolling": False,
             "dedupStrategy": "none", "sortOrder": "Descending"}


def logs(ids, title, exprs, pos, *, desc, max_lines=500):
    if isinstance(exprs, str):
        exprs = [exprs]
    targets = [tgt(e, ref=chr(65 + i), max_lines=max_lines) for i, e in enumerate(exprs)]
    return panel(ids, "logs", title, targets, pos, desc=desc, options=dict(LOGS_OPTS))


def table(ids, title, expr, pos, *, desc, rename, sort_by, hide=()):
    """Tableau de comptages (requête instantanée sur la période)."""
    excl = {"Time": True}
    for h in hide:
        excl[h] = True
    return panel(ids, "table", title, [tgt(expr, instant=True)], pos, desc=desc,
                 options={"showHeader": True, "cellHeight": "sm",
                          "footer": {"show": False, "reducer": ["sum"], "fields": ""},
                          "sortBy": [{"displayName": sort_by, "desc": True}]},
                 custom={"align": "auto", "cellOptions": {"type": "auto"},
                         "inspect": False, "filterable": False},
                 transformations=[
                     {"id": "labelsToFields", "options": {"mode": "columns"}},
                     {"id": "merge", "options": {}},
                     {"id": "organize", "options": {"excludeByName": excl,
                                                    "renameByName": rename}}])


def custom_var(name, label, values, *, desc=""):
    opts = [{"text": "All", "value": "$__all", "selected": True}] + [
        {"text": v, "value": v, "selected": False} for v in values]
    return {"type": "custom", "name": name, "label": label, "description": desc,
            "query": ",".join(values), "multi": True, "includeAll": True,
            "current": {"text": ["All"], "value": ["$__all"]},
            "options": opts, "hide": 0, "skipUrlSync": False}


def text_var():
    return {"type": "textbox", "name": "recherche", "label": "Recherche",
            "description": "Filtre libre appliqué à toutes les requêtes (expression "
                           "régulière, insensible à la casse). Vide = tout.",
            "query": "", "current": {"text": "", "value": ""}, "hide": 0,
            "options": [{"selected": True, "text": "", "value": ""}]}


def links(metric_links):
    out = [{"title": "Accueil des logs", "type": "link", "url": "/d/logs-accueil",
            "icon": "doc", "keepTime": True, "includeVars": False, "targetBlank": False,
            "asDropdown": False, "tags": [], "tooltip": "Page d'accueil des dashboards de logs"},
           {"title": "Autres logs", "type": "dashboards", "tags": ["logs"], "asDropdown": True,
            "icon": "external link", "keepTime": True, "includeVars": False,
            "targetBlank": False, "url": "", "tooltip": ""}]
    out += [{"title": t, "type": "link", "url": f"/d/{u}", "icon": "dashboard",
             "keepTime": True, "includeVars": False, "targetBlank": False,
             "asDropdown": False, "tags": [], "tooltip": tip}
            for t, u, tip in metric_links]
    return out


def dashboard(uid, title, desc, panels, templating, metric_links, annotations=(), rare=()):
    todo = set(rare)
    for p in panels:
        if p["title"] in todo:
            todo.discard(p["title"])
            week = p["title"] in WEEK
            p["timeFrom"] = WEEK_RANGE if week else RARE_RANGE
            p["title"] += WEEK_LABEL if week else RARE_LABEL
            p["description"] += (f" Plage propre au panneau : {'7 derniers jours' if week else '24 dernières heures'}"
                                 " (événements rares), quelle que soit la période du dashboard.")
    assert not todo, todo
    return {
        "id": None, "uid": uid, "title": title, "description": desc,
        "tags": ["logs"], "timezone": "browser", "editable": False, "graphTooltip": 1,
        "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
        "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m"]},
        "fiscalYearStartMonth": 0, "liveNow": False, "schemaVersion": 39, "version": 1,
        "links": links(metric_links),
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
             "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
             "name": "Annotations & Alerts", "type": "dashboard"},
            *annotations]},
        "templating": {"list": templating},
        "panels": panels,
    }


def write(name, dash):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    tmp = out.with_name("." + name + ".tmp")
    tmp.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out)  # écriture atomique : un autre agent peut déployer en même temps
    print("écrit", out)


# Annotations communes
CHAOS_ANN = {"name": "Tests de chaos", "enable": True, "hide": False, "iconColor": "#B877D9",
             "datasource": {"type": "grafana", "uid": "-- Grafana --"},
             "target": {"type": "tags", "tags": ["chaos"], "limit": 100, "matchAny": True}}
PROBE = '{stack="probe", service="probe_transactions"}'
INCIDENT_ANN = {"name": "Sonde : panne / reprise", "enable": True, "hide": False,
                "iconColor": "purple", "datasource": LOKI, "instant": False,
                "expr": PROBE + ' |= "type=incident" | logfmt',
                "titleFormat": "{{etape}}", "textFormat": "{{texte}}", "tagKeys": "phase"}

WORKERS = ["dockerwrk01", "dockerwrk02", "dockerwrk03"]
MANAGERS = ["dockermgr01", "dockermgr02", "dockermgr03"]

# Préfixe lisible des lignes : service court @ machine
PREFIX = '{{ trimPrefix "paiement_" .service }} @ {{ .host }} │ '


# =========================================================================== #
# 1. logs-paiement : application de paiement
# =========================================================================== #
def gen_paiement():
    ids = Ids()
    sel = '{stack="paiement", service=~"$source", host=~"$host"}'
    auth = '{stack="paiement", service="paiement_auth", service=~"$source", host=~"$host"}'
    api = ('{stack="paiement", service="paiement_payment-api", service=~"$source", '
           'host=~"$host"}')
    front = ('{stack="paiement", service="paiement_frontend", service=~"$source", '
             'host=~"$host"}')
    # Niveau réel : champ JSON (auth, payment-api), level= (mailpit), [error] (nginx),
    # code HTTP 5xx (uvicorn et nginx), traces Python.
    err = ('|~ `(?i)("level": "(error|critical)"|level=(error|fatal)|\\[(error|crit|alert|emerg)\\]'
           '|HTTP/[0-9.]+" 5[0-9]{2} |traceback|exception|panic)`')
    warn = '|~ `(?i)("level": "warning"|level=warn(ing)?|\\[warn\\])`'
    # Bruit connu : message bénin au démarrage d'auth (colonne déjà créée)
    noise = '!~ `column "first_name" already exists`'
    # Lignes d'accès seulement (le conteneur écrit aussi le journal d'erreurs nginx)
    nginx = ('|~ `HTTP/[0-9.]+" [0-9]{3} ` | pattern `<ip> - <_> [<_>] "<method> <path> <_>" <status> <_> "<_>" "<ua>" '
             '"<_>"`')
    p, y = [], 0

    p.append(row(ids, "En un coup d'œil", y)); y += 1
    p += [
        stat(ids, "Lignes de logs", f'sum(count_over_time({sel}{SEARCH} [$__range]))',
             (0, y, 4, 4), desc="Nombre de lignes écrites par les services choisis (variable "
             "source) sur la période affichée. Le gros du volume vient des contrôles de santé "
             "et des appels de la sonde (normal)."),
        stat(ids, "Erreurs", f'sum(count_over_time({sel} {err} {noise}{SEARCH} [$__range]))',
             (4, y, 4, 4), thresholds=steps(("green", None), ("red", 1)),
             desc="Lignes d'erreur reconnues au contenu : niveau JSON error, [error] nginx, "
             "réponse HTTP 5xx, trace Python. Le label Loki « level » n'est pas utilisé : il "
             "vaut « error » pour tout ce qui sort sur stderr. Des 502 apparaissent pendant "
             "chaque redémarrage de payment-api (remédiation) : c'est attendu."),
        stat(ids, "Avertissements", f'sum(count_over_time({sel} {warn}{SEARCH} [$__range]))',
             (8, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Lignes de niveau warning : échecs de connexion, visages non enrôlés, base "
             "injoignable vue par payment-api, [warn] nginx."),
        stat(ids, "Paiements acceptés",
             f'sum(count_over_time({api} |= `"msg": "paiement accepté"`{SEARCH} [$__range]))',
             (12, y, 4, 4), thresholds=steps(("red", None), ("green", 1)),
             desc="Paiements confirmés par Stripe (mode test) sur la période, sonde de "
             "transaction comprise (un paiement de contrôle toutes les 30 s)."),
        stat(ids, "Échecs de connexion",
             f'sum(count_over_time({auth} |~ `"result": "(failure|locked)"`{SEARCH} [$__range]))',
             (16, y, 4, 4), thresholds=steps(("green", None), ("orange", 1), ("red", 10)),
             desc="Mots de passe refusés et connexions bloquées par le freinage anti force "
             "brute (result=failure ou locked). Une rafale signale une attaque par "
             "dictionnaire : voir le panneau « Connexions » plus bas et le dashboard Cyber."),
        stat(ids, "Réponses 5xx du frontal",
             f'sum(count_over_time({front} |~ `HTTP/[0-9.]+" 5[0-9]{{2}} `{SEARCH} [$__range]))',
             (20, y, 4, 4), thresholds=steps(("green", None), ("red", 1)),
             desc="Requêtes auxquelles le frontal nginx a répondu 500/502/504 : service "
             "derrière indisponible (redémarrage, panne). Les détails sont dans « Erreurs »."),
    ]
    y += 4
    p.append(bars(ids, "Volume de logs par source",
                  [tgt(f'sum by (service) (count_over_time({sel}{SEARCH} [$__interval]))',
                       "{{service}}")],
                  (0, y, 24, 7),
                  desc="Lignes de logs par minute et par service. Un trou = service muet "
                  "(arrêté ou en cours de redémarrage) ; un pic = rafale de requêtes "
                  "(attaque, test de charge) ou boucle d'erreurs."))
    y += 7

    p.append(row(ids, "Erreurs et avertissements", y)); y += 1
    p.append(logs(ids, "Erreurs et avertissements (tous services)",
                  f'{sel} |~ `(?i)("level": "(error|critical|warning)"|level=(error|fatal|warn)'
                  f'|\\[(error|crit|alert|emerg|warn)\\]|HTTP/[0-9.]+" 5[0-9]{{2}} '
                  f'|traceback|exception|panic)` {noise}{SEARCH} | line_format `{PREFIX}{MASK}`',
                  (0, y, 24, 10),
                  desc="Lignes d'erreur ou d'avertissement des services de la stack paiement, "
                  "plus récentes en premier, préfixées par « service @ machine ». Exclu : "
                  "l'erreur bénigne « column first_name already exists » au démarrage d'auth. "
                  "Repères : 502 sur /remediation/state ou /api/* = service en redémarrage ; "
                  "« base injoignable » = bascule de la base (voir Logs - Base de données)."))
    y += 10

    p.append(row(ids, "Événements clés", y)); y += 1
    p += [
        logs(ids, "Paiements (payment-api)",
             f'{api} |= `"event"`{SEARCH} | json | __error__="" | event=~"payment|store|reconcile" '
             '| line_format `{{ .host }} │ {{ .msg }}{{ if .provider }} · {{ .provider }}{{ end }}'
             '{{ if .amount }} · montant {{ .amount }}{{ end }}{{ if .reference }} · réf. '
             '{{ .reference }}{{ end }}{{ if .owner }} · compte {{ .owner }}{{ end }}'
             '{{ if .db }} · base {{ .db }}{{ end }}{{ if .error }} · erreur : {{ .error }}{{ end }}`',
             (0, y, 12, 10),
             desc="Journal métier de payment-api : paiement créé puis accepté (Stripe ou "
             "PayPal en mode test), base injoignable / de retour, réconciliation avec Stripe "
             "après une coupure. « paiement non journalisé » = paiement encaissé pendant une "
             "panne de la base, rattrapé ensuite par la réconciliation."),
        logs(ids, "Connexions et freinage anti force brute (auth)",
             f'{auth} |= `"event"`{SEARCH} | json | __error__="" | event=~"login|signup" '
             '| result!="success" or ip!~"172[.]20[.].+" '
             '| line_format `{{ .host }} │ {{ .msg }} · utilisateur {{ .username }}'
             '{{ if .role_extracted }} ({{ .role_extracted }}){{ end }}{{ if .ip }} · IP {{ .ip }}{{ end }}`',
             (12, y, 12, 10),
             desc="Connexions au service d'authentification : réussies, échouées (mot de "
             "passe faux), refusées par le freinage anti force brute (« trop d'échecs »), "
             "créations de compte. L'IP est l'IP réelle du client (transmise par le WAF et "
             "le frontal). Masqué : les connexions réussies internes (172.20.x, la sonde se "
             "connecte toutes les 30 s)."),
    ]
    y += 10
    p += [
        logs(ids, "Back-office : reconnaissance faciale et administration (auth)",
             f'{auth} |= `"event"`{SEARCH} | json | __error__="" | event=~"face|admin" '
             '| line_format `{{ .host }} │ {{ .msg }} · opérateur {{ .username }}'
             '{{ if .score }} · score {{ .score }}{{ end }}{{ if .ip }} · IP {{ .ip }}{{ end }}'
             '{{ if .actor }} · par {{ .actor }}{{ end }}{{ if .error }} · {{ .error }}{{ end }}`',
             (0, y, 12, 9),
             desc="Opérateurs du back-office : la caméra est demandée, le visage est reconnu "
             "(score de similarité) ou refusé ; « aucun visage enrôlé » = l'opérateur n'a pas "
             "encore scanné son visage ; « indisponible » = modèles absents côté serveur "
             "(alerte AuthFaceUnavailable). Actions d'administration : visage scanné sous "
             "trois angles, compte créé, habilitations modifiées."),
        logs(ids, "Requêtes refusées ou en erreur au frontal (4xx / 5xx)",
             f'{front}{SEARCH} {nginx} | status >= 400 | status >= 500 or ua!~"resilience-probe.*" '
             '| line_format `{{ .host }} │ {{ .status }} {{ .method }} ' + MASK_PATH +
             ' · client {{ .ip }} · {{ trunc 70 .ua }}`',
             (12, y, 12, 9),
             desc="Journal d'accès nginx du frontal limité aux réponses ≥ 400, avec l'IP "
             "réelle du client (après le WAF). 401/403 = accès refusé, 413/422 = requête "
             "rejetée par l'API, 499 = client parti, 502/504 = service derrière "
             "indisponible. Les 401 de la sonde sur /detector/score (normaux) sont masqués. "
             "Les valeurs de paramètres sensibles dans l'URL sont remplacées par ***."),
    ]
    y += 9
    p += [
        bars(ids, "Réponses du frontal par code HTTP (hors 2xx/3xx)",
             [tgt(f'sum by (status) (count_over_time({front}{SEARCH} {nginx} '
                  f'| status >= 400 [$__interval]))', "{{status}}")],
             (0, y, 8, 8),
             desc="Codes d'erreur renvoyés par nginx, par minute. Un pic de 401/403 = "
             "tentatives d'accès refusées ; un pic de 502 = service applicatif en panne."),
        table(ids, "Événements applicatifs",
              f'sum by (service, event, result, msg) (count_over_time({{stack="paiement", '
              f'service=~"paiement_(auth|payment-api)", service=~"$source", host=~"$host"}} '
              f'|= `"event"`{SEARCH} | json | __error__="" | event!="" [$__range]))',
              (8, y, 8, 8), sort_by="Nombre",
              rename={"service": "Service", "event": "Événement", "result": "Résultat",
                      "msg": "Message", "Value": "Nombre", "Value #A": "Nombre"},
              desc="Comptage des événements métier (JSON) d'auth et de payment-api sur la "
              "période : connexions, paiements, reconnaissance faciale, base…"),
        table(ids, "IP clientes externes les plus actives",
              f'topk(15, sum by (ip) (count_over_time({front}{SEARCH} {nginx} '
              # une alternance de motifs « 127[.]0… | 172[.]… » n'est pas appliquée par Loki
              # (constaté le 22/10) : préfixes groupés
              f'| ip!~`(127|10|172|192)[.].*` [$__range])))',
              (16, y, 8, 8), sort_by="Requêtes",
              rename={"ip": "IP client", "Value": "Requêtes", "Value #A": "Requêtes"},
              desc="Adresses publiques qui ont envoyé le plus de requêtes au frontal sur la "
              "période (IP réelle transmise par le WAF). Les adresses internes (sonde, "
              "contrôles de santé) sont exclues. Une IP isolée très active = attaque "
              "probable : vérifier son bannissement dans le dashboard Cyber."),
    ]
    y += 8

    p.append(row(ids, "Tous les logs", y)); y += 1
    p.append(logs(ids, "Tous les logs de la stack paiement",
                  f'{sel} !~ `"GET /(health|metrics) HTTP/1.1" 200|"Wget" "-"$`{SEARCH} '
                  f'| line_format `{PREFIX}{MASK}`',
                  (0, y, 24, 14), max_lines=1000,
                  desc="Toutes les lignes des services choisis, plus récentes en premier, "
                  "préfixées par « service @ machine ». Seuls les contrôles de santé réussis "
                  "(/health, /metrics, Wget du healthcheck) sont masqués. Utiliser la variable "
                  "« Recherche » pour filtrer (IP, référence de paiement, utilisateur…)."))

    tmpl = [custom_var("host", "Machine", WORKERS,
                       desc="Workers Swarm qui portent les conteneurs de la stack paiement"),
            custom_var("source", "Source",
                       ["paiement_auth", "paiement_payment-api", "paiement_frontend",
                        "paiement_mailpit"],
                       desc="Service Swarm (label service)"),
            text_var()]
    return dashboard(
        "logs-paiement", "Logs - Application paiement",
        "Logs de l'application de paiement (stack Swarm paiement) : authentification, API de "
        "paiement, frontal nginx, mailpit.",
        p, tmpl,
        [("Vue centrale", "central", "Plateforme - vue centrale (métriques)"),
         ("Démo / Remédiation", "demo-remediation", "Sonde, détecteur et moteur"),
         ("Cyber", "resilience-cyber", "WAF, attaques, bannissements")],
        annotations=[CHAOS_ANN, INCIDENT_ANN],
        rare=["Erreurs et avertissements (tous services)",
              "Connexions et freinage anti force brute (auth)",
              "Back-office : reconnaissance faciale et administration (auth)",
              "Requêtes refusées ou en erreur au frontal (4xx / 5xx)",
              "Réponses du frontal par code HTTP (hors 2xx/3xx)",
              "Événements applicatifs", "IP clientes externes les plus actives"])


# =========================================================================== #
# 2. logs-base : PostgreSQL répliqué (Patroni + etcd)
# =========================================================================== #
def gen_base():
    ids = Ids()
    sel = '{stack="paiement", service=~"$source", host=~"$host"}'
    db = '{stack="paiement", service=~"paiement_db[123]", service=~"$source", host=~"$host"}'
    etcd = ('{stack="paiement", service=~"paiement_etcd[123]", service=~"$source", '
            'host=~"$host"}')
    # Battement Patroni (une ligne toutes les 10 s par nœud) : résumé dans « Rôles »
    heartbeat = '!~ `INFO: no action\\. I am `'
    err = ('|~ `(?i)(,[0-9]+ (ERROR|CRITICAL|FATAL):|\\] (ERROR|FATAL|PANIC):'
           '|"level":"(error|fatal|panic|dpanic)"|traceback)`')
    warn = '|~ `(,[0-9]+ WARNING:|\\] WARNING:|"level":"warn")`'
    strip = ('{{ regexReplaceAll "^[0-9-]+ [0-9:.,]+ (UTC \\\\[[0-9]+\\\\] )?" __line__ "" }}')
    pref = '{{ trimPrefix "paiement_" .service }} @ {{ .host }} │ '
    p, y = [], 0

    p.append(row(ids, "En un coup d'œil", y)); y += 1
    p += [
        stat(ids, "Lignes de logs", f'sum(count_over_time({sel}{SEARCH} [$__range]))',
             (0, y, 4, 4), desc="Lignes écrites par les nœuds choisis sur la période. "
             "Patroni écrit une ligne de battement toutes les 10 s par nœud."),
        stat(ids, "Erreurs", f'sum(count_over_time({sel} {err}{SEARCH} [$__range]))',
             (4, y, 4, 4), thresholds=steps(("green", None), ("red", 1)),
             desc="Lignes ERROR / FATAL / PANIC de PostgreSQL et Patroni, level error d'etcd. "
             "Au redémarrage d'un réplica, quelques FATAL sont normaux (« the database "
             "system is starting up », « replication slot is active ») tant qu'ils cessent "
             "en moins d'une minute."),
        stat(ids, "Avertissements", f'sum(count_over_time({sel} {warn}{SEARCH} [$__range]))',
             (8, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="WARNING de Patroni/PostgreSQL et level warn d'etcd (pair perdu, "
             "publication du membre en attente)."),
        stat(ids, "Primaire actuel",
             'sum by (noeud) (count_over_time({stack="paiement", service=~"paiement_db[123]"} '
             '|= "the leader with the lock" | regexp `I am \\((?P<noeud>[a-z0-9]+)\\)` [1m]))',
             (12, y, 4, 4), text_mode="name", no_value="AUCUN", legend="{{noeud}}",
             thresholds=steps(("green", None)),
             desc="Nœud Patroni qui détient le verrou de leader dans etcd (dernière minute) : "
             "c'est le primaire PostgreSQL, les autres sont des réplicas. « AUCUN » = pas de "
             "primaire, écritures impossibles. Ne dépend pas des variables."),
        stat(ids, "Promotions de primaire",
             f'sum(count_over_time({db} |~ `promoted self to leader`{SEARCH} [$__range]))',
             (16, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Nombre de fois où un réplica est devenu primaire sur la période (bascule "
             "automatique après la perte du primaire, ou redémarrage du cluster)."),
        stat(ids, "Démarrages de nœuds",
             f'sum(count_over_time({sel} |~ `starting PostgreSQL [0-9]|"msg":"starting an etcd '
             f'server"`{SEARCH} [$__range]))',
             (20, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Démarrages de PostgreSQL et d'etcd sur la période : conteneur relancé par "
             "Swarm après une panne, un test de chaos ou un redéploiement."),
    ]
    y += 4
    p.append(bars(ids, "Volume de logs par source",
                  [tgt(f'sum by (service) (count_over_time({sel}{SEARCH} [$__interval]))',
                       "{{service}}")],
                  (0, y, 24, 7),
                  desc="Lignes par minute et par nœud. Volume régulier = battements Patroni ; "
                  "pic = redémarrage, rattrapage de réplication ou élection etcd ; trou = nœud "
                  "arrêté."))
    y += 7

    p.append(row(ids, "Erreurs et avertissements", y)); y += 1
    p.append(logs(ids, "Erreurs et avertissements (PostgreSQL, Patroni, etcd)",
                  f'{sel} |~ `(?i)(,[0-9]+ (ERROR|CRITICAL|FATAL|WARNING):|\\] (ERROR|FATAL|PANIC'
                  f'|WARNING):|"level":"(warn|error|fatal|panic|dpanic)"|traceback)`{SEARCH} '
                  f'| line_format `{pref}{strip}`',
                  (0, y, 24, 10),
                  desc="Lignes de gravité warning ou plus, préfixées par « nœud @ machine », "
                  "horodatage interne retiré. Repères : « replication slot … is active » et "
                  "« could not start WAL streaming » au redémarrage d'un réplica = transitoire ; "
                  "« peer became inactive » (etcd) = un membre etcd est tombé ; « failed to "
                  "resolve host » = conteneur voisin pas encore démarré."))
    y += 10

    p.append(row(ids, "Événements clés", y)); y += 1
    p += [
        logs(ids, "Élection du primaire et bascules (Patroni)",
             f'{db} |~ `(?i)promoted self to leader|acquired session lock|following new leader'
             f'|demot|Lock owner: None|received promote request|pg_rewind|starting as a '
             f'secondary|starting as readonly|released leader key|does not have lock'
             f'|bootstrap|failover|switchover|Setting leader to|waiting for leader`{SEARCH} '
             f'| line_format `{pref}{strip}`',
             (0, y, 12, 10),
             desc="Comment Patroni choisit le primaire : « Lock owner: None » = plus de "
             "primaire, « promoted self to leader » = un réplica devient primaire, « following "
             "new leader » = un autre nœud suit le nouveau primaire, « pg_rewind » = l'ancien "
             "primaire est réaligné avant de redevenir réplica, « starting as a secondary » = "
             "nœud redémarré en réplica, « Setting leader to … quorum » = réplication "
             "synchrone recalculée."),
        logs(ids, "Réplication : réplicas, flux WAL, timeline",
             f'{db} |~ `(?i)started streaming WAL|entering standby mode|consistent recovery state'
             f'|ready to accept (read-only )?connections|primary_timeline|Local timeline'
             f'|selected new timeline|synchronous replication|candidate for quorum'
             f'|could not start WAL streaming|unexpected EOF on standby|archive recovery '
             f'complete|redo (starts|done)`{SEARCH} | line_format `{pref}{strip}`',
             (12, y, 12, 10),
             desc="Vie de la réplication : un réplica entre en mode standby, rattrape le WAL "
             "(« redo starts », « consistent recovery state »), puis reçoit le flux du primaire "
             "(« started streaming WAL from primary … on timeline N »). La timeline augmente à "
             "chaque promotion. « Setting synchronous replication to 1 of 2 » = une "
             "transaction attend l'accusé d'au moins un réplica (aucune perte en cas de "
             "bascule). Le retard de réplication n'est pas journalisé (métriques)."),
    ]
    y += 10
    p += [
        logs(ids, "etcd : élections Raft et liens entre membres",
             f'{etcd}{SEARCH} | json | __error__="" | msg=~"(?i).*(elected leader|became leader'
             f'|lost leader|leader changed|starting election|became candidate|became follower'
             f'|peer became|lost TCP streaming|established TCP streaming|starting an etcd server'
             f'|closed etcd server|added member|removed member|failed to publish).*" '
             f'| line_format `{pref}[{{{{ .level_extracted }}}}] {{{{ .msg }}}}'
             f'{{{{ if .error }}}} · {{{{ .error }}}}{{{{ end }}}}`',
             (0, y, 12, 9),
             desc="etcd garde le verrou de leader de Patroni (3 membres, quorum 2). On y lit "
             "l'élection Raft (« elected leader … at term N »), la perte et le retour d'un "
             "membre (« peer became inactive / active », « lost / established TCP "
             "streaming ») et les redémarrages. Si deux membres sur trois tombent, Patroni "
             "ne peut plus élire de primaire."),
        table(ids, "Rôle de chaque nœud (battement Patroni)",
              'sum by (noeud, statut) (count_over_time({stack="paiement", '
              'service=~"paiement_db[123]", host=~"$host"} |= "no action. I am" '
              '| regexp `I am \\((?P<noeud>[a-z0-9]+)\\), (?P<statut>[^,(]+)` [$__range]))',
              (12, y, 6, 9), sort_by="Battements",
              rename={"noeud": "Nœud", "statut": "Rôle annoncé", "Value": "Battements",
                      "Value #A": "Battements"},
              desc="Battements Patroni (« no action. I am (db3), the leader with the lock » "
              "toutes les 10 s) comptés par nœud et par rôle sur la période. Un nœud qui "
              "apparaît avec deux rôles a changé de rôle pendant la période (bascule). Ces "
              "lignes sont masquées ailleurs pour ne pas noyer le reste."),
        logs(ids, "Arrêts et démarrages des nœuds",
             f'{sel} |~ `starting PostgreSQL [0-9]|database system is shut down|received fast '
             f'shutdown|database system is ready to accept|Postgresql is not running'
             f'|"msg":"starting an etcd server"|"msg":"closed etcd server"`{SEARCH} '
             f'| line_format `{pref}{{{{ regexReplaceAll "\\"(ts|caller|logger)\\":\\"[^\\"]*\\"," '
             f'__line__ "" | trunc 160 }}}}`',
             (18, y, 6, 9),
             desc="Arrêts et démarrages de PostgreSQL et d'etcd : chaque relance d'un "
             "conteneur par Swarm (panne de worker, test de chaos, redéploiement)."),
    ]
    y += 9

    p.append(row(ids, "Tous les logs", y)); y += 1
    p.append(logs(ids, "Tous les logs de la base (hors battements Patroni)",
                  f'{sel} {heartbeat}{SEARCH} | line_format `{pref}{MASK}`',
                  (0, y, 24, 14), max_lines=1000,
                  desc="Toutes les lignes de PostgreSQL/Patroni et d'etcd, plus récentes en "
                  "premier, sauf le battement Patroni « no action. I am … » (une ligne toutes "
                  "les 10 s par nœud, résumée dans « Rôle de chaque nœud »). Les points de "
                  "contrôle (checkpoint / restartpoint) toutes les 5 min sont normaux."))

    tmpl = [custom_var("host", "Machine", WORKERS,
                       desc="Workers Swarm (un nœud PostgreSQL et un membre etcd par worker)"),
            custom_var("source", "Source",
                       ["paiement_db1", "paiement_db2", "paiement_db3",
                        "paiement_etcd1", "paiement_etcd2", "paiement_etcd3"],
                       desc="Service Swarm (label service)"),
            text_var()]
    return dashboard(
        "logs-base", "Logs - Base de données (Patroni)",
        "Logs de la base PostgreSQL répliquée (Patroni, 3 nœuds) et de son magasin de "
        "consensus etcd (3 membres) : élection du primaire, réplication, redémarrages.",
        p, tmpl,
        [("Vue centrale", "central", "Plateforme - vue centrale (métriques)"),
         ("Swarm", "swarm-overview", "Docker Swarm - vue d'ensemble"),
         ("Conteneurs", "docker-containers", "Docker Swarm - conteneurs")],
        annotations=[CHAOS_ANN, INCIDENT_ANN],
        rare=["Erreurs et avertissements (PostgreSQL, Patroni, etcd)",
              "Élection du primaire et bascules (Patroni)",
              "Réplication : réplicas, flux WAL, timeline",
              "etcd : élections Raft et liens entre membres",
              "Arrêts et démarrages des nœuds"])


# =========================================================================== #
# 3. logs-remediation : détection et remédiation
# =========================================================================== #
def gen_remediation():
    ids = Ids()
    sel = '{stack=~"paiement|probe", service=~"$source", host=~"$host"}'
    probe = ('{stack="probe", service="probe_transactions", service=~"$source", '
             'host=~"$host"}')
    gw = '{host=~"dockermgr0[123]", host=~"$host", identifier="remediate"}'
    gw_parse = ('| regexp `^caller=(?P<caller>\\S+) code=(?P<code>[0-9]+) (?P<corps>.*)$` '
                '| line_format `{{ .corps }}` | json')
    # Bruit : contrôles de santé et interrogations périodiques (détecteur /score chaque
    # seconde, moteur /state, /health, /metrics)
    polling = '!~ `"GET /(health|score|state|metrics|remediation/state) HTTP/1.1" 200`'
    err_svc = ('|~ `(?i)(traceback|exception|error|erreur|fatal|panic|HTTP/[0-9.]+" 5[0-9]{2} '
               '|result=echec)` != "type=etat"')
    pref = '{{ trimPrefix "paiement_" .service }} @ {{ .host }} │ '
    ev_fmt = ('| line_format `{{ if eq .kind "detect" }}[1 Détection]{{ else if eq .kind "act" }}'
              '[2 Moteur]{{ else if eq .kind "verify" }}[4 Vérification]{{ else if eq .kind '
              '"restore" }}[5 Rétabli]{{ else }}[{{ .kind }}]{{ end }} {{ .texte }}`')
    gw_fmt = ('| line_format `[3 Passerelle {{ .host }}] {{ if .action }}{{ .action }}{{ else }}'
              'refus{{ end }} {{ .service }}{{ if .duration_s }} en {{ .duration_s }} s{{ end }}'
              '{{ if .replicas_desired }} · {{ .replicas_running }}/{{ .replicas_desired }} '
              'réplicas{{ end }} · code {{ .code }}{{ if .error }} · {{ .error }}{{ end }}'
              ' · appel de {{ .caller }}`')
    inc_fmt = ('| line_format `{{ if eq .phase "debut" }}[Sonde : PANNE]{{ else }}'
               '[Sonde : REPRISE]{{ end }} {{ .texte }}`')
    p, y = [], 0

    p.append(row(ids, "En un coup d'œil", y)); y += 1
    p += [
        stat(ids, "Lignes de logs", f'sum(count_over_time({sel}{SEARCH} [$__range]))',
             (0, y, 4, 4), desc="Lignes écrites par le détecteur, le moteur et la sonde sur la "
             "période (hors passerelle). L'essentiel : interrogations périodiques du score "
             "(chaque seconde) et de l'état du moteur."),
        stat(ids, "Erreurs",
             f'(sum(count_over_time({sel} {err_svc}{SEARCH} [$__range])) or vector(0)) '
             f'+ (sum(count_over_time({gw} != " code=0 "{SEARCH} [$__range])) or vector(0))',
             (4, y, 4, 4), thresholds=steps(("green", None), ("red", 1)),
             desc="Traces Python, réponses 5xx, transactions de la sonde en échec et appels "
             "refusés par la passerelle (code ≠ 0). Pendant une remédiation, la sonde voit "
             "quelques transactions échouer : c'est la panne mesurée, pas un défaut du "
             "moteur."),
        stat(ids, "Avertissements",
             f'sum(count_over_time({sel} |~ `(?i)(WARNING:|level=warn)|type=etat .*'
             f'(paiements=panne|sante=echec)`{SEARCH} [$__range]))',
             (8, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Lignes d'état de la sonde (une toutes les 5 s) qui signalent des paiements en "
             "panne ou une santé en échec, plus les WARNING d'uvicorn. Proportionnel à la "
             "durée des pannes : 12 lignes ≈ 1 min de panne."),
        stat(ids, "Anomalies confirmées",
             f'sum(count_over_time({probe} |= "type=evenement" |= "kind=detect"{SEARCH} '
             f'[$__range]))',
             (12, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Incidents confirmés par le détecteur ML (score ≥ seuil 0,55) qui ont "
             "déclenché le moteur, sur la période."),
        stat(ids, "Actions de la passerelle",
             f'sum(count_over_time({gw} |~ `"action": "(restart|scale|rollback)"`{SEARCH} '
             f'[$__range]))',
             (16, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Actions correctives exécutées par la passerelle remediate des managers "
             "(redémarrage, mise à l'échelle, retour arrière) ; les simples lectures (status, "
             "list) ne sont pas comptées."),
        stat(ids, "Pannes vues par la sonde",
             f'sum(count_over_time({probe} |= "type=incident" |= "phase=debut"{SEARCH} '
             f'[$__range]))',
             (20, y, 4, 4), thresholds=steps(("green", None), ("orange", 1)),
             desc="Débuts de panne détectés par la sonde de transaction (client réel qui paie "
             "toutes les 30 s et vérifie la santé toutes les 5 s). La durée de chaque panne "
             "est dans « Pannes et transactions en échec »."),
    ]
    y += 4
    p.append(bars(ids, "Volume de logs par source",
                  [tgt(f'sum by (service) (count_over_time({sel}{SEARCH} [$__interval]))',
                       "{{service}}", ref="A"),
                   tgt(f'sum by (identifier) (count_over_time({gw}{SEARCH} [$__interval]))',
                       "passerelle remediate", ref="B")],
                  (0, y, 24, 7),
                  desc="Lignes par minute : détecteur, moteur, sonde et passerelle remediate. "
                  "Le détecteur est interrogé chaque seconde (volume constant) ; la passerelle "
                  "n'écrit qu'à chaque appel du moteur."))
    y += 7

    p.append(row(ids, "Erreurs et avertissements", y)); y += 1
    p.append(logs(ids, "Erreurs (détecteur, moteur, sonde, passerelle)",
                  [f'{sel} {err_svc}{SEARCH} | line_format `{pref}{MASK}`',
                   f'{gw} != " code=0 "{SEARCH} {gw_parse} {gw_fmt}'],
                  (0, y, 24, 9),
                  desc="Erreurs des composants de la chaîne : traces Python (ex. BrokenPipe de "
                  "la sonde quand un client coupe /metrics, sans conséquence), réponses 5xx, "
                  "transactions de contrôle en échec, appels refusés par la passerelle (ex. "
                  "« service inconnu » : service hors liste blanche ou en cours de "
                  "recréation)."))
    y += 9

    p.append(row(ids, "Événements clés", y)); y += 1
    p += [
        logs(ids, "La chaîne de remédiation, étape par étape",
             [f'{probe} |= "type=evenement"{SEARCH} | logfmt {ev_fmt}',
              f'{gw} |~ `"action": "(restart|scale|rollback)"|code=[1-9]`{SEARCH} {gw_parse} '
              f'{gw_fmt}',
              f'{probe} |= "type=incident"{SEARCH} | logfmt {inc_fmt}'],
             (0, y, 14, 12), max_lines=300,
             desc="À lire de bas en haut (plus récent en haut) : [Sonde : PANNE] la sonde ne "
             "peut plus payer → [1 Détection] le détecteur ML confirme l'anomalie (score ≥ "
             "0,55) → [2 Moteur] décision (recréer le service) → [3 Passerelle] le manager "
             "Swarm exécute l'action (durée, réplicas en marche) → [4 Vérification] "
             "transaction de contrôle → [5 Rétabli] durée totale, 0 intervention humaine → "
             "[Sonde : REPRISE] durée de panne vue par un client. Les étapes 1, 2, 4, 5 "
             "viennent du moteur (recopiées par la sonde, le moteur ne journalise pas "
             "lui-même) ; l'étape 3 vient du journal des managers."),
        logs(ids, "Pannes et transactions en échec (sonde)",
             f'{probe} |~ "type=(transaction|incident)"{SEARCH} | logfmt | result!="ok" '
             '| line_format `{{ if eq .type "incident" }}{{ if eq .phase "debut" }}PANNE{{ else }}'
             'REPRISE{{ end }} │ {{ .texte }}{{ else }}Transaction en échec à l\'étape '
             '{{ .etape_echec }} · {{ .detail }} · {{ .duree_ms }} ms{{ end }}`',
             (14, y, 10, 12),
             desc="Vue client : la sonde paie 1 € toutes les 30 s par l'adresse virtuelle et "
             "vérifie /api/health toutes les 5 s. PANNE / REPRISE encadrent chaque coupure "
             "avec sa durée réelle ; une transaction en échec indique l'étape qui casse "
             "(connexion, création, confirmation) et le code HTTP (0 = pas de réponse)."),
    ]
    y += 12
    p += [
        bars(ids, "Étapes de la chaîne dans le temps",
             [tgt(f'sum by (kind) (count_over_time({probe} |= "type=evenement"{SEARCH} '
                  f'| logfmt [$__interval]))', "moteur : {{kind}}", ref="A"),
              tgt(f'sum by (action) (count_over_time({gw}{SEARCH} '
                  f'| regexp `"action": "(?P<action>[a-z_-]+)"` | action!="" [$__interval]))',
                  "passerelle : {{action}}", ref="B"),
              tgt(f'sum by (phase) (count_over_time({probe} |= "type=incident"{SEARCH} '
                  f'| logfmt [$__interval]))', "sonde : {{phase}}", ref="C")],
             (0, y, 10, 9),
             desc="Chaque barre = un événement : détection (detect), décision et action "
             "(act), vérification (verify), retour à la normale (restore), appels de la "
             "passerelle par action, débuts et fins de panne vus par la sonde. Les "
             "événements d'un même incident sont groupés en moins d'une minute."),
        table(ids, "Appels de la passerelle",
              f'sum by (host, action, service, code) (count_over_time({gw}{SEARCH} {gw_parse} '
              f'[$__range]))',
              (10, y, 7, 9), sort_by="Appels",
              rename={"host": "Manager", "action": "Action", "service": "Service",
                      "code": "Code retour", "Value": "Appels", "Value #A": "Appels"},
              desc="Appels reçus par /usr/local/sbin/remediate sur les managers, par action et "
              "service. Code 0 = exécuté ; code ≠ 0 = refusé (service ou action hors liste "
              "blanche, limite de fréquence). status / list = lectures d'état du moteur."),
        logs(ids, "Accès SSH du moteur à la passerelle",
             f'{{host=~"dockermgr0[123]", host=~"$host", identifier=~"sshd-session|sshd|sudo"}} '
             f'|= "remediation" !~ "pam_unix"{SEARCH} '
             '| line_format `{{ .host }} │ {{ regexReplaceAll "PWD=[^;]*; " __line__ "" }}`',
             (17, y, 7, 9),
             desc="Le moteur n'a pas accès au socket Docker : il se connecte en SSH au compte "
             "« remediation » d'un manager, dont la clé n'autorise qu'une commande forcée "
             "(sudo /usr/local/sbin/remediate <action> <service>). On voit ici la connexion "
             "par clé et la commande exécutée."),
    ]
    y += 9
    p.append(logs(ids, "Redémarrages du détecteur et du moteur",
                  f'{{stack="paiement", service=~"paiement_(detector|remediation)", '
                  f'service=~"$source", host=~"$host"}} |~ `Started server process|Shutting '
                  f'down|Finished server process|remédiation : mode|Application startup '
                  f'complete`{SEARCH} | line_format `{pref}{{{{ __line__ }}}}`',
                  (0, y, 24, 6),
                  desc="Démarrages et arrêts des conteneurs detector et remediation (uvicorn). "
                  "Au démarrage, le moteur annonce son mode (ssh) et les passerelles qu'il "
                  "utilisera (les 3 managers)."))
    y += 6

    p.append(row(ids, "Tous les logs", y)); y += 1
    p += [
        logs(ids, "Détecteur, moteur et sonde (hors interrogations périodiques)",
             f'{sel} {polling}{SEARCH} | line_format `{pref}{MASK}`',
             (0, y, 16, 14), max_lines=1000,
             desc="Toutes les lignes des sources choisies, plus récentes en premier, sauf les "
             "interrogations réussies (/score chaque seconde, /state, /health, /metrics). "
             "Les lignes « type=etat » de la sonde (toutes les 5 s) donnent l'état complet : "
             "paiements, score du détecteur, anomalie, état du moteur. Le score dans le "
             "temps est dans le dashboard Modèle ML."),
        logs(ids, "Passerelle remediate (journal des managers)",
             f'{gw}{SEARCH} {gw_parse} {gw_fmt}',
             (16, y, 8, 14), max_lines=500,
             desc="Chaque appel reçu par la passerelle, résumé : action, service, durée, "
             "réplicas en marche après l'action, code retour, IP du worker qui porte le "
             "moteur. Le détail (état de la mise à jour Swarm, tâches) est dans la ligne "
             "complète (cliquer la ligne). La variable source ne s'applique pas ici."),
    ]

    tmpl = [custom_var("host", "Machine", WORKERS + MANAGERS,
                       desc="Workers (détecteur, moteur, sonde) et managers (passerelle)"),
            custom_var("source", "Source",
                       ["paiement_detector", "paiement_remediation", "probe_transactions"],
                       desc="Service Swarm (label service) ; la passerelle des managers "
                            "est toujours affichée"),
            text_var()]
    ev = PROBE + ' |= "type=evenement" | logfmt'
    return dashboard(
        "logs-remediation", "Logs - Détection et remédiation",
        "Logs de la chaîne de reprise automatique : anomalie détectée, décision du moteur, "
        "action de la passerelle remediate, reprise vue par la sonde de transaction.",
        p, tmpl,
        [("Démo / Remédiation", "demo-remediation", "Vue métriques de la démonstration"),
         ("Modèle ML", "ml-detecteur", "Détecteur d'anomalies (score, seuil, métriques)"),
         ("Vue centrale", "central", "Plateforme - vue centrale")],
        annotations=[
            CHAOS_ANN, INCIDENT_ANN,
            {"name": "Incident détecté", "enable": True, "hide": False, "iconColor": "red",
             "datasource": LOKI, "expr": ev + ' | kind="detect"', "instant": False,
             "titleFormat": "{{etape}}", "textFormat": "{{texte}}", "tagKeys": "kind"},
            {"name": "Service rétabli", "enable": True, "hide": False, "iconColor": "green",
             "datasource": LOKI, "expr": ev + ' | kind="restore"', "instant": False,
             "titleFormat": "{{etape}}", "textFormat": "{{texte}}", "tagKeys": "kind"}],
        rare=["Erreurs (détecteur, moteur, sonde, passerelle)",
              "La chaîne de remédiation, étape par étape",
              "Pannes et transactions en échec (sonde)",
              "Étapes de la chaîne dans le temps", "Appels de la passerelle",
              "Accès SSH du moteur à la passerelle",
              "Redémarrages du détecteur et du moteur",
              "Passerelle remediate (journal des managers)"])


if __name__ == "__main__":
    write("logs-paiement.json", gen_paiement())
    write("logs-base.json", gen_base())
    write("logs-remediation.json", gen_remediation())

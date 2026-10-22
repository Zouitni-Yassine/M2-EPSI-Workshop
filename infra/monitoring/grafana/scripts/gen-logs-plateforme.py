#!/usr/bin/env python3
"""Génère cinq dashboards Grafana de lecture de logs (Loki), dossier « Logs » :

  logs-accueil      Logs - Accueil (page d'entrée des neuf parties)
  logs-waf          Logs - WAF et sécurité (waf01, waf-ban, SSH sur toutes les machines)
  logs-assistant    Logs - Assistant IA (rag01 : Ollama, API RAG, MCP, bot Discord)
  logs-supervision  Logs - Supervision (Loki, Grafana, Alertmanager, VictoriaMetrics, vmagent, Alloy)
  logs-swarm        Logs - Docker Swarm et hôtes (dockermgr/dockerwrk : Docker, keepalived, noyau)

Usage (depuis infra/monitoring/grafana) : python3 -B scripts/gen-logs-plateforme.py
Sortie : dashboards/Logs/logs-<partie>.json (écriture atomique : fichier temporaire puis rename).

Gabarit commun des dashboards « Logs - * » : variables host / source / recherche, rangées
« En un coup d'œil », « Erreurs et avertissements », « Événements clés », « Tous les logs ».
Les autres dashboards Logs (paiement, base, remediation, virtualisation, identite, controle)
sont générés par d'autres scripts ; l'accueil ne fait que les lier par leur uid.

Données personnelles : les journaux de rag01 (rag-api, discord-bot) contiennent le pseudo
Discord de l'auteur de chaque question ; il est retiré de toutes les lignes affichées
(line_format, avant le filtre « recherche ») et n'est jamais extrait en label.
"""
import json
import os
import pathlib
import tempfile

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "dashboards/Logs"

LOKI = {"type": "loki", "uid": "loki"}

HOSTS_ALL = ["ceph01", "ceph02", "ceph03", "control01", "dockermgr01", "dockermgr02",
             "dockermgr03", "dockerwrk01", "dockerwrk02", "dockerwrk03", "iam01",
             "monitoring01", "rag01", "vault01", "vaultwarden01", "vmagent01", "vmagent02",
             "waf01"]
HOSTS_SWARM = ["dockermgr01", "dockermgr02", "dockermgr03",
               "dockerwrk01", "dockerwrk02", "dockerwrk03"]

# Mots-clés d'erreur / d'avertissement (insensibles à la casse), appliqués au texte des lignes :
# le label « level » d'Alloy vient de la priorité journald, et la plupart des services
# (Docker, VictoriaMetrics, Loki...) écrivent leurs erreurs en priorité « info ».
# Pas de « err= » ni de « timed.out » : ces motifs empêchent Loki d'optimiser le filtre en
# recherche de sous-chaînes (requête 30 fois plus lente, 502 sur 6 h pour les gros flux).
ERR = r"(?i)(error|erreur|fail|échec|echec|crit|fatal|panic|denied|refused|timeout|traceback|exception)"
WARN = r"(?i)(warn|avertissement|deprecat)"

# Restes de tests à exclure partout (consigne commune)
JUNK_CONTAINERS = ("determined_sutherland|eloquent_babbage|kind_beaver|loving_shirley|"
                   "objective_wu|sad_hugle|stupefied_hopper")
CLEAN = f'stack!~"dbtest|demo", container!~"{JUNK_CONTAINERS}"'

RECH = ' |~ `(?i)$recherche`'
NO_VALUE = "Aucun événement sur la période (normal hors incident)"
# Identifiants de conteneurs Swarm = <service>.<réplica>.<tâche> : ramenés au nom du service
# dans le label « src » pour que la variable « source » n'ait que des valeurs littérales
# (Grafana échappe les caractères de regex des valeurs pour Loki).
SRC = ' | label_format src=`{{ regexReplaceAll "[.][0-9]+[.].*" .identifier "" }}`'

# Supervision : Loki journalise chaque requête (avec son texte, donc souvent le mot « error ») ;
# on ne retient que les niveaux error/fatal et les échecs de collecte.
ERR_SUP = r"level=error|level=eror|level=crit|level=fatal|\terror\t|\tfatal\t|\tpanic\t|panic:|Traceback|cannot scrape|couldn't send"


# --------------------------------------------------------------------------- #
# Briques de base (mêmes conventions que gen-central-dashboard.py)
# --------------------------------------------------------------------------- #
class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


ID = Ids()


def tgt(expr, legend="", ref="A", instant=False):
    return {"datasource": LOKI, "refId": ref, "expr": expr, "legendFormat": legend,
            "editorMode": "code", "queryType": "instant" if instant else "range"}


def steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


def panel(ptype, title, targets, pos, *, desc="", unit=None, thresholds=None,
          options=None, custom=None, overrides=None, color=None, no_value=None,
          transformations=None, links=None, decimals=None, mappings=None, interval=None,
          time_from=None):
    x, y, w, h = pos
    if no_value is None:
        no_value = NO_VALUE
    defaults = {"mappings": mappings or [],
                "thresholds": thresholds or steps(("green", None))}
    for key, val in (("unit", unit), ("noValue", no_value), ("decimals", decimals)):
        if val is not None:
            defaults[key] = val
    defaults["color"] = color or {"mode": "thresholds"}
    if custom is not None:
        defaults["custom"] = custom
    if links:
        defaults["links"] = links
    p = {"id": ID(), "type": ptype, "title": title, "description": desc,
         "datasource": LOKI, "gridPos": {"x": x, "y": y, "w": w, "h": h},
         "targets": targets,
         "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
         "options": options or {}}
    if transformations:
        p["transformations"] = transformations
    if interval:
        p["interval"] = interval
    if time_from:  # événements rares : fenêtre propre au panneau (titre suffixé « (24 h) »)
        p["timeFrom"] = time_from
        p["title"] = f"{title} ({time_from[:-1]} {time_from[-1]})"
    return p


def row(title, y):
    return {"id": ID(), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(title, expr, pos, *, desc="", thresholds=None, unit="short", no_value="0",
         links=None, color=None, text_mode="value", targets=None, overrides=None):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "justifyMode": "center",
            "textMode": text_mode, "orientation": "auto", "wideLayout": True,
            "showPercentChange": False, "text": {}}
    return panel("stat", title, targets or [tgt(expr, instant=True)], pos, desc=desc,
                 unit=unit, options=opts, no_value=no_value, links=links, color=color,
                 thresholds=thresholds or steps(("blue", None)), overrides=overrides)


def bars(title, targets, pos, *, desc="", legend=True, unit="short", stack=True,
         overrides=None, interval=None, time_from=None):
    custom = {"drawStyle": "bars", "lineWidth": 1, "fillOpacity": 80,
              "gradientMode": "none", "showPoints": "never", "spanNulls": False,
              "axisSoftMin": 0, "barAlignment": 0,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    opts = {"legend": {"displayMode": "list", "placement": "bottom",
                       "showLegend": legend, "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel("timeseries", title, targets, pos, desc=desc, unit=unit, custom=custom,
                 options=opts, color={"mode": "palette-classic"}, overrides=overrides,
                 interval=interval, time_from=time_from)


def points(title, targets, pos, *, desc="", unit="s", time_from=None):
    custom = {"drawStyle": "points", "pointSize": 8, "lineWidth": 1, "fillOpacity": 0,
              "showPoints": "always", "spanNulls": False, "axisSoftMin": 0,
              "stacking": {"mode": "none", "group": "A"}}
    opts = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True,
                       "calcs": ["mean", "max"]},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel("timeseries", title, targets, pos, desc=desc, unit=unit, custom=custom,
                 options=opts, color={"mode": "palette-classic"}, time_from=time_from)


LOGS_OPTS = {"showTime": True, "showLabels": False, "showCommonLabels": False,
             "wrapLogMessage": True, "prettifyLogMessage": False,
             "enableLogDetails": True, "enableInfiniteScrolling": False,
             "dedupStrategy": "none", "sortOrder": "Descending"}


def logs(title, expr, pos, *, desc="", targets=None, time_from=None):
    return panel("logs", title, targets or [tgt(expr)], pos, desc=desc,
                 options=dict(LOGS_OPTS), time_from=time_from)


def count_table(title, expr, pos, columns, value_name, *, desc="", legend="",
                time_from=None):
    """Tableau de comptages : requête instantanée « sum by (labels) » sur la période,
    une ligne par série (labels en colonnes), triée par valeur décroissante."""
    rename = dict(columns)
    rename["Last *"] = value_name
    order = {name: i for i, name in enumerate(list(dict(columns)) + ["Last *"])}
    opts = {"showHeader": True, "cellHeight": "sm",
            "footer": {"show": False, "reducer": ["sum"], "fields": ""}}
    custom = {"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False}
    overrides = [{"matcher": {"id": "byName", "options": value_name},
                  "properties": [{"id": "custom.cellOptions",
                                  "value": {"type": "gauge", "mode": "basic",
                                            "valueDisplayMode": "text"}},
                                 {"id": "color", "value": {"mode": "continuous-BlYlRd"}}]}]
    return panel("table", title, [tgt(expr, legend=legend, instant=True)], pos, desc=desc,
                 options=opts, custom=custom, overrides=overrides, time_from=time_from,
                 transformations=[
                     {"id": "reduce", "options": {"mode": "seriesToRows",
                                                  "reducers": ["lastNotNull"],
                                                  "labelsToFields": True,
                                                  "includeTimeField": False}},
                     {"id": "organize", "options": {
                         "excludeByName": {"Field": True},
                         "indexByName": order, "renameByName": rename}},
                     {"id": "sortBy", "options": {"sort": [{"field": value_name,
                                                            "desc": True}]}}])


def text(title, content, pos, desc=""):
    return panel("text", title, [], pos, desc=desc,
                 options={"mode": "markdown", "content": content,
                          "code": {"language": "plaintext", "showLineNumbers": False,
                                   "showMiniMap": False}})


def custom_var(name, label, pairs, *, multi=True, include_all=True, desc=""):
    """Variable « custom » : pairs = [(texte affiché, valeur)]. Toutes sélectionnées par défaut."""
    query = ",".join(f"{t} : {v}" if t != v else v for t, v in pairs)
    options = [{"text": "All", "value": "$__all", "selected": True}] if include_all else []
    options += [{"text": t, "value": v, "selected": False} for t, v in pairs]
    current = ({"text": ["All"], "value": ["$__all"]} if include_all
               else {"text": pairs[0][0], "value": pairs[0][1]})
    return {"type": "custom", "name": name, "label": label, "description": desc,
            "query": query, "multi": multi, "includeAll": include_all,
            "current": current, "options": options, "hide": 0,
            "skipUrlSync": False}


def textbox(name="recherche", label="Recherche (regex)"):
    return {"type": "textbox", "name": name, "label": label,
            "description": "Filtre texte appliqué aux panneaux de logs (expression régulière, "
                           "insensible à la casse). Vide = tout.",
            "query": "", "current": {"text": "", "value": ""},
            "options": [{"selected": True, "text": "", "value": ""}], "hide": 0}


def dash_links(*extra):
    links = [{"title": "Logs - Accueil", "type": "link", "url": "/d/logs-accueil",
              "icon": "doc", "tooltip": "Page d'entrée des logs : toutes les parties",
              "keepTime": True, "includeVars": False, "targetBlank": False,
              "asDropdown": False, "tags": []},
             {"title": "Autres logs", "type": "dashboards", "tags": ["logs"],
              "asDropdown": True, "keepTime": True, "includeVars": False,
              "targetBlank": False, "icon": "external link", "tooltip": "", "url": ""}]
    for title, uid, tip in extra:
        links.append({"title": title, "type": "link", "url": f"/d/{uid}",
                      "icon": "dashboard", "tooltip": tip, "keepTime": True,
                      "includeVars": False, "targetBlank": False, "asDropdown": False,
                      "tags": []})
    return links


def dashboard(uid, title, desc, panels, variables, links, extra_tags=()):
    return {
        "id": None, "uid": uid, "title": title, "description": desc,
        "tags": ["logs", *extra_tags], "timezone": "browser", "editable": True,
        "graphTooltip": 1, "refresh": "30s",
        "time": {"from": "now-1h", "to": "now"},
        "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
        "fiscalYearStartMonth": 0, "liveNow": False, "schemaVersion": 39, "version": 1,
        "links": links,
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
             "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
             "name": "Annotations & Alerts", "type": "dashboard"}]},
        "templating": {"list": variables},
        "panels": panels,
    }


def write(name, dash):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{name}.json"
    fd, tmp = tempfile.mkstemp(dir=OUT_DIR, prefix=f".{name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(dash, indent=2, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, out)
    print(f"{out} : {len(dash['panels'])} panneaux")


def count(sel, rng="$__range"):
    return f"sum(count_over_time({sel} [{rng}])) or vector(0)"


VOL_DESC = ("Nombre de lignes de logs par intervalle, empilées par source. Un pic isolé = "
            "un événement (redémarrage, attaque, rafale d'erreurs) ; une source qui disparaît "
            "= service arrêté ou collecte (Alloy) en panne.")
ALL_DESC = ("Lignes brutes, les plus récentes en haut. Filtrer avec les variables host, "
            "source et recherche ; cliquer une ligne pour voir ses labels.")
VAR_HOST_DESC = "Machines de la partie (multi-sélection)."


# =========================================================================== #
# 1. Logs - WAF et sécurité
# =========================================================================== #
def build_waf():
    ID.n = 0
    WAF = '{host="waf01", container="resilience-waf"}'
    ACCESS = WAF + ' |= `"event_type"` | json | __error__=""'
    AUDIT = WAF + ' |= `{"transaction"`'
    BAN = '{host="waf01", identifier="waf-ban"}'
    SSH = '{host=~"$host", identifier=~"sshd|sshd-session"}'
    SSH_FAIL = (r'Failed |Invalid user|authentication failure|Connection closed by '
                r'(authenticating|invalid) user|maximum authentication|Unable to negotiate|'
                r'banner exchange|Did not receive identification')
    SEL = '{host=~"$host", identifier=~"$source"}'
    NOISE = (' != `buffered to a temporary file`'     # nginx : grosse réponse mise en tampon
             ' != `syslogin_perform_logout`')         # sshd dans les LXC : bruit connu
    p, y = [], 0

    p.append(row("En un coup d'œil", y)); y += 1
    p += [
        stat("Lignes de logs", count(SEL + RECH), (0, y, 4, 4),
             desc="Lignes reçues sur la période pour les machines et sources sélectionnées."),
        stat("Erreurs", count(SEL + NOISE + f' |~ `{ERR}`' + RECH), (4, y, 4, 4),
             desc="Lignes contenant un mot-clé d'erreur (y compris les refus ModSecurity "
                  "« Access denied »). Bruit exclu : réponses nginx mises en tampon, "
                  "« syslogin_perform_logout » des LXC.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 50))),
        stat("Avertissements", count(SEL + NOISE + f' |~ `{WARN}`' + RECH), (8, y, 4, 4),
             desc="Lignes contenant « warn » (hors bruit nginx « buffered to a temporary file »).",
             thresholds=steps(("green", None), ("orange", 1))),
        stat("Requêtes bloquées (403)", count(ACCESS + ' | status="403"'), (12, y, 4, 4),
             desc="Réponses 403 du WAF (ModSecurity, ou IP déjà bannie) sur la période. "
                  "Plus de 10 en 2 min depuis une même IP déclenche le bannissement automatique.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 10))),
        stat("IP bannies", count(BAN + ' |~ `^ban ip=`'), (16, y, 4, 4),
             desc="Bannissements posés par le récepteur waf-ban sur waf01 (alerte Loki -> "
                  "Alertmanager -> waf-ban, 15 min). Détail dans « Événements clés ».",
             thresholds=steps(("green", None), ("red", 1))),
        stat("Échecs SSH", count(SSH + f' |~ `{SSH_FAIL}`'), (20, y, 4, 4),
             desc="Tentatives SSH refusées (utilisateur inconnu, mauvaise clé ou mot de passe) "
                  "sur les machines sélectionnées.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 10))),
    ]
    y += 4
    p.append(bars("Volume de logs par source",
                  [tgt(f"sum by (identifier) (count_over_time({SEL}{RECH} [$__interval]))",
                       "{{identifier}}")], (0, y, 24, 7), desc=VOL_DESC))
    y += 7

    p.append(row("Erreurs et avertissements", y)); y += 1
    p.append(logs("Erreurs et avertissements",
                  SEL + NOISE + f' |~ `{ERR}|{WARN}`' + RECH
                  + ' | line_format `{{.host}} · {{.identifier}} · {{ __line__ }}`',
                  (0, y, 24, 9),
                  desc="Lignes d'erreur ou d'avertissement des sources sélectionnées. Les "
                       "« ModSecurity: Access denied with code 403 » sont les attaques bloquées "
                       "(règle et IP client dans la ligne). Bruit exclu : « buffered to a "
                       "temporary file » (nginx), « syslogin_perform_logout » (sshd en LXC)."))
    y += 9

    p.append(row("Événements clés", y)); y += 1
    p += [
        logs("Bannissements au WAF (waf-ban)",
             BAN + ' | regexp `^(?P<action>[a-z_]+)` | logfmt | line_format `'
             '{{ if eq .action "ban" }}IP BANNIE   {{.ip}}   raison {{.raison}}, '
             '{{.duree_s}} s, jusqu\'à {{.expire}} (actifs : {{.actifs}})'
             '{{ else if eq .action "expiration" }}LIBÉRÉE     {{.ip}}   fin du bannissement '
             '(actifs : {{.actifs}})'
             '{{ else if eq .action "unban" }}DÉBANNIE    {{.ip}}   levée manuelle'
             '{{ else }}{{ __line__ }}{{ end }}`',
             (0, y, 12, 8),
             time_from="24h", desc="Journal du récepteur waf-ban de waf01 : IP bannie (raison = nom de l'alerte "
                  "Loki : WafSourceAttacks, WafSourceFlood, WafSourceBruteForce), libérée à "
                  "l'expiration (15 min) ou débannie à la main (sudo waf-ban unban <ip>)."),
        count_table("Règles ModSecurity déclenchées",
                    f'topk(15, sum by (rule_id, rule_msg, http_code) (count_over_time({AUDIT}'
                    r' | regexp `"http_code":(?P<http_code>\d+).*?"message":"(?P<rule_msg>[^"]*)".*?"ruleId":"(?P<rule_id>\d+)"`'
                    ' [$__range])))',
                    (12, y, 12, 8),
                    [("rule_id", "Règle"), ("rule_msg", "Description"),
                     ("http_code", "Réponse")], "Requêtes",
                    time_from="24h", desc="Journal d'audit ModSecurity : première règle OWASP CRS déclenchée "
                         "par requête (930130 = accès à un fichier sensible, 942100 = injection "
                         "SQL, 920350 = Host en adresse IP...). Réponse 403 = bloquée ; 200 = "
                         "simplement signalée (score sous le seuil)."),
    ]
    y += 8
    p += [
        count_table("IP bloquées (403)",
                    f'topk(10, sum by (source_ip) (count_over_time({ACCESS} | status="403" '
                    '[$__range])))', (0, y, 8, 8), [("source_ip", "IP source")], "Requêtes 403",
                    time_from="24h", desc="IP réelles des clients (vues par waf01 derrière NPM) ayant reçu des "
                         "403. Une IP en tête de liste avec beaucoup de 403 = scanner ou "
                         "attaquant ; elle est bannie automatiquement au-delà de 10 en 2 min."),
        count_table("Top IP clientes", f'topk(10, sum by (source_ip) (count_over_time({ACCESS}'
                    ' | event_type="http_access" [$__range])))', (8, y, 8, 8),
                    [("source_ip", "IP source")], "Requêtes",
                    desc="Clients les plus actifs sur la période (toutes réponses). La sonde et "
                         "les tests depuis le poste de contrôle (10.0.1.110) y figurent."),
        bars("Réponses du WAF par code HTTP",
             [tgt(f'sum by (status) (count_over_time({ACCESS} | event_type=~"http_access|waf_banned"'
                  ' [$__interval]))', "{{status}}")], (16, y, 8, 8),
             desc="Codes HTTP renvoyés par le WAF. 403 = bloqué (ModSecurity ou IP bannie), "
                  "401/422 = refus applicatif (connexion), 413 = corps trop gros, 5xx = "
                  "application derrière la VIP indisponible.",
             overrides=[{"matcher": {"id": "byName", "options": "403"},
                         "properties": [{"id": "color", "value": {"mode": "fixed",
                                                                  "fixedColor": "red"}}]},
                        {"matcher": {"id": "byName", "options": "200"},
                         "properties": [{"id": "color", "value": {"mode": "fixed",
                                                                  "fixedColor": "green"}}]}]),
    ]
    y += 8
    p += [
        logs("Refus SSH (toutes machines)",
             SSH + f' |~ `{SSH_FAIL}`' + RECH + ' | line_format `{{.host}} · {{ __line__ }}`',
             (0, y, 12, 8),
             time_from="24h", desc="Connexions SSH refusées : utilisateur inexistant, clé ou mot de passe faux, "
                  "négociation impossible. Les machines n'acceptent que des clés ; une rafale "
                  "ici = balayage ou attaque par force brute."),
        count_table("Connexions SSH acceptées",
                    f'sum by (host, user, from) (count_over_time({SSH} |~ `^Accepted`'
                    ' | pattern `Accepted <method> for <user> from <from> port <_>` [$__range]))',
                    (12, y, 12, 8), [("host", "Machine"), ("user", "Utilisateur"),
                                     ("from", "Depuis")], "Connexions",
                    desc="Connexions SSH réussies par machine, compte et adresse d'origine. "
                         "Attendu : root/debian depuis le poste de contrôle 10.0.1.110 "
                         "(Ansible) et les VPN d'administration (10.10.0.0/24, 10.250.90.0/24)."),
    ]
    y += 8

    p.append(row("Tous les logs", y)); y += 1
    p += [
        logs("WAF : accès et blocages (resilience-waf)",
             WAF + RECH + ' | json | line_format `{{ if .event_type }}{{.status}}  {{.method}} '
             '{{.route}}  ← {{.source_ip}}  ({{.duration_s}} s){{ if eq .event_type "waf_banned" }}'
             '  [IP bannie]{{ end }}{{ else }}{{ __line__ }}{{ end }}`',
             (0, y, 12, 12),
             desc="Journal du conteneur resilience-waf (nginx + ModSecurity). Lignes d'accès "
                  "reformatées : code HTTP, méthode, route, IP client, durée. Les autres lignes "
                  "(erreurs nginx, audit ModSecurity) sont affichées brutes."),
        logs("Toutes les sources sélectionnées",
             SEL + RECH + ' | line_format `{{.host}} · {{.identifier}} · {{ __line__ }}`',
             (12, y, 12, 12), desc=ALL_DESC),
    ]

    variables = [
        custom_var("host", "Machine", [(h, h) for h in HOSTS_ALL],
                   desc="waf01 pour le WAF ; toutes les machines pour SSH."),
        custom_var("source", "Source",
                   [("WAF (nginx + ModSecurity)", "resilience-waf"),
                    ("Bannissement (waf-ban)", "waf-ban"),
                    ("SSH (démon)", "sshd"), ("SSH (sessions)", "sshd-session")],
                   desc="Label identifier du journal."),
        textbox(),
    ]
    return dashboard(
        "logs-waf", "Logs - WAF et sécurité",
        "Logs du WAF (waf01 : nginx + ModSecurity OWASP CRS), du bannissement automatique "
        "(waf-ban) et des connexions SSH de toutes les machines.",
        p, variables,
        dash_links(("Cyber (équipe cyber)", "resilience-cyber",
                    "Dashboard de l'équipe cyber : WAF, attaques, bannissements"),
                   ("Vue centrale", "central", "Plateforme - vue centrale")),
        ("waf", "securite"))


# =========================================================================== #
# 2. Logs - Assistant IA (rag01)
# =========================================================================== #
def build_assistant():
    ID.n = 0
    # Pseudo Discord retiré de toutes les lignes (rag-api et discord-bot l'écrivent)
    MASK = ' | line_format `{{ regexReplaceAll "utilisateur=.*? statut=" __line__ "statut=" }}`'
    SEL = '{host=~"$host", unit=~"$source"}' + MASK
    API_Q = '{host="rag01", unit="rag-api.service"} |= "question "'
    BOT_Q = '{host="rag01", unit="discord-bot.service"} |= "question "'
    MCP = '{host="rag01", unit="rag-mcp.service"} |= "outil="'
    NOISE = (' != `LangChainDeprecationWarning` != `db = Chroma(`'   # avertissement LangChain
             ' != `invalid option provided`')                       # options Ollama ignorées
    ERR_RAG = ERR[:-1] + r"|statut=(delai|http_|erreur|echec))"
    p, y = [], 0

    p.append(row("En un coup d'œil", y)); y += 1
    p += [
        stat("Lignes de logs", count(SEL + RECH), (0, y, 4, 4),
             desc="Lignes reçues de rag01 pour les sources sélectionnées (l'indexation "
                  "Ollama en produit beaucoup pendant une resynchronisation)."),
        stat("Erreurs", count(SEL + NOISE + f' |~ `{ERR_RAG}`' + RECH), (4, y, 4, 4),
             desc="Lignes d'erreur, y compris les questions en échec (statut=delai_depasse, "
                  "http_504). Bruit exclu : avertissement de dépréciation LangChain, "
                  "« invalid option provided » d'Ollama.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 20))),
        stat("Avertissements", count(SEL + NOISE + f' |~ `{WARN}`' + RECH), (8, y, 4, 4),
             desc="Lignes contenant « warn » (hors bruit cité dans « Erreurs »).",
             thresholds=steps(("green", None), ("orange", 1))),
        stat("Questions reçues (API)", count(API_Q), (12, y, 4, 4),
             desc="Questions traitées par l'API rag-api (POST /ask), qu'elles viennent du bot "
                  "Discord ou d'un appel direct."),
        stat("dont via Discord", count(BOT_Q), (16, y, 4, 4),
             desc="Questions posées dans le salon #assistance-rag (bot Qwen-RAG-Bot)."),
        stat("Durée moyenne d'une réponse",
             f'avg(avg_over_time({API_Q} | regexp `duree=(?P<duree>[0-9.]+)s` | unwrap duree'
             ' | __error__="" [$__range]))', (20, y, 4, 4), unit="s", no_value="Aucune question sur la période",
             desc="Temps moyen de réponse de l'API (recherche documentaire + modèle + outils "
                  "MCP). Au-delà de 60 s, l'utilisateur Discord attend beaucoup.",
             thresholds=steps(("green", None), ("orange", 30), ("red", 60))),
    ]
    y += 4
    p.append(bars("Volume de logs par service",
                  [tgt(f"sum by (unit) (count_over_time({SEL}{RECH} [$__interval]))",
                       "{{unit}}")], (0, y, 24, 7), desc=VOL_DESC))
    y += 7

    p.append(row("Erreurs et avertissements", y)); y += 1
    p.append(logs("Erreurs et avertissements",
                  SEL + NOISE + f' |~ `{ERR_RAG}|{WARN}`' + RECH
                  + ' | line_format `{{.unit}} · {{ __line__ }}`', (0, y, 24, 9),
                  desc="Erreurs des services de l'assistant. statut=delai_depasse / http_504 : "
                       "réponse non obtenue en 120 s (modèle trop lent ou GPU absent). "
                       "Bruit exclu : dépréciation LangChain (Chroma), « invalid option "
                       "provided » d'Ollama (options mirostat/tfs_z ignorées)."))
    y += 9

    p.append(row("Événements clés", y)); y += 1
    p += [
        logs("Questions reçues (sans auteur)",
             API_Q + r' | regexp `statut=(?P<statut>\S+) mode=(?P<mode>\S+) outils=(?P<outils>\S+) duree=(?P<duree>\S+)`'
             ' | line_format `{{ if eq .statut "ok" }}OK     {{ else }}ÉCHEC  {{ end }}'
             '{{.duree}}  mode {{.mode}}  outils : {{.outils}}{{ if ne .statut "ok" }}'
             '  ({{.statut}}){{ end }}`',
             (0, y, 12, 9),
             time_from="24h", desc="Une ligne par question traitée par l'API : statut, durée, mode (agent = avec "
                  "outils de supervision, documentation = recherche dans le corpus seule) et "
                  "outils MCP appelés. Le texte de la question et le pseudo Discord ne sont "
                  "pas affichés."),
        points("Durée des réponses",
               [tgt(f'max_over_time({API_Q} | regexp `duree=(?P<duree>[0-9.]+)s` | unwrap duree'
                    ' | __error__="" [$__interval])', "API rag-api"),
                tgt(f'max_over_time({BOT_Q} | regexp `total=(?P<total>[0-9.]+)s` | unwrap total'
                    ' | __error__="" [$__interval])', "Discord (de bout en bout)", ref="B")],
               (12, y, 12, 9),
               time_from="24h", desc="Un point par question : durée côté API et durée totale vue par le bot "
                    "Discord. Les réponses longues (> 60 s) enchaînent plusieurs outils MCP ou "
                    "tournent sur le CPU (tunnel GPU absent)."),
    ]
    y += 9
    p += [
        count_table("Outils MCP appelés",
                    f'sum by (outil, statut) (count_over_time({MCP}'
                    r' | regexp `outil=(?P<outil>\S+) .*statut=(?P<statut>\S+)` [$__range]))',
                    (0, y, 8, 8), [("outil", "Outil"), ("statut", "Statut")], "Appels",
                    time_from="24h", desc="Outils du serveur MCP « supervision » (lecture seule : métriques, "
                         "alertes, IP bannies...) appelés par l'agent pour répondre."),
        logs("Tunnel GPU et chargements de modèle", "",
             (8, y, 16, 8),
             targets=[
                 tgt('{host="rag01", identifier=~"sshd|sshd-session"} |= `gpu-tunnel`'
                     ' |~ `Accepted|session closed|Timeout|Disconnected`'
                     ' | line_format `TUNNEL GPU   {{ __line__ }}`'),
                 tgt('{host="rag01", unit="ollama.service"}'
                     r' |~ `msg="(loading model|starting llama-server|llama runner started)`'
                     ' | logfmt | line_format `OLLAMA       {{.msg}}`', ref="B")],
             time_from="24h", desc="Connexion / déconnexion du tunnel SSH du PC GPU de Rémi (utilisateur "
                  "gpu-tunnel) : tant qu'il est connecté, le relais nginx 127.0.0.1:11430 envoie "
                  "les requêtes au GPU ; sinon il bascule sur le CPU de rag01. Lignes OLLAMA : "
                  "chargement d'un modèle en mémoire (premier appel, ~45 s)."),
    ]
    y += 8
    p.append(bars("Appels au modèle Ollama par point d'entrée",
                  [tgt('sum by (path) (count_over_time({host="rag01", unit=~"ollama.service|ollama-index.service"}'
                       r' |= `[GIN]` | regexp `\| (?P<code>\d{3}) \|.*"(?P<path>/api/[a-z]+)"` [$__interval]))',
                       "{{path}}")], (0, y, 24, 6),
                  time_from="24h", desc="Requêtes HTTP reçues par Ollama : /api/embed = calcul d'embeddings "
                       "(indexation ou recherche), /api/generate et /api/chat = génération de "
                       "réponse, /api/tags = liste des modèles (contrôle de santé)."))
    y += 6

    p.append(row("Tous les logs", y)); y += 1
    p += [
        logs("API RAG, bot Discord et MCP (pseudo masqué)",
             '{host=~"$host", unit=~"rag-api.service|discord-bot.service|rag-mcp.service|rag-docs-sync.service"}'
             + MASK + RECH + ' | line_format `{{.unit}} · {{ __line__ }}`', (0, y, 12, 12),
             desc="Journaux applicatifs de l'assistant. Le pseudo Discord de l'auteur est "
                  "retiré de chaque ligne."),
        logs("Toutes les sources sélectionnées",
             SEL + RECH + ' | line_format `{{.unit}} · {{ __line__ }}`', (12, y, 12, 12),
             desc=ALL_DESC + " Le pseudo Discord est retiré de chaque ligne."),
    ]

    variables = [
        custom_var("host", "Machine", [("rag01", "rag01")], desc=VAR_HOST_DESC),
        custom_var("source", "Service",
                   [("Ollama (modèles)", "ollama.service"),
                    ("Ollama (indexation)", "ollama-index.service"),
                    ("API RAG", "rag-api.service"),
                    ("Serveur MCP", "rag-mcp.service"),
                    ("Bot Discord", "discord-bot.service"),
                    ("Synchro du corpus", "rag-docs-sync.service"),
                    ("Relais nginx GPU-CPU", "nginx.service"),
                    ("Interface web (désactivée)", "rag-assistant.service")],
                   desc="Unité systemd de rag01."),
        textbox(),
    ]
    return dashboard(
        "logs-assistant", "Logs - Assistant IA (rag01)",
        "Logs de l'assistant IA sur rag01 : Ollama, API RAG, serveur MCP de supervision, bot "
        "Discord, relais GPU/CPU. Le pseudo Discord des auteurs n'est jamais affiché.",
        p, variables,
        dash_links(("Vue centrale", "central", "Plateforme - vue centrale")),
        ("assistant", "rag"))


# =========================================================================== #
# 3. Logs - Supervision
# =========================================================================== #
def build_supervision():
    ID.n = 0
    SEL = ('{host=~"$host", identifier=~"loki|grafana|prometheus-alertmanager|vmalert|'
           'victoria-metrics|vmauth|vmagent|monitoring_vmagent.*|pve_exporter|alloy-wrapper"}'
           + SRC + ' | src=~"$source"')
    NOTIF = ('{job="alertmanager-notify"} |= `"body":` | json body | line_format `{{.body}}`'
             ' | json status, receiver, alertname="alerts[0].labels.alertname",'
             ' severity="alerts[0].labels.severity", summary="alerts[0].annotations.summary"')
    WARN_SUP = r"level=warn|	warn	"
    COLLECT = ('{host=~"$host", identifier=~"vmagent|monitoring_vmagent.*|alloy-wrapper|vmalert"}'
               r" |~ `cannot scrape|couldn't send|cannot send|error in .* lookup|failed to execute|level=(error|warn)`")
    STRIP = r' | line_format `{{.host}} · {{ regexReplaceAll "^\\S+\\t\\w+\\t\\S+\\t" __line__ "" }}`'
    SUP_UNITS = ("loki|grafana|prometheus-alertmanager|vmalert|victoria-metrics|vmauth|"
                 "vmagent|alloy|pve-exporter")
    p, y = [], 0

    p.append(row("En un coup d'œil", y)); y += 1
    p += [
        stat("Lignes de logs", count(SEL + RECH), (0, y, 4, 4),
             desc="Lignes reçues pour les sources sélectionnées. Loki journalise chacune de ses "
                  "requêtes : c'est la source la plus bavarde."),
        stat("Erreurs", count(SEL + f' |~ `{ERR_SUP}`' + RECH), (4, y, 4, 4),
             desc="Lignes de niveau error/fatal (format level=... ou tabulé de VictoriaMetrics), "
                  "cibles injoignables et échecs d'envoi (remote write).",
             thresholds=steps(("green", None), ("orange", 1), ("red", 50))),
        stat("Avertissements", count(SEL + f' |~ `{WARN_SUP}`' + RECH), (8, y, 4, 4),
             desc="Lignes de niveau warn.", thresholds=steps(("green", None), ("orange", 1))),
        stat("Notifications envoyées", count(NOTIF + ' | __error__=""'), (12, y, 4, 4),
             desc="Notifications d'alerte envoyées par Alertmanager vers Discord (déclenchées "
                  "et résolues), lues dans le journal de notification de monitoring01.",
             thresholds=steps(("blue", None))),
        stat("Alertes déclenchées",
             count(NOTIF + ' | __error__="" | status="firing"'), (16, y, 4, 4),
             desc="Notifications « firing » sur la période (une alerte qui reste active n'est "
                  "renotifiée qu'après le délai de répétition d'Alertmanager).",
             thresholds=steps(("green", None), ("orange", 1))),
        stat("Erreurs de collecte", count(COLLECT), (20, y, 4, 4),
             desc="Cibles que vmagent n'a pas pu interroger, blocs non envoyés à "
                  "VictoriaMetrics, erreurs de découverte DNS du vmagent du Swarm, règles "
                  "vmalert en échec.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 50))),
    ]
    y += 4
    p.append(bars("Volume de logs par source",
                  [tgt('sum by (src) (count_over_time(' + SEL + RECH
                       + ' [$__interval]))', "{{src}}")], (0, y, 24, 7), desc=VOL_DESC))
    y += 7

    p.append(row("Erreurs et avertissements", y)); y += 1
    p.append(logs("Erreurs et avertissements",
                  SEL + f' |~ `{ERR_SUP}|{WARN_SUP}`' + RECH
                  + ' | line_format `{{.host}} · {{.src}} · {{ __line__ }}`',
                  (0, y, 24, 9),
                  desc="Erreurs et avertissements des composants de supervision. À savoir : "
                       "« error notifying scheduler » de Loki et « context canceled » de Grafana "
                       "= requête annulée par le navigateur (bénin) ; « cannot scrape target » = "
                       "machine ou exportateur injoignable (souvent pendant un test de chaos)."))
    y += 9

    p.append(row("Événements clés", y)); y += 1
    p += [
        logs("Notifications d'alerte (Discord)",
             NOTIF + ' | __error__=""' + RECH + ' | line_format `{{ if eq .status "firing" }}'
             'DÉCLENCHÉE{{ else }}RÉSOLUE   {{ end }}  {{.alertname}}  ({{.severity}})  '
             '→ {{.receiver}} : {{.summary}}`',
             (0, y, 14, 9),
             time_from="24h", desc="Chaque notification envoyée par Alertmanager : statut, nom de l'alerte, "
                  "gravité, destinataire et résumé. L'URL du webhook Discord n'est pas dans ce "
                  "journal. Si plusieurs alertes sont groupées, seule la première est nommée."),
        count_table("Notifications par alerte",
                    f'sum by (alertname, severity, status) (count_over_time({NOTIF}'
                    ' | __error__="" [$__range]))', (14, y, 10, 9),
                    [("alertname", "Alerte"), ("severity", "Gravité"), ("status", "Statut")],
                    "Notifications",
                    time_from="24h", desc="Nombre de notifications par alerte et par statut (firing = "
                         "déclenchée, resolved = résolue)."),
    ]
    y += 9
    p += [
        logs("Erreurs de collecte (vmagent, Alloy, vmalert)", COLLECT + RECH + STRIP,
             (0, y, 14, 8),
             desc="Collecte des métriques : cible injoignable (« cannot scrape target » : "
                  "machine arrêtée ou exportateur tombé), remote write vers VictoriaMetrics en "
                  "échec (« couldn't send a block », renvoyé ensuite), résolution DNS d'un "
                  "service Swarm absent (vmagent du Swarm), règle vmalert non évaluée."),
        count_table("Cibles injoignables (vmagent)",
                    'sum by (cible, job) (count_over_time({host=~"$host", identifier="vmagent"}'
                    ' |= `cannot scrape target`'
                    r' | regexp `\(\{host="(?P<cible>[^"]+)".*?job="(?P<job>[^"]+)"`'
                    ' [$__range]))',
                    (14, y, 10, 8), [("cible", "Machine"), ("job", "Exportateur")], "Échecs",
                    desc="Cibles de collecte en échec sur la période, par machine et "
                         "exportateur (node, cadvisor, docker...). Les deux vmagent "
                         "interrogent les mêmes cibles : chaque échec compte deux fois."),
    ]
    y += 8
    p.append(logs("Démarrages et arrêts des services de supervision",
                  '{host=~"$host", identifier="systemd", unit="init.scope"}'
                  f' |~ `(Started|Stopped|Reloaded|Stopping|Failed|failed) ({SUP_UNITS})`' + RECH
                  + ' | line_format `{{.host}} · {{ __line__ }}`', (0, y, 24, 6),
                  time_from="24h", desc="Redémarrages, rechargements et arrêts de Loki, Grafana, Alertmanager, "
                       "VictoriaMetrics, vmalert, vmauth, vmagent, Alloy (playbook Ansible, "
                       "panne, redémarrage de la machine)."))
    y += 6

    p.append(row("Tous les logs", y)); y += 1
    p.append(logs("Toutes les sources sélectionnées",
                  SEL + RECH + ' | line_format `{{.host}} · {{.src}} · {{ __line__ }}`',
                  (0, y, 24, 12), desc=ALL_DESC))

    variables = [
        custom_var("host", "Machine", [(h, h) for h in HOSTS_ALL],
                   desc="monitoring01 et vmagent01-02 ; Alloy tourne sur toutes les machines, "
                        "le vmagent du Swarm sur un worker."),
        custom_var("source", "Composant",
                   [("Loki", "loki"), ("Grafana", "grafana"),
                    ("Alertmanager", "prometheus-alertmanager"), ("vmalert", "vmalert"),
                    ("VictoriaMetrics", "victoria-metrics"), ("vmauth", "vmauth"),
                    ("vmagent (VM)", "vmagent"), ("vmagent du Swarm", "monitoring_vmagent"),
                    ("Exportateur Proxmox", "pve_exporter"), ("Alloy", "alloy-wrapper")],
                   desc="Label identifier du journal."),
        textbox(),
    ]
    return dashboard(
        "logs-supervision", "Logs - Supervision",
        "Logs de la chaîne de supervision : collecte (Alloy, vmagent), stockage (Loki, "
        "VictoriaMetrics), alertes (vmalert, Alertmanager, notifications Discord) et Grafana.",
        p, variables,
        dash_links(("VictoriaMetrics", "victoriametrics", "Supervision - VictoriaMetrics"),
                   ("vmagent", "vmagent", "Supervision - vmagent"),
                   ("vmalert", "vmalert", "Supervision - vmalert"),
                   ("Vue centrale", "central", "Plateforme - vue centrale")),
        ("supervision",))


# =========================================================================== #
# 4. Logs - Docker Swarm et hôtes
# =========================================================================== #
def build_swarm():
    ID.n = 0
    SEL = ('{host=~"$host", identifier=~"dockerd|containerd|Keepalived.*|ipvsadm-start|'
           'registry_registry.*|cadvisor|monitoring_vmagent.*|kernel|systemd"}'
           + SRC + ' | src=~"$source"')
    # Bruit noyau : paquets de diffusion refusés par le pare-feu, « martian source » du
    # réseau 172.17.1.0/24 ; bruit Docker : sondes UDP de memberlist (gossip du Swarm).
    NOISE = (' != `host_fw drop` !~ `martian source|ll header`'
             ' != `memberlist:` != `is unknown to memberlist`')
    ERR_SW = r"(?i)(error|fail|fatal|panic|oom-kill|out of memory|killed process|fault state|timed_out)"
    WARN_SW = r"(?i)(level=warning|\bwarn)"
    KA = '{host=~"$host", identifier=~"Keepalived.*"}'
    DOCKERD = '{host=~"$host", identifier="dockerd"}'
    SWARM_EV = (r"fatal task error|healthcheck failed|heartbeat to manager|elected leader|"
                r"leadership changed|Could not send KILL|task failed|rejected|node .* (down|unknown)")
    SYS_EV = (r"(?i)out of memory|oom-kill|killed process|Linux version|Reached target .*"
              r"(Shutdown|Reboot)|Startup finished|docker.service: (Main process exited|Failed|"
              r"Scheduled restart)|(Started|Stopped) docker.service|(Started|Stopped) keepalived")
    p, y = [], 0

    p.append(row("En un coup d'œil", y)); y += 1
    p += [
        stat("Lignes de logs", count(SEL + RECH), (0, y, 4, 4),
             desc="Lignes reçues des managers et workers Swarm pour les sources sélectionnées "
                  "(hors conteneurs applicatifs : voir Logs - Paiement / Base / Remédiation)."),
        stat("Erreurs", count(SEL + NOISE + f' |~ `{ERR_SW}`' + RECH), (4, y, 4, 4),
             desc="Lignes d'erreur. Bruit exclu : paquets de diffusion refusés par le pare-feu "
                  "(host_fw drop), « martian source », sondes memberlist du Swarm.",
             thresholds=steps(("green", None), ("orange", 1), ("red", 100))),
        stat("Avertissements", count(SEL + NOISE + f' |~ `{WARN_SW}`' + RECH), (8, y, 4, 4),
             desc="Lignes de niveau warning (hors bruit).",
             thresholds=steps(("green", None), ("orange", 1))),
        stat("Prises de la VIP", count(KA + ' |= `Entering MASTER STATE`'), (12, y, 4, 4),
             desc="Nombre de fois où un worker est devenu porteur de la VIP 10.30.1.200 "
                  "(keepalived MASTER). 0 = pas de bascule sur la période.",
             thresholds=steps(("green", None), ("orange", 1))),
        stat("Tâches Swarm en échec", count(DOCKERD + ' |= `fatal task error`'), (16, y, 4, 4),
             desc="Tâches que le Swarm a dû arrêter ou replanifier (« fatal task error »).",
             thresholds=steps(("green", None), ("orange", 1), ("red", 10))),
        stat("Conteneurs arrêtés",
             count('{host=~"$host", identifier="containerd"} |= `shim disconnected`'),
             (20, y, 4, 4),
             desc="Conteneurs terminés (containerd : « shim disconnected ») : redémarrage, "
                  "replanification, mise à jour d'un service ou test de chaos.",
             thresholds=steps(("blue", None))),
    ]
    y += 4
    p.append(bars("Volume de logs par source",
                  [tgt('sum by (src) (count_over_time(' + SEL + RECH
                       + ' [$__interval]))', "{{src}}")], (0, y, 24, 7), desc=VOL_DESC))
    y += 7

    p.append(row("Erreurs et avertissements", y)); y += 1
    p.append(logs("Erreurs et avertissements",
                  SEL + NOISE + f' |~ `{ERR_SW}|{WARN_SW}`' + RECH
                  + ' | line_format `{{.host}} · {{.src}} · {{ __line__ }}`',
                  (0, y, 24, 9),
                  desc="Erreurs des démons Docker / containerd, de keepalived et du noyau. "
                       "Bruit exclu (voir « Erreurs »). « heartbeat to manager failed » = un "
                       "nœud a perdu le contact avec le leader (gel d'une sauvegarde, panne "
                       "réseau, test de chaos)."))
    y += 9

    p.append(row("Événements clés", y)); y += 1
    p += [
        logs("VIP 10.30.1.200 : changements d'état keepalived",
             KA + r' |~ `Entering (MASTER|BACKUP|FAULT) STATE|VRRP_Script\(.*\) (succeeded|failed|timed_out)|Stopping|Starting|Reload`'
             + RECH + ' | line_format `{{.host}} · {{ __line__ }}`', (0, y, 12, 8),
             time_from="24h", desc="keepalived sur les trois workers : MASTER = porte la VIP 10.30.1.200 "
                  "(entrée de l'application), BACKUP = en attente, FAULT = test local du "
                  "frontal (port 5173) en échec, la VIP part ailleurs."),
        logs("Swarm : tâches en échec, nœuds, élections",
             DOCKERD + f' |~ `{SWARM_EV}`' + RECH
             + ' | logfmt msg, error | line_format `{{.host}} · {{.msg}}{{ if .error }} — '
             '{{.error}}{{ end }}`', (12, y, 12, 8),
             time_from="24h", desc="Événements du démon Docker en mode Swarm : tâche arrêtée/replanifiée "
                  "(fatal task error), perte de contact avec un manager (heartbeat), élection "
                  "d'un nouveau leader Raft, conteneur impossible à tuer."),
    ]
    y += 8
    p += [
        bars("Conteneurs démarrés et arrêtés par machine",
             [tgt('sum by (host) (count_over_time({host=~"$host", identifier="systemd"}'
                  ' |= `libcontainer container` |~ `^Started` [$__interval]))', "démarrés {{host}}"),
              tgt('sum by (host) (count_over_time({host=~"$host", identifier="containerd"}'
                  ' |= `shim disconnected` [$__interval]))', "arrêtés {{host}}", ref="B")],
             (0, y, 12, 8), stack=False,
             overrides=[{"matcher": {"id": "byRegexp", "options": "arrêtés.*"},
                         "properties": [{"id": "custom.transform", "value": "negative-Y"}]}],
             desc="Au-dessus de zéro : conteneurs démarrés (systemd « libcontainer "
                  "container ») ; en dessous : conteneurs terminés (containerd). Une paire "
                  "arrêt/démarrage = tâche relancée ou replanifiée sur cette machine."),
        logs("Système : démarrages, arrêts, OOM",
             '{host=~"$host", identifier=~"kernel|systemd|systemd-shutdown", unit!~"user@.*"}'
             f' |~ `{SYS_EV}`' + RECH + ' | line_format `{{.host}} · {{ __line__ }}`',
             (12, y, 12, 8),
             time_from="24h", desc="Démarrage et arrêt des machines (Startup finished, Reached target "
                  "Shutdown), du démon Docker et de keepalived, et tueur OOM du noyau (« Out "
                  "of memory: Killed process ») s'il intervient. Aucun OOM attendu."),
    ]
    y += 8
    p.append(count_table("Messages d'erreur et d'avertissement du démon Docker",
                         f'topk(15, sum by (msg) (count_over_time({DOCKERD} |~ `level=(error|warning|fatal)`'
                         ' | regexp `msg="(?P<msg>[^"]{0,90})` [$__range])))',
                         (0, y, 24, 7), [("msg", "Message")], "Lignes",
                         desc="Messages warning/error les plus fréquents de dockerd. Les "
                              "« memberlist » (sondes UDP du gossip Swarm) sont fréquents et "
                              "bénins tant que les nœuds restent Ready."))
    y += 7

    p.append(row("Tous les logs", y)); y += 1
    p += [
        logs("Démon Docker, containerd, keepalived",
             '{host=~"$host", identifier=~"dockerd|containerd|Keepalived.*|ipvsadm-start"}' + RECH
             + ' | line_format `{{.host}} · {{.identifier}} · {{ __line__ }}`', (0, y, 12, 12),
             desc="Démons de l'hôte, plus récents en haut."),
        logs("Toutes les sources sélectionnées",
             SEL + RECH + ' | line_format `{{.host}} · {{.src}} · {{ __line__ }}`',
             (12, y, 12, 12), desc=ALL_DESC),
    ]

    variables = [
        custom_var("host", "Machine", [(h, h) for h in HOSTS_SWARM], desc=VAR_HOST_DESC),
        custom_var("source", "Source",
                   [("Démon Docker", "dockerd"), ("containerd", "containerd"),
                    ("keepalived (VRRP)", "Keepalived_vrrp"),
                    ("keepalived (processus)", "Keepalived"), ("ipvsadm", "ipvsadm-start"),
                    ("Registre privé", "registry_registry"), ("cAdvisor", "cadvisor"),
                    ("vmagent du Swarm", "monitoring_vmagent"), ("Noyau", "kernel"),
                    ("systemd", "systemd")],
                   desc="Label identifier du journal (hors conteneurs applicatifs)."),
        textbox(),
    ]
    return dashboard(
        "logs-swarm", "Logs - Docker Swarm et hôtes",
        "Logs des hôtes Docker Swarm (dockermgr01-03, dockerwrk01-03) : démon Docker, "
        "containerd, keepalived (VIP 10.30.1.200), registre privé, cAdvisor, noyau.",
        p, variables,
        dash_links(("Swarm - vue d'ensemble", "swarm-overview", "Docker Swarm - vue d'ensemble"),
                   ("Swarm - conteneurs", "docker-containers", "Docker Swarm - conteneurs"),
                   ("Vue centrale", "central", "Plateforme - vue centrale")),
        ("swarm", "docker"))


# =========================================================================== #
# 5. Logs - Accueil
# =========================================================================== #
PARTS = [
    # (uid, titre, description, [sélecteurs] : les comptages sont additionnés)
    ("paiement", "Application paiement",
     "auth, payment-api, frontend, mailpit",
     ['{stack="paiement", service=~"paiement_(auth|payment-api|frontend|mailpit)"}']),
    ("base", "Base de données",
     "Patroni db1-3, etcd1-3",
     ['{service=~"paiement_(db[1-3]|etcd[1-3])"}']),
    ("remediation", "Détection et remédiation",
     "détecteur, moteur, sonde, passerelle",
     ['{service=~"paiement_(detector|remediation)|probe_transactions"}',
      '{host=~"dockermgr0[1-3]", identifier="remediate"}']),
    ("virtualisation", "Virtualisation",
     "Proxmox et Ceph (ceph01-03)",
     ['{host=~"ceph0[1-3]"}']),
    ("identite", "Identité et secrets",
     "Keycloak, Vault, Vaultwarden",
     ['{host=~"iam01|vault01|vaultwarden01"}']),
    ("controle", "Poste de contrôle",
     "control01 : Ansible, Terraform, sauvegardes",
     [f'{{host="control01", {CLEAN}}}']),
    ("waf", "WAF et sécurité",
     "waf01, waf-ban, SSH",
     ['{identifier=~"resilience-waf|waf-ban|sshd|sshd-session"}']),
    ("assistant", "Assistant IA",
     "rag01 : Ollama, API, bot Discord",
     ['{host="rag01"}']),
    ("supervision", "Supervision",
     "Loki, Grafana, alertes, collecte",
     ['{identifier=~"loki|grafana|prometheus-alertmanager|vmalert|victoria-metrics|vmauth|'
      'vmagent|monitoring_vmagent.*|pve_exporter|alloy-wrapper"}',
      '{job="alertmanager-notify"}'], ERR_SUP),
    ("swarm", "Docker Swarm et hôtes",
     "Docker, keepalived (VIP), noyau",
     ['{host=~"docker(mgr|wrk)0[1-3]", identifier=~"dockerd|containerd|Keepalived.*|'
      'ipvsadm-start|registry_registry.*|cadvisor|monitoring_vmagent.*|kernel|systemd"}']),
]
HOME_NOISE = (' != `buffered to a temporary file` != `syslogin_perform_logout`'
              ' != `LangChainDeprecationWarning` != `invalid option provided`'
              ' != `host_fw drop` != `memberlist`'
              ' != `caller=metrics.go`')  # requêtes journalisées par Loki (texte de la requête)


def sum_sels(sels, pipeline=""):
    parts = [f"(sum(count_over_time({s}{pipeline} [$__range])) or vector(0))" for s in sels]
    return " + ".join(parts)


def build_home():
    ID.n = 0
    p, y = [], 0
    p.append(text("Comment lire ces dashboards", """\
**Logs de RESILIENCE-ALPHA, une page par partie du projet.** Chaque voyant ci-dessous compte les
lignes d'erreur de sa partie sur la période choisie (en haut à droite) et le volume total de logs ;
**cliquer sur un voyant** ouvre le dashboard de la partie, sur la même période.

Dans chaque dashboard « Logs - … », même organisation : *En un coup d'œil* (voyants, volume par
source), *Erreurs et avertissements*, *Événements clés* (ce qui raconte la partie : bascule,
bannissement, alerte…), *Tous les logs*. Trois filtres en haut :
**host** (machines), **source** (service, unité ou conteneur), **recherche** (texte ou expression
régulière, sans tenir compte de la casse : `timeout`, `10\\.0\\.1\\.110`, `403|401`…).
Cliquer une ligne de log affiche ses labels ; le menu « Autres logs » passe d'une partie à l'autre.""",
                  (0, y, 24, 5)))
    y += 5

    p.append(row("Les neuf parties : erreurs sur la période (volume de logs)", y)); y += 1
    for i, (uid, title, sub, sels, *rx) in enumerate(PARTS):  # grille 3 x 3
        err = rx[0] if rx else ERR
        x, yy = (i % 3) * 8, y + (i // 3) * 4
        link = [{"title": f"Ouvrir Logs - {title}",
                 "url": f"/d/logs-{uid}?${{__url_time_range}}", "targetBlank": False}]
        p.append(stat(
            title, None, (x, yy, 8, 4),
            targets=[tgt(sum_sels(sels, HOME_NOISE + f' |~ `{err}`'), "Erreurs", instant=True),
                     tgt(sum_sels(sels), "Lignes", ref="B", instant=True)],
            text_mode="value_and_name", links=link,
            desc=f"{sub}. Erreurs = lignes contenant un mot-clé d'erreur (error, fail, fatal, "
                 "denied, timeout…), bruit connu exclu ; Lignes = volume total. Cliquer pour "
                 f"ouvrir Logs - {title}. Le décompte fin des erreurs (bruit propre à la partie "
                 "retiré) est dans ce dashboard.",
            thresholds=steps(("green", None), ("orange", 1), ("red", 100)),
            overrides=[{"matcher": {"id": "byName", "options": "Lignes"},
                        "properties": [{"id": "color", "value": {"mode": "fixed",
                                                                 "fixedColor": "#5a6f8c"}},
                                       {"id": "unit", "value": "short"}]}]))
    y += 12

    p.append(row("Toutes les machines", y)); y += 1
    p.append(bars("Volume de logs par machine",
                  [tgt(f'sum by (host) (count_over_time({{host=~"$host", {CLEAN}}}{RECH}'
                       ' [$__interval]))', "{{host}}")], (0, y, 24, 8),
                  desc="Lignes de logs par machine et par intervalle, empilées. Un trou = "
                       "machine éteinte ou Alloy arrêté ; un pic = incident, test de chaos, "
                       "attaque ou déploiement."))
    y += 8
    p.append(logs("Dernières erreurs, toutes parties confondues",
                  f'{{host=~"$host", {CLEAN}}}' + HOME_NOISE + f' |~ `{ERR}`' + RECH
                  + ' | line_format `{{.host}} · {{ or .service .container .unit .identifier .job }}'
                  ' · {{ __line__ }}`', (0, y, 24, 12),
                  desc="Lignes d'erreur de toutes les machines, plus récentes en haut "
                       "(préfixe : machine · service). Bruit connu exclu : tampon nginx du WAF, "
                       "déconnexions SSH des LXC, dépréciation LangChain, options Ollama, "
                       "paquets de diffusion refusés par le pare-feu, sondes memberlist du "
                       "Swarm. Ouvrir la partie concernée pour le contexte."))

    links = [{"title": "Parties", "type": "dashboards", "tags": ["logs"], "asDropdown": True,
              "keepTime": True, "includeVars": False, "targetBlank": False,
              "icon": "external link", "tooltip": "", "url": ""},
             {"title": "Vue centrale", "type": "link", "url": "/d/central", "icon": "dashboard",
              "tooltip": "Plateforme - vue centrale (métriques)", "keepTime": True,
              "includeVars": False, "targetBlank": False, "asDropdown": False, "tags": []},
             {"title": "Démo / Remédiation", "type": "link", "url": "/d/demo-remediation",
              "icon": "dashboard", "tooltip": "Écran de la démonstration", "keepTime": True,
              "includeVars": False, "targetBlank": False, "asDropdown": False, "tags": []}]
    variables = [custom_var("host", "Machine", [(h, h) for h in HOSTS_ALL],
                            desc="Filtre l'histogramme et les dernières erreurs."),
                 textbox()]
    return dashboard(
        "logs-accueil", "Logs - Accueil",
        "Page d'entrée des logs (Loki) de RESILIENCE-ALPHA : erreurs et volume par partie, "
        "liens vers les neuf dashboards « Logs - … ».",
        p, variables, links, ("accueil",))


if __name__ == "__main__":
    write("logs-waf", build_waf())
    write("logs-assistant", build_assistant())
    write("logs-supervision", build_supervision())
    write("logs-swarm", build_swarm())
    write("logs-accueil", build_home())

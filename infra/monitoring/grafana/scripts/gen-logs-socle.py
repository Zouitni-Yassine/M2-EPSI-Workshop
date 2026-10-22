#!/usr/bin/env python3
"""Génère trois dashboards Grafana de lecture des logs (Loki) du socle de la plateforme :

- logs-virtualisation : « Logs - Virtualisation (Proxmox / Ceph) » (hyperviseurs ceph01-03) ;
- logs-identite       : « Logs - Identité et secrets » (Keycloak, Vault, Vaultwarden) ;
- logs-controle       : « Logs - Sauvegardes et poste de contrôle » (control01, sauvegardes).

Usage (depuis infra/monitoring/grafana) : python3 -B scripts/gen-logs-socle.py [--check FICHIER]
Sortie : dashboards/Logs/logs-{virtualisation,identite,controle}.json
--check écrit en plus la liste des requêtes (variables remplacées) au format de q.py file.

Gabarit commun aux dashboards « Logs - … » : variables host / source / recherche, rangées
« En un coup d'œil », « Erreurs et avertissements », « Événements clés », « Tous les logs ».

Secrets : les journaux de Vaultwarden contiennent le jeton d'accès des clients web
(GET /notifications/hub?access_token=…), ceux de Vault des identifiants de bail, ceux de
Keycloak des identifiants de session, le journal d'audit de Vault des valeurs hachées (HMAC)
de jetons et de secrets, ceux d'Ansible les paramètres des modules. Les panneaux ne montrent
donc jamais une ligne brute de ces sources : masquage par regexReplaceAll (MASKS), champs
choisis du journal d'audit, nom du module seulement pour Ansible, détails des lignes
(étiquettes extraites) désactivés.
"""
import json
import pathlib
import sys

OUTDIR = pathlib.Path(__file__).resolve().parent.parent / "dashboards/Logs"
LOKI = {"type": "loki", "uid": "loki"}

# Mots-clés d'erreur communs aux dashboards « Logs - … » (« echec » : script de sauvegarde)
ERR = (r"(?i)(error|erreur|err=|fail|échec|echec|crit|fatal|panic|denied|refused|timeout|"
       r"traceback|exception|unable|cannot)")
WARN = r"(?i)(\bwarn(ing)?\b|\[warn\])"
SEARCH = ' |~ `(?i)$recherche`'

NO_VALUE = "Aucun événement sur la période (normal hors incident)"
# Panneaux d'événements rares : plage relative propre de 24 h (le lab est éteint la nuit)
RARE = {
    "logs-virtualisation": {
        "Actions HA", "Sauvegardes de VM réussies", "Sauvegardes de VM en échec",
        "Erreurs et avertissements des hyperviseurs", "Haute disponibilité : actions sur les VM",
        "Cluster : quorum corosync et pmxcfs", "Sauvegardes vzdump vers le PBS",
        "Ceph : OSD, moniteurs, gestionnaire", "Connexions à l'interface Proxmox",
        "Connexions par utilisateur"},
    "logs-identite": {
        "Connexions SSO réussies", "Connexions refusées", "Refus Vault",
        "Erreurs et avertissements (Keycloak, Vault, Vaultwarden, PostgreSQL)",
        "Keycloak : connexions SSO (realm epsi)", "Keycloak : connexions par utilisateur",
        "Vault : scellement, descellement, leader", "Vaultwarden : connexions",
        "PostgreSQL de Keycloak (iam01, fichier)"},
    "logs-controle": {
        "Erreurs", "Échecs de sauvegarde", "Sauvegardes de VM réussies",
        "Erreurs et avertissements", "Sauvegardes vzdump des VM vers le PBS"},
}

# Masquage : clé=valeur (valeur entre guillemets ou jusqu'au prochain séparateur)
MASK_KEYS = ["access_token", "refresh_token", "id_token", "client_secret", "password",
             "passwd", "secret", "token", "otp", "totp", "code", "code_id", "token_id",
             "refresh_token_id", "updated_refresh_token_id", "sessionId", "session_state", "lease_id", "accessor",
             "client_token", "secret_id", "role_id"]
MASKS = ([(r"\b%s=(\"[^\"]*\"|[^ &,\"]+)" % k, "%s=***" % k) for k in MASK_KEYS]
         + [(r"(?i)bearer [A-Za-z0-9._~+/=-]+", "Bearer ***"),
            (r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.?[A-Za-z0-9_-]*", "***jwt***"),
            (r"hvs\.[A-Za-z0-9_-]+", "hvs.***"),
            (r"hmac-sha256:[0-9a-f]+", "hmac-sha256:***"),
            # identifiant de jeton d'API Proxmox (utilisateur!jeton) : seul l'utilisateur reste
            (r"@pve![^ \[]+", "@pve!(jeton)"), (r"@pam![^ \[]+", "@pam!(jeton)")])


def go_str(s):
    """Chaîne Go entre guillemets (dans une chaîne LogQL entre accents graves)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def masked(src="__line__", masks=MASKS):
    for rx, repl in masks:
        src = f"(regexReplaceAll {go_str(rx)} {src} {go_str(repl)})"
    return src


def fmt(template):
    return f" | line_format `{template}`"


def fmt_masked(prefix="{{.host}} "):
    return fmt(prefix + "{{ " + masked()[1:-1] + " }}")


# --------------------------------------------------------------------------- #
# Briques de base (mêmes conventions que gen-demo-dashboard.py)
# --------------------------------------------------------------------------- #
CHECKS = []          # (titre, requête) pour --check
SUBST = {}           # variables du dashboard en cours -> valeurs de test


def tgt(expr, legend="", ref="A", instant=False, title=""):
    test = expr
    for k, v in SUBST.items():
        test = test.replace(k, v)
    CHECKS.append((title, test))
    return {"datasource": LOKI, "refId": ref, "expr": expr, "legendFormat": legend,
            "editorMode": "code", "queryType": "instant" if instant else "range"}


def steps(*pairs):
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in pairs]}


class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return self.n


def panel(ids, ptype, title, targets, pos, *, unit=None, thresholds=None, options=None,
          custom=None, overrides=None, desc="", decimals=None, color=None,
          transformations=None, interval=None, no_value=None):
    x, y, w, h = pos
    defaults = {"mappings": [], "thresholds": thresholds or steps(("green", None))}
    if no_value is None:
        no_value = NO_VALUE
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


def row(ids, title, y):
    return {"id": ids(), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def stat(ids, title, expr, pos, desc, thresholds=None, unit="short"):
    opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background", "graphMode": "none", "justifyMode": "center",
            "textMode": "value", "orientation": "auto", "wideLayout": True,
            "showPercentChange": False, "text": {}}
    return panel(ids, "stat", title, [tgt(expr, instant=True, title=title)], pos,
                 options=opts, desc=desc, unit=unit, decimals=0, no_value="0",
                 thresholds=thresholds or steps(("blue", None)))


def volume(ids, title, expr, legend, pos, desc):
    custom = {"drawStyle": "bars", "lineWidth": 1, "fillOpacity": 80,
              "gradientMode": "none", "showPoints": "never", "spanNulls": False,
              "axisSoftMin": 0, "barAlignment": 0,
              "stacking": {"mode": "normal", "group": "A"}}
    opts = {"legend": {"displayMode": "list", "placement": "right", "showLegend": True,
                       "calcs": []},
            "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel(ids, "timeseries", title, [tgt(expr, legend, title=title)], pos,
                 custom=custom, options=opts, desc=desc, unit="short",
                 color={"mode": "palette-classic"})


def logs(ids, title, exprs, pos, desc, order="Descending", dedup="none"):
    opts = {"showTime": True, "showLabels": False, "showCommonLabels": False,
            "wrapLogMessage": True, "prettifyLogMessage": False,
            # détails désactivés : ils afficheraient les étiquettes extraites (json, regexp)
            "enableLogDetails": False, "enableInfiniteScrolling": False,
            "dedupStrategy": dedup, "sortOrder": order}
    if isinstance(exprs, str):
        exprs = [exprs]
    targets = [tgt(e, ref=chr(65 + i), title=title) for i, e in enumerate(exprs)]
    return panel(ids, "logs", title, targets, pos, options=opts, desc=desc)


def table(ids, title, expr, pos, desc, rename, order):
    """Comptage instantané (Loki) présenté en tableau : une ligne par combinaison d'étiquettes."""
    excl = {"Time": True}
    return panel(ids, "table", title, [tgt(expr, instant=True, title=title)], pos, desc=desc,
                 custom={"align": "auto", "cellOptions": {"type": "auto"}, "inspect": False},
                 options={"showHeader": True, "cellHeight": "sm",
                          "sortBy": [{"displayName": rename.get("Value", "Value"),
                                      "desc": True}],
                          "footer": {"show": False, "reducer": ["sum"], "fields": ""}},
                 transformations=[
                     {"id": "labelsToFields", "options": {}},
                     {"id": "merge", "options": {}},
                     {"id": "organize", "options": {
                         "excludeByName": excl,
                         "indexByName": {k: i for i, k in enumerate(order)},
                         "renameByName": rename}}])


def custom_var(name, label, values):
    opts = [{"selected": True, "text": "All", "value": "$__all"}] + [
        {"selected": False, "text": v, "value": v} for v in values]
    return {"name": name, "label": label, "type": "custom", "query": ",".join(values),
            "multi": True, "includeAll": True, "options": opts, "hide": 0,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}}


def loki_label_var(name, label, lbl, stream, regex, desc):
    return {"name": name, "label": label, "type": "query", "datasource": LOKI,
            "description": desc,
            "query": {"type": 1, "label": lbl, "stream": stream,
                      "refId": "LokiVariableQueryEditor-VariableQuery"},
            "definition": f"label_values({stream},{lbl})", "regex": regex,
            "refresh": 2, "includeAll": True, "multi": True, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]},
            "options": [], "hide": 0}


def text_var():
    return {"name": "recherche", "label": "Recherche (texte ou regex)", "type": "textbox",
            "query": "", "current": {"selected": False, "text": "", "value": ""},
            "options": [{"selected": True, "text": "", "value": ""}], "hide": 0,
            "description": "Filtre appliqué à tous les panneaux de logs, sans distinction de "
                           "casse (expression régulière). Vide = tout."}


def links(metrics):
    base = [("Accueil des logs", "logs-accueil", "Page d'accueil des dashboards de logs")]
    return [{"title": t, "type": "link", "url": f"/d/{u}", "icon": "dashboard",
             "keepTime": True, "includeVars": False, "targetBlank": False,
             "asDropdown": False, "tags": [], "tooltip": tip}
            for t, u, tip in base + metrics]


def dashboard(uid, title, desc, panels, variables, metric_links):
    return {
        "id": None, "uid": uid, "title": title, "description": desc,
        "tags": ["logs"], "timezone": "browser", "editable": False, "graphTooltip": 1,
        "refresh": "30s", "time": {"from": "now-1h", "to": "now"},
        "timepicker": {"refresh_intervals": ["10s", "30s", "1m", "5m", "15m"]},
        "fiscalYearStartMonth": 0, "liveNow": False, "schemaVersion": 39, "version": 1,
        "links": links(metric_links),
        "annotations": {"list": [
            {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
             "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
             "name": "Annotations & Alerts", "type": "dashboard"}]},
        "templating": {"list": variables},
        "panels": panels,
    }


def write(name, dash):
    for p in dash["panels"]:
        if p["type"] != "row" and p["title"] in RARE.get(name, ()):
            p["timeFrom"] = "24h"
            p["title"] += " (24 h)"
            p["description"] += (" Plage fixe des dernières 24 h (événements rares : souvent "
                                 "aucun sur 1 h).")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / f"{name}.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dash, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out)
    print(f"{out} : {len(dash['panels'])} panneaux")


# Requête partagée : sauvegardes vzdump (planifiées : pvescheduler ; manuelles : pvedaemon ;
# en ligne de commande : session SSH) vues dans le journal des hyperviseurs
VZDUMP = ('{host=~"$host", job="journal"} |~ `(Starting|Finished) Backup of (VM|CT)|Backup of '
          '(VM|CT) [0-9]+ failed|Backup job finished|starting new backup job|ERROR: Backup`'
          + SEARCH
          + fmt('{{.host}}  {{ regexReplaceAll " --.*$" (regexReplaceAll "^(INFO|ERROR): " '
                '__line__ "") "" }}'))
VZDUMP_DESC = ("Sauvegardes des VM et conteneurs vers le PBS (workshop-local-pbs) : début du job "
               "(liste des VM), début et fin de chaque VM avec sa durée (hh:mm:ss), erreurs "
               "« Backup of VM … failed » et fin du job. Jobs planifiés 13h00 et 21h00 (heure de "
               "Paris) ; une sauvegarde gèle chaque VM environ 45 s. La taille transférée n'est "
               "pas journalisée par Proxmox (elle se lit dans le PBS).")


# =========================================================================== #
# 1. Logs - Virtualisation (Proxmox / Ceph)
# =========================================================================== #
def gen_virtualisation():
    ids = Ids()
    SUBST.clear()
    SUBST.update({"$host": "ceph0[1-3]", "$source": ".+", "$recherche": ""})
    # sudo : smartctl lancé toutes les heures par ceph-mon (bruit, aucune information utile)
    SEL = '{host=~"$host", job="journal", unit=~"$source", identifier!="sudo"}'
    BASE = SEL + SEARCH
    # bruit connu : SIGHUP de logrotate aux démons Ceph, ceph-crash sans trousseau au démarrage,
    # qmeventd à l'arrêt d'une VM, sondes de santé des modules du mgr
    NOISE = (' !~ `Hangup|/proc/[0-9]+/cmdline|ObjectNotFound|Connection reset by peer|'
             'Loading module|set_numa_affinity`')
    panels, y = [], 0

    panels.append(row(ids, "En un coup d'œil", y)); y += 1
    H = 4
    panels += [
        stat(ids, "Lignes de logs", f"sum(count_over_time({BASE} [$__range])) or vector(0)",
             (0, y, 4, H), "Nombre de lignes du journal des unités Proxmox / Ceph retenues "
             "(variables host et source) sur la période affichée."),
        stat(ids, "Erreurs", f"sum(count_over_time({BASE} |~ `{ERR}` {NOISE[1:]} [$__range])) "
             "or vector(0)", (4, y, 4, H),
             "Lignes contenant un mot-clé d'erreur (error, fail, denied, timeout…), bruit connu "
             "exclu (voir le panneau « Erreurs et avertissements »). 0 attendu en temps normal.",
             steps(("green", None), ("orange", 1), ("red", 20))),
        stat(ids, "Avertissements", f"sum(count_over_time({BASE} |~ `{WARN}` [$__range])) "
             "or vector(0)", (8, y, 4, H),
             "Lignes de niveau WARN / warning (rares : Proxmox ne préfixe pas le niveau).",
             steps(("green", None), ("orange", 1))),
        stat(ids, "Actions HA", 'sum(count_over_time({host=~"$host", unit=~"pve-ha-(crm|lrm)'
             '.service"} |~ `state changed|starting service|stopping service|fence|recover|'
             'migrat|relocat` [$__range])) or vector(0)', (0, y + H, 4, H),
             "Changements d'état des services HA (VM démarrée, arrêtée, migrée, relancée sur "
             "un autre nœud, nœud isolé « fence »). Non nul après un incident ou un "
             "redémarrage du lab.", steps(("blue", None))),
        stat(ids, "Sauvegardes de VM réussies", 'sum(count_over_time({host=~"$host", '
             'job="journal"} |~ `Finished Backup of (VM|CT)` [$__range])) or vector(0)',
             (4, y + H, 4, H), "VM ou conteneurs sauvegardés avec succès vers le PBS sur la "
             "période (jobs vzdump).", steps(("blue", None), ("green", 1))),
        stat(ids, "Sauvegardes de VM en échec", 'sum(count_over_time({host=~"$host", '
             'job="journal"} |~ `Backup of (VM|CT) [0-9]+ failed|Backup job failed` '
             '[$__range])) or vector(0)', (8, y + H, 4, H),
             "Sauvegardes vzdump en erreur (VM ou job entier). 0 attendu.",
             steps(("green", None), ("red", 1))),
        volume(ids, "Volume de logs par unité",
               f"sum by (unit) (count_over_time({BASE} [$__interval]))", "{{unit}}",
               (12, y, 12, 2 * H),
               "Lignes par unité systemd et par intervalle (barres empilées). Un pic signale "
               "une activité : démarrage du lab (tous les services), sauvegarde (pvescheduler), "
               "incident HA (pve-ha-*), panne réseau (corosync)."),
    ]
    y += 2 * H

    panels.append(row(ids, "Erreurs et avertissements", y)); y += 1
    panels.append(logs(
        ids, "Erreurs et avertissements des hyperviseurs",
        f"{BASE} |~ `{ERR}|{WARN[4:]}` {NOISE[1:]}" + fmt('{{.host}} [{{.unit}}] {{ __line__ }}'),
        (0, y, 24, 9),
        "Lignes d'erreur ou d'avertissement, plus récentes en haut. Bruit exclu : signaux "
        "SIGHUP envoyés par logrotate aux démons Ceph, « ObjectNotFound » de ceph-crash au "
        "démarrage, « Connection reset by peer » de qmeventd à l'arrêt d'une VM, chargement "
        "des modules du mgr, smartctl lancé par sudo. « invalid PVE ticket » : session de "
        "l'interface expirée (sans gravité). « heartbeat_check: no reply » : un OSD ne répond "
        "plus (nœud ou réseau Ceph en panne). Au démarrage du lab, pve-cluster signale « "
        "cpg_initialize failed » tant que corosync n'est pas prêt (normal)."))
    y += 9

    panels.append(row(ids, "Événements clés", y)); y += 1
    H = 10
    panels += [
        logs(ids, "Haute disponibilité : actions sur les VM",
             '{host=~"$host", unit=~"pve-ha-(crm|lrm).service"} |~ `state changed|adding new '
             'service|removing stale|fence|recover|migrat|relocat|status change|acquired lock|'
             'starting service|stopping service|started with PID|starting CT|lost` '
             '!~ `still active`' + SEARCH
             + fmt('{{.host}}  {{ regexReplaceAll ": UPID:[^ ]+" (regexReplaceAll " using '
                   'pve-qemu-kvm[^ ]*" __line__ "") "" }}'),
             (0, y, 12, H),
             "Décisions du gestionnaire HA (pve-ha-crm, un seul nœud « master ») et actions des "
             "agents locaux (pve-ha-lrm) : service ajouté, démarré, arrêté, migré, relancé "
             "ailleurs (« recover ») ou nœud isolé (« fence ») après la perte d'un hyperviseur. "
             "« status change slave => master » : bascule du gestionnaire."),
        logs(ids, "Cluster : quorum corosync et pmxcfs",
             '{host=~"$host", unit=~"corosync.service|pve-cluster.service"} |~ `(?i)quorum|'
             'member|joined|left|lost|link|crit|failed`' + SEARCH
             + fmt("{{.host}} [{{.unit}}] {{ __line__ }}"),
             (12, y, 12, H),
             "Appartenance au cluster : « Members[3]: 1 2 3 » = les trois nœuds sont présents ; "
             "« This node is within the primary component » = quorum atteint ; « left », "
             "« lost » ou « link down » = nœud ou lien perdu. pve-cluster (pmxcfs) : base de "
             "configuration partagée (synchronisation, erreurs critiques)."),
    ]
    y += H
    panels += [
        logs(ids, "Sauvegardes vzdump vers le PBS", VZDUMP, (0, y, 12, H), VZDUMP_DESC),
        logs(ids, "Ceph : OSD, moniteurs, gestionnaire",
             '{host=~"$host", unit=~"ceph-(osd|mon|mgr)@.*|ceph-crash.service", '
             'identifier!="sudo"}' + NOISE + SEARCH
             + fmt('{{.host}} [{{.unit}}] {{ regexReplaceAll "^[0-9T:.+-]+ [0-9a-f]+ +-?[0-9]+ "'
                   ' __line__ "" }}'),
             (12, y, 12, H),
             "Messages des démons Ceph (bruit des signaux de logrotate exclu) : « heartbeat_check:"
             " no reply from … osd.N » = OSD injoignable, « marked down / boot » = OSD sorti ou "
             "revenu. L'état de santé global (HEALTH_OK / WARN) est dans le journal du cluster "
             "(/var/log/ceph/ceph.log, non collecté) : le lire dans le dashboard Proxmox & Ceph."),
    ]
    y += H
    AUTH = ('{host=~"$host", unit=~"pvedaemon.service|pveproxy.service"} |~ `successful '
            '(openid )?auth for user|authentication failure`')
    panels += [
        logs(ids, "Connexions à l'interface Proxmox", AUTH + SEARCH
             + fmt('{{.host}}  {{ regexReplaceAll "^<[^>]+> " (regexReplaceAll "msg=.*$" '
                   '__line__ "") "" }}'),
             (0, y, 14, 9),
             "Authentifications sur l'interface web / API Proxmox : « successful openid auth » = "
             "connexion SSO Keycloak (TOTP), « successful auth » = renouvellement du ticket "
             "(toutes les 15 min tant que l'onglet est ouvert), « authentication failure » = "
             "échec (utilisateur, IP source). « invalid PVE ticket » : session expirée. Aucun "
             "jeton ni mot de passe n'apparaît."),
        table(ids, "Connexions par utilisateur",
              'sum by (resultat, utilisateur) (count_over_time(' + AUTH
              + ' | regexp `(?P<resultat>successful (?:openid )?auth|authentication failure)'
              '.*user[ =]\'?(?P<utilisateur>[^\' ;]+)` [$__range]))',
              (14, y, 10, 9),
              "Nombre d'authentifications par utilisateur et par résultat sur la période. "
              "« successful auth » inclut les renouvellements automatiques de ticket.",
              {"resultat": "Résultat", "utilisateur": "Utilisateur", "Value": "Nombre"},
              ["utilisateur", "resultat", "Value"]),
    ]
    y += 9

    panels.append(row(ids, "Tous les logs", y)); y += 1
    panels += [
        logs(ids, "Journal des hyperviseurs (unités Proxmox / Ceph)",
             BASE + fmt_masked("{{.host}} [{{.unit}}] "), (0, y, 24, 12),
             "Toutes les lignes des unités choisies dans « source », plus récentes en haut. "
             "Lignes de sudo (smartctl lancé par ceph-mon) exclues."),
    ]
    y += 12
    panels.append(logs(
        ids, "Journal d'accès de l'interface web (pveproxy, hors comptes de service)",
        '{host=~"$host", job="pveproxy"} !~ `![^ ]+ \\[` !~ `svc_`' + SEARCH
        + fmt_masked(), (0, y, 24, 10),
        "Requêtes HTTP sur l'interface web Proxmox (port 8006) : IP source, utilisateur, "
        "requête, code de retour. Les appels des jetons d'API (supervision, Terraform) et des "
        "comptes de service svc_* sont exclus (plusieurs milliers par heure). Code 401 sur "
        "/access/ticket = échec de connexion."))

    variables = [
        custom_var("host", "Hyperviseur", ["ceph01", "ceph02", "ceph03"]),
        loki_label_var("source", "Unité (source)", "unit",
                       '{host=~"$host", job="journal"}',
                       r"/^(?:pve.*|qmeventd|corosync|watchdog-mux|spiceproxy|ceph-.*|lxcfs)"
                       r"\.service$/",
                       "Unités systemd Proxmox et Ceph des hyperviseurs."),
        text_var(),
    ]
    write("logs-virtualisation", dashboard(
        "logs-virtualisation", "Logs - Virtualisation (Proxmox / Ceph)",
        "Journaux des hyperviseurs ceph01-03 : haute disponibilité, quorum corosync, Ceph, "
        "sauvegardes vzdump, connexions à l'interface Proxmox.",
        panels, variables,
        [("Proxmox & Ceph (métriques)", "proxmox", "Métriques du cluster Proxmox et de Ceph"),
         ("Vue centrale", "central", "Plateforme - vue centrale")]))


# =========================================================================== #
# 2. Logs - Identité et secrets
# =========================================================================== #
def gen_identite():
    ids = Ids()
    SUBST.clear()
    SUBST.update({"$host": "iam01|vault01|vaultwarden01", "$source": ".+", "$recherche": ""})
    # le journal d'audit de Vault (vault-audit, JSON) a ses propres panneaux
    SEL = '{host=~"$host", job="journal", unit=~"$source", identifier!="vault-audit"}'
    BASE = SEL + SEARCH
    AUDIT = '{host=~"$host", identifier="vault-audit"} |= `"type":"response"`'
    # bruit : avertissement de configuration du client grafana répété à chaque échange de jeton,
    # renouvellement horaire du certificat TLS de Keycloak, baux AppRole révoqués (vault-env)
    NOISE = ' !~ `full-scope-allowed|revoked lease|keys are pending|GOAWAY`'
    KC = ('{host=~"$host", unit="keycloak.service"} |= `org.keycloak.events` '
          '| regexp `type="(?P<evt>[A-Z_]+)"`')
    KC_FIELDS = (' | regexp `clientId="(?P<client>[^"]*)"` | regexp `username="(?P<user>[^"]*)"`'
                 ' | regexp `ipAddress="(?P<ip>[^"]*)"` | regexp `error="(?P<err>[^"]*)"`')
    panels, y = [], 0

    panels.append(row(ids, "En un coup d'œil", y)); y += 1
    H = 4
    panels += [
        stat(ids, "Lignes de logs", f"sum(count_over_time({BASE} [$__range])) or vector(0)",
             (0, y, 4, H), "Lignes du journal de Keycloak, PostgreSQL (iam01), Vault (hors "
             "audit) et Vaultwarden sur la période."),
        stat(ids, "Erreurs", f"sum(count_over_time({BASE} |~ `{ERR}`{NOISE} [$__range])) "
             "or vector(0)", (4, y, 4, H),
             "Lignes d'erreur (mots-clés error, fail, denied…). Inclut les échecs de connexion "
             "(LOGIN_ERROR, mot de passe incorrect).", steps(("green", None), ("orange", 1),
                                                         ("red", 20))),
        stat(ids, "Avertissements", f"sum(count_over_time({BASE} |~ `{WARN}| WARN `{NOISE} "
             "[$__range])) or vector(0)", (8, y, 4, H),
             "Lignes de niveau WARN (bruit répétitif exclu, voir « Erreurs et avertissements »).",
             steps(("green", None), ("orange", 1))),
        stat(ids, "Connexions SSO réussies", f'sum(count_over_time({KC} | evt="LOGIN" '
             '[$__range])) or vector(0)', (0, y + H, 4, H),
             "Connexions réussies sur Keycloak (realm epsi, mot de passe + TOTP) vers Grafana, "
             "Proxmox ou la console d'administration.", steps(("blue", None))),
        stat(ids, "Connexions refusées", f'(sum(count_over_time({KC} | evt="LOGIN_ERROR" '
             '[$__range])) or vector(0)) + (sum(count_over_time({host=~"$host", '
             'unit="vaultwarden.service"} |= `Username or password is incorrect` [$__range])) '
             'or vector(0))', (4, y + H, 4, H),
             "Échecs de connexion : Keycloak (LOGIN_ERROR : mot de passe ou code TOTP faux) et "
             "Vaultwarden (mot de passe maître incorrect). Une série rapprochée = tentative "
             "de force brute.", steps(("green", None), ("orange", 1), ("red", 5))),
        stat(ids, "Refus Vault", 'sum(count_over_time({host=~"$host", identifier="vault-audit"}'
             ' |= `"type":"response"` |= `"error":` [$__range])) or vector(0)',
             (8, y + H, 4, H),
             "Réponses de Vault en erreur dans le journal d'audit (permission denied, jeton "
             "invalide, chemin inconnu).", steps(("green", None), ("orange", 1))),
        volume(ids, "Volume de logs par source",
               'sum by (identifier) (count_over_time({host=~"$host", job="journal", '
               'unit=~"$source"}' + SEARCH + ' [$__interval]))', "{{identifier}}",
               (12, y, 12, 2 * H),
               "Lignes par programme et par intervalle (barres empilées). vault-audit : une "
               "ligne par requête et par réponse ; chaque exécution de vault-env (Ansible, "
               "Terraform) lit une quinzaine de secrets, d'où des pics réguliers."),
    ]
    y += 2 * H

    panels.append(row(ids, "Erreurs et avertissements", y)); y += 1
    panels.append(logs(
        ids, "Erreurs et avertissements (Keycloak, Vault, Vaultwarden, PostgreSQL)",
        f"{BASE} |~ `{ERR}|{WARN[4:]}| WARN `{NOISE}" + fmt_masked("{{.host}} [{{.unit}}] "),
        (0, y, 24, 9),
        "Lignes d'erreur ou d'avertissement, valeurs sensibles masquées (jetons, sessions, "
        "baux). Bruit exclu : avertissement « Full scope allowed » du client grafana (à "
        "chaque échange de jeton), baux AppRole révoqués par vault-env, « keys are pending » "
        "de raft. « REFRESH_TOKEN_ERROR invalid_token » : session Grafana expirée.")); y += 9

    panels.append(row(ids, "Événements clés", y)); y += 1
    H = 10
    kc_fmt = ('{{ if eq .evt "LOGIN" }}Connexion réussie{{ else if eq .evt "LOGIN_ERROR" }}'
              'ÉCHEC de connexion{{ else if eq .evt "LOGOUT" }}Déconnexion{{ else }}{{.evt}}'
              '{{ end }} : {{ if .user }}{{.user}}{{ else }}?{{ end }} vers {{.client}} depuis '
              '{{.ip}}{{ if .err }} (erreur : {{.err}}){{ end }}')
    panels += [
        logs(ids, "Keycloak : connexions SSO (realm epsi)",
             KC + ' | evt=~"LOGIN|LOGIN_ERROR|LOGOUT|UPDATE_TOTP|REMOVE_TOTP|UPDATE_PASSWORD.*|'
             'UPDATE_CREDENTIAL.*|RESET_PASSWORD.*|USER_DISABLED_BY_TEMPORARY_LOCKOUT|'
             'USER_DISABLED_BY_PERMANENT_LOCKOUT"' + KC_FIELDS + SEARCH + fmt(kc_fmt),
             (0, y, 12, H),
             "Événements de connexion Keycloak : réussite (mot de passe + TOTP), échec "
             "(invalid_user_credentials, invalid_totp…), déconnexion, enrôlement TOTP, "
             "changement de mot de passe, verrouillage anti force brute. Applications : "
             "grafana, proxmox, security-admin-console. Ni jeton ni identifiant de session."),
        table(ids, "Keycloak : connexions par utilisateur",
              f'sum by (evt, user, client) (count_over_time({KC} | evt=~"LOGIN|LOGIN_ERROR"'
              + KC_FIELDS + ' [$__range]))', (12, y, 12, H),
              "Nombre de connexions réussies (LOGIN) et refusées (LOGIN_ERROR) par utilisateur "
              "et par application sur la période.",
              {"evt": "Événement", "user": "Utilisateur", "client": "Application",
               "Value": "Nombre"}, ["user", "evt", "client", "Value"]),
    ]
    y += H
    panels += [
        logs(ids, "Vault : scellement, descellement, leader",
             '{host=~"$host", unit="vault.service", identifier="vault"} |~ `(?i)vault is '
             '(un)?sealed|seal|post-unseal|pre-seal|standby|acquired lock|active operation|'
             'leader state|shutdown|stopping|starting listener|Vault server started`'
             ' !~ `GOAWAY`' + SEARCH
             + fmt('{{.host}}  {{ regexReplaceAll "^[0-9TZ:.-]+ " (regexReplaceAll ": config=.*$"'
                   ' __line__ "") "" }}'),
             (0, y, 12, H),
             "Cycle de vie de Vault : « vault is unsealed » puis « post-unseal setup complete » "
             "= Vault descellé (commande vault-unseal après chaque démarrage du lab) ; « vault "
             "is sealed » = scellé (secrets inaccessibles, Ansible et Terraform bloqués). "
             "Raft à un nœud : l'élection du leader suit chaque descellement."),
        logs(ids, "Vault : authentifications et refus (audit)",
             AUDIT + ' |~ `"path":"(auth/[^"]*/login|sys/(seal|unseal|init))|"error":`'
             + SEARCH + ' | json path="request.path", op="request.operation", '
             'who="auth.display_name", ip="request.remote_address", err="error"'
             + fmt('{{ if .err }}REFUS{{ else }}OK   {{ end }} {{ if .who }}{{.who}}{{ else }}'
                   '(sans jeton){{ end }} : {{.op}} {{.path}} depuis {{.ip}}{{ if .err }} : '
                   '{{ regexReplaceAll "[\\n\\t*]+" .err " " }}{{ end }}'),
             (12, y, 12, H),
             "Journal d'audit de Vault, champs choisis uniquement (jamais les jetons ni les "
             "valeurs) : connexions AppRole (Ansible, Terraform via vault-env, depuis "
             "10.0.1.110) et userpass (compte breakglass), descellement, et toute réponse en "
             "erreur (permission denied, jeton invalide)."),
    ]
    y += H
    panels += [
        logs(ids, "Vaultwarden : connexions",
             '{host=~"$host", unit="vaultwarden.service"} |~ `vaultwarden::api::(identity|'
             'core::two_factor|admin)|/admin`' + SEARCH
             + fmt('{{.host}}  {{ regexReplaceAll '
                   + go_str(r"^\[[^\]]+\]\[[^\]]+\]") + ' ' + masked() + ' "" }}'),
             (0, y, 12, H),
             "Coffre de secours Vaultwarden : « logged in successfully » = connexion réussie "
             "(utilisateur, IP), « Username or password is incorrect » = échec, double "
             "facteur et page /admin. Le jeton d'accès des clients web, présent dans le "
             "journal brut (notifications), est masqué."),
        table(ids, "Vault : lectures de secrets par chemin",
              'sum by (path, who) (count_over_time(' + AUDIT + ' |= `"operation":"read"` '
              '|= `"path":"secret/data/` | json path="request.path", who="auth.display_name" '
              '[$__range]))', (12, y, 12, H),
              "Secrets lus (chemin KV) et par qui (approle = Ansible / Terraform via vault-env, "
              "userpass-breakglass = humain, root = jeton initial) : seuls les chemins sont "
              "affichés, jamais les valeurs.",
              {"path": "Chemin", "who": "Identité", "Value": "Lectures"},
              ["path", "who", "Value"]),
    ]
    y += H

    panels.append(row(ids, "Tous les logs", y)); y += 1
    panels += [
        logs(ids, "Journal des services d'identité (valeurs sensibles masquées)",
             BASE + ' !~ `revoked lease`' + fmt_masked("{{.host}} [{{.unit}}] "),
             (0, y, 24, 12),
             "Toutes les lignes des unités choisies dans « source » (Keycloak, PostgreSQL de "
             "Keycloak, Vault, Vaultwarden), plus récentes en haut. Masqués : jetons, codes, "
             "identifiants de session et de bail, jetons JWT, en-têtes Authorization. Exclu : "
             "« revoked lease » de Vault (une ligne par bail AppRole expiré)."),
    ]
    y += 12
    panels += [
        logs(ids, "Vault : journal d'audit (champs choisis)",
             AUDIT + SEARCH + ' | json path="request.path", op="request.operation", '
             'who="auth.display_name", ip="request.remote_address", err="error", '
             'mount="request.mount_type"'
             + fmt('{{ if .err }}REFUS{{ else }}OK   {{ end }} {{ if .who }}{{.who}}{{ else }}'
                   '(sans jeton){{ end }} : {{.op}} {{.path}} ({{.mount}}) depuis {{.ip}}'),
             (0, y, 12, 10),
             "Une ligne par réponse de Vault : résultat, identité, opération, chemin, IP source. "
             "Les jetons, accesseurs et valeurs (hachés HMAC dans le journal brut) ne sont "
             "jamais affichés."),
        logs(ids, "PostgreSQL de Keycloak (iam01, fichier)",
             '{host=~"$host", job="postgresql"} !~ `checkpoint (starting|complete)`' + SEARCH
             + fmt_masked(), (12, y, 12, 10),
             "Fichier /var/log/postgresql/postgresql-17-main.log de iam01 (base de Keycloak), "
             "hors points de contrôle périodiques (checkpoint, toutes les 5 min)."),
    ]

    variables = [
        custom_var("host", "Machine", ["iam01", "vault01", "vaultwarden01"]),
        loki_label_var("source", "Unité (source)", "unit",
                       '{host=~"$host", job="journal"}',
                       r"/^(?:keycloak|postgresql@.*|vault|vaultwarden)\.service$/",
                       "Keycloak, sa base PostgreSQL, Vault et Vaultwarden."),
        text_var(),
    ]
    write("logs-identite", dashboard(
        "logs-identite", "Logs - Identité et secrets",
        "Journaux de Keycloak (SSO, TOTP), Vault (descellement, AppRole, refus) et "
        "Vaultwarden (coffre de secours), valeurs sensibles masquées.",
        panels, variables,
        [("Vue centrale", "central", "Plateforme - vue centrale"),
         ("Nœuds (Node Exporter)", "node-exporter-full", "Métriques des machines")]))


# =========================================================================== #
# 3. Logs - Sauvegardes et poste de contrôle
# =========================================================================== #
def gen_controle():
    ids = Ids()
    SUBST.clear()
    SUBST.update({"$host": "control01|ceph0[1-3]", "$source": ".+", "$recherche": ""})
    # Ansible : seul le nom du module est montré (les paramètres peuvent contenir des valeurs)
    SEL = ('{host=~"$host", job="journal", identifier=~"$source", '
           'identifier!~"ansible-.*"}')
    BASE = SEL + SEARCH
    # bruit : lignes d'information du collecteur Alloy qui contiennent « timeout » en paramètre
    NOISE = ' !~ `level=info`'
    DB ='{host="control01", identifier="paiement-db-backup"}'
    SSH = ('{host=~"$host", identifier=~"sshd.*"} |~ `Accepted \\S+ for|Failed \\S+ for|'
           'Invalid user`')
    SSH_RE = (' | regexp `(?P<resultat>Accepted|Failed|Invalid user)( (?P<methode>\\S+) for)?'
              '( invalid user)? (?P<utilisateur>\\S+) from (?P<ip>\\S+)`')
    panels, y = [], 0

    panels.append(row(ids, "En un coup d'œil", y)); y += 1
    H = 4
    panels += [
        stat(ids, "Lignes de logs", f"sum(count_over_time({BASE} [$__range])) or vector(0)",
             (0, y, 4, H), "Lignes retenues (variables host et source) sur la période."),
        stat(ids, "Erreurs", f"sum(count_over_time({BASE} |~ `{ERR}`{NOISE} [$__range])) "
             "or vector(0)", (4, y, 4, H),
             "Lignes d'erreur (error, échec, fail, denied…) : sauvegarde en échec, connexion SSH "
             "refusée…", steps(("green", None), ("orange", 1), ("red", 20))),
        stat(ids, "Sauvegardes de la base réussies",
             f"count(sum by (fichier) (count_over_time({DB} |= `ok base=` | logfmt "
             "[$__range]))) or vector(0)", (8, y, 4, H),
             "Dumps pg_dump réussis (bases payments et auth, toutes les 15 min, depuis le "
             "primaire Patroni) sur la période : 8 attendus par heure.",
             steps(("red", None), ("green", 1))),
        stat(ids, "Échecs de sauvegarde",
             f"(sum(count_over_time({DB} |= `echec` [$__range])) or vector(0)) + "
             '(sum(count_over_time({host=~"$host", job="journal"} |~ `Backup of (VM|CT) '
             '[0-9]+ failed|Backup job failed` [$__range])) or vector(0))', (0, y + H, 4, H),
             "Sauvegardes en échec : dump de la base (primaire introuvable…) et sauvegardes "
             "vzdump des VM. 0 attendu (chaque échec de dump est journalisé deux fois).",
             steps(("green", None), ("red", 1))),
        stat(ids, "Sauvegardes de VM réussies", 'sum(count_over_time({host=~"$host", '
             'job="journal"} |~ `Finished Backup of (VM|CT)` [$__range])) or vector(0)',
             (4, y + H, 4, H), "VM et conteneurs sauvegardés vers le PBS (jobs 13h00 et 21h00).",
             steps(("blue", None), ("green", 1))),
        stat(ids, "Connexions SSH acceptées", f"sum(count_over_time({SSH} |= `Accepted` "
             "[$__range])) or vector(0)", (8, y + H, 4, H),
             "Sessions SSH ouvertes (clé publique) sur les machines retenues : poste de "
             "contrôle et hyperviseurs.", steps(("blue", None))),
        volume(ids, "Volume de logs par source",
               f"sum by (identifier) (count_over_time({BASE} [$__interval]))",
               "{{identifier}}", (12, y, 12, 2 * H),
               "Lignes par programme et par intervalle (barres empilées) : sshd-session et "
               "systemd-logind suivent les connexions SSH (Ansible, scripts), "
               "paiement-db-backup les dumps, pvescheduler les sauvegardes des VM."),
    ]
    y += 2 * H

    panels.append(row(ids, "Erreurs et avertissements", y)); y += 1
    panels.append(logs(
        ids, "Erreurs et avertissements",
        f"{BASE} |~ `{ERR}|{WARN[4:]}`{NOISE}" + fmt_masked("{{.host}} [{{.identifier}}] "),
        (0, y, 24, 8),
        "Lignes d'erreur ou d'avertissement du poste de contrôle et des hyperviseurs (source "
        "choisie) : « echec : primaire PostgreSQL introuvable » = dump impossible pendant une "
        "bascule ou au démarrage du lab ; « Failed publickey » = clé SSH refusée. Exclu : lignes level=info du collecteur Alloy.")); y += 8

    panels.append(row(ids, "Événements clés", y)); y += 1
    H = 10
    db_fmt = ('{{ if .base }}OK      {{.base}} depuis {{.noeud}} : {{.taille}} octets en '
              '{{.duree_s}} s{{ else if .restaures }}TEST DE RESTAURATION : {{.restaures}} '
              'paiements restaurés (production : {{.production}}) en {{.duree_s}} s, dump de '
              '{{.dump_age_s}} s{{ else }}{{ __line__ }}{{ end }}')
    panels += [
        logs(ids, "Sauvegardes de la base (pg_dump) et tests de restauration",
             DB + SEARCH + " | logfmt" + fmt(db_fmt), (0, y, 12, H),
             "Dumps logiques toutes les 15 min (timer paiement-db-backup sur control01, "
             "/var/backups/paiement) : base, nœud du primaire Patroni, taille, durée. "
             "« TEST DE RESTAURATION » : paiement-db-restore-test (restauration dans une base "
             "jetable, comparaison au nombre de paiements en production). « echec » = dump "
             "impossible. Les doublons (journal + logger) sont repliés.",
             dedup="exact"),
        panel(ids, "timeseries", "Taille des dumps de la base",
              [tgt(f"max by (base) (max_over_time({DB} |= `ok base=` | logfmt | __error__=\"\""
                   " | unwrap taille [15m]))", "{{base}}", title="Taille des dumps")],
              (12, y, 12, H), unit="bytes", interval="5m",
              custom={"drawStyle": "line", "lineWidth": 2, "fillOpacity": 10,
                      "gradientMode": "opacity", "showPoints": "auto", "spanNulls": True,
                      "axisSoftMin": 0, "stacking": {"mode": "none", "group": "A"}},
              options={"legend": {"displayMode": "list", "placement": "bottom",
                                  "showLegend": True, "calcs": []},
                       "tooltip": {"mode": "multi", "sort": "desc"}},
              color={"mode": "palette-classic"},
              desc="Taille de chaque dump (octets), lue dans le journal de la sauvegarde : "
                   "elle croît avec le nombre de paiements ; une chute ou un trou signale un "
                   "dump vide ou manqué."),
    ]
    y += H
    panels += [
        logs(ids, "Sauvegardes vzdump des VM vers le PBS", VZDUMP, (0, y, 12, H), VZDUMP_DESC),
        logs(ids, "Sessions SSH",
             SSH + SEARCH + SSH_RE
             + fmt('{{.host}}  {{ if eq .resultat "Accepted" }}Connexion{{ else }}REFUS{{ end }}'
                   ' {{.utilisateur}} depuis {{.ip}}{{ if .methode }} ({{.methode}}){{ end }}'),
             (12, y, 12, H),
             "Connexions SSH sur le poste de contrôle et les hyperviseurs : utilisateur, IP "
             "source, méthode (publickey). « REFUS » = mot de passe ou clé refusés, "
             "utilisateur inconnu. 10.10.0.3 = poste d'administration (VPN), 10.0.1.110 = "
             "poste de contrôle (Ansible, scripts de chaos)."),
    ]
    y += H
    panels += [
        table(ids, "Sessions SSH par utilisateur et IP source",
              f"sum by (host, resultat, utilisateur, ip) (count_over_time({SSH}{SSH_RE} "
              "[$__range]))", (0, y, 12, 9),
              "Nombre de connexions SSH par machine, résultat, utilisateur et IP source sur "
              "la période.",
              {"host": "Machine", "resultat": "Résultat", "utilisateur": "Utilisateur",
               "ip": "IP source", "Value": "Connexions"},
              ["host", "utilisateur", "ip", "resultat", "Value"]),
        volume(ids, "Exécutions Ansible vues sur les machines (modules par minute)",
               'sum by (host) (count_over_time({identifier=~"ansible-.*"} [$__interval]))',
               "{{host}}", (12, y, 12, 9),
               "Modules Ansible exécutés sur chaque machine gérée (journal des cibles, toutes "
               "machines, indépendamment de la variable host) : chaque barre = un passage de "
               "playbook lancé depuis control01 par vault-env ansible-playbook. Terraform ne "
               "journalise rien côté machines."),
    ]
    y += 9
    panels.append(logs(
        ids, "Modules Ansible exécutés (nom du module seulement)",
        '{identifier=~"ansible-.*"}' + SEARCH
        + fmt('{{.host}}  {{ regexReplaceAll "^ansible-" .identifier "" }}'),
        (0, y, 24, 7),
        "Un module Ansible par ligne et par machine cible. Les paramètres des modules (qui "
        "peuvent contenir des contenus de fichiers) ne sont pas affichés.")); y += 7

    panels.append(row(ids, "Tous les logs", y)); y += 1
    panels.append(logs(
        ids, "Journal du poste de contrôle et des hyperviseurs (source choisie)",
        BASE + fmt_masked("{{.host}} [{{.identifier}}] "), (0, y, 24, 12),
        "Toutes les lignes des programmes choisis dans « source », plus récentes en haut, "
        "valeurs sensibles masquées. Les invocations de modules Ansible sont exclues (panneau "
        "dédié ci-dessus)."))

    variables = [
        custom_var("host", "Machine", ["control01", "ceph01", "ceph02", "ceph03"]),
        loki_label_var("source", "Programme (source)", "identifier",
                       '{host=~"$host", job="journal"}',
                       r"/^(?:paiement-db-backup|sshd|sshd-session|pvescheduler|pvedaemon|"
                       r"systemd-logind|CRON|cron|sudo|su|alloy-wrapper)$/",
                       "Programmes (SYSLOG_IDENTIFIER) du journal : sauvegardes, SSH, "
                       "planificateur Proxmox, cron, collecteur Alloy."),
        text_var(),
    ]
    write("logs-controle", dashboard(
        "logs-controle", "Logs - Sauvegardes et poste de contrôle",
        "Sauvegardes de la base (pg_dump, tests de restauration) et des VM (vzdump vers le "
        "PBS), connexions SSH et exécutions Ansible depuis le poste de contrôle control01.",
        panels, variables,
        [("Vue centrale", "central", "Plateforme - vue centrale"),
         ("Proxmox & Ceph (métriques)", "proxmox", "Métriques du cluster et des sauvegardes")]))


gen_virtualisation()
n1 = len(CHECKS)
gen_identite()
gen_controle()
if "--check" in sys.argv:
    path = pathlib.Path(sys.argv[sys.argv.index("--check") + 1])
    path.write_text("".join(f"loki\t{t}\t{e}\n" for t, e in CHECKS), encoding="utf-8")
    print(f"{path} : {len(CHECKS)} requêtes")

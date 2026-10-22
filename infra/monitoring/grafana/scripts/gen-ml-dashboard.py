#!/usr/bin/env python3
"""Génère le dashboard Grafana « Modèle ML / Détecteur d'anomalies » (uid ml-detecteur).

Suit le travail du détecteur d'anomalies (detector/app/main.py) pour la démo et le jury :
état du modèle, score dans le temps, variables d'entrée, chaîne détection -> action ->
reprise, qualité (évaluation hors ligne et indicateurs en ligne).

Usage (depuis infra/monitoring/grafana) : python3 scripts/gen-ml-dashboard.py
Sortie : dashboards/Modèle ML/ml-detecteur.json

Le modèle : IsolationForest (200 arbres) + distance robuste à la normale (médiane, MAD) ;
score brut = le plus élevé des deux, ramené sur [0, 1]. Une observation de payment-api par
seconde (/api/status, 6 variables). Apprentissage pendant l'échauffement (WARMUP_SECONDS
secondes où l'API répond), puis modèle figé : pas de réentraînement continu, seulement au
redémarrage du conteneur (modèle en mémoire) ou par POST /reset (jeton admin). Anomalie
confirmée quand le score BRUT dépasse THRESHOLD PERSISTENCE secondes de suite ; le score
publié est lissé (moyenne exponentielle, facteur 0,5).

Sources :
- /metrics du détecteur (detector_*, job paiement_detector, vmagent du Swarm, 30 s) ; une série
  par conteneur (label instance) : toujours agréger (max / sum) ;
- la sonde de transaction (stack probe) : lignes logfmt toutes les 5 s dans Loki (type=etat :
  score, anomalie, moteur), recopie des événements du moteur (type=evenement) et des pannes
  vues par un client (type=incident). Le score à 5 s près se lit donc dans Loki ;
- journaux du détecteur (Loki, service paiement_detector) : démarrages (réapprentissage) et
  appels POST /reset.

Les réglages (seuil, persistance, échauffement) et les résultats de l'évaluation hors ligne
sont lus dans le dépôt à la génération : relancer le script après un changement.
Conventions et helpers recopiés de gen-demo-dashboard.py (pas d'import : fichier autonome).
"""
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent.parent  # racine du dépôt
OUT = HERE.parent / "dashboards/Modèle ML/ml-detecteur.json"


# --------------------------------------------------------------------------- #
# Réglages réels du détecteur, lus dans le dépôt
# --------------------------------------------------------------------------- #
def grab(path, pattern, cast=str):
    m = re.search(pattern, (ROOT / path).read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit(f"{path} : motif introuvable ({pattern})")
    return cast(m.group(1))


STACK = "infra/app/paiement-stack.yml.j2"
DETECTOR = "detector/app/main.py"
# Échauffement : variable Ansible de la stack (défaut du code : 120 s)
WARMUP = grab("infra/ansible/roles/app_stack/defaults/main.yml",
              r"^app_detector_warmup_seconds:\s*(\d+)", int)
# Seuil : fixé dans la stack ; persistance : défaut du code si la stack ne la fixe pas
THRESHOLD = grab(STACK, r'^\s*THRESHOLD:\s*"?([0-9.]+)"?', float)
_stack = (ROOT / STACK).read_text(encoding="utf-8")
PERSISTENCE = (int(re.search(r'^\s*PERSISTENCE:\s*"?(\d+)"?', _stack, re.M).group(1))
               if re.search(r'^\s*PERSISTENCE:', _stack, re.M)
               else grab(DETECTOR, r'PERSISTENCE = int\(os\.getenv\("PERSISTENCE", "(\d+)"\)\)', int))
EVAL_README = "evaluation/README.md"


def eval_metric(name):
    return grab(EVAL_README, r"^\|\s*" + re.escape(name) + r"\s*\|\s*([^|]+?)\s*\|")


EVAL = {k: eval_metric(k) for k in ("Precision", "Recall", "F1-score", "AUC-ROC",
                                    "Délai de détection")}
EVAL_WARMUP = grab(EVAL_README, r"warmup (\d+) s", int)


def fr(x):
    """0.811 -> 0,811 (affichage)."""
    return str(x).replace(".", ",")


VM = {"type": "prometheus", "uid": "victoriametrics"}
LOKI = {"type": "loki", "uid": "loki"}
MIXED = {"type": "datasource", "uid": "-- Mixed --"}

DET = 'service="paiement_detector"'
PROBE = '{stack="probe", service="probe_transactions"}'
ETAT = PROBE + ' |= "type=etat"'
DET_LOGS = '{stack="paiement", service="paiement_detector"}'
RETRAIN = DET_LOGS + ' |~ "Application startup complete|POST /reset"'


def unwrap(field, fn="last_over_time", window="15s", selector=ETAT):
    """Valeur numérique d'un champ logfmt des lignes de la sonde, agrégée sur une fenêtre."""
    return (f'max({fn}({selector} | logfmt {field} | __error__="" '
            f'| unwrap {field} [{window}]))')


# --------------------------------------------------------------------------- #
# Briques de base (mêmes conventions que gen-demo-dashboard.py)
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


def row(title, y):
    return {"id": next(_ids), "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


DASHED = {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}}
NO_FILL = {"id": "custom.fillOpacity", "value": 0}
RIGHT = {"id": "custom.axisPlacement", "value": "right"}


# --------------------------------------------------------------------------- #
# Panneaux
# --------------------------------------------------------------------------- #
panels = []
y = 0

# ---- 1. État du modèle -----------------------------------------------------------
panels.append(row("État du modèle", y))
y += 1
H = 5
panels += [
    stat("Modèle",
         # vmagent marque les séries périmées quand le conteneur ne répond plus : plus de
         # detector_ready -> -1 (injoignable)
         [tgt(f'max(detector_ready{{{DET}}}) or vector(-1)', instant=True)],
         (0, y, 5, H),
         mappings=[text_map(1, "PRÊT", "green"), text_map(0, "ÉCHAUFFEMENT", "orange"),
                   text_map(-1, "INJOIGNABLE", "red")],
         thresholds=steps(("red", None), ("orange", 0), ("green", 1)),
         desc=f"PRÊT : la normale est apprise, chaque seconde reçoit un score. ÉCHAUFFEMENT : "
              f"le modèle apprend ({WARMUP} premières secondes où l'API répond, après un "
              f"redémarrage du détecteur ou un POST /reset). INJOIGNABLE : /metrics ne répond "
              f"plus (alerte PaiementDetectorDown au bout de 2 min). Mesure toutes les 30 s."),
    stat("Normale apprise",
         [tgt(f'max(detector_training_samples{{{DET}}})', instant=True)],
         (5, y, 4, H), unit=f"suffix: / {WARMUP} s", decimals=0, minv=0, maxv=WARMUP,
         thresholds=steps(("orange", None), ("green", WARMUP)),
         desc=f"Secondes d'observation apprises pendant l'échauffement (WARMUP_SECONDS = "
              f"{WARMUP} en production, {EVAL_WARMUP} lors de l'évaluation hors ligne). Le "
              f"modèle n'est plus réentraîné ensuite : la normale est figée."),
    stat("Score d'anomalie",
         [tgt(unwrap("score"), ds=LOKI)],
         (9, y, 4, H), ds=LOKI, interval="5s", decimals=2, minv=0, maxv=1,
         thresholds=steps(("green", None), ("orange", THRESHOLD * 0.8), ("red", THRESHOLD)),
         desc=f"Score courant (0 normal, 1 très anormal), seuil {fr(THRESHOLD)}. Valeur lissée "
              "(moyenne exponentielle) recopiée de /detector/score par la sonde toutes les "
              "5 s ; /metrics n'est collecté que toutes les 30 s."),
    stat("Verdict",
         # fenêtre 30 s : une ligne toutes les 5 s, avec quelques secondes de retard d'ingestion
         [tgt(unwrap("anomalie", window="30s") + " or vector(2)", ds=LOKI)],
         (13, y, 5, H), ds=LOKI, interval="5s",
         mappings=[text_map(0, "NORMAL", "green"), text_map(1, "ANOMALIE CONFIRMÉE", "red"),
                   text_map(2, "SONDE MUETTE", "orange")],
         thresholds=steps(("green", None), ("red", 1), ("orange", 2)),
         desc=f"ANOMALIE CONFIRMÉE : score brut ≥ {fr(THRESHOLD)} pendant {PERSISTENCE} "
              "secondes de suite ; le moteur de remédiation agit. À 5 s près (sonde)."),
    stat("Anomalies confirmées",
         [tgt(f'sum(increase(detector_anomalies_total{{{DET}}}[$__range])) or vector(0)',
              instant=True)],
         (18, y, 3, H), decimals=0, color_mode="value",
         thresholds=steps(("green", None), ("orange", 1)),
         desc="Passages de normal à anormal sur la période affichée (compteur "
              "detector_anomalies_total : garde la trace d'une anomalie plus brève que la "
              "collecte de 30 s)."),
    stat("Alertes du détecteur",
         # last_over_time [1m] : une alerte résolue disparaît en 1 min (comme le dashboard Démo)
         [tgt('max by (alertname) (last_over_time(ALERTS{alertstate="firing", '
              'alertname=~"PaiementAnomalieDetectee|PaiementDetectorDown"}[1m])) '
              'or on() label_set(vector(0), "alertname", "aucune")',
              "{{alertname}}", instant=True)],
         (21, y, 3, H), text_mode="name",
         thresholds=steps(("green", None), ("red", 1)),
         desc="Alertes vmalert en cours : PaiementAnomalieDetectee (anomalie confirmée, "
              "remédiation en cours), PaiementDetectorDown (détecteur muet : remédiation "
              "automatique aveugle)."),
]
y += H

# ---- 2. Score dans le temps -------------------------------------------------------
H = 10
panels += [
    timeseries("Score d'anomalie, seuil et anomalies confirmées",
               [tgt(unwrap("score", fn="max_over_time", window="$__interval"),
                    "score (5 s)", ds=LOKI),
                tgt(unwrap("anomalie", fn="max_over_time", window="$__interval"),
                    "anomalie confirmée", "B", ds=LOKI),
                tgt(f'max(detector_anomaly_score{{{DET}}})', "score /metrics (30 s)", "C"),
                tgt(f'max(detector_threshold{{{DET}}})', "seuil", "D")],
               (0, y, 16, H), ds=MIXED, interval="5s", decimals=2, minv=0, maxv=1,
               overrides=[
                   override_name("score (5 s)", [fixed("purple")]),
                   override_name("score /metrics (30 s)", [
                       fixed("text"), {"id": "custom.lineWidth", "value": 1}, NO_FILL,
                       {"id": "custom.showPoints", "value": "always"},
                       {"id": "custom.pointSize", "value": 4}]),
                   override_name("seuil", [fixed("red"), DASHED, NO_FILL,
                                           {"id": "custom.lineWidth", "value": 2}]),
                   override_name("anomalie confirmée", [
                       fixed("red"), {"id": "custom.lineWidth", "value": 0},
                       {"id": "custom.fillOpacity", "value": 25},
                       {"id": "custom.gradientMode", "value": "none"},
                       {"id": "custom.lineInterpolation", "value": "stepAfter"}])],
               desc=f"Violet : score lissé lu toutes les 5 s par la sonde ; points gris : le "
                    f"même score collecté par VictoriaMetrics (30 s). Tirets rouges : seuil "
                    f"{fr(THRESHOLD)}. Zone rouge : anomalie confirmée (score brut au-dessus du "
                    f"seuil {PERSISTENCE} s de suite). La décision porte sur le score brut : une "
                    f"anomalie peut être confirmée alors que la courbe lissée reste juste sous "
                    f"le seuil. Traits verticaux : événements du moteur, tests de chaos."),
    panel("text", "Le modèle en bref", [], (16, y, 8, H), ds=None,
          options={"mode": "markdown", "content": f"""\
**IsolationForest** (scikit-learn, 200 arbres) **+ distance robuste** à la normale
(médiane / MAD). Score brut = le plus élevé des deux, ramené sur [0, 1].

- **Entrée** : une observation de payment-api **par seconde**, 6 variables
  (req/s, taux d'erreur, p95, latence Stripe, API et Stripe joignables).
- **Apprentissage** : les **{WARMUP} premières secondes** où l'API répond, puis
  **modèle figé** (pas de réentraînement continu). Réapprend au redémarrage du
  conteneur ou sur `POST /reset` (jeton administrateur).
- **Décision** : score brut **≥ {fr(THRESHOLD)}** pendant **{PERSISTENCE} s de suite**
  (une seconde isolée est un soubresaut).

**Évaluation hors ligne** (`evaluation/`) : attaque réelle de 47 s (surcharge et
requêtes en erreur), score capturé chaque seconde et comparé seconde par seconde à
la fenêtre d'attaque (warmup {EVAL_WARMUP} s).

| Precision | Recall | F1 | AUC-ROC | Délai |
|:-:|:-:|:-:|:-:|:-:|
| **{fr(EVAL['Precision'])}** | **{fr(EVAL['Recall'])}** | **{fr(EVAL['F1-score'])}** | **{fr(EVAL['AUC-ROC'])}** | **{EVAL['Délai de détection']}** |
"""}),
]
panels[-1].pop("datasource")
panels[-1].pop("targets")
y += H

# ---- 3. Persistance et indicateurs en ligne ----------------------------------------
H = 8
panels += [
    timeseries("Persistance : secondes au-dessus du seuil / anomalies confirmées",
               [tgt(f'sum(increase(detector_over_threshold_seconds_total{{{DET}}}'
                    '[$__interval]))', "secondes au-dessus du seuil"),
                tgt(f'sum(increase(detector_anomalies_total{{{DET}}}[$__interval]))',
                    "anomalies confirmées", "B")],
               (0, y, 14, H), draw="bars", fill=70, decimals=0, interval="1m",
               overrides=[override_name("secondes au-dessus du seuil", [fixed("orange")]),
                          override_name("anomalies confirmées", [
                              fixed("red"), RIGHT, {"id": "custom.drawStyle", "value": "points"},
                              {"id": "custom.showPoints", "value": "always"},
                              {"id": "custom.pointSize", "value": 14}])],
               desc=f"Par minute. Orange : secondes dont le score brut dépasse {fr(THRESHOLD)} ; "
                    f"rouge (axe de droite) : anomalies confirmées. Des barres orange sans point "
                    f"rouge = soubresauts filtrés par la persistance ({PERSISTENCE} s de suite "
                    "exigées) : pas de remédiation inutile."),
    stat("Indicateurs en ligne (période affichée)",
         [tgt(f'sum(rate(detector_observations_total{{{DET}}}[5m]))',
              "observations/s (attendu 1)", instant=True),
          tgt(f'sum(increase(detector_over_threshold_seconds_total{{{DET}}}[$__range])) / '
              f'sum(increase(detector_observations_total{{{DET}}}[$__range]))',
              "temps au-dessus du seuil", "B", instant=True),
          tgt(f'avg_over_time(max(detector_anomaly{{{DET}}})[$__range:30s])',
              "temps en anomalie confirmée", "C", instant=True),
          tgt(f'sum(count_over_time({RETRAIN} [$__range])) or vector(0)',
              "réapprentissages", "D", ds=LOKI, instant=True)],
         (14, y, 10, H), ds=MIXED, text_mode="value_and_name", color_mode="value",
         decimals=2, color={"mode": "fixed", "fixedColor": "blue"},
         overrides=[override_name("temps au-dessus du seuil",
                                  [{"id": "unit", "value": "percentunit"},
                                   {"id": "decimals", "value": 1}]),
                    override_name("temps en anomalie confirmée",
                                  [{"id": "unit", "value": "percentunit"},
                                   {"id": "decimals", "value": 1}]),
                    override_name("réapprentissages", [{"id": "decimals", "value": 0}])],
         desc="Observations/s : rythme réel de la boucle (5 dernières min), doit rester ≈ 1 "
              "(une décision par seconde). Temps au-dessus du seuil : part des secondes "
              "observées dont le score brut dépasse le seuil. Temps en anomalie confirmée : "
              "part du temps (échantillons à 30 s) avec verdict anormal. Réapprentissages : "
              "démarrages du détecteur et POST /reset (journaux Loki) ; chacun relance "
              "l'échauffement."),
]
y += H

# ---- 4. Variables d'entrée : pourquoi le score monte -------------------------------
panels.append(row("Variables d'entrée du modèle (dernière valeur collectée, 30 s)", y))
y += 1
H = 8


def feature(name):
    return f'max(detector_feature{{{DET}, feature="{name}"}})'


panels += [
    timeseries("Trafic et erreurs",
               [tgt(feature("rps"), "requêtes/s"),
                tgt(feature("errRate"), "taux d'erreur", "B")],
               (0, y, 8, H), unit="reqps", decimals=1,
               overrides=[override_name("requêtes/s", [fixed("blue")]),
                          override_name("taux d'erreur", [
                              fixed("red"), RIGHT, {"id": "unit", "value": "percentunit"},
                              {"id": "max", "value": 1}, {"id": "decimals", "value": 0}])],
               desc="rps : requêtes par seconde sur les 10 dernières secondes ; errRate : part "
                    "des réponses en erreur (axe de droite). Une attaque par surcharge fait "
                    "monter les deux. API muette : errRate = 100 %, rps = 0."),
    timeseries("Latences",
               [tgt(feature("p95"), "p95 payment-api"),
                tgt(feature("stripeLatency"), "latence Stripe", "B")],
               (8, y, 8, H), unit="ms", decimals=0,
               overrides=[override_name("p95 payment-api", [fixed("orange")]),
                          override_name("latence Stripe", [fixed("purple")])],
               desc="p95 : 95e centile de la durée des requêtes de payment-api ; latence de "
                    "l'appel de santé à Stripe (mode test). 0 quand l'API ne répond pas."),
    panel("state-timeline", "Joignabilité vue par le modèle",
          [tgt(feature("apiUp"), "payment-api"),
           tgt(feature("stripeUp"), "Stripe", "B")],
          (16, y, 8, H),
          mappings=[text_map(1, "répond", "green"), text_map(0, "MUET", "red")],
          thresholds=steps(("red", None), ("green", 1)),
          custom={"lineWidth": 0, "fillOpacity": 85},
          options={"showValue": "auto", "mergeValues": True, "rowHeight": 0.8,
                   "alignValue": "center", "legend": {"showLegend": False},
                   "tooltip": {"mode": "single"}},
          desc="apiUp : /api/status de payment-api répond (une API muette est aussi une "
               "observation : toutes ses variables passent à 0 et le taux d'erreur à 100 %). "
               "stripeUp : Stripe joignable depuis payment-api."),
]
y += H

# ---- 5. Chaîne de décision : détection -> action -> reprise -------------------------
panels.append(row("Chaîne de décision : détection → action du moteur → reprise", y))
y += 1
H = 10
EVENTS = PROBE + ' |= "type=evenement"'


def last_number(selector, field, regexp=None):
    """Dernière valeur sur 24 h, tous flux confondus : by (stack) regroupe les flux (un par
    conteneur de la sonde) AVANT de prendre la dernière valeur ; un max() pris après
    renverrait la plus grande des dernières valeurs de chaque flux."""
    parse = f"regexp `{regexp}`" if regexp else f"logfmt {field}"
    return (f'last_over_time({selector} | {parse} | __error__="" '
            f'| unwrap {field} [24h]) by (stack)')


panels += [
    panel("logs", "Chronologie : verdict du modèle, action, reprise",
          [tgt(PROBE + ' |~ "type=(evenement|incident)" | logfmt '
               '| line_format "{{.etape}} : {{.texte}}"', ds=LOKI),
           tgt(RETRAIN + f' | line_format "Modèle : démarrage ou réinitialisation sur '
               f'{{{{.host}}}}, réapprentissage de la normale ({WARMUP} s)"', ref="B", ds=LOKI)],
          (0, y, 15, H), ds=LOKI,
          options={"showTime": True, "showLabels": False, "showCommonLabels": False,
                   "wrapLogMessage": True, "prettifyLogMessage": False,
                   "enableLogDetails": False, "enableInfiniteScrolling": False,
                   "dedupStrategy": "none", "sortOrder": "Ascending"},
          desc="« Incident détecté » : anomalie confirmée par le détecteur (avec son score), "
               "lue par le moteur ; puis décision, redémarrage par la passerelle, transaction "
               "de contrôle, reprise. « Sonde » : panne et retour vus par un client réel. "
               "« Modèle » : redémarrage du détecteur ou POST /reset (nouvel échauffement). "
               "Événements du moteur recopiés par la sonde (heure à 5 s près). Vide si "
               "rien ne s'est passé sur la période."),
    stat("Dernière remédiation (24 h)",
         [tgt(last_number(EVENTS + ' |= "kind=restore"', "reprise_s",
                          r"rétabli en (?P<reprise_s>[0-9.]+) s"),
              "détection → service rétabli (moteur)", ds=LOKI, instant=True),
          tgt(last_number(EVENTS + ' |= "kind=act" |= "passerelle"', "restart_s",
                          r"en (?P<restart_s>[0-9.]+) s,"),
              "dont redémarrage par la passerelle", "B", ds=LOKI, instant=True),
          tgt(last_number(PROBE + ' |= "type=incident" |= "phase=fin"', "duree_s"),
              "panne vue par un client (sonde)", "C", ds=LOKI, instant=True)],
         (15, y, 9, H), ds=LOKI, unit="s", decimals=0, text_mode="value_and_name",
         color_mode="value", no_value="aucune",
         thresholds=steps(("green", None), ("orange", 60), ("red", 120)),
         desc=f"Durées de la dernière remédiation des 24 dernières heures, lues dans les "
              f"événements du moteur et de la sonde. S'y ajoute le délai de confirmation du "
              f"modèle ({PERSISTENCE} s de persistance ; délai de détection mesuré hors ligne : "
              f"{EVAL['Délai de détection']})."),
]
y += H


# --------------------------------------------------------------------------- #
# Annotations
# --------------------------------------------------------------------------- #
def loki_annotation(name, color, expr, title="{{etape}}", text="{{texte}}", tags="kind"):
    return {"name": name, "enable": True, "hide": False, "iconColor": color,
            "datasource": LOKI, "expr": expr, "instant": False,
            "titleFormat": title, "textFormat": text, "tagKeys": tags}


EV = EVENTS + " | logfmt"
dashboard = {
    "id": None,
    "uid": "ml-detecteur",
    "title": "Modèle ML / Détecteur d'anomalies",
    "description": "Travail du détecteur d'anomalies (IsolationForest) de Resilience Pay : état "
                   "du modèle, score, variables d'entrée, chaîne détection → remédiation, "
                   "qualité.",
    "tags": ["ml", "detecteur", "paiement"],
    "timezone": "browser",
    "editable": False,
    "graphTooltip": 1,
    "refresh": "10s",
    "time": {"from": "now-30m", "to": "now"},
    "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m", "5m"]},
    "fiscalYearStartMonth": 0,
    "liveNow": False,
    "schemaVersion": 39,
    "version": 1,
    "links": [{"title": "Démo / Remédiation", "type": "link", "url": "/d/demo-remediation",
               "icon": "dashboard", "keepTime": True, "includeVars": False,
               "targetBlank": False, "asDropdown": False, "tags": [],
               "tooltip": "Écran de la démonstration"}],
    "annotations": {"list": [
        {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
         "name": "Annotations & Alerts", "type": "dashboard"},
        loki_annotation("Anomalie confirmée (moteur)", "red", EV + ' | kind="detect"'),
        loki_annotation("Action du moteur", "orange", EV + ' | kind="act"'),
        loki_annotation("Service rétabli", "green", EV + ' | kind="restore"'),
        # Démarrage du conteneur (modèle en mémoire) ou POST /reset : nouvel échauffement
        loki_annotation("Réapprentissage du modèle", "blue", RETRAIN,
                        title="Réapprentissage du modèle",
                        text=f"Détecteur démarré ou réinitialisé sur {{{{host}}}} : "
                             f"échauffement de {WARMUP} s",
                        tags="host"),
        # Posées par infra/chaos/chaos.sh (API Grafana, tag chaos) : une zone par test
        {"name": "Tests de chaos", "enable": True, "hide": False, "iconColor": "#B877D9",
         "datasource": {"type": "grafana", "uid": "-- Grafana --"},
         "target": {"type": "tags", "tags": ["chaos"], "limit": 100, "matchAny": True}},
        {"name": "Alertes du détecteur", "enable": True, "hide": False, "iconColor": "yellow",
         "datasource": VM,
         "expr": 'ALERTS{alertstate="firing", '
                 'alertname=~"PaiementAnomalieDetectee|PaiementDetectorDown"}',
         "step": "30s", "titleFormat": "{{alertname}}", "textFormat": "{{service}}",
         "tagKeys": "severity", "useValueForTime": False}]},
    "templating": {"list": []},
    "panels": panels,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{OUT} : {len(panels)} panels (warmup {WARMUP} s, seuil {THRESHOLD}, "
      f"persistance {PERSISTENCE} s)")

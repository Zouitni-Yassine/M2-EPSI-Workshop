#!/usr/bin/env python3
"""Sonde de transaction de Resilience Pay (stack Swarm "probe", docs/application.md).

Joue le rôle d'un vrai client, par le relais public de l'application (port 5173), jamais
par les réseaux internes de la stack :

- vérification légère toutes les PROBE_HEALTH_INTERVAL s (5) : page d'accueil du frontal
  (200 et <div id="root">) puis GET /api/health (200, "ok": true) ;
- transaction complète toutes les PROBE_TRANSACTION_INTERVAL s (30) : connexion du compte
  client, création d'un paiement de PROBE_AMOUNT centimes au nom de PROBE_HOLDER ("Sonde",
  pour le reconnaître), confirmation avec la carte de test Stripe 4242..., statut attendu
  "succeeded". Après une panne, dès que la vérification légère repasse, une transaction est
  rejouée sans attendre : la fin de panne est mesurée à 5 s près, pas à 30 s ;
- observation (même cadence que la vérification légère), avec une session opérateur en
  lecture seule : score du détecteur (/detector/score) et chronologie du moteur de
  remédiation (/remediation/state). Le moteur ne journalise pas ses événements : la sonde
  les recopie dans son propre journal (donc dans Loki), une ligne par nouvel événement.

Sorties :
- /metrics (prometheus_client), métriques préfixées paiement_probe_, collectées par le
  vmagent du Swarm sur le réseau overlay "monitoring" ;
- /healthz : 200 tant que la boucle de vérification tourne (healthcheck du conteneur) ;
- stdout : une ligne logfmt par vérification ("type=etat"), par transaction
  ("type=transaction"), par début et fin de panne ("type=incident") et par événement du moteur
  ("type=evenement"). VictoriaMetrics ne garde qu'un échantillon par 30 s (déduplication) :
  le dashboard Démo lit l'état à 5 s près dans ces lignes (Loki), les métriques servent aux
  alertes et aux tendances.

Mots de passe lus dans des secrets Swarm (fichiers), jamais dans l'environnement ni dans
les journaux.
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# --------------------------------------------------------------------------- #
# Configuration (variables d'environnement de la stack)
# --------------------------------------------------------------------------- #
BASE_URLS = [u.strip().rstrip("/") for u in os.getenv("PROBE_BASE_URLS", "http://10.30.1.221:5173").split(",") if u.strip()]
HEALTH_INTERVAL = float(os.getenv("PROBE_HEALTH_INTERVAL", "5"))
TRANSACTION_INTERVAL = float(os.getenv("PROBE_TRANSACTION_INTERVAL", "30"))
HTTP_TIMEOUT = float(os.getenv("PROBE_HTTP_TIMEOUT", "4"))
TRANSACTION_TIMEOUT = float(os.getenv("PROBE_TRANSACTION_TIMEOUT", "15"))
AMOUNT = int(os.getenv("PROBE_AMOUNT", "100"))
HOLDER = os.getenv("PROBE_HOLDER", "Sonde")
CARD = os.getenv("PROBE_CARD", "4242424242424242")  # carte de test publique de Stripe
CLIENT_USER = os.getenv("PROBE_CLIENT_USER", "client")
CLIENT_PASSWORD_FILE = os.getenv("PROBE_CLIENT_PASSWORD_FILE", "/run/secrets/client_password")
OPERATOR_USER = os.getenv("PROBE_OPERATOR_USER", "operateur")
OPERATOR_PASSWORD_FILE = os.getenv("PROBE_OPERATOR_PASSWORD_FILE", "/run/secrets/operateur_password")
LISTEN_PORT = int(os.getenv("PROBE_LISTEN_PORT", "9110"))
USER_AGENT = "resilience-probe/1.0 (sonde de transaction infra)"

# Étapes du moteur (champ "kind" de /remediation/state) -> libellé affiché
ENGINE_STEPS = {
    "detect": "Incident détecté",
    "act": "Action du moteur",
    "verify": "Vérification",
    "restore": "Service rétabli",
}

# --------------------------------------------------------------------------- #
# Métriques
# --------------------------------------------------------------------------- #
CHECKS = ("sante", "transaction")
UP = Gauge("paiement_probe_up", "Dernier résultat de la vérification (1 = réussie)", ["check"])
PAYMENTS_OK = Gauge("paiement_probe_payments_ok", "État vu par la sonde : 1 = paiements possibles, 0 = en panne")
CHECKS_TOTAL = Counter("paiement_probe_checks_total", "Vérifications par résultat", ["check", "result"])
STEP_TOTAL = Counter("paiement_probe_step_total", "Étapes par résultat", ["step", "result"])
STEP_DURATION = Gauge("paiement_probe_step_duration_seconds", "Durée de la dernière exécution de l'étape", ["step"])
TRANSACTION_DURATION = Histogram(
    "paiement_probe_transaction_duration_seconds", "Durée d'une transaction complète réussie",
    buckets=(0.25, 0.5, 1, 1.5, 2, 3, 5, 8, 13, 20))
TRANSACTIONS = Counter("paiement_probe_transactions_total", "Transactions de test par statut final", ["status"])
LAST_SUCCESS = Gauge("paiement_probe_last_success_timestamp_seconds", "Horodatage du dernier succès", ["check"])
SINCE_SUCCESS = Gauge("paiement_probe_seconds_since_success", "Secondes écoulées depuis le dernier succès", ["check"])
CONSECUTIVE_FAILURES = Gauge("paiement_probe_consecutive_failures", "Échecs consécutifs", ["check"])
DOWN_SECONDS = Counter("paiement_probe_down_seconds_total", "Temps cumulé passé en panne (vu par la sonde)")
LAST_OUTAGE = Gauge("paiement_probe_last_outage_seconds", "Durée de la dernière panne terminée (vue par la sonde)")
LAST_OUTAGE_END = Gauge("paiement_probe_last_outage_end_timestamp_seconds", "Fin de la dernière panne terminée")
OBSERVER_UP = Gauge("paiement_probe_observer_up", "Lecture du détecteur et du moteur avec la session opérateur (1 = OK)")
DETECTOR_SCORE = Gauge("paiement_probe_detector_score", "Score d'anomalie courant du détecteur (recopié de /detector/score)")
DETECTOR_THRESHOLD = Gauge("paiement_probe_detector_threshold", "Seuil d'anomalie du détecteur")
DETECTOR_ANOMALY = Gauge("paiement_probe_detector_anomaly", "Anomalie confirmée par le détecteur (1 = oui)")
DETECTOR_READY = Gauge("paiement_probe_detector_ready", "Détecteur entraîné (1) ou en apprentissage (0)")
ENGINE_ACTIVE = Gauge("paiement_probe_remediation_in_progress", "Moteur de remédiation en action (1) ou en veille (0)")
ENGINE_ACTIONS = Gauge("paiement_probe_remediation_actions", "Actions du moteur depuis son démarrage")
ENGINE_RECOVERY = Gauge("paiement_probe_remediation_last_recovery_seconds", "Dernier temps de reprise mesuré par le moteur")
ENGINE_EVENTS = Counter("paiement_probe_remediation_events_total", "Événements du moteur vus par la sonde", ["kind"])

for _c in CHECKS:
    UP.labels(_c).set(0)
    CONSECUTIVE_FAILURES.labels(_c)
    for _r in ("ok", "echec"):
        CHECKS_TOTAL.labels(_c, _r)
for _s in ("frontal", "sante", "connexion", "creation", "confirmation"):
    for _r in ("ok", "echec"):
        STEP_TOTAL.labels(_s, _r)
for _k in ENGINE_STEPS:
    ENGINE_EVENTS.labels(_k)


# --------------------------------------------------------------------------- #
# Journal logfmt
# --------------------------------------------------------------------------- #
_log_lock = threading.Lock()


def _fmt(value) -> str:
    if isinstance(value, float):
        value = f"{value:.3f}".rstrip("0").rstrip(".")
    text = str(value)
    if text == "" or any(c in text for c in ' "=\t\n'):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'
    return text


def log(**fields) -> None:
    line = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items() if v is not None)
    with _log_lock:
        print(line, flush=True)


# --------------------------------------------------------------------------- #
# Client HTTP (cookies de session, comme un navigateur)
# --------------------------------------------------------------------------- #
class Session:
    def __init__(self, user: str, password_file: str) -> None:
        self.user = user
        self.password_file = password_file
        self.base = BASE_URLS[0]
        self._new_jar()

    def _new_jar(self) -> None:
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method: str, path: str, body=None, timeout: float = HTTP_TIMEOUT, base: str | None = None):
        """(code HTTP, corps JSON ou texte). Code 0 : pas de réponse (refus, délai)."""
        req = urllib.request.Request(
            (base or self.base) + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": USER_AGENT})
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                code = resp.status
        except urllib.error.HTTPError as exc:
            raw, code = exc.read(), exc.code
        except Exception as exc:  # refus de connexion, délai, DNS
            return 0, type(exc).__name__
        try:
            return code, json.loads(raw or b"{}")
        except ValueError:
            return code, raw.decode("utf-8", "replace")

    def login(self, timeout: float = HTTP_TIMEOUT) -> int:
        self._new_jar()
        with open(self.password_file, encoding="utf-8") as fh:
            password = fh.read().strip()
        code, _ = self.call("POST", "/auth/login", {"username": self.user, "password": password}, timeout)
        return code


# --------------------------------------------------------------------------- #
# État partagé
# --------------------------------------------------------------------------- #
_lock = threading.Lock()
_state = {
    "health_ok": None,           # dernier résultat de la vérification légère
    "tx_ok": None,               # dernier résultat de transaction
    "last_success": {c: None for c in CHECKS},
    "failures": {c: 0 for c in CHECKS},
    "outage_start": None,        # début de la panne en cours (vue par la sonde)
    "last_tick": time.time(),
    "detector": {},
    "engine_status": None,
    "fast_retries": 0,           # transactions rejouées sans attendre depuis le retour de l'API
}
FAST_RETRIES = 6  # au plus 6 essais rapprochés (30 s), ensuite retour à la cadence normale
_wake_transaction = threading.Event()
_stop = threading.Event()


def _since(check: str) -> float:
    with _lock:
        ts = _state["last_success"][check]
    return round(time.time() - ts, 1) if ts else float("nan")


for _c in CHECKS:
    SINCE_SUCCESS.labels(_c).set_function(lambda c=_c: _since(c))


def record(check: str, ok: bool, at: float | None = None) -> None:
    """Résultat d'une vérification : compteurs, puis transitions panne / reprise.

    at : instant retenu pour le début ou la fin de panne. Pour la vérification légère, c'est
    son lancement : une vérification qui échoue par délai dépassé (4 s) date la panne du moment
    où elle a commencé, pas de la fin de son attente.
    """
    now = time.time()
    edge = at or now
    CHECKS_TOTAL.labels(check, "ok" if ok else "echec").inc()
    UP.labels(check).set(1 if ok else 0)
    with _lock:
        if ok:
            _state["last_success"][check] = now
            _state["failures"][check] = 0
        else:
            _state["failures"][check] += 1
        CONSECUTIVE_FAILURES.labels(check).set(_state["failures"][check])
        if ok:
            LAST_SUCCESS.labels(check).set(now)
        _state["health_ok" if check == "sante" else "tx_ok"] = ok
        # Paiements possibles = frontal et API répondent, et la dernière transaction a réussi
        # (inconnue au démarrage : seule la vérification légère compte).
        down = _state["health_ok"] is False or _state["tx_ok"] is False
        PAYMENTS_OK.set(0 if down else 1)
        start = _state["outage_start"]
        if down and start is None:
            _state["outage_start"] = edge
            cause = "vérification légère" if _state["health_ok"] is False else "transaction"
            log(type="incident", phase="debut", etape="Sonde : paiements en panne",
                texte=f"Paiements en panne (échec : {cause})")
        elif not down and start is not None:
            _state["outage_start"] = None
            duration = max(0.0, edge - start)
            LAST_OUTAGE.set(round(duration, 1))
            LAST_OUTAGE_END.set(now)
            log(type="incident", phase="fin", etape="Sonde : paiements rétablis", duree_s=round(duration, 1),
                texte=f"Paiements rétablis après {duration:.0f} s de panne (vue par la sonde)")


def step(name: str, ok: bool, started: float) -> None:
    STEP_TOTAL.labels(name, "ok" if ok else "echec").inc()
    STEP_DURATION.labels(name).set(round(time.time() - started, 3))


# --------------------------------------------------------------------------- #
# Vérification légère + observation (toutes les HEALTH_INTERVAL s)
# --------------------------------------------------------------------------- #
anon = Session("anonyme", "")
operator = Session(OPERATOR_USER, OPERATOR_PASSWORD_FILE)
_seen_events: set[str] = set()
_events_primed = False


def health_check() -> tuple[bool, str]:
    """Frontal puis /api/health, sur la première adresse qui répond (repli sur les suivantes)."""
    detail = ""
    for base in BASE_URLS:
        t0 = time.time()
        code, body = anon.call("GET", "/", base=base)
        front_ok = code == 200 and isinstance(body, str) and 'id="root"' in body
        step("frontal", front_ok, t0)
        if code == 0:
            detail = f"frontal injoignable ({body}) sur {base}"
            continue  # nœud ou port injoignable : adresse suivante, comme le WAF
        if not front_ok:
            return False, f"frontal : HTTP {code}"
        t0 = time.time()
        code, body = anon.call("GET", "/api/health", base=base)
        api_ok = code == 200 and isinstance(body, dict) and body.get("ok") is True
        step("sante", api_ok, t0)
        if api_ok:
            anon.base = base
            return True, base
        return False, f"/api/health : HTTP {code}"
    return False, detail


def observe() -> None:
    """Score du détecteur et chronologie du moteur, avec la session opérateur."""
    global _events_primed
    code, score = operator.call("GET", "/detector/score", base=anon.base)
    if code in (401, 403):
        operator.base = anon.base
        if operator.login() == 200:
            code, score = operator.call("GET", "/detector/score", base=anon.base)
    code2, engine = operator.call("GET", "/remediation/state", base=anon.base) if code == 200 else (code, None)
    ok = code == 200 and code2 == 200 and isinstance(score, dict) and isinstance(engine, dict)
    OBSERVER_UP.set(1 if ok else 0)
    if not ok:
        with _lock:
            _state["detector"], _state["engine_status"] = {}, None
        return
    current, threshold = score.get("current"), score.get("threshold")
    if current is not None:
        DETECTOR_SCORE.set(float(current))
    if threshold is not None:
        DETECTOR_THRESHOLD.set(float(threshold))
    DETECTOR_ANOMALY.set(1 if score.get("over") else 0)
    DETECTOR_READY.set(1 if score.get("status") == "ready" else 0)
    ENGINE_ACTIVE.set(1 if engine.get("status") == "remediating" else 0)
    ENGINE_ACTIONS.set(engine.get("actions") or 0)
    if engine.get("lastRecoverySeconds") is not None:
        ENGINE_RECOVERY.set(engine["lastRecoverySeconds"])
    with _lock:
        _state["detector"] = {"score": current, "seuil": threshold, "anomalie": bool(score.get("over")),
                              "detecteur": score.get("status")}
        _state["engine_status"] = engine.get("status")
    # Nouveaux événements, du plus ancien au plus récent. Au premier passage, l'historique
    # déjà présent n'est pas rejoué (il le serait à chaque redémarrage de la sonde).
    events = [e for e in (engine.get("events") or []) if isinstance(e, dict) and e.get("id")]
    for ev in reversed(events):
        if ev["id"] in _seen_events:
            continue
        _seen_events.add(ev["id"])
        if not _events_primed:
            continue
        kind = ev.get("kind", "")
        if kind in ENGINE_STEPS:
            ENGINE_EVENTS.labels(kind).inc()
        log(type="evenement", source="moteur", kind=kind, etape=ENGINE_STEPS.get(kind, kind),
            at=ev.get("at"), texte=ev.get("text", ""))
    _events_primed = True


def health_loop() -> None:
    while not _stop.is_set():
        t0 = time.time()
        ok, detail = health_check()
        record("sante", ok, at=t0)
        try:
            observe()
        except Exception as exc:  # une réponse inattendue ne doit pas arrêter la sonde
            OBSERVER_UP.set(0)
            log(type="erreur", texte=f"observation : {type(exc).__name__}")
        with _lock:
            _state["last_tick"] = time.time()
            down = _state["health_ok"] is False or _state["tx_ok"] is False
            det, engine = dict(_state["detector"]), _state["engine_status"]
            if not ok:
                _state["fast_retries"] = 0
            retry = ok and _state["tx_ok"] is False and _state["fast_retries"] < FAST_RETRIES
            if retry:
                _state["fast_retries"] += 1
            since_tx = _state["last_success"]["transaction"]
        log(type="etat", paiements="panne" if down else "ok", panne=1 if down else 0,
            sante="ok" if ok else "echec", detail=None if ok else detail,
            depuis_succes_s=round(time.time() - since_tx, 1) if since_tx else None,
            score=round(det["score"], 3) if det.get("score") is not None else None,
            seuil=det.get("seuil"), anomalie=(1 if det.get("anomalie") else 0) if det else None,
            moteur=engine, remediation=(1 if engine == "remediating" else 0) if engine else None)
        if retry:
            _wake_transaction.set()  # l'API répond de nouveau : rejouer une transaction tout de suite
        _stop.wait(max(0.0, HEALTH_INTERVAL - (time.time() - t0)))


# --------------------------------------------------------------------------- #
# Transaction complète (toutes les TRANSACTION_INTERVAL s)
# --------------------------------------------------------------------------- #
client = Session(CLIENT_USER, CLIENT_PASSWORD_FILE)


def transaction() -> tuple[bool, str, str]:
    """(réussie, étape en échec ou "", détail). Une nouvelle session à chaque fois."""
    client.base = anon.base
    t0 = time.time()
    code = client.login(TRANSACTION_TIMEOUT)
    step("connexion", code == 200, t0)
    if code != 200:
        return False, "connexion", f"HTTP {code}"
    t0 = time.time()
    code, pi = client.call("POST", "/api/payment_intents", {"amount": AMOUNT, "holder": HOLDER}, TRANSACTION_TIMEOUT)
    created = code == 201 and isinstance(pi, dict) and pi.get("id")
    step("creation", bool(created), t0)
    if not created:
        return False, "creation", f"HTTP {code}"
    t0 = time.time()
    code, conf = client.call("POST", f"/api/payment_intents/{pi['id']}/confirm", {"number": CARD}, TRANSACTION_TIMEOUT)
    status = conf.get("status") if isinstance(conf, dict) else None
    confirmed = code == 200 and status == "succeeded"
    step("confirmation", confirmed, t0)
    if not confirmed:
        return False, "confirmation", f"HTTP {code}, statut {status}"
    return True, "", str(pi["id"])


def transaction_loop() -> None:
    while not _stop.is_set():
        t0 = time.time()
        try:
            ok, failed_step, detail = transaction()
        except Exception as exc:
            ok, failed_step, detail = False, "interne", type(exc).__name__
        duration = time.time() - t0
        if ok:
            TRANSACTION_DURATION.observe(duration)
            TRANSACTIONS.labels("succeeded").inc()
        else:
            TRANSACTIONS.labels("echec_" + failed_step).inc()
        record("transaction", ok)
        log(type="transaction", result="ok" if ok else "echec", etape_echec=failed_step or None,
            duree_ms=int(duration * 1000), montant=AMOUNT, detail=detail if not ok else None,
            paiement=detail if ok else None)
        _wake_transaction.clear()
        # Prochaine transaction : à l'échéance, ou plus tôt si la vérification légère constate
        # le retour de l'API après un échec (au plus une fois par HEALTH_INTERVAL).
        _wake_transaction.wait(max(0.0, TRANSACTION_INTERVAL - duration))
        if _wake_transaction.is_set():
            _stop.wait(max(0.0, HEALTH_INTERVAL - (time.time() - t0)))


# --------------------------------------------------------------------------- #
# Serveur HTTP : /metrics et /healthz
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/metrics"):
            body, ctype, code = generate_latest(), CONTENT_TYPE_LATEST, 200
        elif self.path.startswith("/healthz"):
            with _lock:
                alive = time.time() - _state["last_tick"] < 6 * HEALTH_INTERVAL + 30
            body, ctype, code = (b"ok\n" if alive else b"bloquee\n"), "text/plain", (200 if alive else 503)
        else:
            body, ctype, code = b"not found\n", "text/plain", 404
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # pas de ligne par scrape
        pass


def main() -> None:
    for f in (CLIENT_PASSWORD_FILE, OPERATOR_PASSWORD_FILE):
        if not os.access(f, os.R_OK):
            print(f"sonde : secret illisible : {f}", file=sys.stderr, flush=True)
            sys.exit(2)
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log(type="demarrage", urls=",".join(BASE_URLS), sante_s=HEALTH_INTERVAL, transaction_s=TRANSACTION_INTERVAL,
        montant=AMOUNT, titulaire=HOLDER, port=LISTEN_PORT)
    signal.signal(signal.SIGTERM, lambda *_: _stop.set())
    workers = [threading.Thread(target=health_loop, daemon=True), threading.Thread(target=transaction_loop, daemon=True)]
    for w in workers:
        w.start()
    _stop.wait()
    _wake_transaction.set()
    server.shutdown()


if __name__ == "__main__":
    main()

"""
Moteur de remédiation — Resilience Pay.

Écoute le verdict du détecteur. Quand une anomalie est confirmée, il décide,
agit sur le conteneur visé, puis vérifie que le service métier répond de
nouveau avant de déclarer la reprise. Aucun opérateur n'intervient.

Ses droits sont volontairement étroits, et il n'expose aucune route d'écriture.
Deux chemins pour agir, choisis par REMEDIATION_MODE :

- `docker` (défaut, compose local) : un proxy du socket Docker qui n'autorise
  que le redémarrage, et uniquement sur les conteneurs de sa liste ;
- `ssh` (cluster Swarm) : la passerelle `remediate` des managers, jointe en SSH
  avec une clé dédiée. Elle n'accepte qu'une liste fermée d'actions sur les
  stacks autorisées, avec limitation de débit. Pas de socket Docker.
"""

from __future__ import annotations

import atexit
import collections
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DETECTOR_URL = os.getenv("DETECTOR_URL", "http://detector:8100")
API_URL = os.getenv("API_URL", "http://payment-api:8000/api")
DOCKER_URL = os.getenv("DOCKER_URL", "http://docker-socket-proxy:2375")
# Les seuls conteneurs sur lesquels le moteur a le droit d'agir.
TARGETS = [t.strip() for t in os.getenv("TARGETS", "payment-api").split(",") if t.strip()]
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "45"))
VERIFY_TIMEOUT = int(os.getenv("VERIFY_TIMEOUT", "40"))
ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:4173").split(",") if o.strip()]

# Chemin d'action : "docker" (proxy du socket, compose local) ou "ssh" (passerelle Swarm).
MODE = os.getenv("REMEDIATION_MODE", "docker").strip().lower()
if MODE not in ("docker", "ssh"):
    raise RuntimeError(f"REMEDIATION_MODE inconnu : {MODE!r} (attendu : docker ou ssh)")
# Managers qui portent la passerelle, essayés dans l'ordre : un manager peut être en panne.
GATEWAYS = [g.strip() for g in os.getenv("REMEDIATION_GATEWAYS", "").split(",") if g.strip()]
SSH_USER = os.getenv("REMEDIATION_SSH_USER", "remediation")
SSH_KEY_FILE = os.getenv("REMEDIATION_SSH_KEY_FILE", "/run/secrets/remediation_ssh_key")
KNOWN_HOSTS_FILE = os.getenv("REMEDIATION_KNOWN_HOSTS_FILE", "/run/configs/remediation_known_hosts")
# La passerelle attend la convergence du service (180 s au plus) avant de répondre.
SSH_TIMEOUT = int(os.getenv("REMEDIATION_SSH_TIMEOUT", "200"))

# Même règle que la passerelle (infra/ansible/roles/remediation_gateway/files/remediate) :
# un nom refusé ici ne part jamais sur le réseau.
SERVICE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]{0,252}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SSH_UNREACHABLE = 255  # code de ssh lui-même : connexion, hôte inconnu ou authentification refusée
GATEWAY_CODES = {
    2: "requête invalide",
    3: "refusé par la politique",
    4: "limite de débit atteinte",
    5: "échec Docker ou délai de convergence dépassé",
}

if MODE == "ssh":
    if not GATEWAYS or not all(HOST_RE.match(g) for g in GATEWAYS):
        raise RuntimeError("REMEDIATION_GATEWAYS vide ou mal formé")
    if not USER_RE.match(SSH_USER):
        raise RuntimeError("REMEDIATION_SSH_USER mal formé")

app = FastAPI(title="Resilience Pay — remédiation", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET"], allow_headers=["*"])

_lock = threading.Lock()
_state: dict[str, Any] = {
    "status": "idle",
    "events": collections.deque(maxlen=50),
    "actions": 0,
    "humanActions": 0,
    "cooldownUntil": 0.0,
    "lastRecoverySeconds": None,
}


def _clock() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def event(kind: str, text: str) -> None:
    with _lock:
        _state["events"].appendleft(
            {"id": uuid.uuid4().hex[:8], "at": _clock(), "kind": kind, "text": text, "actor": "plateforme"}
        )


def verdict() -> dict[str, Any]:
    try:
        return requests.get(f"{DETECTOR_URL}/score", timeout=0.9).json()
    except Exception:
        return {"status": "absent", "over": False, "current": None, "threshold": None}


def service_ok() -> bool:
    """La reprise se juge sur le métier : l'API répond et sa sonde Stripe passe."""
    try:
        body = requests.get(f"{API_URL}/status", timeout=1.5).json()
        return body.get("api") == "up" and bool(body.get("stripe", {}).get("up"))
    except Exception:
        return False


class RateLimited(RuntimeError):
    """La passerelle a refusé pour cause de débit (code 4) : pas un échec, on réessaiera."""

    def __init__(self, message: str, retry_in: int | None) -> None:
        super().__init__(message)
        self.retry_in = retry_in


_key_lock = threading.Lock()
_key_path: str | None = None


def _short(text: str, size: int = 120) -> str:
    return " ".join((text or "").split())[:size]


def ssh_key() -> str:
    """Copie de la clé privée dans un fichier 0600 du tmpfs /tmp.

    Le secret Swarm est monté en lecture seule, avec des droits que ssh peut refuser
    (0444) ; le conteneur est read_only, seul /tmp est inscriptible. La clé n'est
    jamais journalisée, seul son chemin l'est en cas d'erreur.
    """
    global _key_path
    with _key_lock:
        if _key_path and os.path.exists(_key_path):
            return _key_path
        try:
            with open(SSH_KEY_FILE, "rb") as src:
                data = src.read()
        except OSError as exc:
            raise RuntimeError(f"clé SSH illisible ({SSH_KEY_FILE} : {exc.strerror})") from None
        fd, path = tempfile.mkstemp(prefix="remediation-key-")  # créé en 0600
        with os.fdopen(fd, "wb") as dst:
            dst.write(data)
        os.chmod(path, 0o600)
        atexit.register(lambda: os.path.exists(path) and os.remove(path))
        _key_path = path
        return path


def gateway(*args: str) -> tuple[int, dict[str, Any], str]:
    """Envoie une commande à la passerelle, en essayant les managers dans l'ordre.

    Renvoie (code retour, réponse JSON, manager qui a répondu). On ne passe au manager
    suivant que si ssh n'a pas pu le joindre (code 255) : une réponse de la passerelle,
    même un refus, est définitive. Un délai dépassé ne fait pas non plus essayer le
    suivant : l'action est peut-être en cours, la relancer ailleurs la doublerait.
    """
    key = ssh_key()
    command = " ".join(args)
    unreachable = []
    for gw in GATEWAYS:
        argv = [
            "ssh", "-T", "-F", "/dev/null",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={KNOWN_HOSTS_FILE}",
            "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3",
            "-o", "IdentitiesOnly=yes",
            "-o", "LogLevel=ERROR",
            "-i", key,
            f"{SSH_USER}@{gw}",
            command,
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=SSH_TIMEOUT,
                                  stdin=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"la passerelle {gw} n'a pas répondu en {SSH_TIMEOUT} s") from None
        if proc.returncode == SSH_UNREACHABLE:
            unreachable.append(gw)
            event("act", f"Passerelle {gw} injoignable ({_short(proc.stderr, 80)}), essai de la suivante")
            continue
        lines = (proc.stdout or "").strip().splitlines()
        try:
            payload = json.loads(lines[-1]) if lines else {}
        except ValueError:
            payload = {"error": _short(proc.stdout or proc.stderr)}
        if not isinstance(payload, dict):
            payload = {"error": _short(str(payload))}
        return proc.returncode, payload, gw
    raise ConnectionError(f"aucune passerelle joignable ({', '.join(unreachable) or 'liste vide'})")


def _restart_ssh(target: str) -> str:
    code, out, gw = gateway("restart", target)
    if code == 0:
        replicas = ""
        if out.get("replicas_desired") is not None:
            replicas = f", {out.get('replicas_running')}/{out.get('replicas_desired')} réplicas en marche"
        return (f"redémarré par la passerelle {gw} en {out.get('duration_s', '?')} s{replicas}"
                " — actions limitées à une liste fermée")
    detail = _short(str(out.get("error") or ""), 100)
    if code == 4:
        raise RateLimited(f"{GATEWAY_CODES[4]} sur {gw} ({detail})", out.get("retry_in"))
    reason = GATEWAY_CODES.get(code, "erreur inattendue")
    raise RuntimeError(f"passerelle {gw}, code {code} ({reason}) : {detail}")


def restart(target: str) -> str:
    """Redémarre une cible de la liste ; renvoie le texte de l'événement de réussite."""
    if target not in TARGETS:
        raise PermissionError(f"{target} n'est pas dans la liste des cibles autorisées")
    if MODE == "ssh":
        if not SERVICE_RE.match(target):
            raise PermissionError(f"{target!r} n'est pas un nom de service valide")
        return _restart_ssh(target)
    res = requests.post(f"{DOCKER_URL}/containers/{target}/restart", params={"t": 5}, timeout=30)
    if res.status_code not in (204, 304):
        # Le proxy répond parfois en HTML : on n'en garde que le texte, court.
        detail = re.sub(r"<[^>]+>", " ", res.text)
        detail = " ".join(detail.split())[:80]
        raise RuntimeError(f"Docker a répondu {res.status_code} : {detail}")
    return "redémarré via le proxy Docker — droits limités au redémarrage"


def remediate(score: float | None, threshold: float | None) -> None:
    started = time.time()
    with _lock:
        _state["status"] = "remediating"
        _state["actions"] += 1

    shown = f"score {score:.2f} ≥ {threshold:.2f}" if score is not None and threshold is not None else "détecteur"
    event("detect", f"Anomalie confirmée par le détecteur ({shown})")
    event("act", f"Décision : recréer {TARGETS[0]} à partir de son image")

    try:
        event("act", f"{TARGETS[0]} {restart(TARGETS[0])}")
    except RateLimited as exc:
        # La passerelle protège le service contre les redémarrages en rafale : on ne
        # vérifie rien, on rend la main et on retentera après le délai indiqué.
        wait = max(int(exc.retry_in), 5) if exc.retry_in else COOLDOWN_SECONDS
        event("act", f"Action différée : {exc} — nouvel essai dans {wait} s")
        with _lock:
            _state["status"] = "idle"
            _state["cooldownUntil"] = time.time() + wait
        return
    except Exception as exc:
        event("act", f"Échec du redémarrage : {exc}")

    deadline = time.time() + VERIFY_TIMEOUT
    while time.time() < deadline and not service_ok():
        time.sleep(1)

    if service_ok():
        event("verify", "Transaction de contrôle passée — l’API répond et Stripe est joignable")
        # On attend que le détecteur lui-même retire son verdict : la reprise
        # n'est déclarée que quand plus personne ne voit d'anomalie.
        calm_deadline = time.time() + 30
        while time.time() < calm_deadline and verdict().get("over"):
            time.sleep(1)
        elapsed = int(time.time() - started)
        with _lock:
            _state["lastRecoverySeconds"] = elapsed
        event("restore", f"Service rétabli en {elapsed} s — 0 intervention humaine")
    else:
        event("verify", f"{TARGETS[0]} ne répond toujours pas après {VERIFY_TIMEOUT} s — escalade nécessaire")

    with _lock:
        _state["status"] = "idle"
        _state["cooldownUntil"] = time.time() + COOLDOWN_SECONDS


def loop() -> None:
    if MODE == "ssh":
        # Vérification au démarrage : une clé absente se voit dans les logs tout de suite,
        # pas au moment de la première panne. On ne s'arrête pas : le secret peut arriver.
        try:
            ssh_key()
            print(f"remédiation : mode ssh, passerelles {', '.join(GATEWAYS)}", flush=True)
        except Exception as exc:
            print(f"remédiation : mode ssh, {exc}", flush=True)
    while True:
        v = verdict()
        with _lock:
            idle = _state["status"] == "idle"
            cooled = time.time() >= _state["cooldownUntil"]
        if idle and cooled and v.get("status") == "ready" and v.get("over"):
            remediate(v.get("current"), v.get("threshold"))
        time.sleep(1)


threading.Thread(target=loop, daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    with _lock:
        return {"ok": True, "status": _state["status"], "targets": TARGETS, "mode": MODE}


@app.get("/state")
def state() -> dict[str, Any]:
    with _lock:
        return {
            "status": _state["status"],
            "events": list(_state["events"]),
            "actions": _state["actions"],
            "humanActions": _state["humanActions"],
            "cooldownUntil": _state["cooldownUntil"],
            "lastRecoverySeconds": _state["lastRecoverySeconds"],
            "targets": TARGETS,
        }

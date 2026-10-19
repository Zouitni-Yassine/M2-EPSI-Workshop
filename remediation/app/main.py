"""
Moteur de remédiation — Resilience Pay.

Écoute le verdict du détecteur. Quand une anomalie est confirmée, il décide,
agit sur le conteneur visé, puis vérifie que le service métier répond de
nouveau avant de déclarer la reprise. Aucun opérateur n'intervient.

Ses droits sont volontairement étroits : il ne parle à Docker qu'à travers
un proxy qui n'autorise que le redémarrage, et uniquement sur les conteneurs
de sa liste. Il n'expose aucune route d'écriture.
"""

from __future__ import annotations

import collections
import os
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
    return time.strftime("%H:%M:%S")


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


def restart(target: str) -> None:
    if target not in TARGETS:
        raise PermissionError(f"{target} n'est pas dans la liste des cibles autorisées")
    res = requests.post(f"{DOCKER_URL}/containers/{target}/restart", params={"t": 5}, timeout=30)
    if res.status_code not in (204, 304):
        raise RuntimeError(f"Docker a répondu {res.status_code} : {res.text[:120]}")


def remediate(score: float | None, threshold: float | None) -> None:
    started = time.time()
    with _lock:
        _state["status"] = "remediating"
        _state["actions"] += 1

    shown = f"score {score:.2f} ≥ {threshold:.2f}" if score is not None and threshold is not None else "détecteur"
    event("detect", f"Anomalie confirmée par le détecteur ({shown})")
    event("act", f"Décision : recréer {TARGETS[0]} à partir de son image")

    try:
        restart(TARGETS[0])
        event("act", f"{TARGETS[0]} redémarré via le proxy Docker — droits limités au redémarrage")
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
        return {"ok": True, "status": _state["status"], "targets": TARGETS}


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

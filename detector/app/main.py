"""
Détecteur d'anomalies — Resilience Pay.

Lit l'état de payment-api chaque seconde, apprend ce qu'est un trafic normal
pendant la période d'échauffement, puis attribue un score d'anomalie à chaque
seconde avec un IsolationForest. Aucune règle codée en dur : le modèle ne sait
pas ce qu'est une attaque, il sait ce qu'est la normale et mesure l'écart.

Le score est publié sur /score. La supervision l'affiche, le moteur de
remédiation s'en sert pour décider.
"""

from __future__ import annotations

import collections
import hmac
import os
import threading
import time
from typing import Any

import numpy as np
import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sklearn.ensemble import IsolationForest

API_URL = os.getenv("API_URL", "http://localhost:8000/api")
WARMUP_SECONDS = int(os.getenv("WARMUP_SECONDS", "120"))
THRESHOLD = float(os.getenv("THRESHOLD", "0.55"))
# Secondes consécutives au-dessus du seuil avant de confirmer : une seconde
# isolée est un soubresaut, trois sont une anomalie.
PERSISTENCE = int(os.getenv("PERSISTENCE", "3"))
WINDOW = 120

# Qui a le droit de réinitialiser le modèle. Sans jeton, personne : effacer la
# normale, c'est aveugler la détection — exactement ce qu'un attaquant voudrait.
ADMIN_TOKEN = os.getenv("DETECTOR_ADMIN_TOKEN", "")
ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:4173").split(",") if o.strip()]

# Six variables, toutes réellement observées sur payment-api.
FEATURES = ["rps", "errRate", "p95", "stripeLatency", "apiUp", "stripeUp"]

# Échelle minimale de chaque variable, dans son unité. Une plateforme calme
# a des variables quasi constantes ; sans plancher, la moindre requête
# deviendrait un écart infini. Ce sont des unités, pas des règles.
SCALE_FLOOR = np.array([1.0, 0.05, 100.0, 100.0, 0.5, 0.5])

app = FastAPI(title="Resilience Pay — détecteur", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["GET"], allow_headers=["*"])

_lock = threading.Lock()
_state: dict[str, Any] = {
    "status": "learning",
    "model": None,
    "mu": None,
    "sd": None,
    "train": [],
    "points": collections.deque(maxlen=WINDOW),
    "seq": 0,
    "last": None,
    "trained_at": None,
    "ema": None,
    "streak": 0,
    "over": False,
}


def sample() -> list[float]:
    """Une observation. Quand l'API ne répond pas, c'est une observation aussi."""
    try:
        res = requests.get(f"{API_URL}/status", timeout=0.9)
        body = res.json()
        m, s = body["metrics"], body["stripe"]
        return [
            float(m["rps"]),
            float(m["errRate"]),
            float(m["p95"]),
            float(s["latencyMs"]),
            1.0,
            1.0 if s["up"] else 0.0,
        ]
    except Exception:
        return [0.0, 1.0, 0.0, 0.0, 0.0, 0.0]


def to_score(decision: float) -> float:
    """decision_function : positif = normal, négatif = anormal. Ramené sur [0, 1], 0.5 à la frontière."""
    return float(min(1.0, max(0.0, 0.5 - 2.0 * decision)))


def fit(train: list[list[float]]) -> tuple[IsolationForest, np.ndarray, np.ndarray]:
    """Deux lectures de la normale : la forêt, et la distance robuste à ce qui a été vu."""
    data = np.array(train)
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42).fit(data)
    mu = np.median(data, axis=0)
    mad = np.median(np.abs(data - mu), axis=0) * 1.4826
    sd = np.maximum(np.maximum(mad, data.std(axis=0)), SCALE_FLOOR)
    return model, mu, sd


def distance_score(x: list[float], mu: np.ndarray, sd: np.ndarray) -> float:
    """Écart quadratique moyen en unités d'écart-type, ramené sur [0, 1]."""
    z = (np.array(x) - mu) / sd
    return float(1.0 - np.exp(-np.sqrt(np.mean(z**2)) / 4.0))


def loop() -> None:
    while True:
        started = time.time()
        x = sample()
        with _lock:
            model = _state["model"]
            if model is None:
                # On n'apprend que des secondes où l'API répond : la normale, pas la panne.
                if x[4] == 1.0:
                    _state["train"].append(x)
                if len(_state["train"]) >= WARMUP_SECONDS:
                    _state["model"], _state["mu"], _state["sd"] = fit(_state["train"])
                    _state["status"] = "ready"
                    _state["trained_at"] = time.time()
                score = None
            else:
                forest = to_score(model.decision_function(np.array([x]))[0])
                distance = distance_score(x, _state["mu"], _state["sd"])
                raw = max(forest, distance)
                # Lissage pour l'affichage, persistance pour la décision.
                _state["ema"] = raw if _state["ema"] is None else 0.5 * _state["ema"] + 0.5 * raw
                _state["streak"] = _state["streak"] + 1 if raw >= THRESHOLD else 0
                _state["over"] = _state["streak"] >= PERSISTENCE
                score = _state["ema"]
            _state["seq"] += 1
            if score is not None:
                _state["points"].append({"seq": _state["seq"], "score": round(score, 3)})
            _state["last"] = dict(zip(FEATURES, x))
        time.sleep(max(0.0, 1.0 - (time.time() - started)))


threading.Thread(target=loop, daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    with _lock:
        return {"ok": True, "status": _state["status"], "samples": len(_state["train"])}


@app.get("/score")
def score() -> dict[str, Any]:
    with _lock:
        points = list(_state["points"])
        current = points[-1]["score"] if points else None
        return {
            "status": _state["status"],
            "progress": min(1.0, len(_state["train"]) / WARMUP_SECONDS),
            "warmupSeconds": WARMUP_SECONDS,
            "threshold": THRESHOLD,
            "current": current,
            "over": bool(_state["over"]),
            "persistence": PERSISTENCE,
            "points": points,
            "features": FEATURES,
            "last": _state["last"],
            "trainedAt": _state["trained_at"],
        }


@app.post("/reset")
def reset(x_admin_token: str = Header(default="")) -> dict[str, Any]:
    """Réapprend la normale à partir de maintenant. Réservé à l'opérateur qui détient le jeton."""
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="DETECTOR_ADMIN_TOKEN non configuré : réinitialisation désactivée")
    if not hmac.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(status_code=403, detail="Jeton d'administration invalide")
    with _lock:
        _state.update(status="learning", model=None, mu=None, sd=None, train=[], trained_at=None, ema=None, streak=0, over=False)
        _state["points"].clear()
    return {"ok": True}

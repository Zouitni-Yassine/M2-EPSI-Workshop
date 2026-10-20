"""
Métriques Prometheus de payment-api, et le journal JSON des paiements.

Ce que l'infra collecte sur /metrics (contrat de déploiement, § 4) :

    payments_total{provider, status}            ok · refused · error
    http_requests_total{method, route, code}
    http_request_duration_seconds{method, route}
    payment_api_dependency_up{dependency}       stripe · paypal · db

Les routes sont étiquetées par leur modèle (/api/payment_intents/{intent_id}), jamais par
l'URL brute : un identifiant par série ferait exploser le stockage. Une URL qui ne
correspond à aucune route — un scan, typiquement — compte sous route="unmatched".
"""

from __future__ import annotations

import collections
import logging
import threading
from typing import Any

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

log = logging.getLogger("payment-api.payments")

PAYMENTS = Counter(
    "payments_total",
    "Paiements arrivés à leur issue (ok, refused) et échecs du prestataire (error)",
    ["provider", "status"],
)
REQUESTS = Counter("http_requests_total", "Requêtes HTTP reçues", ["method", "route", "code"])
LATENCY = Histogram("http_request_duration_seconds", "Durée de traitement des requêtes HTTP", ["method", "route"])
DEPENDENCY_UP = Gauge("payment_api_dependency_up", "1 si la dépendance répond à payment-api", ["dependency"])

for _provider in ("stripe", "paypal"):
    for _status in ("ok", "refused", "error"):
        PAYMENTS.labels(_provider, _status)  # séries présentes à 0 : rate() et les alertes fonctionnent dès le départ

# Issue d'un paiement : comptée une seule fois, même si le frontend relit le paiement ensuite.
_OUTCOME = {"succeeded": "ok", "canceled": "refused"}
_counted: collections.OrderedDict[str, None] = collections.OrderedDict()
_lock = threading.Lock()


def observe_http(request: Request, code: int, seconds: float) -> None:
    route = getattr(request.scope.get("route"), "path", None) or "unmatched"
    if route == "/metrics":
        return
    REQUESTS.labels(request.method, route, str(code)).inc()
    LATENCY.labels(request.method, route).observe(seconds)


def payment(intent: dict[str, Any], provider: str) -> dict[str, Any]:
    """Compte et journalise l'issue d'un paiement la première fois qu'elle est connue."""
    status = _OUTCOME.get(intent.get("status", ""))
    if status is None:
        return intent
    with _lock:
        if intent["id"] in _counted:
            return intent
        _counted[intent["id"]] = None
        while len(_counted) > 1000:
            _counted.popitem(last=False)
    PAYMENTS.labels(provider, status).inc()
    error = intent.get("error") or {}
    log.info(
        "paiement accepté" if status == "ok" else "paiement refusé",
        extra={
            "fields": {
                "event": "payment",
                "provider": provider,
                "payment_id": intent["id"],
                "reference": intent.get("reference", ""),
                "owner": intent.get("owner", ""),
                "amount": intent.get("amount"),
                "status": intent["status"],
                **({"decline_code": error["code"]} if error.get("code") else {}),
            }
        },
    )
    return intent


def created(intent: dict[str, Any], provider: str) -> dict[str, Any]:
    log.info(
        "paiement créé",
        extra={
            "fields": {
                "event": "payment",
                "provider": provider,
                "payment_id": intent["id"],
                "reference": intent.get("reference", ""),
                "owner": intent.get("owner", ""),
                "amount": intent.get("amount"),
                "status": intent.get("status"),
            }
        },
    )
    return intent


def provider_error(provider: str, detail: str) -> None:
    PAYMENTS.labels(provider, "error").inc()
    log.warning("échec chez le prestataire", extra={"fields": {"event": "payment", "provider": provider, "error": detail}})


def render(dependencies: dict[str, bool]) -> tuple[bytes, str]:
    for name, up in dependencies.items():
        DEPENDENCY_UP.labels(name).set(1 if up else 0)
    return generate_latest(), CONTENT_TYPE_LATEST

"""
API de paiement — Resilience Pay.

Porte la clé secrète Stripe (le navigateur ne la voit jamais) et expose au
frontend une vue normalisée de la machine à états d'un paiement : statut,
étapes du rail, motif de refus, historique. C'est ce conteneur que le canary
teste et que l'attaque vise.
"""

from __future__ import annotations

import collections
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import stripe
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import paypal

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

app = FastAPI(title="Resilience Pay API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")

# ---------------------------------------------------------------- observabilité
#
# Ce que la supervision lit en direct : les requêtes des dix dernières secondes
# (débit, taux de 5xx, p95) et une sonde Stripe. Les sondes elles-mêmes ne
# comptent pas dans les métriques, sinon elles les gonfleraient.

_requests: collections.deque[tuple[float, float, int]] = collections.deque(maxlen=600)
_PROBE_PATHS = {"/api/health", "/api/status"}
_stripe_probe: dict[str, Any] = {"at": 0.0, "up": False, "ms": 0}


@app.middleware("http")
async def observe(request: Request, call_next):
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if request.url.path not in _PROBE_PATHS:
            _requests.append((time.time(), (time.perf_counter() - started) * 1000, status))


def probe_stripe() -> dict[str, Any]:
    """Un appel léger à Stripe, mis en cache trois secondes."""
    now = time.time()
    if now - _stripe_probe["at"] < 3:
        return _stripe_probe
    started = time.perf_counter()
    try:
        stripe.Balance.retrieve()
        up = True
    except Exception:
        up = False
    _stripe_probe.update(at=now, up=up, ms=int((time.perf_counter() - started) * 1000))
    return _stripe_probe


STAGES = ("authorization", "authentication", "capture", "settlement")

# Codes de refus Stripe que le frontend sait afficher, avec un message
# qui dit au porteur quoi faire — pas seulement ce qui a échoué.
DECLINE_MESSAGES: dict[str, str] = {
    "insufficient_funds": "La provision du compte est insuffisante. Utilisez un autre moyen de paiement.",
    "card_declined": "L’émetteur a refusé la transaction. Contactez votre banque ou changez de carte.",
    "expired_card": "Cette carte a expiré. Vérifiez la date inscrite au recto.",
    "incorrect_cvc": "Le cryptogramme ne correspond pas à la carte. Il figure au dos, à trois chiffres.",
    "processing_error": "Le réseau d’autorisation n’a pas répondu. Réessayez dans un instant.",
    "fraudulent": "La transaction a été bloquée par le contrôle de fraude.",
    "authentication_failed": "L’authentification a échoué. Le paiement n’a pas été confirmé par votre banque.",
}

BRANDS = {"visa", "mastercard", "amex"}


class CreateIntent(BaseModel):
    amount: int = Field(gt=0, le=99_999_999, description="Montant en centimes")
    holder: str = Field(default="", max_length=120)


# ---------------------------------------------------------------- helpers


def _reference() -> str:
    n = f"{secrets.randbelow(10**8):08d}"
    return f"RSL-{n[:4]}-{n[4:]}"


def _clock(ts: int | None) -> str:
    return datetime.fromtimestamp(ts or 0, tz=timezone.utc).isoformat()


def _iso(ts: int | None) -> str:
    return datetime.fromtimestamp(ts or 0, tz=timezone.utc).isoformat()


def _meta(pi: Any, key: str) -> str:
    """stripe-python expose metadata comme un StripeObject : pas de .get()."""
    try:
        return str(pi.metadata.to_dict().get(key, "") or "")
    except AttributeError:
        return ""


def _decline(err: Any) -> dict[str, str] | None:
    """Ramène last_payment_error à un code que le frontend connaît."""
    if not err:
        return None
    code = getattr(err, "decline_code", None) or getattr(err, "code", None) or "card_declined"
    if code == "payment_intent_authentication_failure":
        code = "authentication_failed"
    if code not in DECLINE_MESSAGES:
        code = "card_declined"
    return {"code": code, "message": DECLINE_MESSAGES[code]}


def _status(pi: Any, error: dict[str, str] | None) -> str:
    s = pi.status
    if s in ("succeeded", "canceled", "requires_action"):
        return s
    if s in ("processing", "requires_capture"):
        return "processing"
    # requires_payment_method après un refus : la tentative est terminée.
    return "canceled" if error else "requires_confirmation"


def _three_ds(charge: Any) -> bool:
    try:
        return bool(charge.payment_method_details.card.three_d_secure)
    except AttributeError:
        return False


def _rail(status: str, three_ds: bool, error: dict[str, str] | None) -> dict[str, str]:
    rail = {k: "pending" for k in STAGES}
    if status == "requires_confirmation":
        return rail
    if status == "requires_action":
        rail.update(authorization="done", authentication="active")
        return rail
    if status == "canceled":
        if error and error["code"] == "authentication_failed":
            rail.update(authorization="done", authentication="failed")
        else:
            rail["authorization"] = "failed"
        return rail
    rail.update(authorization="done", authentication="done" if three_ds else "skipped")
    if status == "processing":
        rail["capture"] = "active"
    else:
        rail.update(capture="done", settlement="done")
    return rail


def _history(pi: Any, charge: Any, status: str, three_ds: bool, error: dict[str, str] | None) -> list[dict[str, str]]:
    events = [{"at": _clock(pi.created), "status": "requires_confirmation", "note": "Intention de paiement créée chez Stripe"}]
    when = _clock(getattr(charge, "created", None) or pi.created)
    if status == "requires_action":
        events.append({"at": when, "status": "requires_action", "note": "L’émetteur exige une authentification forte"})
    if three_ds:
        events.append({"at": when, "status": "processing", "note": "Authentification 3-D Secure validée par l’émetteur"})
    if status in ("processing", "succeeded"):
        events.append({"at": when, "status": "processing", "note": "Autorisation accordée par le réseau"})
    if status == "succeeded":
        events.append({"at": when, "status": "succeeded", "note": "Fonds capturés — en attente de versement"})
    if status == "canceled" and error:
        events.append({"at": when, "status": "canceled", "note": f"Refus réseau — {error['code']}"})
    return events


def _card(pi: Any, charge: Any) -> dict[str, str]:
    brand, last4, holder = "unknown", "", _meta(pi, "holder")
    try:
        card = charge.payment_method_details.card
        brand = card.brand if card.brand in BRANDS else "unknown"
        last4 = card.last4 or ""
        holder = charge.billing_details.name or holder
    except AttributeError:
        pass
    return {"brand": brand, "last4": last4, "holder": holder}


def to_intent(pi: Any) -> dict[str, Any]:
    """La forme exacte du type `PaymentIntent` du frontend."""
    charge = pi.latest_charge if hasattr(pi.latest_charge, "id") else None
    error = _decline(pi.last_payment_error)
    status = _status(pi, error)
    three_ds = _three_ds(charge)
    out: dict[str, Any] = {
        "id": pi.id,
        "idempotencyKey": _meta(pi, "idempotency_key"),
        "amount": pi.amount,
        "currency": "EUR",
        "status": status,
        "card": _card(pi, charge),
        "createdAt": _iso(pi.created),
        "reference": _meta(pi, "reference"),
        "rail": _rail(status, three_ds, error),
        "history": _history(pi, charge, status, three_ds, error),
    }
    if error:
        out["error"] = error
    return out


def _stripe(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except stripe.StripeError as exc:  # pragma: no cover - dépend du réseau
        raise HTTPException(status_code=502, detail=f"Stripe : {exc.user_message or exc}") from exc


# ---------------------------------------------------------------- routes


@api.get("/health")
def health() -> dict[str, Any]:
    key = stripe.api_key
    return {
        "ok": True,
        "stripe": bool(key),
        "mode": "test" if key.startswith("sk_test_") else "live" if key else "none",
        "paypal": paypal.configured(),
    }


@api.get("/status")
def status() -> dict[str, Any]:
    now = time.time()
    window = [r for r in _requests if now - r[0] <= 10]
    latencies = sorted(ms for _, ms, _ in window)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    errors = sum(1 for _, _, code in window if code >= 500)
    probe = probe_stripe()
    pp = paypal.probe()
    return {
        "api": "up",
        "stripe": {"up": probe["up"], "latencyMs": probe["ms"]},
        "paypal": {"configured": paypal.configured(), "up": pp["up"], "latencyMs": pp["ms"]},
        "metrics": {
            "rps": round(len(window) / 10, 1),
            "errRate": errors / len(window) if window else 0.0,
            "p95": round(p95),
            "wafBlocks": 0,
        },
        "time": now,
    }


@api.post("/payment_intents", status_code=201)
def create_intent(body: CreateIntent) -> dict[str, Any]:
    if not stripe.api_key:
        raise HTTPException(status_code=503, detail="STRIPE_SECRET_KEY absente côté serveur")
    key = f"idem_{secrets.token_hex(6)}"
    pi = _stripe(
        stripe.PaymentIntent.create,
        amount=body.amount,
        currency="eur",
        # Carte uniquement, sans redirection : confirmCardPayment reste dans la page.
        automatic_payment_methods={"enabled": True, "allow_redirects": "never"},
        description="Resilience Pay — commande",
        metadata={"reference": _reference(), "holder": body.holder, "idempotency_key": key},
        idempotency_key=key,
    )
    return {**to_intent(pi), "clientSecret": pi.client_secret}


@api.get("/payment_intents")
def list_intents() -> list[dict[str, Any]]:
    page = _stripe(stripe.PaymentIntent.list, limit=25, expand=["data.latest_charge"])
    return [to_intent(pi) for pi in page.data]


@api.get("/payment_intents/{intent_id}")
def get_intent(intent_id: str) -> dict[str, Any]:
    pi = _stripe(stripe.PaymentIntent.retrieve, intent_id, expand=["latest_charge"])
    return to_intent(pi)


@api.get("/balance")
def balance() -> dict[str, Any]:
    bal = _stripe(stripe.Balance.retrieve)

    def eur(entries: list[Any]) -> int:
        for e in entries:
            if e.currency == "eur":
                return e.amount
        return entries[0].amount if entries else 0

    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {"available": eur(bal.available), "pending": eur(bal.pending), "nextPayoutAt": tomorrow.isoformat()}


api.include_router(paypal.router)
app.include_router(api)

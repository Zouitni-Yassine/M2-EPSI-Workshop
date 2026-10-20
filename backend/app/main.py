"""
API de paiement — Resilience Pay.

Porte la clé secrète Stripe (le navigateur ne la voit jamais) et expose au
frontend une vue normalisée de la machine à états d'un paiement : statut,
étapes du rail, motif de refus, historique. C'est ce conteneur que le canary
teste et que l'attaque vise.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import stripe
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import metrics, paypal, store
from .security import User, current_user, require_operator

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]


class _Json(logging.Formatter):
    """Une ligne JSON par événement, lue par Loki et le SIEM. Jamais de secret ni de numéro de carte."""

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "payment-api",
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(line, ensure_ascii=False)


log = logging.getLogger("payment-api")
_handler = logging.StreamHandler()
_handler.setFormatter(_Json())
log.addHandler(_handler)
log.setLevel(logging.INFO)
log.propagate = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    # La sonde de la base tourne en fond ; chaque retour de la base (démarrage compris) relance la réconciliation.
    store.watch(on_recover=reconcile_stripe)
    yield


app = FastAPI(title="Resilience Pay API", version="0.1.0", lifespan=lifespan)
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
        elapsed = time.perf_counter() - started
        metrics.observe_http(request, status, elapsed)
        if request.url.path not in _PROBE_PATHS:
            _requests.append((time.time(), elapsed * 1000, status))


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

# Cartes de test Stripe → jetons pré-tokenisés officiels. Le navigateur saisit le
# numéro dans nos champs, le serveur le remplace par le jeton : aucun numéro n'est
# jamais transmis à Stripe. Ne fonctionne qu'avec des cartes de test, par construction.
TEST_TOKENS: dict[str, str] = {
    "4242424242424242": "pm_card_visa",
    "4000056655665556": "pm_card_visa_debit",
    "5555555555554444": "pm_card_mastercard",
    "2223003122003222": "pm_card_mastercard",
    "378282246310005": "pm_card_amex",
    "6011111111111117": "pm_card_discover",
    "4000002500003155": "pm_card_threeDSecure2Required",
    "4000002760003184": "pm_card_threeDSecure2Required",
    "4000000000003220": "pm_card_threeDSecure2Required",
    "4000000000000002": "pm_card_chargeDeclined",
    "4000000000009995": "pm_card_chargeDeclinedInsufficientFunds",
    "4000000000009987": "pm_card_chargeDeclinedLostCard",
    "4000000000009979": "pm_card_chargeDeclinedStolenCard",
    "4000000000000069": "pm_card_chargeDeclinedExpiredCard",
    "4000000000000127": "pm_card_chargeDeclinedIncorrectCvc",
    "4000000000000119": "pm_card_chargeDeclinedProcessingError",
    "4100000000000019": "pm_card_radarBlock",
}


class CreateIntent(BaseModel):
    amount: int = Field(gt=0, le=99_999_999, description="Montant en centimes")
    holder: str = Field(default="", max_length=120)


class ConfirmIntent(BaseModel):
    number: str = Field(min_length=12, max_length=23)
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
        # Pas de charge (refus avant capture) : la carte est dans l'erreur de paiement.
        try:
            card = pi.last_payment_error.payment_method.card
            brand = card.brand if card.brand in BRANDS else "unknown"
            last4 = card.last4 or ""
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
        "owner": _meta(pi, "owner"),
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
        metrics.provider_error("stripe", str(exc))
        raise HTTPException(status_code=502, detail=f"Stripe : {exc.user_message or exc}") from exc


def reconcile_stripe() -> None:
    """
    Rejoue les 100 derniers paiements Stripe dans la base. Lancé au démarrage et à chaque
    retour de la base : ce qui a été payé pendant une panne réapparaît dans le journal.
    """
    if not stripe.api_key:
        return
    try:
        page = stripe.PaymentIntent.list(limit=100, expand=["data.latest_charge"])
    except stripe.StripeError as exc:
        log.warning("réconciliation impossible", extra={"fields": {"event": "reconcile", "error": str(exc)}})
        return
    for done, pi in enumerate(page.data):
        try:
            store.save(to_intent(pi), "stripe")
        except store.StoreError as exc:
            log.warning("réconciliation interrompue", extra={"fields": {"event": "reconcile", "saved": done, "error": str(exc)}})
            return
    log.info("journal réconcilié avec Stripe", extra={"fields": {"event": "reconcile", "saved": len(page.data)}})


def _owned(intent_id: str, user: User) -> Any:
    """Relit l'intention et vérifie qu'elle appartient au client. Sinon 404 : on ne confirme même pas qu'elle existe."""
    pi = _stripe(stripe.PaymentIntent.retrieve, intent_id, expand=["latest_charge"])
    if not user.is_operator and _meta(pi, "owner") != user.username:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    return pi


# ---------------------------------------------------------------- routes
#
# /health et /status restent ouverts : le détecteur, le moteur de remédiation et
# le canary les sondent chaque seconde. Tout le reste exige un jeton.


@api.get("/health")
def health() -> dict[str, Any]:
    key = stripe.api_key
    return {
        "ok": True,
        "stripe": bool(key),
        "mode": "test" if key.startswith("sk_test_") else "live" if key else "none",
        "paypal": paypal.configured(),
        # Informatif : redémarrer l'API ne répare pas une base en panne, /health reste donc à 200.
        "db": bool(store.up()),
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
        "db": {"up": bool(store.up())},
        "metrics": {
            "rps": round(len(window) / 10, 1),
            "errRate": errors / len(window) if window else 0.0,
            "p95": round(p95),
            "wafBlocks": 0,
        },
        "time": now,
    }


@api.post("/payment_intents", status_code=201)
def create_intent(body: CreateIntent, user: User = Depends(current_user)) -> dict[str, Any]:
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
        metadata={"reference": _reference(), "holder": body.holder, "idempotency_key": key, "owner": user.username},
        idempotency_key=key,
    )
    intent = metrics.created(to_intent(pi), "stripe")
    return {**store.record(intent, "stripe"), "clientSecret": pi.client_secret}


@api.post("/payment_intents/{intent_id}/confirm")
def confirm_intent(intent_id: str, body: ConfirmIntent, user: User = Depends(current_user)) -> dict[str, Any]:
    """Confirme avec le jeton de test correspondant au numéro saisi. Le numéro ne quitte pas ce serveur."""
    if not user.is_operator:
        _owned(intent_id, user)
    token = TEST_TOKENS.get(re.sub(r"\D", "", body.number))
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Ce numéro n’est pas une carte de test Stripe. Utilisez 4242 4242 4242 4242 ou une autre carte de test.",
        )
    try:
        pi = stripe.PaymentIntent.confirm(intent_id, payment_method=token, expand=["latest_charge"])
    except stripe.CardError:
        # Refus émetteur : l'intention porte le motif, on la relit telle quelle.
        pi = _stripe(stripe.PaymentIntent.retrieve, intent_id, expand=["latest_charge"])
    except stripe.StripeError as exc:
        metrics.provider_error("stripe", str(exc))
        raise HTTPException(status_code=502, detail=f"Stripe : {exc.user_message or exc}") from exc
    intent = metrics.payment(to_intent(pi), "stripe")
    return {**store.record(intent, "stripe"), "clientSecret": pi.client_secret}


@api.get("/payment_intents")
def list_intents(user: User = Depends(current_user)) -> list[dict[str, Any]]:
    try:
        return store.recent("stripe", None if user.is_operator else user.username)
    except store.StoreError:
        pass  # Base injoignable : on relit Stripe, plus lent mais complet.
    # Un client ne voit que ses paiements : on lit plus large pour en garder 25 après filtrage.
    page = _stripe(stripe.PaymentIntent.list, limit=25 if user.is_operator else 100, expand=["data.latest_charge"])
    mine = [pi for pi in page.data if user.is_operator or _meta(pi, "owner") == user.username]
    return [to_intent(pi) for pi in mine[:25]]


@api.get("/payment_intents/{intent_id}")
def get_intent(intent_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    # Relu chez Stripe (après 3-D Secure, l'état a changé hors de nos routes) puis mis à jour en base.
    return store.record(metrics.payment(to_intent(_owned(intent_id, user)), "stripe"), "stripe")


@api.get("/balance", dependencies=[Depends(require_operator)])
def balance() -> dict[str, Any]:
    bal = _stripe(stripe.Balance.retrieve)

    def eur(entries: list[Any]) -> int:
        for e in entries:
            if e.currency == "eur":
                return e.amount
        return entries[0].amount if entries else 0

    tomorrow = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return {"available": eur(bal.available), "pending": eur(bal.pending), "nextPayoutAt": tomorrow.isoformat()}


@app.get("/metrics", include_in_schema=False)
def prometheus() -> Response:
    """Format Prometheus, à la racine comme le veut le contrat de déploiement. Ne déclenche aucune sonde."""
    deps = {"stripe": bool(_stripe_probe["up"]), "db": bool(store.up())}
    if paypal.configured():
        deps["paypal"] = bool(paypal._probe["up"])
    body, content_type = metrics.render(deps)
    return Response(body, media_type=content_type)


api.include_router(paypal.router)
app.include_router(api)

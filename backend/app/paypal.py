"""
PayPal en mode sandbox — Orders API v2.

Le navigateur ouvre la fenêtre PayPal (SDK JS v6) ; ce module porte le secret,
crée la commande, la capture après approbation du payeur et la ramène à la
même forme `PaymentIntent` que Stripe, pour que le stepper, le reçu et le
journal fonctionnent sans savoir d'où vient le paiement.
"""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import store
from .security import User, current_user

# Figée : même avec des identifiants live collés par erreur, aucun argent réel ne bouge.
SANDBOX_API = "https://api-m.sandbox.paypal.com"

_http = httpx.Client(base_url=SANDBOX_API, timeout=httpx.Timeout(5.0))

router = APIRouter(prefix="/paypal")

# Refus PayPal ramenés aux codes que le frontend sait afficher (DeclineCode).
DECLINES: dict[str, tuple[str, str]] = {
    "INSTRUMENT_DECLINED": ("card_declined", "PayPal a refusé le moyen de paiement choisi. Relancez le paiement et choisissez-en un autre."),
    "TRANSACTION_REFUSED": ("card_declined", "PayPal a refusé la transaction. Essayez un autre moyen de paiement."),
    "PAYER_CANNOT_PAY": ("insufficient_funds", "Ce compte PayPal ne peut pas régler cette commande. Utilisez un autre moyen de paiement."),
    "COMPLIANCE_VIOLATION": ("fraudulent", "La transaction a été bloquée par les contrôles de PayPal."),
    "PAYEE_BLOCKED_TRANSACTION": ("fraudulent", "La transaction a été bloquée par les contrôles de PayPal."),
}
PROCESSING = ("processing_error", "PayPal n’a pas confirmé la capture. Réessayez dans un instant.")

_ORDER_ID = re.compile(r"^[A-Z0-9]{8,36}$")


class PayPalError(Exception):
    def __init__(self, status: int, issue: str, message: str, debug_id: str = "") -> None:
        super().__init__(message)
        self.status, self.issue, self.debug_id = status, issue, debug_id


class CreateOrder(BaseModel):
    amount: int = Field(gt=0, le=99_999_999, description="Montant en centimes")


# ---------------------------------------------------------------- configuration


def _secret(name: str) -> str:
    """NAME, ou le fichier pointé par NAME_FILE (secret Docker, rendu Vault Agent, SOPS)."""
    path = os.getenv(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv(name, "")


def configured() -> bool:
    # Lu à chaque appel : main.py charge le .env après l'import de ce module.
    return bool(os.getenv("PAYPAL_CLIENT_ID") and _secret("PAYPAL_CLIENT_SECRET"))


# ---------------------------------------------------------------- protection sortante
#
# PayPal est un service tiers, hors du périmètre d'attaque. Un déni de service
# sur payment-api ne doit pas se transformer en rafale d'appels vers PayPal :
# au-delà de PAYPAL_MAX_RPS, on répond 429 sans sortir.


class _Bucket:
    def __init__(self, rate: float) -> None:
        self.rate, self.capacity, self.last = rate, max(1.0, rate), time.monotonic()
        self.tokens = self.capacity
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens < 1:
                return False
            self.tokens -= 1
            return True


_bucket: _Bucket | None = None


def _limiter() -> _Bucket:
    # Créé au premier appel, une fois le .env chargé par main.py.
    global _bucket
    if _bucket is None:
        _bucket = _Bucket(float(os.getenv("PAYPAL_MAX_RPS") or 5))
    return _bucket

# ---------------------------------------------------------------- client OAuth + Orders

_token: dict[str, Any] = {"value": "", "expires": 0.0}
_token_lock = threading.Lock()


def _access_token(force: bool = False) -> str:
    with _token_lock:
        if not force and _token["value"] and time.time() < _token["expires"]:
            return _token["value"]
        try:
            res = _http.post(
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(os.getenv("PAYPAL_CLIENT_ID", ""), _secret("PAYPAL_CLIENT_SECRET")),
            )
        except httpx.HTTPError as exc:  # pragma: no cover - dépend du réseau
            raise PayPalError(502, "NETWORK_ERROR", f"PayPal injoignable ({type(exc).__name__})") from exc
        if res.status_code != 200:
            body = _json(res)
            raise PayPalError(res.status_code, body.get("error", "AUTHENTICATION_FAILURE"), body.get("error_description", "Identifiants PayPal refusés"))
        body = res.json()
        # Marge d'une minute pour ne jamais présenter un jeton sur le point d'expirer.
        _token.update(value=body["access_token"], expires=time.time() + int(body.get("expires_in", 0)) - 60)
        return _token["value"]


def _json(res: httpx.Response) -> dict[str, Any]:
    try:
        body = res.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _call(method: str, path: str, *, json: Any = None, request_id: str = "", limited: bool = True) -> dict[str, Any]:
    if limited and not _limiter().take():
        raise PayPalError(429, "OUTBOUND_RATE_LIMITED", "Trop de paiements PayPal en même temps. Réessayez dans un instant.")
    for attempt in range(2):
        # Content-Type exigé par PayPal même sans corps (capture), sinon 415 « payload is not supported ».
        headers = {
            "Authorization": f"Bearer {_access_token(force=attempt > 0)}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            res = _http.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:  # pragma: no cover - dépend du réseau
            raise PayPalError(502, "NETWORK_ERROR", f"PayPal injoignable ({type(exc).__name__})") from exc
        # Jeton révoqué côté PayPal : on en redemande un, une seule fois.
        if res.status_code == 401 and attempt == 0:
            continue
        body = _json(res)
        if res.status_code >= 400:
            details = body.get("details") or [{}]
            raise PayPalError(
                res.status_code,
                details[0].get("issue") or body.get("name", "PAYPAL_ERROR"),
                details[0].get("description") or body.get("message", f"HTTP {res.status_code}"),
                body.get("debug_id", ""),
            )
        return body
    raise AssertionError("unreachable")


def _http_error(exc: PayPalError) -> HTTPException:
    """Comme main._stripe : une erreur PayPal devient une réponse HTTP lisible par le frontend."""
    if exc.status == 429:
        return HTTPException(status_code=429, detail=str(exc))
    if exc.status == 404:
        return HTTPException(status_code=404, detail="Commande PayPal inconnue")
    if exc.issue == "ORDER_NOT_APPROVED":
        return HTTPException(status_code=409, detail="Le payeur n’a pas encore approuvé la commande PayPal")
    suffix = f" (debug_id {exc.debug_id})" if exc.debug_id else ""
    return HTTPException(status_code=502, detail=f"PayPal : {exc}{suffix}")


def _paypal(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        return _call(method, path, **kwargs)
    except PayPalError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------- sonde (supervision)

_probe: dict[str, Any] = {"at": 0.0, "up": False, "ms": 0}


def probe() -> dict[str, Any]:
    """Un appel authentifié léger, mis en cache dix secondes : PayPal n'est pas à nous, on le ménage."""
    now = time.time()
    if not configured() or now - _probe["at"] < 10:
        return _probe
    started = time.perf_counter()
    try:
        _call("GET", "/v1/notifications/webhooks-event-types", limited=False)
        up = True
    except Exception:
        up = False
    _probe.update(at=now, up=up, ms=int((time.perf_counter() - started) * 1000))
    return _probe


# ---------------------------------------------------------------- normalisation


def _reference() -> str:
    """Même format que main._reference : RSL-1234-5678."""
    n = f"{secrets.randbelow(10**8):08d}"
    return f"RSL-{n[:4]}-{n[4:]}"


def _when(iso: str | None) -> datetime:
    if not iso:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(iso)


def _clock(iso: str | None) -> str:
    return _when(iso).astimezone().strftime("%H:%M:%S")


def _cents(value: str | None) -> int:
    return int(Decimal(value or "0") * 100)


def _euros(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


def to_intent(order: dict[str, Any], error: dict[str, str] | None = None) -> dict[str, Any]:
    """Une commande PayPal sous la forme exacte du type `PaymentIntent` du frontend."""
    unit = (order.get("purchase_units") or [{}])[0]
    capture = ((unit.get("payments") or {}).get("captures") or [{}])[0]
    state, captured = order.get("status"), capture.get("status")
    if captured in ("DECLINED", "FAILED") and not error:
        error = dict(zip(("code", "message"), DECLINES["TRANSACTION_REFUSED"]))

    if error or order.get("status") == "VOIDED":
        status = "canceled"
    elif captured == "COMPLETED":
        status = "succeeded"
    elif captured == "PENDING" or state == "APPROVED":
        status = "processing"
    elif state == "PAYER_ACTION_REQUIRED":
        status = "requires_action"
    else:
        status = "requires_confirmation"

    # Sur PayPal, le payeur s'authentifie et autorise dans la même fenêtre ;
    # c'est la capture qui peut échouer ensuite.
    rail = {"authorization": "pending", "authentication": "pending", "capture": "pending", "settlement": "pending"}
    if status == "requires_action":
        rail.update(authorization="done", authentication="active")
    elif status == "processing":
        rail.update(authorization="done", authentication="done", capture="active")
    elif status == "succeeded":
        rail = {k: "done" for k in rail}
    elif status == "canceled":
        if error:
            rail.update(authorization="done", authentication="done", capture="failed")
        else:
            rail["authorization"] = "failed"

    created = order.get("create_time")
    later = capture.get("create_time") or order.get("update_time") or created
    history = [{"at": _clock(created), "status": "requires_confirmation", "note": "Commande créée chez PayPal"}]
    if status in ("processing", "succeeded") or error:
        history.append({"at": _clock(later), "status": "processing", "note": "Le payeur a validé le paiement dans la fenêtre PayPal"})
    if captured == "PENDING":
        reason = (capture.get("status_details") or {}).get("reason", "")
        history.append({"at": _clock(later), "status": "processing", "note": f"Capture en attente chez PayPal {reason}".strip()})
    if status == "succeeded":
        history.append({"at": _clock(later), "status": "succeeded", "note": "Fonds capturés par PayPal"})
    if status == "canceled":
        history.append({"at": _clock(later), "status": "canceled", "note": f"Refus PayPal — {error['code']}" if error else "Commande annulée ou expirée"})

    name = (order.get("payer") or {}).get("name") or {}
    # custom_id = « clé d'idempotence:propriétaire », gardé par PayPal : il survit à un redémarrage de l'API.
    key, _, owner = unit.get("custom_id", "").partition(":")
    out: dict[str, Any] = {
        "id": order["id"],
        "idempotencyKey": key,
        "owner": owner,
        "amount": _cents((unit.get("amount") or {}).get("value")),
        "currency": "EUR",
        "status": status,
        "method": "paypal",
        "card": {"brand": "unknown", "last4": "", "holder": " ".join(filter(None, (name.get("given_name"), name.get("surname"))))},
        "createdAt": _when(created).isoformat(),
        "reference": unit.get("reference_id", ""),
        "rail": rail,
        "history": history,
    }
    if error:
        out["error"] = error
    return out


# Pas d'API « lister les commandes » chez PayPal : le journal est notre base, et lui seul.
# Contrairement à Stripe, une commande manquée pendant une panne de la base ne se rattrape pas.
def _remember(intent: dict[str, Any]) -> dict[str, Any]:
    return store.record(intent, "paypal")


def _order_id(order_id: str) -> str:
    if not _ORDER_ID.match(order_id):
        raise HTTPException(status_code=400, detail="Identifiant de commande PayPal invalide")
    return order_id


def _require_configured() -> None:
    if not configured():
        raise HTTPException(status_code=503, detail="PAYPAL_CLIENT_ID ou PAYPAL_CLIENT_SECRET absent côté serveur")


def _check_owner(owner: str, user: User) -> None:
    # 404 plutôt que 403 : un client ne doit pas pouvoir sonder les commandes des autres.
    if not user.is_operator and owner != user.username:
        raise HTTPException(status_code=404, detail="Commande introuvable")


def _owner_of(order_id: str, path: str) -> str:
    try:
        known = store.owner_of(order_id)
    except store.StoreError:
        known = None
    if known is not None:
        return known
    # Inconnue de la base (ou base en panne) : PayPal garde le propriétaire dans custom_id.
    return to_intent(_paypal("GET", path))["owner"]


# ---------------------------------------------------------------- routes


@router.post("/orders", status_code=201)
def create_order(body: CreateOrder, user: User = Depends(current_user)) -> dict[str, Any]:
    _require_configured()
    key = f"idem_{secrets.token_hex(6)}"
    order = _paypal(
        "POST",
        "/v2/checkout/orders",
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": _reference(),
                    "custom_id": f"{key}:{user.username}",
                    "description": "Resilience Pay — commande",
                    "amount": {"currency_code": "EUR", "value": _euros(body.amount)},
                }
            ],
        },
        # Rejouer la même requête (timeout, double clic) ne crée pas de seconde commande.
        request_id=key,
    )
    return _remember(to_intent(order))


@router.post("/orders/{order_id}/capture")
def capture_order(order_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    _require_configured()
    path = f"/v2/checkout/orders/{_order_id(order_id)}"
    if not user.is_operator:
        _check_owner(_owner_of(order_id, path), user)
    try:
        order = _call("POST", f"{path}/capture")
    except PayPalError as exc:
        if exc.issue == "ORDER_ALREADY_CAPTURED":
            # Deuxième capture (nouvel essai après une coupure) : PayPal n'encaisse qu'une fois.
            return _remember(to_intent(_paypal("GET", path)))
        if exc.status == 422 and exc.issue in DECLINES:
            code, message = DECLINES[exc.issue]
            return _remember(to_intent(_paypal("GET", path), error={"code": code, "message": message}))
        if exc.status >= 500:
            # Issue incertaine (timeout, panne PayPal) : on relit la commande plutôt que d'annoncer un refus.
            return _remember(to_intent(_paypal("GET", path)))
        raise _http_error(exc) from exc
    return _remember(to_intent(order))


@router.get("/orders/{order_id}")
def get_order(order_id: str, user: User = Depends(current_user)) -> dict[str, Any]:
    _require_configured()
    intent = to_intent(_paypal("GET", f"/v2/checkout/orders/{_order_id(order_id)}"))
    _check_owner(intent["owner"], user)
    return _remember(intent)


@router.get("/orders")
def list_orders(user: User = Depends(current_user)) -> list[dict[str, Any]]:
    try:
        return store.recent("paypal", None if user.is_operator else user.username)
    except store.StoreError as exc:
        raise HTTPException(status_code=503, detail="Journal PayPal indisponible : base injoignable") from exc

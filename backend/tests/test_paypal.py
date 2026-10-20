"""
Parcours PayPal de bout en bout contre un faux PayPal (httpx.MockTransport) :
aucun appel réseau, aucun identifiant réel.

    cd backend && python -m pytest
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, paypal


class FakePayPal:
    """Le strict nécessaire de l'API Orders v2 pour exercer nos routes."""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.by_request_id: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.token = "A21-test-token"
        self.decline = False
        self.capture_down = False

    def approve(self, order_id: str) -> None:
        order = self.orders[order_id]
        order.update(status="APPROVED", update_time="2026-10-19T10:00:05Z")
        order["payer"] = {"name": {"given_name": "Camille", "surname": "Testeuse"}}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((method, path))

        if path == "/v1/oauth2/token":
            expected = base64.b64encode(b"test-client:test-secret").decode()
            if request.headers.get("authorization") != f"Basic {expected}":
                return httpx.Response(401, json={"error": "invalid_client", "error_description": "Client Authentication failed"})
            return httpx.Response(200, json={"access_token": self.token, "token_type": "Bearer", "expires_in": 32400})

        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"name": "AUTHENTICATION_FAILURE"})

        # Comme le vrai PayPal : un POST sans Content-Type JSON est refusé, même sans corps.
        if method == "POST" and request.headers.get("content-type") != "application/json":
            return httpx.Response(415, json={"name": "UNSUPPORTED_MEDIA_TYPE", "message": "The request payload is not supported", "debug_id": "dbg415"})

        if path == "/v1/notifications/webhooks-event-types":
            return httpx.Response(200, json={"event_types": []})

        if method == "POST" and path == "/v2/checkout/orders":
            key = request.headers["paypal-request-id"]
            if key in self.by_request_id:
                return httpx.Response(200, json=self.orders[self.by_request_id[key]])
            unit = json.loads(request.content)["purchase_units"][0]
            order_id = f"7TEST{len(self.orders):012d}"
            self.orders[order_id] = {
                "id": order_id,
                "intent": "CAPTURE",
                "status": "CREATED",
                "create_time": "2026-10-19T10:00:00Z",
                "purchase_units": [unit],
            }
            self.by_request_id[key] = order_id
            return httpx.Response(201, json=self.orders[order_id])

        order_id = path.split("/")[4]
        order = self.orders.get(order_id)
        if order is None:
            return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND", "details": [{"issue": "INVALID_RESOURCE_ID"}]})

        if method == "GET":
            return httpx.Response(200, json=order)

        if path.endswith("/capture"):
            if self.capture_down:
                return httpx.Response(500, json={"name": "INTERNAL_SERVER_ERROR", "message": "An internal server error occurred."})
            issue = {"CREATED": "ORDER_NOT_APPROVED", "COMPLETED": "ORDER_ALREADY_CAPTURED"}.get(order["status"])
            if issue is None and self.decline:
                issue = "INSTRUMENT_DECLINED"
            if issue:
                return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": issue}], "debug_id": "dbg123"})
            order["status"] = "COMPLETED"
            unit = order["purchase_units"][0]
            unit["payments"] = {"captures": [{"id": "CAP1", "status": "COMPLETED", "amount": unit["amount"], "create_time": "2026-10-19T10:00:06Z"}]}
            return httpx.Response(201, json=order)

        return httpx.Response(405)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakePayPal:
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET_FILE", raising=False)
    fake = FakePayPal()
    monkeypatch.setattr(paypal, "_http", httpx.Client(base_url=paypal.SANDBOX_API, transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(paypal, "_bucket", paypal._Bucket(100))
    paypal._token.update(value="", expires=0.0)
    paypal._ledger.clear()
    paypal._probe.update(at=0.0, up=False, ms=0)
    return fake


client = TestClient(main.app)


def create(amount: int = 34_080) -> dict:
    res = client.post("/api/paypal/orders", json={"amount": amount})
    assert res.status_code == 201, res.text
    return res.json()


def test_health_annonce_paypal(fake: FakePayPal, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/health").json()["paypal"] is True
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET")
    assert client.get("/api/health").json()["paypal"] is False


def test_creation_renvoie_un_payment_intent(fake: FakePayPal) -> None:
    intent = create(12_34)
    assert intent["status"] == "requires_confirmation"
    assert intent["method"] == "paypal"
    assert intent["amount"] == 1234
    assert intent["reference"].startswith("RSL-")
    assert intent["idempotencyKey"].startswith("idem_")
    assert set(intent["rail"].values()) == {"pending"}
    sent = fake.orders[intent["id"]]["purchase_units"][0]
    assert sent["amount"] == {"currency_code": "EUR", "value": "12.34"}
    assert sent["custom_id"] == intent["idempotencyKey"]


def test_capture_apres_approbation(fake: FakePayPal) -> None:
    intent = create()
    assert client.post(f"/api/paypal/orders/{intent['id']}/capture").status_code == 409

    fake.approve(intent["id"])
    paid = client.post(f"/api/paypal/orders/{intent['id']}/capture").json()
    assert paid["status"] == "succeeded"
    assert set(paid["rail"].values()) == {"done"}
    assert paid["card"]["holder"] == "Camille Testeuse"
    assert [h["status"] for h in paid["history"]] == ["requires_confirmation", "processing", "succeeded"]

    # Nouvel essai après une coupure : PayPal répond ORDER_ALREADY_CAPTURED, on relit sans doubler.
    again = client.post(f"/api/paypal/orders/{intent['id']}/capture").json()
    assert again["status"] == "succeeded"
    assert sum(1 for m, p in fake.calls if p.endswith("/capture")) == 3


def test_refus_du_moyen_de_paiement(fake: FakePayPal) -> None:
    intent = create()
    fake.approve(intent["id"])
    fake.decline = True
    out = client.post(f"/api/paypal/orders/{intent['id']}/capture").json()
    assert out["status"] == "canceled"
    assert out["error"]["code"] == "card_declined"
    assert out["rail"]["capture"] == "failed"


def test_panne_paypal_pendant_la_capture(fake: FakePayPal) -> None:
    intent = create()
    fake.approve(intent["id"])
    fake.capture_down = True
    out = client.post(f"/api/paypal/orders/{intent['id']}/capture").json()
    # Pas de faux refus : la commande est approuvée, la capture reste à refaire.
    assert out["status"] == "processing"
    assert "error" not in out


def test_journal_du_plus_recent_au_plus_ancien(fake: FakePayPal) -> None:
    first, second = create(), create()
    ids = [i["id"] for i in client.get("/api/paypal/orders").json()]
    assert ids == [second["id"], first["id"]]


def test_identifiant_invalide_ne_sort_pas(fake: FakePayPal) -> None:
    assert client.post("/api/paypal/orders/..%2Fadmin/capture").status_code in (400, 404)
    assert client.get("/api/paypal/orders/abc").status_code == 400
    assert fake.calls == []


def test_plafond_sortant(fake: FakePayPal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paypal, "_bucket", paypal._Bucket(1))
    create()
    res = client.post("/api/paypal/orders", json={"amount": 100})
    assert res.status_code == 429
    assert sum(1 for m, p in fake.calls if p == "/v2/checkout/orders") == 1


def test_jeton_mis_en_cache_puis_renouvele(fake: FakePayPal) -> None:
    create(), create()
    assert fake.calls.count(("POST", "/v1/oauth2/token")) == 1
    fake.token = "A21-rotated"  # PayPal révoque l'ancien jeton
    create()
    assert fake.calls.count(("POST", "/v1/oauth2/token")) == 2


def test_sans_identifiants(fake: FakePayPal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYPAL_CLIENT_ID")
    assert client.post("/api/paypal/orders", json={"amount": 100}).status_code == 503


def test_status_expose_la_sonde(fake: FakePayPal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "probe_stripe", lambda: {"at": 0.0, "up": True, "ms": 1})
    body = client.get("/api/status").json()
    assert body["paypal"]["configured"] is True
    assert body["paypal"]["up"] is True

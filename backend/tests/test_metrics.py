"""
/metrics au format Prometheus, issues de paiement comptées une seule fois, journal JSON.

    cd backend && python -m pytest
"""

from __future__ import annotations

import json
import logging

import pytest
import stripe
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app import main, metrics, security, store
from app.security import User


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def as_client():
    main.app.dependency_overrides[security.current_user] = lambda: User("alice", "client")
    yield
    main.app.dependency_overrides.clear()


client = TestClient(main.app)


def test_format_prometheus_a_la_racine() -> None:
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    for name in ("payments_total", "http_requests_total", "http_request_duration_seconds", "payment_api_dependency_up"):
        assert f"# TYPE {name}" in res.text
    # Séries présentes dès le démarrage, à zéro : les alertes en rate() fonctionnent tout de suite.
    assert 'payments_total{provider="stripe",status="error"}' in res.text


def test_route_par_modele_jamais_par_url_brute(as_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_owned", lambda *_: (_ for _ in ()).throw(main.HTTPException(404)))
    before = value("http_requests_total", method="GET", route="/api/payment_intents/{intent_id}", code="404")
    client.get("/api/payment_intents/pi_abc")
    client.get("/api/payment_intents/pi_def")
    after = value("http_requests_total", method="GET", route="/api/payment_intents/{intent_id}", code="404")
    assert after - before == 2
    assert 'route="/api/payment_intents/pi_abc"' not in client.get("/metrics").text


def test_scan_compte_sous_unmatched() -> None:
    before = value("http_requests_total", method="GET", route="unmatched", code="404")
    client.get("/wp-admin/setup.php")
    assert value("http_requests_total", method="GET", route="unmatched", code="404") - before == 1


def test_issue_comptee_une_seule_fois() -> None:
    intent = {"id": "pi_unique_1", "status": "succeeded", "amount": 100, "owner": "alice"}
    before = value("payments_total", provider="stripe", status="ok")
    metrics.payment(intent, "stripe")
    metrics.payment(intent, "stripe")  # le frontend relit le paiement : pas de double compte
    assert value("payments_total", provider="stripe", status="ok") - before == 1


def test_refus_et_paiement_en_cours() -> None:
    before = value("payments_total", provider="stripe", status="refused")
    metrics.payment({"id": "pi_wait", "status": "requires_action"}, "stripe")  # pas encore d'issue
    metrics.payment({"id": "pi_ko", "status": "canceled", "error": {"code": "card_declined"}}, "stripe")
    assert value("payments_total", provider="stripe", status="refused") - before == 1


def test_panne_stripe_comptee_en_error(as_client, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(**_):
        raise stripe.APIConnectionError("Stripe injoignable")

    monkeypatch.setattr(main.stripe, "api_key", "sk_test_x")
    monkeypatch.setattr(main.stripe.PaymentIntent, "create", down)
    before = value("payments_total", provider="stripe", status="error")
    assert client.post("/api/payment_intents", json={"amount": 100}).status_code == 502
    assert value("payments_total", provider="stripe", status="error") - before == 1


def test_dependances_sans_declencher_de_sonde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "probe_stripe", lambda: pytest.fail("/metrics ne doit pas sonder Stripe"))
    monkeypatch.setitem(main._stripe_probe, "up", True)
    store._up = False
    client.get("/metrics")
    assert value("payment_api_dependency_up", dependency="stripe") == 1
    assert value("payment_api_dependency_up", dependency="db") == 0


def test_journal_json_d_un_paiement() -> None:
    lines: list[dict] = []

    class Grab(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(json.loads(main._Json().format(record)))

    grab = Grab()
    main.log.addHandler(grab)  # le logger des paiements remonte vers celui de payment-api
    try:
        metrics.payment({"id": "pi_log_1", "status": "canceled", "amount": 900, "owner": "bob", "error": {"code": "insufficient_funds"}}, "stripe")
    finally:
        main.log.removeHandler(grab)
    [line] = [entry for entry in lines if entry.get("payment_id") == "pi_log_1"]
    assert line["event"] == "payment"
    assert line["status"] == "canceled"
    assert line["decline_code"] == "insufficient_funds"
    assert line["service"] == "payment-api"

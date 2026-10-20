"""
Vérification des jetons par payment-api, contre un faux service d'authentification
(httpx.MockTransport) qui publie une clé Ed25519 générée pour le test.

    cd backend && python -m pytest
"""

from __future__ import annotations

import base64
import json
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main, security
from app.security import User

KEY = Ed25519PrivateKey.generate()
KID = "test-kid"


def _jwks() -> dict:
    raw = KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"keys": [{"kty": "OKP", "crv": "Ed25519", "x": x, "kid": KID, "alg": "EdDSA", "use": "sig"}]}


def token(sub: str = "alice", role: str = "client", *, ttl: int = 600, aud: str = security.AUDIENCE, kid: str = KID, key=KEY) -> str:
    now = int(time.time())
    claims = {"iss": security.ISSUER, "aud": aud, "sub": sub, "role": role, "iat": now, "exp": now + ttl}
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": kid})


class FakeAuth:
    def __init__(self) -> None:
        self.calls = 0
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.down:
            return httpx.Response(503)
        assert request.url.path == "/auth/jwks.json"
        return httpx.Response(200, json=_jwks())


@pytest.fixture
def auth(monkeypatch: pytest.MonkeyPatch) -> FakeAuth:
    fake = FakeAuth()
    monkeypatch.setattr(security, "_http", httpx.Client(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(security, "_keys", {})
    monkeypatch.setattr(security, "_fetched_at", -security.REFRESH_SECONDS)
    return fake


@pytest.fixture
def balance(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SimpleNamespace(currency="eur", amount=1234)
    monkeypatch.setattr(main.stripe.Balance, "retrieve", lambda: SimpleNamespace(available=[entry], pending=[entry]))


client = TestClient(main.app)


def get(path: str, bearer: str | None = None) -> httpx.Response:
    return client.get(path, headers={"Authorization": f"Bearer {bearer}"} if bearer else {})


def test_sans_jeton_401(auth: FakeAuth) -> None:
    res = get("/api/payment_intents")
    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"
    assert client.post("/api/payment_intents", json={"amount": 100}).status_code == 401
    assert client.post("/api/paypal/orders", json={"amount": 100}).status_code == 401


def test_sondes_restent_ouvertes(auth: FakeAuth, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "probe_stripe", lambda: {"at": 0.0, "up": True, "ms": 1})
    assert get("/api/health").status_code == 200
    assert get("/api/status").status_code == 200
    assert auth.calls == 0


def test_solde_reserve_aux_operateurs(auth: FakeAuth, balance: None) -> None:
    assert get("/api/balance", token(role="client")).status_code == 403
    res = get("/api/balance", token("operateur", "operator"))
    assert res.status_code == 200
    assert res.json()["available"] == 1234


def test_cle_chargee_une_fois_puis_gardee(auth: FakeAuth, balance: None) -> None:
    for _ in range(3):
        assert get("/api/balance", token("operateur", "operator")).status_code == 200
    assert auth.calls == 1

    # Le service d'authentification tombe : les sessions ouvertes continuent.
    auth.down = True
    assert get("/api/balance", token("operateur", "operator")).status_code == 200


def test_jeton_expire(auth: FakeAuth) -> None:
    res = get("/api/payment_intents", token(ttl=-5))
    assert res.status_code == 401
    assert "expirée" in res.json()["detail"]


def test_mauvaise_audience(auth: FakeAuth) -> None:
    assert get("/api/payment_intents", token(aud="autre-service")).status_code == 401


def test_signe_par_une_autre_cle(auth: FakeAuth) -> None:
    assert get("/api/payment_intents", token(key=Ed25519PrivateKey.generate())).status_code == 401


def test_hs256_forge_avec_la_cle_publique(auth: FakeAuth) -> None:
    forged = jwt.encode(
        {"iss": security.ISSUER, "aud": security.AUDIENCE, "sub": "pirate", "role": "operator", "exp": 2**31},
        _jwks()["keys"][0]["x"],
        algorithm="HS256",
        headers={"kid": KID},
    )
    assert get("/api/balance", forged).status_code == 401


def test_role_inconnu(auth: FakeAuth) -> None:
    assert get("/api/payment_intents", token(role="admin")).status_code == 401


def test_kid_inconnus_en_rafale_un_seul_rechargement(auth: FakeAuth, balance: None) -> None:
    assert get("/api/balance", token("operateur", "operator")).status_code == 200  # charge la clé
    for i in range(5):
        assert get("/api/payment_intents", token(kid=f"inconnu-{i}")).status_code == 401
    assert auth.calls == 1


def test_kid_non_textuel(auth: FakeAuth) -> None:
    # Fabriqué à la main : PyJWT refuse lui-même d'émettre un tel en-tête.
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    bad = f"{part({'alg': 'EdDSA', 'kid': ['a']})}.{part({'sub': 'x', 'role': 'client'})}.c2ln"
    assert get("/api/payment_intents", bad).status_code == 401


def test_auth_injoignable_sans_cle_connue_503(auth: FakeAuth) -> None:
    auth.down = True
    assert get("/api/payment_intents", token()).status_code == 503


def test_un_client_ne_relit_pas_le_paiement_d_un_autre(monkeypatch: pytest.MonkeyPatch) -> None:
    pi = SimpleNamespace(metadata=SimpleNamespace(to_dict=lambda: {"owner": "alice"}))
    monkeypatch.setattr(main.stripe.PaymentIntent, "retrieve", lambda *a, **k: pi)
    assert main._owned("pi_1", User("alice", "client")) is pi
    assert main._owned("pi_1", User("operateur", "operator")) is pi
    with pytest.raises(HTTPException) as exc:
        main._owned("pi_1", User("bob", "client"))
    assert exc.value.status_code == 404


def test_session_par_cookie_du_navigateur(auth: FakeAuth, balance: None) -> None:
    res = client.get("/api/balance", headers={"Cookie": f"rp_session={token('operateur', 'operator')}"})
    assert res.status_code == 200
    assert client.get("/api/balance", headers={"Cookie": f"rp_session={token(role='client')}"}).status_code == 403


def test_bearer_prioritaire_sur_le_cookie(auth: FakeAuth, balance: None) -> None:
    headers = {"Authorization": f"Bearer {token('operateur', 'operator')}", "Cookie": f"rp_session={token(role='client')}"}
    assert client.get("/api/balance", headers=headers).status_code == 200


def test_documentation_sous_le_prefixe_api() -> None:
    assert client.get("/api/docs").status_code == 200
    assert "/api/payment_intents" in client.get("/api/openapi.json").json()["paths"]

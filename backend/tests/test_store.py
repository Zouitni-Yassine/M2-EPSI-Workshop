"""
Journal des paiements : écriture, lecture filtrée, panne de la base, réconciliation avec Stripe.

    cd backend && python -m pytest
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, security, store
from app.security import User


def intent(pid: str, owner: str = "alice", status: str = "succeeded", at: str = "2026-10-20T10:00:00+00:00") -> dict:
    return {
        "id": pid,
        "idempotencyKey": f"idem_{pid}",
        "amount": 1200,
        "currency": "EUR",
        "status": status,
        "owner": owner,
        "card": {"brand": "visa", "last4": "4242", "holder": "Alice"},
        "createdAt": at,
        "reference": "RSL-0000-0001",
        "rail": {},
        "history": [],
        "clientSecret": "pi_secret_ne_doit_pas_rester",
    }


@pytest.fixture
def as_user():
    def login(user: User) -> None:
        main.app.dependency_overrides[security.current_user] = lambda: user

    yield login
    main.app.dependency_overrides.clear()


client = TestClient(main.app)


def test_ecrit_puis_relit_sans_client_secret() -> None:
    store.save(intent("pi_1"), "stripe")
    [row] = store.recent("stripe")
    assert row["id"] == "pi_1"
    assert "clientSecret" not in row


def test_mise_a_jour_au_lieu_de_doublon() -> None:
    store.save(intent("pi_1", status="processing"), "stripe")
    store.save(intent("pi_1", status="succeeded"), "stripe")
    assert [r["status"] for r in store.recent("stripe")] == ["succeeded"]


def test_filtre_par_client_et_par_prestataire() -> None:
    store.save(intent("pi_a", owner="alice", at="2026-10-20T10:00:00+00:00"), "stripe")
    store.save(intent("pi_b", owner="bob", at="2026-10-20T11:00:00+00:00"), "stripe")
    store.save(intent("7PAYPAL0001", owner="alice"), "paypal")
    assert [r["id"] for r in store.recent("stripe")] == ["pi_b", "pi_a"]
    assert [r["id"] for r in store.recent("stripe", "alice")] == ["pi_a"]
    assert store.owner_of("7PAYPAL0001") == "alice"
    assert store.owner_of("inconnu") is None


def test_survit_au_redemarrage() -> None:
    store.save(intent("pi_1"), "stripe")
    store.reset()
    assert [r["id"] for r in store.recent("stripe")] == ["pi_1"]


def test_base_en_panne_record_ne_leve_pas() -> None:
    store._up = False
    assert store.record(intent("pi_1"), "stripe")["id"] == "pi_1"
    with pytest.raises(store.StoreError):
        store.save(intent("pi_1"), "stripe")


def test_base_injoignable_erreur_propre(monkeypatch: pytest.MonkeyPatch, journal) -> None:
    # Un dossier à la place du fichier : SQLite ne peut pas ouvrir la base.
    (journal / "dossier.db").mkdir()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{journal / 'dossier.db'}")
    store.reset()
    assert store.ping() is False
    with pytest.raises(store.StoreError):
        store.recent("stripe")


def test_mot_de_passe_hors_de_l_url(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    secret = tmp_path / "pw"
    secret.write_bytes(b"s3cret\r\n")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://payments@db:5432/payments")
    monkeypatch.setenv("DB_PASSWORD_FILE", str(secret))
    url = store.database_url()
    assert url.password == "s3cret"
    assert "s3cret" not in str(url)  # masqué si l'URL est journalisée


def test_journal_lu_en_base_par_client(as_user) -> None:
    store.save(intent("pi_a", owner="alice"), "stripe")
    store.save(intent("pi_b", owner="bob"), "stripe")
    as_user(User("alice", "client"))
    assert [r["id"] for r in client.get("/api/payment_intents").json()] == ["pi_a"]
    as_user(User("operateur", "operator"))
    assert len(client.get("/api/payment_intents").json()) == 2


def test_base_en_panne_le_journal_repasse_par_stripe(as_user, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(*_a, **_k):
        raise store.StoreError("base injoignable")

    monkeypatch.setattr(store, "recent", down)
    monkeypatch.setattr(main.stripe.PaymentIntent, "list", lambda **_k: SimpleNamespace(data=[]))
    as_user(User("alice", "client"))
    assert client.get("/api/payment_intents").json() == []


def test_reconciliation_rejoue_stripe(monkeypatch: pytest.MonkeyPatch) -> None:
    pis = [SimpleNamespace(id="pi_1"), SimpleNamespace(id="pi_2")]
    monkeypatch.setattr(main.stripe, "api_key", "sk_test_x")
    monkeypatch.setattr(main.stripe.PaymentIntent, "list", lambda **_k: SimpleNamespace(data=pis))
    monkeypatch.setattr(main, "to_intent", lambda pi: intent(pi.id))
    main.reconcile_stripe()
    assert sorted(r["id"] for r in store.recent("stripe")) == ["pi_1", "pi_2"]


def test_status_et_health_exposent_la_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "probe_stripe", lambda: {"at": 0.0, "up": True, "ms": 1})
    store._up = True
    assert client.get("/api/status").json()["db"] == {"up": True}
    store._up = False
    assert client.get("/api/status").json()["db"] == {"up": False}
    # Une base en panne ne rend pas l'API « malade » : la redémarrer ne réparerait rien.
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["db"] is False

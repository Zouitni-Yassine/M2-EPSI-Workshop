"""
Journal des paiements, dans PostgreSQL.

Stripe et PayPal restent la source de vérité de l'argent. La base garde notre
vue : qui a payé quoi, le dernier état connu, de quoi afficher le journal sans
redemander à Stripe. Elle survit aux redémarrages de payment-api : après une
remédiation, le journal est intact.

Si la base tombe, les paiements continuent : l'écriture est sautée et
journalisée. Quand elle revient, payment-api rejoue les derniers paiements
Stripe pour combler le trou (voir `reconcile_stripe` dans main.py).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Column, DateTime, MetaData, String, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import URL, Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger("payment-api.store")

metadata = MetaData()
payments = Table(
    "payments",
    metadata,
    Column("id", String(64), primary_key=True),  # pi_… chez Stripe, identifiant de commande chez PayPal
    Column("provider", String(16), nullable=False),
    Column("owner", String(64), nullable=False, index=True),
    Column("amount", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("status", String(32), nullable=False),
    Column("reference", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Le PaymentIntent tel que le frontend l'affiche, sans clientSecret.
    Column("data", JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
)


class StoreError(Exception):
    """La base n'a pas répondu."""


_engine: Engine | None = None
_schema_ready = False
_lock = threading.Lock()
# None tant que la sonde n'a rien dit ; False quand la base est injoignable.
_up: bool | None = None


def _secret(name: str) -> str:
    """NAME, ou le fichier pointé par NAME_FILE (secret Docker, rendu Vault Agent, SOPS)."""
    path = os.getenv(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv(name, "")


def database_url() -> URL:
    """DATABASE_URL, mot de passe lu à part (DB_PASSWORD ou DB_PASSWORD_FILE) : il n'est jamais dans l'URL."""
    url = make_url(os.getenv("DATABASE_URL") or "sqlite:///./data/payments.db")
    password = _secret("DB_PASSWORD")
    return url.set(password=password) if password else url


def _get_engine() -> Engine:
    global _engine, _schema_ready
    with _lock:
        if _engine is None:
            url = database_url()
            options: dict[str, Any] = {"pool_pre_ping": True}
            if url.get_backend_name() == "postgresql":
                # Une base injoignable répond en deux secondes, pas après le délai TCP du système.
                options.update(connect_args={"connect_timeout": 2}, pool_size=5, max_overflow=5, pool_timeout=2)
            elif url.database:
                os.makedirs(os.path.dirname(url.database) or ".", exist_ok=True)
            _engine = create_engine(url, **options)
        if not _schema_ready:
            metadata.create_all(_engine)
            _schema_ready = True
        return _engine


def _guard() -> None:
    if _up is False:
        # La sonde sait déjà que la base est tombée : on n'attend pas deux secondes par requête.
        raise StoreError("base injoignable")


def _run(work: Callable[[Connection], Any]) -> Any:
    try:
        with _get_engine().begin() as conn:
            return work(conn)
    except SQLAlchemyError as exc:
        raise StoreError(str(getattr(exc, "orig", exc)).splitlines()[0]) from exc


def save(intent: dict[str, Any], provider: str) -> None:
    _guard()
    data = {k: v for k, v in intent.items() if k != "clientSecret"}  # il permet de confirmer le paiement
    row = {
        "id": intent["id"],
        "provider": provider,
        "owner": intent.get("owner", ""),
        "amount": intent["amount"],
        "currency": intent.get("currency", "EUR"),
        "status": intent["status"],
        "reference": intent.get("reference", ""),
        "created_at": datetime.fromisoformat(intent["createdAt"]),
        "updated_at": datetime.now(timezone.utc),
        "data": data,
    }

    def write(conn: Connection) -> None:
        insert = postgresql.insert if conn.dialect.name == "postgresql" else sqlite.insert
        stmt = insert(payments).values(**row)
        fresh = {k: stmt.excluded[k] for k in ("owner", "amount", "status", "reference", "updated_at", "data")}
        conn.execute(stmt.on_conflict_do_update(index_elements=[payments.c.id], set_=fresh))

    _run(write)


def record(intent: dict[str, Any], provider: str) -> dict[str, Any]:
    """Écrit le paiement sans jamais faire échouer la requête : l'argent a déjà bougé chez le prestataire."""
    try:
        save(intent, provider)
    except StoreError as exc:
        log.warning(
            "paiement non journalisé",
            extra={"fields": {"event": "store", "payment_id": intent.get("id"), "provider": provider, "error": str(exc)}},
        )
    return intent


def recent(provider: str, owner: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Les derniers paiements d'un prestataire, du plus récent au plus ancien ; ceux d'un client si `owner`."""

    def read(conn: Connection) -> list[dict[str, Any]]:
        q = select(payments.c.data).where(payments.c.provider == provider)
        if owner is not None:
            q = q.where(payments.c.owner == owner)
        q = q.order_by(payments.c.created_at.desc(), payments.c.updated_at.desc()).limit(limit)
        return [row.data for row in conn.execute(q)]

    _guard()
    return _run(read)


def owner_of(payment_id: str) -> str | None:
    _guard()
    return _run(lambda conn: conn.execute(select(payments.c.owner).where(payments.c.id == payment_id)).scalar_one_or_none())


def ping() -> bool:
    try:
        _run(lambda conn: conn.execute(text("SELECT 1")))
        return True
    except StoreError:
        return False


def up() -> bool | None:
    return _up


def watch(on_recover: Callable[[], None], every: float = 2.0) -> None:
    """
    Sonde la base en tâche de fond. /status lit le résultat sans jamais attendre la base :
    une base lente ne doit pas faire passer l'API pour morte aux yeux du détecteur.
    """

    def loop() -> None:
        global _up
        while True:
            ok = ping()
            if ok and _up is not True:
                if _up is False:
                    log.warning("base de retour", extra={"fields": {"event": "store", "db": "up"}})
                threading.Thread(target=on_recover, name="reconcile", daemon=True).start()
            elif not ok and _up is not False:
                log.warning("base injoignable", extra={"fields": {"event": "store", "db": "down"}})
            _up = ok
            time.sleep(every)

    threading.Thread(target=loop, name="db-probe", daemon=True).start()


def reset() -> None:
    """Oublie la connexion et l'état de la sonde (tests, changement d'URL)."""
    global _engine, _schema_ready, _up
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine, _schema_ready, _up = None, False, None

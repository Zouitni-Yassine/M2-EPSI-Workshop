from __future__ import annotations

import pytest

from app import store


@pytest.fixture(autouse=True)
def journal(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Chaque test a sa base SQLite jetable : même code SQLAlchemy que PostgreSQL, sans serveur."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'payments.db'}")
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("DB_PASSWORD_FILE", raising=False)
    store.reset()
    yield tmp_path
    store.reset()

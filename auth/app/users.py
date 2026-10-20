"""
Comptes utilisateurs : stockage, mots de passe, comptes de démonstration.

La base est choisie par DATABASE_URL : PostgreSQL sous Docker, SQLite dans
AUTH_DATA_DIR quand le service tourne seul. Le mot de passe ne figure jamais
dans l'URL : il vient de DB_PASSWORD ou du fichier DB_PASSWORD_FILE.

    python -m app.users add alice client     # mot de passe demandé au clavier
    python -m app.users list
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from dataclasses import dataclass
from typing import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, create_engine, func, select, text
from sqlalchemy.engine import URL, make_url

ROLES = ("client", "operator")
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MIN_PASSWORD = 8

_hasher = PasswordHasher()  # argon2id, paramètres recommandés par la bibliothèque

# Hash d'un mot de passe que personne ne connaît. On le vérifie quand l'identifiant
# n'existe pas : la réponse prend le même temps, et ne dit pas quels comptes existent.
_DUMMY = _hasher.hash("compte-inexistant-resilience-pay")

metadata = MetaData()
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), unique=True, nullable=False),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(16), nullable=False),
    Column("disabled", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


@dataclass(frozen=True)
class User:
    username: str
    role: str


def secret(name: str) -> str:
    """NAME, ou le fichier pointé par NAME_FILE (secret Docker, rendu Vault Agent, SOPS)."""
    path = os.getenv(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return os.getenv(name, "")


def database_url(data_dir: str) -> URL:
    url = make_url(os.getenv("DATABASE_URL") or f"sqlite:///{data_dir}/auth.db")
    password = secret("DB_PASSWORD")
    return url.set(password=password) if password else url


def _verify(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def check(username: str, role: str, password: str) -> str | None:
    """Ce qui rend le compte invalide, ou None."""
    if not USERNAME.match(username):
        return "identifiant invalide (minuscules, chiffres, . _ -, 2 à 64 caractères)"
    if role not in ROLES:
        return f"rôle inconnu « {role} » (attendu : {', '.join(ROLES)})"
    if len(password) < MIN_PASSWORD:
        return f"mot de passe trop court (au moins {MIN_PASSWORD} caractères)"
    return None


class Store:
    def __init__(self, url: URL) -> None:
        options: dict = {"pool_pre_ping": True}
        if url.get_backend_name() == "postgresql":
            # Une base injoignable répond en deux secondes, pas après le délai TCP du système.
            options["connect_args"] = {"connect_timeout": 2}
        elif url.database:
            os.makedirs(os.path.dirname(url.database) or ".", exist_ok=True)
        self.engine = create_engine(url, **options)
        metadata.create_all(self.engine)

    def ping(self) -> bool:
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def get(self, username: str) -> User | None:
        with self.engine.connect() as c:
            row = c.execute(select(users).where(users.c.username == username)).first()
        if row is None or row.disabled:
            return None
        return User(row.username, row.role)

    def authenticate(self, username: str, password: str) -> User | None:
        with self.engine.connect() as c:
            row = c.execute(select(users).where(users.c.username == username)).first()
        if row is None or row.disabled:
            _verify(_DUMMY, password)
            return None
        if not _verify(row.password_hash, password):
            return None
        if _hasher.check_needs_rehash(row.password_hash):
            self._set_hash(username, _hasher.hash(password))
        return User(row.username, row.role)

    def create(self, username: str, password: str, role: str) -> bool:
        """Crée le compte ; False s'il existe déjà (jamais d'écrasement, contrairement au seed)."""
        with self.engine.begin() as c:
            row = c.execute(select(users.c.id).where(users.c.username == username)).first()
            if row is not None:
                return False
            c.execute(users.insert().values(username=username, password_hash=_hasher.hash(password), role=role))
            return True

    def upsert(self, username: str, password: str, role: str) -> str:
        """Crée le compte, ou aligne son mot de passe et son rôle. Renvoie ce qui a été fait."""
        with self.engine.begin() as c:
            row = c.execute(select(users).where(users.c.username == username)).first()
            if row is None:
                c.execute(users.insert().values(username=username, password_hash=_hasher.hash(password), role=role))
                return "created"
            if _verify(row.password_hash, password) and row.role == role and not row.disabled:
                return "unchanged"
            c.execute(
                users.update()
                .where(users.c.username == username)
                .values(password_hash=_hasher.hash(password), role=role, disabled=False)
            )
            return "updated"

    def list(self) -> list[tuple[str, str, bool]]:
        with self.engine.connect() as c:
            rows = c.execute(select(users.c.username, users.c.role, users.c.disabled).order_by(users.c.id))
            return [(r.username, r.role, r.disabled) for r in rows]

    def _set_hash(self, username: str, stored: str) -> None:
        with self.engine.begin() as c:
            c.execute(users.update().where(users.c.username == username).values(password_hash=stored))


def seed_from_env(store: Store, audit: Callable[..., None]) -> None:
    """
    Comptes déclarés dans AUTH_SEED_USERS (« operateur:operator,alice:client »).
    Le mot de passe de chacun vient de AUTH_PASSWORD_<IDENTIFIANT> ou de son _FILE.
    Sans mot de passe valable, le compte n'est pas créé : jamais de compte ouvert par défaut.
    """
    for item in filter(None, (s.strip() for s in os.getenv("AUTH_SEED_USERS", "").split(","))):
        username, _, role = item.partition(":")
        username, role = username.strip().lower(), role.strip()
        variable = "AUTH_PASSWORD_" + re.sub(r"[^A-Z0-9]", "_", username.upper())
        password = secret(variable)
        problem = check(username, role, password) if password else f"{variable} absent"
        if problem:
            audit("warning", "compte de démonstration ignoré", event="seed", username=username, reason=problem)
            continue
        audit("info", "compte de démonstration prêt", event="seed", username=username, role=role, result=store.upsert(username, password, role))


def _cli(argv: list[str]) -> int:
    from dotenv import load_dotenv

    load_dotenv()
    store = Store(database_url(os.getenv("AUTH_DATA_DIR", "./data")))

    if argv[:1] == ["list"]:
        for username, role, disabled in store.list():
            print(f"{username:<24} {role:<9} {'désactivé' if disabled else ''}")
        return 0

    if len(argv) == 3 and argv[0] == "add":
        username, role = argv[1].lower(), argv[2]
        password = getpass.getpass("Mot de passe : ")
        if password != getpass.getpass("Encore une fois : "):
            print("Les deux saisies diffèrent.", file=sys.stderr)
            return 1
        problem = check(username, role, password)
        if problem:
            print(problem, file=sys.stderr)
            return 1
        print(f"{username} : {store.upsert(username, password, role)}")
        return 0

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))

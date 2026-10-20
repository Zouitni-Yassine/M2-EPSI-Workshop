"""
Vérification des jetons délivrés par le service d'authentification.

payment-api n'a jamais la clé de signature : il récupère la clé publique sur
/auth/jwks.json et vérifie chaque jeton localement. Une fois la clé connue,
une panne du service d'authentification n'interrompt pas les paiements des
sessions déjà ouvertes.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ISSUER = "resilience-auth"
AUDIENCE = "resilience-pay"
ROLES = {"client", "operator"}
# Un `kid` inconnu déclenche au plus un rechargement toutes les dix secondes : des jetons
# forgés en rafale ne transforment pas l'API en relais vers le service d'authentification.
REFRESH_SECONDS = 10.0

_http = httpx.Client(timeout=httpx.Timeout(2.0))
_keys: dict[str, Any] = {}
_lock = threading.Lock()
_fetched_at = -REFRESH_SECONDS


@dataclass(frozen=True)
class User:
    username: str
    role: str

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"


def _refresh() -> None:
    global _fetched_at
    with _lock:
        if time.monotonic() - _fetched_at < REFRESH_SECONDS:
            return
        _fetched_at = time.monotonic()
        # Lu à chaque appel : main.py charge le .env après l'import de ce module.
        url = os.getenv("AUTH_URL", "http://localhost:8300").rstrip("/")
        try:
            res = _http.get(f"{url}/auth/jwks.json")
            res.raise_for_status()
            for jwk in res.json().get("keys", []):
                key = jwt.PyJWK(jwk)
                if key.key_id:
                    _keys[key.key_id] = key.key
        except (httpx.HTTPError, ValueError, jwt.PyJWKError):
            pass  # On garde les clés déjà connues.


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


_bearer = HTTPBearer(auto_error=False, description="Jeton délivré par POST /auth/login du service d'authentification")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if cred is None:
        raise _unauthorized("Connexion requise")
    token = cred.credentials
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Jeton illisible") from exc
    if not isinstance(kid, str):
        raise _unauthorized("Jeton sans identifiant de clé")

    key = _keys.get(kid)
    if key is None:
        _refresh()
        key = _keys.get(kid)
    if key is None:
        if not _keys:
            raise HTTPException(status_code=503, detail="Service d'authentification injoignable : session impossible à vérifier")
        raise _unauthorized("Jeton signé par une clé inconnue")

    try:
        # Algorithme figé : « alg: none » ou HS256 signé avec la clé publique sont refusés.
        claims = jwt.decode(
            token,
            key,
            algorithms=["EdDSA"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Session expirée, reconnectez-vous") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("Jeton invalide") from exc

    if claims["role"] not in ROLES:
        raise _unauthorized("Rôle inconnu")
    return User(claims["sub"], claims["role"])


def require_operator(user: User = Depends(current_user)) -> User:
    if not user.is_operator:
        raise HTTPException(status_code=403, detail="Réservé aux opérateurs")
    return user

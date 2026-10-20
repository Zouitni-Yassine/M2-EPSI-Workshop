"""
Jetons de session : signés en Ed25519, vérifiables par tous, falsifiables par personne.

La clé privée ne quitte pas ce service. Les autres services ne reçoivent que la
clé publique (/auth/jwks.json) : même compromis, payment-api ne peut pas
fabriquer un jeton d'opérateur.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ISSUER = "resilience-auth"
AUDIENCE = "resilience-pay"
ALGORITHM = "EdDSA"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def load_key(data_dir: str) -> Ed25519PrivateKey:
    """
    JWT_PRIVATE_KEY_FILE si fourni (secret Docker, Vault, SOPS). Sinon une clé
    générée au premier démarrage et gardée dans AUTH_DATA_DIR : un redémarrage
    du service ne déconnecte personne.
    """
    path = os.getenv("JWT_PRIVATE_KEY_FILE") or os.path.join(data_dir, "jwt_ed25519.pem")
    if os.path.exists(path):
        with open(path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError(f"{path} n'est pas une clé Ed25519")
        return key

    if os.getenv("JWT_PRIVATE_KEY_FILE"):
        raise FileNotFoundError(f"JWT_PRIVATE_KEY_FILE pointe vers {path}, introuvable")

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    os.makedirs(data_dir, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return key


class Signer:
    def __init__(self, key: Ed25519PrivateKey, ttl_seconds: int) -> None:
        self.key = key
        self.ttl = ttl_seconds
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.kid = _b64(hashlib.sha256(raw).digest())[:16]
        self.jwk = {"kty": "OKP", "crv": "Ed25519", "x": _b64(raw), "kid": self.kid, "alg": ALGORITHM, "use": "sig"}

    def issue(self, username: str, role: str) -> tuple[str, int]:
        now = int(time.time())
        expires = now + self.ttl
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": username,
            "role": role,
            "iat": now,
            "exp": expires,
            "jti": secrets.token_hex(8),
        }
        return jwt.encode(claims, self.key, algorithm=ALGORITHM, headers={"kid": self.kid}), expires

    def issue_reset(self, username: str, minutes: int) -> str:
        """Jeton à usage unique pour la réinitialisation : courte durée, marqué `purpose`."""
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": username,
            "purpose": "reset",
            "iat": now,
            "exp": now + minutes * 60,
            "jti": secrets.token_hex(8),
        }
        return jwt.encode(claims, self.key, algorithm=ALGORITHM, headers={"kid": self.kid})

    def verify_reset(self, token: str) -> dict[str, Any]:
        claims = jwt.decode(
            token,
            self.key.public_key(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "jti"]},
        )
        if claims.get("purpose") != "reset":
            # Un jeton de session ne doit jamais permettre de changer un mot de passe.
            raise jwt.InvalidTokenError("purpose")
        return claims

    def verify(self, token: str) -> dict[str, Any]:
        # Algorithme figé : un jeton « alg: none » ou HS256 signé avec la clé publique est refusé.
        return jwt.decode(
            token,
            self.key.public_key(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "role"]},
        )

"""
Crée les secrets locaux manquants dans secrets/ (ignoré par Git). N'écrase jamais un fichier existant.

    python scripts/init-secrets.py

Les mêmes fichiers servent à `docker compose` et à `docker stack deploy` (secrets Docker).
Changer un mot de passe de base après le premier démarrage impose de recréer le volume
(docker compose down -v) : les rôles PostgreSQL ne sont créés qu'à l'initialisation.
En production, ces fichiers viennent de Vault ou de SOPS.
"""

import base64
import pathlib
import secrets

# En-tête PKCS#8 d'une clé privée Ed25519 (RFC 8410), suivi des 32 octets de la graine.
ED25519_PKCS8 = bytes.fromhex("302e020100300506032b657004220420")


def password() -> bytes:
    # Octets bruts, sans fin de ligne : pas de \r glissé par Windows dans le mot de passe.
    return secrets.token_urlsafe(24).encode()


def ed25519_pem() -> bytes:
    der = base64.b64encode(ED25519_PKCS8 + secrets.token_bytes(32)).decode()
    return f"-----BEGIN PRIVATE KEY-----\n{der}\n-----END PRIVATE KEY-----\n".encode()


FILES = {
    "postgres_password.txt": password,
    "auth_db_password.txt": password,
    "payments_db_password.txt": password,
    # Clé de signature des jetons, partagée par toutes les réplicas d'auth.
    "jwt_private_key.pem": ed25519_pem,
}

folder = pathlib.Path(__file__).resolve().parent.parent / "secrets"
folder.mkdir(exist_ok=True)
for name, make in FILES.items():
    path = folder / name
    if path.exists():
        print(f"{name} : déjà présent, conservé")
        continue
    path.write_bytes(make())
    print(f"{name} : créé")

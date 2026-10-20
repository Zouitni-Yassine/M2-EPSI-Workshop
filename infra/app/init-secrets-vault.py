#!/usr/bin/env python3
"""Secrets générés de l'application « Resilience Pay » dans Vault (secret/infra/paiement-app).

    python3 /srv/M2-EPSI-Workshop/infra/app/init-secrets-vault.py

Équivalent Vault de scripts/init-secrets.py : crée les clés manquantes, ne régénère JAMAIS une
clé existante (un mot de passe de base changé après l'initialisation du volume PostgreSQL ne
serait plus accepté). Écriture avec contrôle de version (cas) : pas d'écrasement concurrent.
Aucune valeur n'est affichée, seulement les noms de clés créées ou conservées.

Les secrets fournis par l'utilisateur (clés Stripe, PayPal) vont dans secret/infra/paiement,
que ce script ne touche pas.

Token : VAULT_TOKEN (token admin) ou, à défaut, root_token de /root/.vault/init.json.
"""
import base64
import json
import os
import secrets
import ssl
import sys
import urllib.error
import urllib.request

VAULT_ADDR = os.environ.get("VAULT_ADDR", "https://10.0.1.242:8200")
INIT_FILE = "/root/.vault/init.json"
PATH = "secret/infra/paiement-app"
CTX = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")

# En-tête PKCS#8 d'une clé privée Ed25519 (RFC 8410), suivi des 32 octets de la graine.
ED25519_PKCS8 = bytes.fromhex("302e020100300506032b657004220420")


def password() -> str:
    # 32 caractères URL-safe : ni apostrophe, ni espace, ni fin de ligne
    return secrets.token_urlsafe(24)


def ed25519_pem() -> str:
    der = base64.b64encode(ED25519_PKCS8 + secrets.token_bytes(32)).decode()
    return f"-----BEGIN PRIVATE KEY-----\n{der}\n-----END PRIVATE KEY-----\n"


KEYS = {
    "PAIEMENT_POSTGRES_PASSWORD": password,     # superutilisateur postgres
    "PAIEMENT_AUTH_DB_PASSWORD": password,      # rôle auth
    "PAIEMENT_PAYMENTS_DB_PASSWORD": password,  # rôle payments
    "PAIEMENT_JWT_PRIVATE_KEY": ed25519_pem,    # signature des jetons de session (auth)
    "PAIEMENT_DETECTOR_ADMIN_TOKEN": password,  # POST /reset du détecteur
    "PAIEMENT_AUTH_PASSWORD_OPERATEUR": password,  # compte semé "operateur" (rôle operator)
    "PAIEMENT_AUTH_PASSWORD_CLIENT": password,     # compte semé "client" (rôle client)
}


def die(msg):
    print(f"init-secrets-vault : {msg}", file=sys.stderr)
    sys.exit(1)


def token() -> str:
    if os.environ.get("VAULT_TOKEN"):
        return os.environ["VAULT_TOKEN"]
    try:
        with open(INIT_FILE) as f:
            return json.load(f)["root_token"]
    except (OSError, KeyError, ValueError) as e:
        die(f"pas de VAULT_TOKEN et {INIT_FILE} illisible ({type(e).__name__})")


def api(method, path, tok, data=None, ok404=False):
    mount, _, rest = path.partition("/")
    req = urllib.request.Request(
        f"{VAULT_ADDR}/v1/{mount}/data/{rest}", method=method,
        headers={"X-Vault-Token": tok, "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and ok404:
            return None
        die(f"{method} {path} : HTTP {e.code}")
    except OSError as e:
        die(f"Vault injoignable ({VAULT_ADDR}) : {e}")


def main():
    tok = token()
    current = api("GET", PATH, tok, ok404=True)
    if current and current.get("data", {}).get("data") is not None:
        data = dict(current["data"]["data"])
        version = current["data"]["metadata"]["version"]
    else:
        data, version = {}, 0
    created = []
    for key, make in KEYS.items():
        if data.get(key):
            print(f"{key} : déjà présente, conservée")
        else:
            data[key] = make()
            created.append(key)
            print(f"{key} : créée")
    if created:
        api("POST", PATH, tok, {"options": {"cas": version}, "data": data})
        print(f"{PATH} : version {version + 1} écrite ({len(created)} clé(s) ajoutée(s))")
    else:
        print(f"{PATH} : rien à faire")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Crée (ou renouvelle) les identifiants du registre d'images dans Vault.

    python3 roles/app_registry/files/registry-credentials.py            # crée s'ils manquent
    python3 roles/app_registry/files/registry-credentials.py --rotate   # nouveau mot de passe

Écrit secret/infra/registry (KV v2) avec les clés REGISTRY_USERNAME et REGISTRY_PASSWORD,
que vault-env exporte ensuite à Ansible. Écriture avec le token root (/root/.vault/init.json) :
l'AppRole "ansible" ne fait que lire. Aucune valeur n'est affichée.
Après une rotation : vault-env ansible-playbook app-build.yml (nouveau secret Swarm htpasswd,
service du registre mis à jour, docker login refait sur les managers).
"""
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request

VAULT_ADDR = "https://10.0.1.242:8200"
PATH = "secret/data/infra/registry"
USERNAME = "swarm"
CTX = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")


def api(method, path, token, data=None):
    req = urllib.request.Request(
        f"{VAULT_ADDR}/v1/{path}", method=method, headers={"X-Vault-Token": token},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
        body = r.read()
        return json.loads(body) if body else {}


def main():
    rotate = "--rotate" in sys.argv[1:]
    with open("/root/.vault/init.json") as f:
        token = json.load(f)["root_token"]
    try:
        current = api("GET", PATH, token)["data"]["data"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        current = {}
    if current.get("REGISTRY_USERNAME") and current.get("REGISTRY_PASSWORD") and not rotate:
        print("secret/infra/registry : déjà présent, inchangé")
        return
    api("POST", PATH, token, {"data": {
        "REGISTRY_USERNAME": current.get("REGISTRY_USERNAME") or USERNAME,
        # Alphanumérique : pas de caractère à échapper dans docker login ni dans htpasswd
        "REGISTRY_PASSWORD": "".join(secrets.choice(
            "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789") for _ in range(40)),
    }})
    print("secret/infra/registry : " + ("mot de passe renouvelé" if current else "créé"))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Crée (ou renouvelle) le compte en lecture seule `app-ops` de la page Supervision.

    python3 /srv/M2-EPSI-Workshop/infra/app/app-ops-credentials.py            # crée s'il manque
    python3 /srv/M2-EPSI-Workshop/infra/app/app-ops-credentials.py --rotate   # nouveaux mots de passe

Écrit secret/infra/app-ops (KV v2), clés :
  APP_OPS_READ_PASSWORD  vmauth (/api/v1/query) et nginx de Loki (requêtes, lecture des alertes) ;
                         injecté dans le frontal en secret Swarm ops_monitoring_auth ;
  APP_OPS_AM_PASSWORD    nginx de monitoring01 -> Alertmanager (local, ne quitte pas monitoring01).
Écriture avec le token root (/root/.vault/init.json) : l'AppRole "ansible" ne fait que lire.
Aucune valeur n'est affichée. Ensuite (ou après une rotation) :
    vault-env ansible-playbook monitoring.yml --limit monitoring_core
    vault-env ansible-playbook app-deploy.yml
"""
import json
import secrets
import ssl
import sys
import urllib.error
import urllib.request

VAULT_ADDR = "https://10.0.1.242:8200"
PATH = "secret/data/infra/app-ops"
KEYS = ("APP_OPS_READ_PASSWORD", "APP_OPS_AM_PASSWORD")
CTX = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")


def api(method, path, token, data=None):
    req = urllib.request.Request(
        f"{VAULT_ADDR}/v1/{path}", method=method, headers={"X-Vault-Token": token},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, context=CTX, timeout=10) as r:
        body = r.read()
        return json.loads(body) if body else {}


def password():
    # Alphanumérique : rien à échapper dans htpasswd, vmauth (%{...}) ni l'en-tête Basic
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789") for _ in range(40))


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
    if all(current.get(k) for k in KEYS) and not rotate:
        print("secret/infra/app-ops : déjà présent, inchangé")
        return
    api("POST", PATH, token, {"data": {k: (password() if rotate or not current.get(k) else current[k]) for k in KEYS}})
    print("secret/infra/app-ops : " + ("mots de passe renouvelés" if rotate else "créé"))


if __name__ == "__main__":
    main()

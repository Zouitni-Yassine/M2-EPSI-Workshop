#!/usr/bin/python3
"""Extrait /vaultwarden et /web-vault d'une image OCI (copiée par skopeo) vers un répertoire.
Usage : extract-image.py <répertoire-oci> <destination>"""
import json
import os
import sys
import tarfile

oci, dest = sys.argv[1], sys.argv[2]
blob = lambda d: os.path.join(oci, "blobs", *d.split(":"))
index = json.load(open(os.path.join(oci, "index.json")))
manifest = json.load(open(blob(index["manifests"][0]["digest"])))
os.makedirs(dest, exist_ok=True)
for layer in manifest["layers"]:
    with tarfile.open(blob(layer["digest"])) as t:
        members = [m for m in t.getmembers()
                   if m.name.lstrip("./").split("/")[0] in ("vaultwarden", "web-vault")
                   and (m.isfile() or m.isdir())]
        t.extractall(dest, members=members, filter="data")
if not os.path.isfile(os.path.join(dest, "vaultwarden")):
    sys.exit("binaire vaultwarden absent de l'image")

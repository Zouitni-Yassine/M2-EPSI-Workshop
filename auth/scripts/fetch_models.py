"""
Télécharge les deux modèles ONNX de la reconnaissance faciale, depuis OpenCV Zoo.

- YuNet (détection du visage), environ 230 ko ;
- SFace (reconnaissance : un vecteur de 128 nombres par visage), environ 37 Mo.

    python scripts/fetch_models.py                # dans auth/models (développement)
    python scripts/fetch_models.py /srv/models    # dans l'image Docker (Dockerfile)

Un fichier déjà présent et de taille plausible n'est pas retéléchargé. L'empreinte SHA-256
de chaque fichier est affichée : à reporter dans PINNED pour figer la version.
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

BASE = "https://github.com/opencv/opencv_zoo/raw/main/models"
# nom → (URL, taille minimale en octets : en dessous, c'est un pointeur Git LFS, pas le modèle)
MODELS = {
    "face_detection_yunet_2023mar.onnx": (f"{BASE}/face_detection_yunet/face_detection_yunet_2023mar.onnx", 100_000),
    "face_recognition_sface_2021dec.onnx": (f"{BASE}/face_recognition_sface/face_recognition_sface_2021dec.onnx", 30_000_000),
}
# Empreintes attendues (relevées le 21/10/2026) : un fichier différent arrête le build.
PINNED: dict[str, str] = {
    "face_detection_yunet_2023mar.onnx": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    "face_recognition_sface_2021dec.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
}


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(target: str) -> int:
    os.makedirs(target, exist_ok=True)
    for name, (url, minimum) in MODELS.items():
        path = os.path.join(target, name)
        if not (os.path.isfile(path) and os.path.getsize(path) >= minimum):
            print(f"téléchargement de {name}…", flush=True)
            tmp = path + ".part"
            urllib.request.urlretrieve(url, tmp)
            if os.path.getsize(tmp) < minimum:
                os.remove(tmp)
                print(f"{name} : fichier trop petit, probablement un pointeur Git LFS ({url})", file=sys.stderr)
                return 1
            os.replace(tmp, path)
        digest = sha256(path)
        if name in PINNED and PINNED[name] != digest:
            print(f"{name} : empreinte inattendue {digest}", file=sys.stderr)
            return 1
        print(f"{name}  {os.path.getsize(path)} octets  sha256 {digest}")
    return 0


if __name__ == "__main__":
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "models")
    sys.exit(fetch(sys.argv[1] if len(sys.argv) > 1 else default))

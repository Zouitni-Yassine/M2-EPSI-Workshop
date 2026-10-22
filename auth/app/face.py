"""
Reconnaissance faciale du back-office (consigne additionnelle 1).

Après l'identifiant d'un compte du back-office, le navigateur du poste allume sa caméra,
envoie quelques images puis l'éteint. Ici, une IA légère compare le visage au gabarit
enregistré pour ce compte : seul un visage reconnu ouvre la saisie du mot de passe.

- Détection : YuNet ; reconnaissance : SFace. Deux modèles ONNX d'OpenCV Zoo, sur CPU,
  chargés au premier usage seulement (le service tourne avec peu de mémoire).
- Aucune image n'est conservée : seulement un gabarit, vecteur de 128 nombres par enrôlement.
- Deux cycles ratés (visage refusé, ou mauvais mot de passe après un visage reconnu)
  bloquent l'identifiant 5 minutes ; après un visage refusé, 30 s avant de réessayer.
- Les comptes de service (la sonde de transaction) sont dispensés de visage, mais
  seulement depuis le réseau interne : depuis Internet, ils doivent passer la caméra.
"""

from __future__ import annotations

import ipaddress
import os
import secrets as _secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, String, delete, func, insert, select

from . import users

# ---------------------------------------------------------------- réglages

MODELS_DIR = os.getenv("FACE_MODELS_DIR", os.path.join(os.path.dirname(__file__), "..", "models"))
DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"

# Seuil de similarité cosinus recommandé par OpenCV pour SFace : au-dessus, même personne.
THRESHOLD = float(os.getenv("FACE_THRESHOLD", "0.363"))
MIN_FRAMES = int(os.getenv("FACE_MIN_FRAMES", "2"))  # images exploitables pour juger
ENROLL_MIN_FRAMES = int(os.getenv("FACE_ENROLL_MIN_FRAMES", "3"))
MAX_FRAMES = 8
MAX_FRAME_BYTES = 400_000
MAX_TEMPLATES = 5

# Scan d'enrôlement sous trois angles : de face, puis la tête tournée d'un côté et de l'autre.
# L'orientation se lit sur les repères de YuNet : décalage du nez par rapport au milieu des yeux,
# rapporté à l'écart des yeux (0 de face ; environ 0,2 pour une tête tournée de 25°).
SCAN_POSES = ("face", "gauche", "droite")
SCAN_MIN_FRAMES = int(os.getenv("FACE_SCAN_MIN_FRAMES", "2"))  # images exploitables par angle
FRONT_MAX_YAW = float(os.getenv("FACE_FRONT_MAX_YAW", "0.12"))
SIDE_MIN_YAW = float(os.getenv("FACE_SIDE_MIN_YAW", "0.18"))

CAPTURE_SECONDS = int(os.getenv("FACE_CAPTURE_SECONDS", "60"))  # pour envoyer les images
PASSWORD_SECONDS = int(os.getenv("FACE_PASSWORD_SECONDS", "120"))  # pour saisir le mot de passe
RETRY_SECONDS = int(os.getenv("FACE_RETRY_SECONDS", "30"))  # après un visage refusé
LOCK_SECONDS = int(os.getenv("FACE_LOCK_SECONDS", "300"))  # après deux cycles ratés
MAX_CYCLES = int(os.getenv("FACE_MAX_CYCLES", "2"))  # un essai, puis un seul nouvel essai
FAILURE_WINDOW = int(os.getenv("FACE_FAILURE_WINDOW", "900"))
# Guidage du placement (détection seule) pendant la capture : quelques images par seconde au plus.
MAX_PROBES = int(os.getenv("FACE_MAX_PROBES", str(CAPTURE_SECONDS * 8)))

# Comptes de service dispensés de visage, depuis le réseau interne uniquement.
EXEMPT_USERS = {u.strip().lower() for u in os.getenv("FACE_EXEMPT_USERS", "operateur").split(",") if u.strip()}
SERVICE_NETS = [
    ipaddress.ip_network(n.strip())
    for n in os.getenv("FACE_SERVICE_NETS", "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128").split(",")
    if n.strip()
]

# ---------------------------------------------------------------- tables (même base que les comptes)

face_templates = users.Table(
    "face_templates",
    users.metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(64), nullable=False, index=True),
    Column("embedding", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("created_by", String(64)),
)

access_policies = users.Table(
    "access_policies",
    users.metadata,
    Column("username", String(64), primary_key=True),
    Column("service_account", Boolean, nullable=False, default=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_by", String(64)),
)

auth_events = users.Table(
    "auth_events",
    users.metadata,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime(timezone=True), server_default=func.now(), index=True),
    Column("kind", String(32), nullable=False),
    Column("username", String(64)),
    Column("actor", String(64)),
    Column("ip", String(64)),
    Column("detail", String(255)),
)


def is_internal(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(address.version == n.version and address in n for n in SERVICE_NETS)


# ---------------------------------------------------------------- moteur (IA légère, CPU)


class EngineUnavailable(RuntimeError):
    """Modèles absents ou OpenCV indisponible : la reconnaissance ne peut pas juger."""


class Engine:
    """YuNet trouve le visage, SFace en tire un vecteur de 128 nombres, normalisé."""

    def __init__(self, models_dir: str = MODELS_DIR) -> None:
        self.models_dir = models_dir
        self._lock = threading.Lock()  # les réseaux OpenCV ne sont pas partageables entre fils
        self._detector = None
        self._recognizer = None

    def _load(self) -> None:
        if self._recognizer is not None:
            return
        detector = os.path.join(self.models_dir, DETECTOR_FILE)
        recognizer = os.path.join(self.models_dir, RECOGNIZER_FILE)
        if not (os.path.isfile(detector) and os.path.isfile(recognizer)):
            raise EngineUnavailable(f"modèles absents de {self.models_dir} : lancer scripts/fetch_models.py")
        try:
            import cv2
        except ImportError as exc:  # pragma: no cover - dépend de l'image
            raise EngineUnavailable("OpenCV indisponible") from exc
        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(detector, "", (320, 320), 0.9, 0.3, 5000)
        self._recognizer = cv2.FaceRecognizerSF.create(recognizer, "")

    def embed(self, data: bytes) -> tuple[np.ndarray | None, str]:
        """(vecteur normalisé, "ok") ou (None, raison) : image illisible, aucun ou plusieurs visages."""
        vector, why, _ = self.analyze(data)
        return vector, why

    def analyze(self, data: bytes) -> tuple[np.ndarray | None, str, float]:
        """Comme embed, plus l'orientation de la tête (0 de face, signe selon le côté)."""
        with self._lock:
            image, faces = self._detect(data)
            if image is None:
                return None, "image illisible", 0.0
            if len(faces) == 0:
                return None, "aucun visage", 0.0
            if len(faces) > 1:
                return None, "plusieurs visages", 0.0
            aligned = self._recognizer.alignCrop(image, faces[0])
            vector = self._recognizer.feature(aligned).flatten().astype(np.float32)
            return vector / (np.linalg.norm(vector) + 1e-9), "ok", yaw(faces[0])

    def locate(self, data: bytes) -> dict:
        """
        Où est le visage, pour guider la personne devant la caméra : nombre de visages, boîte et
        repères du plus net (de 0 à 1 dans l'image), orientation. Détection seule, sans reconnaissance.
        """
        with self._lock:
            image, faces = self._detect(data)
        if image is None or len(faces) == 0:
            return {"faces": 0}
        height, width = image.shape[:2]
        best = faces[0]
        x, y, w, h = (float(v) for v in best[:4])
        return {
            "faces": int(len(faces)),
            "box": [round(x / width, 4), round(y / height, 4), round(w / width, 4), round(h / height, 4)],
            "points": [[round(float(best[i]) / width, 4), round(float(best[i + 1]) / height, 4)] for i in range(4, 14, 2)],
            "yaw": yaw(best),
        }

    def _detect(self, data: bytes):
        """(image, visages trouvés par YuNet) ; (None, []) si l'image est illisible. Sous verrou."""
        self._load()
        cv2 = self._cv2
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return None, []
        height, width = image.shape[:2]
        if max(height, width) > 640:
            scale = 640 / max(height, width)
            image = cv2.resize(image, (int(width * scale), int(height * scale)))
            height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(image)
        return image, ([] if faces is None else faces)


def yaw(detection) -> float:
    """
    Orientation de la tête d'après les repères de YuNet (yeux en 4-7, bout du nez en 8-9) :
    décalage horizontal du nez par rapport au milieu des yeux, rapporté à l'écart des yeux.
    """
    right_x, left_x, nose_x = float(detection[4]), float(detection[6]), float(detection[8])
    spread = abs(left_x - right_x) or 1.0
    return round((nose_x - (right_x + left_x) / 2) / spread, 3)


class ScanRefused(ValueError):
    """Le scan ne convient pas ; le message dit quoi corriger, rien n'est enregistré."""


def check_scan(poses: dict[str, list[tuple[np.ndarray, float]]], reasons: dict[str, list[str]]) -> tuple[list[np.ndarray], dict[str, float]]:
    """
    Valide un scan sous trois angles : assez d'images exploitables par angle, la première de
    face, les deux autres tournées de part et d'autre, et la même personne sur les trois.
    Renvoie un gabarit par angle et l'orientation mesurée ; lève ScanRefused sinon.
    """
    labels = {"face": "de face", "gauche": "tête tournée d'un côté", "droite": "tête tournée de l'autre côté"}
    templates: dict[str, np.ndarray] = {}
    yaws: dict[str, float] = {}
    for pose in SCAN_POSES:
        shots = poses.get(pose, [])
        if len(shots) < SCAN_MIN_FRAMES:
            why = reasons.get(pose, ["aucun visage"])[0] if reasons.get(pose) else "aucun visage"
            raise ScanRefused(f"Prise {labels[pose]} : visage trouvé sur {len(shots)} image(s) seulement ({why}). Recommencez, seul face à la caméra, bien éclairé.")
        templates[pose] = template_from([v for v, _ in shots])
        yaws[pose] = round(float(np.median([y for _, y in shots])), 3)

    if abs(yaws["face"]) > FRONT_MAX_YAW:
        raise ScanRefused(f"Prise de face : la tête était tournée ({yaws['face']:+.2f}). Regardez droit la caméra.")
    for pose in ("gauche", "droite"):
        if abs(yaws[pose]) < SIDE_MIN_YAW:
            raise ScanRefused(
                f"Prise {labels[pose]} : tête pas assez tournée ({abs(yaws[pose]):.2f}, il faut au moins {SIDE_MIN_YAW:.2f}). Tournez davantage la tête."
            )
    if (yaws["gauche"] > 0) == (yaws["droite"] > 0):
        raise ScanRefused("Les deux prises de côté sont tournées du même côté : tournez la tête vers la gauche, puis vers la droite.")

    # Les trois angles doivent montrer la même personne que la prise de face.
    for pose in ("gauche", "droite"):
        similarity = float(templates["face"] @ templates[pose])
        if similarity < THRESHOLD:
            raise ScanRefused(f"La prise {labels[pose]} ne semble pas montrer la même personne que la prise de face. Recommencez le scan.")
    return [templates[p] for p in SCAN_POSES], yaws


def match(embeddings: list[np.ndarray], templates: list[np.ndarray], threshold: float = THRESHOLD) -> tuple[bool, float]:
    """Similarité médiane des images avec le meilleur gabarit du compte ; reconnu au-dessus du seuil."""
    if not embeddings or not templates:
        return False, 0.0
    stacked = np.stack(templates)
    scores = [float(np.max(stacked @ e)) for e in embeddings]
    score = float(np.median(scores))
    return score >= threshold, round(score, 3)


def template_from(embeddings: list[np.ndarray]) -> np.ndarray:
    mean = np.mean(np.stack(embeddings), axis=0)
    return (mean / (np.linalg.norm(mean) + 1e-9)).astype(np.float32)


# ---------------------------------------------------------------- gabarits, politiques, journal


class FaceStore:
    def __init__(self, engine) -> None:
        self.engine = engine
        users.metadata.create_all(engine)

    def templates(self, username: str) -> list[np.ndarray]:
        with self.engine.connect() as c:
            rows = c.execute(select(face_templates.c.embedding).where(face_templates.c.username == username))
            return [np.frombuffer(r.embedding, dtype="<f4").copy() for r in rows]

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as c:
            rows = c.execute(select(face_templates.c.username, func.count()).group_by(face_templates.c.username))
            return {r[0]: int(r[1]) for r in rows}

    def add_template(self, username: str, vector: np.ndarray, actor: str) -> int:
        """Ajoute un gabarit (au plus MAX_TEMPLATES : le plus ancien part). Renvoie le nombre de gabarits."""
        with self.engine.begin() as c:
            ids = [r.id for r in c.execute(
                select(face_templates.c.id).where(face_templates.c.username == username).order_by(face_templates.c.id)
            )]
            while len(ids) >= MAX_TEMPLATES:
                c.execute(delete(face_templates).where(face_templates.c.id == ids.pop(0)))
            c.execute(insert(face_templates).values(
                username=username, embedding=vector.astype("<f4").tobytes(), created_by=actor,
            ))
            return len(ids) + 1

    def replace_templates(self, username: str, vectors: list[np.ndarray], actor: str) -> int:
        """Un nouveau scan remplace les gabarits du compte, en une seule transaction."""
        with self.engine.begin() as c:
            c.execute(delete(face_templates).where(face_templates.c.username == username))
            for vector in vectors:
                c.execute(insert(face_templates).values(
                    username=username, embedding=vector.astype("<f4").tobytes(), created_by=actor,
                ))
        return len(vectors)

    def delete_templates(self, username: str) -> int:
        with self.engine.begin() as c:
            return c.execute(delete(face_templates).where(face_templates.c.username == username)).rowcount or 0

    def service_accounts(self) -> set[str]:
        with self.engine.connect() as c:
            rows = c.execute(select(access_policies.c.username).where(access_policies.c.service_account == True))  # noqa: E712
            return {r.username for r in rows} | EXEMPT_USERS

    def set_service_account(self, username: str, value: bool, actor: str) -> None:
        with self.engine.begin() as c:
            c.execute(delete(access_policies).where(access_policies.c.username == username))
            c.execute(insert(access_policies).values(
                username=username, service_account=value, updated_by=actor, updated_at=datetime.now(timezone.utc),
            ))

    def event(self, kind: str, username: str | None, actor: str | None, ip: str | None, detail: str = "") -> None:
        with self.engine.begin() as c:
            c.execute(insert(auth_events).values(
                kind=kind, username=username, actor=actor, ip=ip, detail=detail[:255], at=datetime.now(timezone.utc),
            ))

    def events(self, limit: int = 50) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(auth_events).order_by(auth_events.c.id.desc()).limit(limit))
            return [
                {
                    "at": r.at.isoformat() if r.at else None,
                    "kind": r.kind,
                    "username": r.username,
                    "actor": r.actor,
                    "ip": r.ip,
                    "detail": r.detail or "",
                }
                for r in rows
            ]


def requires_face(user: users.User, ip: str, service_accounts: set[str]) -> bool:
    """Le back-office (rôle opérateur) passe la caméra, sauf un compte de service depuis le réseau interne."""
    if user.role != "operator":
        return False
    return not (user.username in service_accounts and is_internal(ip))


# ---------------------------------------------------------------- cycle d'identification


@dataclass
class Challenge:
    id: str
    username: str
    ip: str
    started: float
    status: str = "capture"  # capture → recognized → used ; ou failed
    recognized_at: float = 0.0
    probes: int = 0


@dataclass
class _Account:
    failures: list[float] = field(default_factory=list)
    retry_until: float = 0.0
    locked_until: float = 0.0


class Gate:
    """
    Garde en mémoire les identifications en cours et les échecs par identifiant.
    Un redémarrage du service les oublie : l'utilisateur recommence simplement l'identification.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._challenges: dict[str, Challenge] = {}
        self._accounts: dict[str, _Account] = {}

    def wait(self, username: str) -> tuple[str, int]:
        """("locked" | "retry" | "", secondes à attendre)."""
        now = time.monotonic()
        with self._lock:
            acc = self._accounts.get(username)
            if acc is None:
                return "", 0
            if acc.locked_until > now:
                return "locked", int(acc.locked_until - now) + 1
            if acc.retry_until > now:
                return "retry", int(acc.retry_until - now) + 1
            return "", 0

    def start(self, username: str, ip: str) -> Challenge:
        now = time.monotonic()
        with self._lock:
            # Une seule identification en cours par compte ; les anciennes et les périmées partent.
            self._challenges = {
                k: c for k, c in self._challenges.items()
                if c.username != username and now - c.started < CAPTURE_SECONDS + PASSWORD_SECONDS
            }
            challenge = Challenge(id=_secrets.token_urlsafe(18), username=username, ip=ip, started=now)
            self._challenges[challenge.id] = challenge
            return challenge

    def capturing(self, challenge_id: str, ip: str) -> Challenge | None:
        """L'identification attend ses images, depuis la même adresse, dans le délai."""
        with self._lock:
            c = self._challenges.get(challenge_id)
            if c is None or c.status != "capture" or c.ip != ip:
                return None
            if time.monotonic() - c.started > CAPTURE_SECONDS:
                c.status = "failed"
                return None
            return c

    def probe(self, challenge_id: str, ip: str) -> Challenge | None:
        """Comme capturing, en comptant les images de guidage : au-delà de MAX_PROBES, l'identification est close."""
        challenge = self.capturing(challenge_id, ip)
        if challenge is None:
            return None
        with self._lock:
            challenge.probes += 1
            if challenge.probes > MAX_PROBES:
                challenge.status = "failed"
                return None
            return challenge

    def recognize(self, challenge: Challenge) -> None:
        with self._lock:
            challenge.status = "recognized"
            challenge.recognized_at = time.monotonic()

    def recognized(self, challenge_id: str | None, username: str, ip: str) -> Challenge | None:
        """Le visage de ce compte a été reconnu depuis cette adresse, et le délai du mot de passe court encore."""
        if not challenge_id:
            return None
        with self._lock:
            c = self._challenges.get(challenge_id)
            if c is None or c.status != "recognized" or c.username != username or c.ip != ip:
                return None
            if time.monotonic() - c.recognized_at > PASSWORD_SECONDS:
                c.status = "failed"
                return None
            return c

    def close(self, challenge: Challenge, status: str) -> None:
        with self._lock:
            challenge.status = status
            self._challenges.pop(challenge.id, None)

    def fail(self, username: str, *, cooldown: bool) -> tuple[str, int]:
        """Compte un cycle raté. Renvoie ("locked", 300) au deuxième, sinon ("retry", 30) ou ("", 0)."""
        now = time.monotonic()
        with self._lock:
            acc = self._accounts.setdefault(username, _Account())
            acc.failures = [t for t in acc.failures if now - t < FAILURE_WINDOW] + [now]
            if len(acc.failures) >= MAX_CYCLES:
                # Bloqué 5 min ; à l'issue, un nouvel essai et un seul nouvel essai, et ainsi de suite.
                acc.failures.clear()
                acc.retry_until = 0.0
                acc.locked_until = now + LOCK_SECONDS
                return "locked", LOCK_SECONDS
            if cooldown:
                acc.retry_until = now + RETRY_SECONDS
                return "retry", RETRY_SECONDS
            return "", 0

    def success(self, username: str) -> None:
        with self._lock:
            self._accounts.pop(username, None)

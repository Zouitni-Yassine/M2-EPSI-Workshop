"""
Service d'authentification — Resilience Pay.

Vérifie un identifiant et un mot de passe, puis délivre un jeton signé qui dit
qui est l'utilisateur et ce qu'il a le droit de faire : `client` (payer, voir
ses paiements) ou `operator` (tout voir, superviser). Les autres services
vérifient ce jeton eux-mêmes avec la clé publique : une panne de ce service
n'interrompt pas les sessions déjà ouvertes.

Chaque tentative est comptée (/metrics) et journalisée en JSON. Après quelques
échecs depuis une même adresse, on refuse sans même vérifier le mot de passe :
la force brute devient lente, et elle se voit.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from . import face, mail, tokens, users

load_dotenv()

ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
# Échecs tolérés sur une fenêtre glissante : par couple adresse + identifiant, puis par adresse
# quel que soit l'identifiant visé. On ne bloque jamais un compte pour tout le monde : sinon
# l'attaquant n'aurait qu'à se tromper cinq fois pour enfermer l'opérateur dehors.
MAX_FAILURES = int(os.getenv("AUTH_MAX_FAILURES", "5"))
MAX_FAILURES_PER_IP = int(os.getenv("AUTH_MAX_FAILURES_PER_IP", "20"))
WINDOW_SECONDS = int(os.getenv("AUTH_LOCKOUT_SECONDS", "300"))

# Cookie de session. Secure seulement derrière HTTPS : en HTTP (démo sur le point d'accès),
# le navigateur refuserait de le renvoyer.
COOKIE = "rp_session"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# ---------------------------------------------------------------- journal et métriques

LOGINS = Counter("auth_login_total", "Tentatives de connexion, par issue", ["result"])
SIGNUPS = Counter("auth_signup_total", "Créations de compte, par issue", ["result"])
RESETS = Counter("auth_reset_total", "Réinitialisations de mot de passe, par issue", ["result"])
RESET_TTL_MINUTES = int(os.getenv("RESET_TTL_MINUTES", "15"))
APP_URL = os.getenv("APP_URL", "http://localhost:5173")
FACES = Counter("auth_face_total", "Vérifications faciales du back-office, par issue", ["result"])
for _result in ("success", "failure", "locked"):
    LOGINS.labels(_result)
for _result in ("recognized", "rejected", "locked", "enrolled"):
    FACES.labels(_result)


class _Json(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": "auth",
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(line, ensure_ascii=False)


_log = logging.getLogger("auth")
_handler = logging.StreamHandler()
_handler.setFormatter(_Json())
_log.addHandler(_handler)
_log.setLevel(logging.INFO)
_log.propagate = False


def audit(level: str, msg: str, **fields: Any) -> None:
    """Une ligne JSON par événement, lue par Loki et le SIEM. Jamais de mot de passe ni de jeton."""
    _log.log(getattr(logging, level.upper()), msg, extra={"fields": fields})


# ---------------------------------------------------------------- freinage de la force brute


class Throttle:
    def __init__(self) -> None:
        self._fails: dict[str, collections.deque[float]] = {}
        self._lock = threading.Lock()

    def wait(self, key: str, limit: int) -> int:
        """Secondes avant de pouvoir réessayer, 0 si la tentative est permise."""
        with self._lock:
            q = self._fails.get(key)
            if not q:
                return 0
            now = time.monotonic()
            while q and now - q[0] > WINDOW_SECONDS:
                q.popleft()
            if len(q) < limit:
                return 0
            return int(WINDOW_SECONDS - (now - q[-limit])) + 1

    def fail(self, key: str) -> None:
        with self._lock:
            if len(self._fails) > 10_000:
                # Des milliers d'identifiants inventés ne font pas grossir la mémoire sans fin.
                now = time.monotonic()
                self._fails = {k: q for k, q in self._fails.items() if q and now - q[-1] <= WINDOW_SECONDS}
            self._fails.setdefault(key, collections.deque(maxlen=100)).append(time.monotonic())

    def clear(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


throttle = Throttle()

# ---------------------------------------------------------------- application


class _State:
    store: users.Store
    signer: tokens.Signer
    faces: face.FaceStore
    engine: face.Engine = face.Engine()
    gate: face.Gate = face.Gate()


state = _State()


@asynccontextmanager
async def lifespan(_: FastAPI):
    data_dir = os.getenv("AUTH_DATA_DIR", "./data")
    # La base peut démarrer après nous (Swarm ne garantit aucun ordre) : on l'attend une minute.
    for attempt in range(1, 31):
        try:
            state.store = users.Store(users.database_url(data_dir))
            break
        except OperationalError as exc:
            audit("warning", "base injoignable, nouvel essai", event="db", attempt=attempt, error=str(exc.orig).splitlines()[0])
            time.sleep(2)
    else:
        raise RuntimeError("base injoignable après une minute")
    state.faces = face.FaceStore(state.store.engine)
    state.signer =tokens.Signer(tokens.load_key(data_dir), ttl_seconds=int(os.getenv("TOKEN_TTL_MINUTES", "120")) * 60)
    users.seed_from_env(state.store, audit)
    audit("info", "service d'authentification prêt", event="start", kid=state.signer.kid)
    yield


# Documentation sous /auth : c'est le seul préfixe que le relais nginx transmet à ce service.
app = FastAPI(
    title="Resilience Pay — authentification",
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/auth/docs",
    openapi_url="/auth/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
_bearer = HTTPBearer(auto_error=False)


class Register(BaseModel):
    email: str = Field(min_length=3, max_length=64)
    firstName: str = Field(min_length=1, max_length=64)
    lastName: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Forgot(BaseModel):
    email: str = Field(min_length=1, max_length=64)


class Reset(BaseModel):
    token: str = Field(min_length=1, max_length=2048)
    password: str = Field(min_length=1, max_length=256)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # Plafonné : un mot de passe de plusieurs mégaoctets ne doit pas occuper le CPU.
    password: str = Field(min_length=1, max_length=256)
    # Back-office : l'identification dont le visage vient d'être reconnu (POST /auth/identify).
    challenge: str | None = Field(default=None, max_length=64)


class Identify(BaseModel):
    username: str = Field(min_length=1, max_length=64)


class NewAccount(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: str = "operator"
    firstName: str = Field(default="", max_length=64)
    lastName: str = Field(default="", max_length=64)


class AccountChange(BaseModel):
    role: str | None = None
    disabled: bool | None = None
    serviceAccount: bool | None = None


class NewPassword(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "inconnue"


def _wait_text(seconds: int) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest:02d} s" if minutes else f"{rest} s"


def _claims(request: Request, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict[str, Any]:
    """Le jeton vient du cookie de session (navigateur) ou de l'en-tête Authorization (scripts, services)."""
    token = cred.credentials if cred else request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Connexion requise", headers={"WWW-Authenticate": "Bearer"})
    try:
        return state.signer.verify(token)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Jeton invalide ou expiré", headers={"WWW-Authenticate": "Bearer"}) from exc


@app.get("/health")
def health(response: Response) -> dict[str, Any]:
    db = state.store.ping()
    if not db:
        response.status_code = 503
    return {"ok": db, "db": db}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/auth/jwks.json")
def jwks(response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "public, max-age=300"
    return {"keys": [state.signer.jwk]}


def _authenticate(body: Credentials, request: Request) -> users.User:
    """Vérifie l'identifiant et le mot de passe, freine la force brute, journalise chaque tentative."""
    ip = request.client.host if request.client else "inconnue"
    username = body.username.strip().lower()
    pair = f"{ip}|{username}"

    wait = max(throttle.wait(pair, MAX_FAILURES), throttle.wait(ip, MAX_FAILURES_PER_IP))
    if wait:
        LOGINS.labels("locked").inc()
        audit("warning", "connexion refusée : trop d'échecs", event="login", result="locked", username=username, ip=ip, retry_after=wait)
        raise HTTPException(status_code=429, detail=f"Trop de tentatives. Réessayez dans {wait} s.", headers={"Retry-After": str(wait)})

    user = state.store.authenticate(username, body.password)
    if user is None:
        throttle.fail(pair)
        throttle.fail(ip)
        LOGINS.labels("failure").inc()
        audit("warning", "échec de connexion", event="login", result="failure", username=username, ip=ip)
        raise HTTPException(status_code=401, detail="Identifiant ou mot de passe incorrect.")

    # Seul le couple est remis à zéro : un compte valable ne blanchit pas une adresse qui en essaie d'autres.
    throttle.clear(pair)
    LOGINS.labels("success").inc()
    audit("info", "connexion réussie", event="login", result="success", username=user.username, role=user.role, ip=ip)
    return user


def _open_session(response: Response, username: str, role: str) -> int:
    """
    Pose la session du navigateur : le jeton part dans un cookie httpOnly, illisible par le
    JavaScript — une faille XSS ne peut pas le voler. SameSite=Strict : aucun autre site ne
    peut s'en servir. Renvoie l'expiration.
    """
    token, expires = state.signer.issue(username, role)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=COOKIE_SECURE, path="/")
    return expires


def _face_required(username: str, ip: str) -> bool:
    """Ce compte doit-il passer la caméra depuis cette adresse ? (back-office, hors compte de service interne)"""
    user = state.store.get(username)
    return user is not None and face.requires_face(user, ip, state.faces.service_accounts())


@app.post("/auth/identify")
def identify(body: Identify, request: Request) -> dict[str, Any]:
    """
    Première étape de la connexion. Un client, ou un identifiant inconnu, passe directement au
    mot de passe : la réponse ne dit pas quels comptes existent. Un compte du back-office passe
    d'abord la caméra du poste ; la saisie du mot de passe ne s'ouvre qu'à un visage reconnu.
    """
    ip = _ip(request)
    username = body.username.strip().lower()
    if not _face_required(username, ip):
        return {"step": "password"}

    wait = throttle.wait(ip, MAX_FAILURES_PER_IP)
    kind = "ip" if wait else ""
    if not wait:
        kind, wait = state.gate.wait(username)
    if wait:
        if kind == "locked":
            message = f"Identifiant bloqué après deux essais ratés. Réessayez dans {_wait_text(wait)}."
        elif kind == "retry":
            message = f"Visage non reconnu. Nouvel essai possible dans {wait} s."
        else:
            message = f"Trop de tentatives. Réessayez dans {wait} s."
        raise HTTPException(status_code=429, detail=message, headers={"Retry-After": str(wait), "X-Auth-Lock": kind})

    if not state.faces.templates(username):
        audit("warning", "identification impossible : aucun visage enrôlé", event="face", result="no_template", username=username, ip=ip)
        raise HTTPException(
            status_code=409,
            detail="Aucun visage enregistré pour ce compte : un administrateur doit l'enrôler depuis les habilitations.",
        )

    challenge = state.gate.start(username, ip)
    audit("info", "identification : caméra demandée", event="face", result="started", username=username, ip=ip)
    return {"step": "face", "challenge": challenge.id, "frames": 5, "captureSeconds": face.CAPTURE_SECONDS}


def _read_frames(frames: list[UploadFile]) -> list[bytes]:
    if not frames or len(frames) > face.MAX_FRAMES:
        raise HTTPException(status_code=422, detail=f"Envoyer entre 1 et {face.MAX_FRAMES} images.")
    data = []
    for upload in frames:
        content = upload.file.read(face.MAX_FRAME_BYTES + 1)
        if len(content) > face.MAX_FRAME_BYTES:
            raise HTTPException(status_code=413, detail="Image trop lourde.")
        data.append(content)
    return data


def _embeddings(frames: list[bytes]) -> tuple[list, list[str]]:
    """Vecteurs des images où l'on voit un seul visage, et pourquoi les autres sont écartées."""
    vectors, reasons = [], []
    for data in frames:
        try:
            vector, why = state.engine.embed(data)
        except face.EngineUnavailable as exc:
            audit("error", "reconnaissance faciale indisponible", event="face", result="unavailable", error=str(exc))
            raise HTTPException(status_code=503, detail="Reconnaissance faciale indisponible côté serveur.") from exc
        if vector is None:
            reasons.append(why)
        else:
            vectors.append(vector)
    return vectors, reasons


def _locate(frame: UploadFile) -> dict[str, Any]:
    """Où est le visage dans une image de la caméra, et les angles attendus, pour guider la personne."""
    [data] = _read_frames([frame])
    try:
        located = state.engine.locate(data)
    except face.EngineUnavailable as exc:
        audit("error", "reconnaissance faciale indisponible", event="face", result="unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="Reconnaissance faciale indisponible côté serveur.") from exc
    return {**located, "frontMaxYaw": face.FRONT_MAX_YAW, "sideMinYaw": face.SIDE_MIN_YAW}


@app.post("/auth/identify/{challenge_id}/probe")
def identify_probe(challenge_id: str, request: Request, frame: UploadFile = File(...)) -> dict[str, Any]:
    """
    Guidage pendant la capture : le navigateur n'envoie ses images au jugement qu'une fois le
    visage bien placé dans l'ovale. Détection seule, rien n'est comparé ni conservé, aucun échec compté.
    """
    if state.gate.probe(challenge_id, _ip(request)) is None:
        raise HTTPException(
            status_code=410,
            detail="Identification expirée : saisissez de nouveau votre identifiant.",
            headers={"X-Auth-Restart": "identify"},
        )
    return _locate(frame)


@app.post("/auth/identify/{challenge_id}/frames")
def identify_frames(challenge_id: str, request: Request, frames: list[UploadFile] = File(...)) -> dict[str, Any]:
    """
    Les images prises par le navigateur juste après l'identifiant. Le visage est comparé au
    gabarit du compte ; aucune image n'est conservée. Un refus compte comme un cycle raté.
    """
    ip = _ip(request)
    challenge = state.gate.capturing(challenge_id, ip)
    if challenge is None:
        raise HTTPException(
            status_code=410,
            detail="Identification expirée : saisissez de nouveau votre identifiant.",
            headers={"X-Auth-Restart": "identify"},
        )
    username = challenge.username
    vectors, reasons = _embeddings(_read_frames(frames))
    enough = len(vectors) >= face.MIN_FRAMES
    recognized, score = face.match(vectors, state.faces.templates(username)) if enough else (False, 0.0)

    if recognized:
        state.gate.recognize(challenge)
        FACES.labels("recognized").inc()
        audit("info", "visage reconnu", event="face", result="recognized", username=username, ip=ip, score=score)
        state.faces.event("face_ok", username, None, ip, f"visage reconnu (similarité {score})")
        return {"status": "recognized", "passwordSeconds": face.PASSWORD_SECONDS}

    state.gate.close(challenge, "failed")
    throttle.fail(ip)
    why = "visage différent du gabarit" if enough else (reasons[0] if reasons else "aucun visage")
    outcome, wait = state.gate.fail(username, cooldown=True)
    FACES.labels("locked" if outcome == "locked" else "rejected").inc()
    audit("warning", "visage non reconnu", event="face", result="rejected", username=username, ip=ip, reason=why, score=score)
    state.faces.event("face_ko", username, None, ip, f"visage non reconnu : {why} (similarité {score})")
    if outcome == "locked":
        state.faces.event("locked", username, None, ip, f"identifiant bloqué {_wait_text(wait)} après deux cycles ratés")
    return {"status": "locked" if outcome == "locked" else "rejected", "retryAfter": wait, "reason": why}


@app.post("/auth/login")
def login(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
    ip = _ip(request)
    username = body.username.strip().lower()
    if not _face_required(username, ip):
        user = _authenticate(body, request)
        return {"expiresAt": _open_session(response, user.username, user.role), "user": user.payload()}

    # Back-office : sans visage reconnu juste avant, le mot de passe n'est même pas vérifié.
    challenge = state.gate.recognized(body.challenge, username, ip)
    if challenge is None:
        audit("warning", "connexion refusée : visage non vérifié", event="login", result="face_required", username=username, ip=ip)
        raise HTTPException(
            status_code=403,
            detail="Vérification du visage requise : saisissez d'abord votre identifiant.",
            headers={"X-Auth-Restart": "identify"},
        )
    try:
        user = _authenticate(body, request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        # Mauvais mot de passe : on recommence toute l'identification, et le cycle compte.
        state.gate.close(challenge, "failed")
        outcome, wait = state.gate.fail(username, cooldown=False)
        state.faces.event("password_ko", username, None, ip, "mot de passe refusé après un visage reconnu")
        detail = "Mot de passe incorrect : recommencez l'identification."
        if outcome == "locked":
            FACES.labels("locked").inc()
            state.faces.event("locked", username, None, ip, f"identifiant bloqué {_wait_text(wait)} après deux cycles ratés")
            detail = f"Mot de passe incorrect. Identifiant bloqué {_wait_text(wait)}."
        raise HTTPException(status_code=401, detail=detail, headers={"X-Auth-Restart": "identify"}) from exc

    state.gate.close(challenge, "used")
    state.gate.success(username)
    state.faces.event("login_ok", username, None, ip, "connexion au back-office : visage puis mot de passe")
    return {"expiresAt": _open_session(response, user.username, user.role), "user": user.payload()}


@app.post("/auth/token")
def issue_token(body: Credentials, request: Request) -> dict[str, Any]:
    """Pour les scripts et les services (transaction de contrôle, Swagger) : jeton à envoyer en Authorization: Bearer."""
    if _face_required(body.username.strip().lower(), _ip(request)):
        raise HTTPException(
            status_code=403,
            detail="Ce compte du back-office exige la reconnaissance faciale : connectez-vous par la page de connexion.",
        )
    user = _authenticate(body, request)
    token, expires = state.signer.issue(user.username, user.role)
    return {"token": token, "expiresAt": expires, "user": user.payload()}


@app.post("/auth/register", status_code=201)
def register(body: Register, request: Request, response: Response) -> dict[str, Any]:
    """
    Création de compte en libre-service : toujours le rôle client, jamais opérateur.
    Le nouveau compte est connecté d'emblée, par le même cookie httpOnly que /auth/login.
    """
    ip = request.client.host if request.client else "inconnue"
    email = body.email.strip().lower()
    first, last = body.firstName.strip(), body.lastName.strip()

    # Même frein que la connexion : une adresse qui enchaîne les créations attend.
    wait = throttle.wait(ip, MAX_FAILURES_PER_IP)
    if wait:
        SIGNUPS.labels("locked").inc()
        audit("warning", "inscription refusée : trop de tentatives", event="signup", result="locked", ip=ip, retry_after=wait)
        raise HTTPException(status_code=429, detail=f"Trop de tentatives. Réessayez dans {wait} s.", headers={"Retry-After": str(wait)})

    problem = users.check_signup(email, first, last, body.password)
    if problem:
        SIGNUPS.labels("invalid").inc()
        raise HTTPException(status_code=422, detail=problem.capitalize())

    if not state.store.create(email, body.password, "client", first, last):
        throttle.fail(ip)
        SIGNUPS.labels("exists").inc()
        audit("warning", "inscription refusée : adresse prise", event="signup", result="exists", username=email, ip=ip)
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cette adresse.")

    expires = _open_session(response, email, "client")
    SIGNUPS.labels("success").inc()
    audit("info", "compte créé", event="signup", result="success", username=email, ip=ip)
    return {"expiresAt": expires, "user": {"username": email, "role": "client", "firstName": first, "lastName": last}}


@app.post("/auth/logout", status_code=204)
def logout(response: Response) -> None:
    # Le JavaScript ne peut pas effacer un cookie httpOnly : c'est le serveur qui le fait.
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=COOKIE_SECURE)


@app.get("/auth/verify")
def verify(role: str | None = None, claims: dict[str, Any] = Depends(_claims)) -> dict[str, Any]:
    """
    Pour le relais nginx (auth_request) : 200 si la session vaut pour ce rôle, 401 sans session
    valable, 403 si le rôle manque. Sans base : appelé à chaque requête de supervision.
    """
    if role and claims["role"] != role:
        raise HTTPException(status_code=403, detail="Rôle insuffisant")
    return {}


@app.post("/auth/forgot")
def forgot(body: Forgot, request: Request) -> dict[str, str]:
    """Toujours la même réponse : la route ne révèle pas quels comptes existent."""
    ip = request.client.host if request.client else "inconnue"
    email = body.email.strip().lower()

    wait = throttle.wait(ip, MAX_FAILURES_PER_IP)
    if wait:
        RESETS.labels("locked").inc()
        raise HTTPException(status_code=429, detail=f"Trop de tentatives. Réessayez dans {wait} s.", headers={"Retry-After": str(wait)})
    throttle.fail(ip)  # Chaque demande compte : impossible d'inonder la boîte d'un tiers.

    # Un identifiant hérité sans forme d'e-mail (comptes seedés comme « operateur ») ne
    # déclenche jamais d'envoi : la réinitialisation ne vaut que pour les comptes à adresse.
    if not users.EMAIL.match(email):
        RESETS.labels("unknown").inc()
        return {"detail": "Si un compte existe avec cette adresse, un e-mail vient de partir."}

    user = state.store.get(email)
    if user is not None and user.role == "operator":
        # Un lien par e-mail ouvrirait une session sans passer la caméra : le back-office
        # ne se réinitialise que par un administrateur, depuis les habilitations.
        RESETS.labels("backoffice").inc()
        audit("warning", "réinitialisation par e-mail refusée : compte du back-office", event="reset", result="backoffice", username=email, ip=ip)
    elif user is not None:
        token = state.signer.issue_reset(email, RESET_TTL_MINUTES, state.store.password_stamp(email) or "")
        link = APP_URL.rstrip("/") + "/?reset=" + token
        try:
            mail.send_reset(email, user.first_name, link, RESET_TTL_MINUTES)
            RESETS.labels("sent").inc()
            audit("info", "e-mail de réinitialisation envoyé", event="reset", result="sent", username=email, ip=ip)
        except OSError as exc:  # smtplib.SMTPException dérive d'OSError.
            RESETS.labels("smtp_error").inc()
            audit("warning", "envoi du mail de réinitialisation impossible", event="reset", result="smtp_error", username=email, error=str(exc)[:200])
    else:
        RESETS.labels("unknown").inc()
        audit("info", "réinitialisation demandée pour une adresse inconnue", event="reset", result="unknown", ip=ip)
    return {"detail": "Si un compte existe avec cette adresse, un e-mail vient de partir."}


@app.post("/auth/reset")
def reset(body: Reset, request: Request, response: Response) -> dict[str, Any]:
    ip = request.client.host if request.client else "inconnue"
    try:
        claims = state.signer.verify_reset(body.token)
    except jwt.InvalidTokenError as exc:
        RESETS.labels("invalid").inc()
        audit("warning", "réinitialisation refusée : jeton invalide", event="reset", result="invalid", ip=ip)
        raise HTTPException(status_code=401, detail="Lien invalide ou expiré. Redemandez un e-mail.") from exc
    # Le lien est scellé sur l'empreinte du mot de passe au moment de la demande : dès que le mot
    # de passe change, tous les liens émis avant deviennent inertes — rejeu impossible, même après
    # un redémarrage du service ou avec plusieurs répliques.
    if claims.get("fp") != state.store.password_stamp(claims["sub"]):
        RESETS.labels("replayed").inc()
        audit("warning", "réinitialisation refusée : lien déjà utilisé ou périmé", event="reset", result="replayed", username=claims["sub"], ip=ip)
        raise HTTPException(status_code=401, detail="Ce lien a déjà servi. Redemandez un e-mail.")
    if len(body.password) < users.MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Mot de passe trop court (au moins {users.MIN_PASSWORD} caractères).")
    target = state.store.get(claims["sub"])
    if target is not None and target.role == "operator":
        RESETS.labels("backoffice").inc()
        raise HTTPException(status_code=403, detail="Les comptes du back-office ne se réinitialisent pas par e-mail : demandez à un administrateur.")

    if not state.store.set_password(claims["sub"], body.password):
        RESETS.labels("gone").inc()
        raise HTTPException(status_code=401, detail="Compte introuvable ou désactivé.")

    user = state.store.get(claims["sub"])
    # Connecté d'emblée avec le nouveau mot de passe, par le cookie de session.
    expires = _open_session(response, claims["sub"], user.role if user else "client")
    RESETS.labels("success").inc()
    audit("info", "mot de passe réinitialisé", event="reset", result="success", username=claims["sub"], ip=ip)
    return {"expiresAt": expires, "user": user.payload() if user else {"username": claims["sub"], "role": "client"}}


@app.get("/auth/me")
def me(claims: dict[str, Any] = Depends(_claims)) -> dict[str, Any]:
    # Relu en base : un compte désactivé perd l'accès même avec un jeton encore valide ici.
    user = state.store.get(claims["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="Compte désactivé ou supprimé", headers={"WWW-Authenticate": "Bearer"})
    return {**user.payload(), "expiresAt": claims["exp"]}


# ---------------------------------------------------------------- habilitations du back-office
#
# Toutes les modifications passent par POST : le WAF (OWASP CRS) refuse PATCH et DELETE.


def _operator(claims: dict[str, Any] = Depends(_claims)) -> dict[str, Any]:
    if claims.get("role") != "operator":
        raise HTTPException(status_code=403, detail="Réservé au back-office.")
    if state.store.get(claims["sub"]) is None:
        raise HTTPException(status_code=401, detail="Compte désactivé ou supprimé", headers={"WWW-Authenticate": "Bearer"})
    return claims


def _target(username: str) -> str:
    username = username.strip().lower()
    if not state.store.exists(username):
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    return username


@app.get("/auth/admin/accounts")
def admin_accounts(claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    counts = state.faces.counts()
    service = state.faces.service_accounts()
    accounts = []
    for account in state.store.accounts():
        name = account["username"]
        accounts.append({
            **account,
            "faces": counts.get(name, 0),
            "serviceAccount": name in service,
            "serviceFromConfig": name in face.EXEMPT_USERS,
            "faceRequired": account["role"] == "operator" and name not in service,
            "self": name == claims["sub"],
        })
    return {"accounts": accounts, "threshold": face.THRESHOLD}


@app.post("/auth/admin/accounts", status_code=201)
def admin_create(body: NewAccount, request: Request, claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    username = body.username.strip().lower()
    problem = users.check(username, body.role, body.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem.capitalize())
    if not state.store.create(username, body.password, body.role, body.firstName.strip(), body.lastName.strip()):
        raise HTTPException(status_code=409, detail="Cet identifiant existe déjà.")
    state.faces.event("account_created", username, claims["sub"], _ip(request), f"compte créé, rôle {body.role}")
    audit("info", "compte créé par le back-office", event="admin", result="created", username=username, role=body.role, actor=claims["sub"])
    return {"username": username}


@app.post("/auth/admin/accounts/{username}")
def admin_update(username: str, body: AccountChange, request: Request, claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    username = _target(username)
    if username == claims["sub"] and (body.role is not None or body.disabled is not None or body.serviceAccount is not None):
        raise HTTPException(status_code=409, detail="Vous ne pouvez pas modifier vos propres habilitations.")
    if body.role is not None and body.role not in users.ROLES:
        raise HTTPException(status_code=422, detail=f"Rôle inconnu (attendu : {', '.join(users.ROLES)}).")
    if body.serviceAccount is False and username in face.EXEMPT_USERS:
        raise HTTPException(status_code=409, detail="Compte de service défini par la configuration (FACE_EXEMPT_USERS).")
    state.store.update(username, role=body.role, disabled=body.disabled)
    if body.serviceAccount is not None:
        state.faces.set_service_account(username, body.serviceAccount, claims["sub"])
    changes = [
        *([f"rôle {body.role}"] if body.role is not None else []),
        *(["compte désactivé" if body.disabled else "compte réactivé"] if body.disabled is not None else []),
        *(["compte de service" if body.serviceAccount else "visage exigé"] if body.serviceAccount is not None else []),
    ]
    state.faces.event("account_updated", username, claims["sub"], _ip(request), ", ".join(changes) or "aucun changement")
    audit("info", "habilitations modifiées", event="admin", result="updated", username=username, actor=claims["sub"], changes=changes)
    return {"ok": True}


@app.post("/auth/admin/accounts/{username}/password")
def admin_password(username: str, body: NewPassword, request: Request, claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    username = _target(username)
    if len(body.password) < users.MIN_PASSWORD:
        raise HTTPException(status_code=422, detail=f"Mot de passe trop court (au moins {users.MIN_PASSWORD} caractères).")
    if not state.store.set_password(username, body.password):
        raise HTTPException(status_code=409, detail="Compte désactivé : réactivez-le d'abord.")
    state.faces.event("password_set", username, claims["sub"], _ip(request), "mot de passe défini par un administrateur")
    audit("info", "mot de passe défini par le back-office", event="admin", result="password", username=username, actor=claims["sub"])
    return {"ok": True}


@app.post("/auth/admin/accounts/{username}/face")
def admin_enroll(
    username: str, request: Request, frames: list[UploadFile] = File(...), claims: dict[str, Any] = Depends(_operator)
) -> dict[str, Any]:
    """Enrôle le visage de la personne devant la caméra du poste : un gabarit de plus pour ce compte."""
    username = _target(username)
    vectors, reasons = _embeddings(_read_frames(frames))
    if len(vectors) < face.ENROLL_MIN_FRAMES:
        why = reasons[0] if reasons else "aucun visage"
        raise HTTPException(
            status_code=422,
            detail=f"Visage trouvé sur {len(vectors)} image(s) seulement ({why}). Placez-vous seul face à la caméra, bien éclairé.",
        )
    total = state.faces.add_template(username, face.template_from(vectors), claims["sub"])
    FACES.labels("enrolled").inc()
    state.faces.event("face_enrolled", username, claims["sub"], _ip(request), f"gabarit ajouté ({total} au total)")
    audit("info", "visage enrôlé", event="admin", result="enrolled", username=username, actor=claims["sub"], templates=total)
    return {"faces": total}


def _analyze(frames: list[bytes]) -> tuple[list[tuple[Any, float]], list[str]]:
    """(vecteur, orientation) des images où l'on voit un seul visage, et pourquoi les autres sont écartées."""
    shots, reasons = [], []
    for data in frames:
        try:
            vector, why, angle = state.engine.analyze(data)
        except face.EngineUnavailable as exc:
            audit("error", "reconnaissance faciale indisponible", event="face", result="unavailable", error=str(exc))
            raise HTTPException(status_code=503, detail="Reconnaissance faciale indisponible côté serveur.") from exc
        if vector is None:
            reasons.append(why)
        else:
            shots.append((vector, angle))
    return shots, reasons


@app.post("/auth/admin/accounts/{username}/face/scan")
def admin_scan(
    username: str,
    request: Request,
    front: list[UploadFile] = File(..., alias="face"),
    left: list[UploadFile] = File(..., alias="gauche"),
    right: list[UploadFile] = File(..., alias="droite"),
    claims: dict[str, Any] = Depends(_operator),
) -> dict[str, Any]:
    """
    Scan guidé sous trois angles (de face, tête tournée d'un côté puis de l'autre). Chaque angle
    est vérifié sur les repères du visage, et les trois doivent montrer la même personne. Le scan
    remplace les gabarits du compte ; s'il ne convient pas, rien n'est enregistré.
    """
    username = _target(username)
    poses, reasons = {}, {}
    for pose, uploads in zip(face.SCAN_POSES, (front, left, right)):
        poses[pose], reasons[pose] = _analyze(_read_frames(uploads))
    try:
        templates, angles = face.check_scan(poses, reasons)
    except face.ScanRefused as exc:
        audit("info", "scan du visage refusé", event="admin", result="scan_refused", username=username, actor=claims["sub"], reason=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    total = state.faces.replace_templates(username, templates, claims["sub"])
    FACES.labels("enrolled").inc()
    detail = "scan sous 3 angles : " + ", ".join(f"{p} {a:+.2f}" for p, a in angles.items())
    state.faces.event("face_enrolled", username, claims["sub"], _ip(request), detail)
    audit("info", "visage scanné sous trois angles", event="admin", result="scanned", username=username, actor=claims["sub"], angles=angles)
    return {"faces": total, "angles": angles}


@app.post("/auth/admin/face/probe")
def admin_face_probe(frame: UploadFile = File(...), claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    """Guidage du scan : position et orientation de la tête, image par image, sans rien enregistrer."""
    return _locate(frame)


@app.post("/auth/admin/accounts/{username}/face/delete")
def admin_face_delete(username: str, request: Request, claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    username = _target(username)
    deleted = state.faces.delete_templates(username)
    state.faces.event("face_deleted", username, claims["sub"], _ip(request), f"{deleted} gabarit(s) supprimé(s)")
    audit("info", "visage supprimé", event="admin", result="face_deleted", username=username, actor=claims["sub"], templates=deleted)
    return {"deleted": deleted}


@app.get("/auth/admin/events")
def admin_events(limit: int = 50, claims: dict[str, Any] = Depends(_operator)) -> dict[str, Any]:
    return {"events": state.faces.events(min(max(limit, 1), 200))}

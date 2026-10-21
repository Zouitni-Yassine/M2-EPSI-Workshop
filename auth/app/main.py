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
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from . import mail, tokens, users

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
for _result in ("success", "failure", "locked"):
    LOGINS.labels(_result)


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
    state.signer = tokens.Signer(tokens.load_key(data_dir), ttl_seconds=int(os.getenv("TOKEN_TTL_MINUTES", "120")) * 60)
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


@app.post("/auth/login")
def login(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
    user = _authenticate(body, request)
    return {"expiresAt": _open_session(response, user.username, user.role), "user": user.payload()}


@app.post("/auth/token")
def issue_token(body: Credentials, request: Request) -> dict[str, Any]:
    """Pour les scripts et les services (transaction de contrôle, Swagger) : jeton à envoyer en Authorization: Bearer."""
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
    if user is not None:
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

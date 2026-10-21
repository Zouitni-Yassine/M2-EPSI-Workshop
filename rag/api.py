"""API HTTP de l'assistant (service rag-api, port 8600), appelée par le bot Discord de l'équipe.

    POST /ask   Authorization: Bearer <jeton>   {"question": "...", "user": "pseudo"}
             -> {"answer": "...", "tools": [...], "model": "...", "mode": "agent|documentation",
                 "duration_s": 12.3}
    GET /health -> {"status": "ok"}  (sans authentification)

Garde-fous : jeton comparé à temps constant (lu dans RAG_API_TOKEN_FILE), question de 1000
caractères au plus, 10 questions par minute au total, une question à la fois (un seul GPU),
120 s au plus par question. Une ligne de journal par question (utilisateur, outils, durée,
statut ; ni la question ni la réponse), sur la sortie standard donc dans journald et Loki.
"""

import asyncio
import hmac
import os
import re
import sys
import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import agent

TOKEN_FILE = os.getenv("RAG_API_TOKEN_FILE", "/etc/rag/api_token")
LIMITE_PAR_MINUTE = int(os.getenv("RAG_API_RATE_PER_MIN", "10"))
DELAI = float(os.getenv("RAG_API_TIMEOUT", "120"))
ATTENTE_FILE = float(os.getenv("RAG_API_QUEUE_WAIT", "30"))
TAILLE_MAX_CORPS = 8192

with open(TOKEN_FILE, encoding="utf-8") as f:
    JETON = f.read().strip().encode()
if len(JETON) < 32:
    sys.exit("rag-api : jeton absent ou trop court")

app = FastAPI(title="Assistant opérateur RESILIENCE-ALPHA", docs_url=None, redoc_url=None,
              openapi_url=None)
verrou = asyncio.Lock()
recentes = deque()


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    user: str | None = Field(default=None, max_length=100)


class Reponse(BaseModel):
    answer: str
    tools: list[str]
    model: str
    mode: str
    duration_s: float


def journal(utilisateur, statut, outils=(), duree=0.0, mode="-"):
    nom = re.sub(r"[^\w.@#-]", "_", utilisateur or "-")[:64]
    print(f"question utilisateur={nom} statut={statut} mode={mode} outils={','.join(outils) or '-'} "
          f"duree={duree:.1f}s", flush=True)


def erreur(code, message, **entetes):
    return JSONResponse({"detail": message}, status_code=code, headers=entetes or None)


@app.middleware("http")
async def garde(request: Request, suite):
    if request.url.path == "/health":
        return await suite(request)
    entete = request.headers.get("authorization", "")
    fourni = entete[7:].strip().encode() if entete[:7].lower() == "bearer " else b""
    if not hmac.compare_digest(fourni, JETON):
        return erreur(401, "jeton absent ou invalide", **{"WWW-Authenticate": "Bearer"})
    try:
        if int(request.headers.get("content-length", "0")) > TAILLE_MAX_CORPS:
            return erreur(413, "requête trop volumineuse")
    except ValueError:
        return erreur(400, "Content-Length invalide")
    return await suite(request)


@app.get("/health")
async def sante():
    return {"status": "ok"}


@app.post("/ask", response_model=Reponse)
async def ask(q: Question):
    # Limite de débit globale (fenêtre glissante d'une minute)
    maintenant = time.monotonic()
    while recentes and maintenant - recentes[0] > 60:
        recentes.popleft()
    if len(recentes) >= LIMITE_PAR_MINUTE:
        journal(q.user, "limite_debit")
        return erreur(429, f"trop de questions ({LIMITE_PAR_MINUTE} par minute au plus)",
                      **{"Retry-After": str(int(60 - (maintenant - recentes[0])) + 1)})
    recentes.append(maintenant)

    # Une question à la fois : les suivantes attendent un peu, puis sont refusées
    try:
        await asyncio.wait_for(verrou.acquire(), ATTENTE_FILE)
    except asyncio.TimeoutError:
        journal(q.user, "occupe")
        return erreur(503, "assistant occupé, réessayer dans un moment", **{"Retry-After": "30"})
    debut = time.monotonic()
    try:
        r = await asyncio.wait_for(agent.repondre(q.question), DELAI)
    except asyncio.TimeoutError:
        journal(q.user, "delai_depasse", duree=time.monotonic() - debut)
        return erreur(504, f"pas de réponse en {DELAI:.0f} s")
    except Exception as e:
        journal(q.user, f"erreur_{e.__class__.__name__}", duree=time.monotonic() - debut)
        return erreur(500, "erreur interne de l'assistant")
    finally:
        verrou.release()
    journal(q.user, "ok", r["tools"], r["duration_s"], r["mode"])
    return r

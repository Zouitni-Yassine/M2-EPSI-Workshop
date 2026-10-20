FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AUTH_DATA_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Utilisateur non privilégié. /data porte la base des comptes et la clé de
# signature : c'est le seul dossier où le conteneur (en lecture seule) écrit.
RUN useradd --system --uid 10004 auth && mkdir /data && chown auth /data && chmod 700 /data
USER auth
VOLUME /data

EXPOSE 8300
HEALTHCHECK --interval=5s --timeout=2s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8300/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]

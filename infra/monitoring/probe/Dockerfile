# Sonde de transaction de Resilience Pay (stack Swarm "probe", rôle Ansible probe).
# Image minimale : Python standard + prometheus_client, utilisateur non root, compatible
# read_only et cap_drop ALL (rien n'est écrit sur le disque).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-compile -r requirements.txt \
 && useradd --system --uid 10010 --no-create-home --shell /usr/sbin/nologin probe
COPY probe.py .

USER 10010
EXPOSE 9110
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:9110/healthz', timeout=2).status == 200 else 1)"]
CMD ["python", "/app/probe.py"]

# PostgreSQL 16 + Patroni (bascule automatique), pour la stack "paiement" (docs/application.md).
# Construite sur le manager par le rôle app_stack (tag = empreinte de ce dossier), poussée dans
# le registre privé. Base : image officielle Debian (dépôt PGDG déjà configuré), Patroni et son
# client etcd en paquets PGDG/Debian, versions figées.
FROM postgres:16.15-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      patroni=4.1.5-2.pgdg12+1 python3-etcd python3-psycopg2 \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/patroni-entrypoint
# Exploitation : docker exec <conteneur> pctl list (patronictl avec les secrets)
COPY pctl /usr/local/bin/pctl

# Le volume monté sur /var/lib/postgresql/data hérite du propriétaire du dossier de l'image
# (postgres) : aucune capacité nécessaire, pas de passage par root
USER postgres
ENTRYPOINT ["/usr/local/bin/patroni-entrypoint"]

#!/bin/sh
# Patroni ne lit pas de fichiers de secrets : les mots de passe (secrets Swarm) sont exportés pour
# ce seul processus, jamais dans la spec du service (même principe que STRIPE_SECRET_KEY).
# Configuration : /etc/patroni/patroni.yml (config Swarm) ; nom et adresses : PATRONI_NAME,
# PATRONI_RESTAPI_CONNECT_ADDRESS, PATRONI_POSTGRESQL_CONNECT_ADDRESS (variables du service).
set -eu

secret() { tr -d '\r\n' < "/run/secrets/$1"; }

PATRONI_SUPERUSER_PASSWORD="$(secret postgres_password)"
PATRONI_REPLICATION_PASSWORD="$(secret replication_password)"
PATRONI_RESTAPI_PASSWORD="$(secret patroni_api_password)"
export PATRONI_SUPERUSER_PASSWORD PATRONI_REPLICATION_PASSWORD PATRONI_RESTAPI_PASSWORD

exec patroni "${PATRONI_CONFIG:-/etc/patroni/patroni.yml}"

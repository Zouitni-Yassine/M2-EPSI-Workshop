#!/bin/sh
# Exécuté une seule fois, à la création du volume : un rôle et une base par service.
# Chaque rôle ne peut ouvrir que sa base : auth ne lit pas les paiements, et inversement.
set -e

secret() { tr -d '\r\n' < "/run/secrets/$1"; }

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v auth_pw="$(secret auth_db_password)" \
  -v payments_pw="$(secret payments_db_password)" <<'SQL'
CREATE ROLE auth LOGIN PASSWORD :'auth_pw';
CREATE DATABASE auth OWNER auth;
REVOKE ALL ON DATABASE auth FROM PUBLIC;

CREATE ROLE payments LOGIN PASSWORD :'payments_pw';
CREATE DATABASE payments OWNER payments;
REVOKE ALL ON DATABASE payments FROM PUBLIC;
SQL

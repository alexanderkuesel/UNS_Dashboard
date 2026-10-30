#!/usr/bin/env bash
# docker-entrypoint-initdb.d hook for the demo-db container: source schema,
# demo data, then the uns layer. Runs once, on an empty data volume.
set -euo pipefail
export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB"

psql -v ON_ERROR_STOP=1 -q -f /uns/db/source/muthur_historian_timescaledb.sql
psql -v ON_ERROR_STOP=1 -q -c "ALTER ROLE grafana PASSWORD '${UNS_PG_PASSWORD//\'/\'\'}'"
psql -v ON_ERROR_STOP=1 -q -f /uns/db/demo/seed_muthur_demo_timescaledb.sql
ENGINE=postgres ADAPTER=muthur_historian READER=grafana PSQL=psql /uns/tools/install_uns.sh

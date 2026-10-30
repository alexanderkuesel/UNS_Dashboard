#!/usr/bin/env bash
# docker-entrypoint-initdb.d hook for the bundled MariaDB containers.
# Runs once, on an empty data volume: historian schema, user passwords,
# demo data (only when UNS_DEMO=1), then the uns layer for the dashboards.
set -euo pipefail

sql() { mariadb --protocol=socket -uroot -p"$MARIADB_ROOT_PASSWORD" "$@"; }
quote() { printf "'%s'" "${1//\'/\'\'}"; }

sql < /uns/db/source/muthur_historian_mariadb.sql
sql -e "ALTER USER 'grafana'@'%' IDENTIFIED BY $(quote "$UNS_MARIADB_PASSWORD")"
if [[ -n "${NODERED_MARIADB_PASSWORD:-}" ]]; then
    sql -e "ALTER USER 'nodered'@'%' IDENTIFIED BY $(quote "$NODERED_MARIADB_PASSWORD")"
fi
if [[ "${UNS_DEMO:-0}" == 1 ]]; then
    sql < /uns/db/demo/seed_muthur_demo_mariadb.sql
fi
ENGINE=mariadb ADAPTER=muthur_historian READER=grafana \
    MARIADB="mariadb --protocol=socket -uroot -p$MARIADB_ROOT_PASSWORD" /uns/tools/install_uns.sh

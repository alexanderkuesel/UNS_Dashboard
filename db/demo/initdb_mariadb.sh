#!/usr/bin/env bash
# docker-entrypoint-initdb.d hook for the demo-mariadb container: source
# schema, demo data, then the uns layer. Runs once, on an empty data volume.
set -euo pipefail

sql() { mariadb --protocol=socket -uroot -p"$MARIADB_ROOT_PASSWORD" "$@"; }

sql < /uns/db/source/muthur_historian_mariadb.sql
sql -e "ALTER USER 'grafana'@'%' IDENTIFIED BY '${UNS_MARIADB_PASSWORD//\'/\'\'}'"
sql < /uns/db/demo/seed_muthur_demo_mariadb.sql
ENGINE=mariadb ADAPTER=muthur_historian READER=grafana \
    MARIADB="mariadb --protocol=socket -uroot -p$MARIADB_ROOT_PASSWORD" /uns/tools/install_uns.sh

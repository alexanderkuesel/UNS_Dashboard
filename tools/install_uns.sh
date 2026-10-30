#!/usr/bin/env bash
# Install (or re-install) the uns layer for one source adapter.
#
#   ENGINE=postgres ADAPTER=muthur_historian READER=grafana tools/install_uns.sh
#   ENGINE=mariadb  ADAPTER=muthur_historian READER=grafana tools/install_uns.sh
#
# Connection: set the client command for the engine, e.g. on the Pi:
#   PSQL="docker exec -i timescaledb psql -U postgres -d home_data"   (postgres)
#   MARIADB="docker exec -i mariadb mariadb -uroot -pSECRET"            (mariadb)
# Defaults are plain `psql` (honours PGHOST/PGUSER/...) and `mariadb`.
#
# The uns schema/database only holds views and functions, so it is
# dropped and rebuilt; source data is never touched. On PostgreSQL this
# happens in one transaction.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
engine="${ENGINE:-postgres}"
adapter="${ADAPTER:-muthur_historian}"
reader="${READER:-grafana}"
dir="$here/db/uns/$engine"
adapter_file="$dir/adapters/$adapter.sql"

if [[ ! -d "$dir" ]]; then
    echo "unknown engine '$engine' (postgres | mariadb)" >&2
    exit 1
fi
if [[ ! -f "$adapter_file" ]]; then
    echo "unknown $engine adapter '$adapter'; available:" >&2
    for f in "$dir"/adapters/[!_]*.sql; do basename "$f" .sql; done >&2
    exit 1
fi

echo "installing uns layer (engine=$engine, adapter=$adapter, reader=$reader)"
case "$engine" in
    postgres)
        {
            echo "SET client_min_messages = warning;"
            echo "DROP SCHEMA IF EXISTS uns CASCADE;"
            echo "CREATE SCHEMA uns;"
            cat "$adapter_file" "$dir/core.sql"
        } | ${PSQL:-psql} -v ON_ERROR_STOP=1 -v reader="$reader" --single-transaction -q -f -
        ;;
    mariadb)
        # MariaDB accounts are user@host; a bare name means any host.
        [[ "$reader" == *@* ]] || reader="'$reader'@'%'"
        {
            echo "DROP DATABASE IF EXISTS uns;"
            echo "CREATE DATABASE uns CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            cat "$adapter_file"
            sed "s/__READER__/$reader/g" "$dir/core.sql"
        } | ${MARIADB:-mariadb}
        ;;
esac
echo "done"

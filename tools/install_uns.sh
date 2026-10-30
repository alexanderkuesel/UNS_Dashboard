#!/usr/bin/env bash
# Install (or re-install) the uns schema for one source adapter.
#
#   ADAPTER=muthur_historian READER=grafana tools/install_uns.sh
#
# Connection: set PSQL to the psql command to run, e.g. against the
# timescaledb container on the Pi:
#   PSQL="docker exec -i timescaledb psql -U postgres -d home_data" tools/install_uns.sh
# Defaults to plain `psql`, which honours PGHOST/PGUSER/PGDATABASE/...
#
# The uns schema only holds views and functions, so it is dropped and
# rebuilt in a single transaction; source data is never touched.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
adapter="${ADAPTER:-muthur_historian}"
reader="${READER:-grafana}"
psql_cmd="${PSQL:-psql}"
adapter_file="$here/db/uns/adapters/$adapter.sql"

if [[ ! -f "$adapter_file" ]]; then
    echo "unknown adapter '$adapter'; available:" >&2
    for f in "$here"/db/uns/adapters/[!_]*.sql; do basename "$f" .sql; done >&2
    exit 1
fi

echo "installing uns schema (adapter=$adapter, reader=$reader)"
{
    echo "SET client_min_messages = warning;"
    echo "DROP SCHEMA IF EXISTS uns CASCADE;"
    cat "$adapter_file"
    cat "$here/db/uns/core.sql"
} | $psql_cmd -v ON_ERROR_STOP=1 -v reader="$reader" --single-transaction -q -f -
echo "done"

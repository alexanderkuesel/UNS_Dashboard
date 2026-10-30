# UNS Dashboard

Grafana dashboards for a **Unified Namespace** organised along the **ISA-95** equipment
hierarchy (enterprise › site › area › line › device), backed by **TimescaleDB** or
**MariaDB** and built to run in Docker on a Raspberry Pi.

The dashboards never query your tables directly. They read a small, fixed **`uns`
contract schema**, and an **adapter** maps each source schema onto it. The first adapter
covers the MUTHUR historian schema (`historian.points` + `historian.readings`), which
ships in two editions:
[TimescaleDB](db/source/muthur_historian_timescaledb.sql) and
[MariaDB](db/source/muthur_historian_mariadb.sql). To support another schema you write one
adapter file; the dashboards stay the same.

```
 MQTT ─► Node-RED ─► historian.points / historian.readings / readings_1h   (your schema)
                                  │
              db/uns/<engine>/adapters/muthur_historian.sql                (mapping, views only)
                                  │
             uns.points · uns.readings · uns.readings_1h                   (contract)
                                  │
         db/uns/<engine>/core.sql: latest values, health, hierarchy, trend helpers
                                  │
              Grafana dashboards (grafana/dashboards/<engine>/*.json)
```

### Engines

| | TimescaleDB / PostgreSQL | MariaDB (10.6+, tested on 11.4 LTS) |
|---|---|---|
| Raw readings | hypertable, compressed after 7 days | InnoDB table clustered on `(point_id, time)` |
| Hourly rollup | continuous aggregate | `readings_1h` table, refreshed every 5 min by an `EVENT` (needs `event_scheduler=ON`) |
| Time zone | `timestamptz` | `DATETIME` in **UTC**: write `UTC_TIMESTAMP(3)` or UTC from Node-RED |
| Grafana data source | `UNS Historian` (postgres) | `UNS Historian (MariaDB)` (mysql, session forced to UTC) |
| Dashboards folder | *UNS · TimescaleDB* | *UNS · MariaDB* |

Each engine gets the same four dashboards with the same layout. Only the SQL dialect
differs: MariaDB has no table functions, arrays or `LATERAL`, so its rollup selection is
inlined in the panel queries instead of living in `uns.trend()`. You can run either
engine or both at once. A folder whose database isn't configured just shows errors and
can be ignored.

## Dashboards

| Dashboard | What it answers |
|---|---|
| **UNS · Enterprise overview** | Model size, % of points reporting, bad-quality share, an interactive **node graph of the ISA-95 tree** (red = silent), per-area health table (click to drill down), ingest rate per site. |
| **UNS · Equipment** | Cascading enterprise › site › area › line › device › measurement filters. Live value tiles, one trend panel **per measurement** (auto-repeated), state timeline for `bool` points, point list with quality/age, asset attributes from the `attributes` jsonb (fw, ip, model…). |
| **UNS · Point trend** | Search any point by UNS path; avg with min/max envelope, statistics, good-quality %, newest raw samples. |
| **UNS · Communication health** | ok / stale / never / disabled counts, silence per device, problem points first, non-good OPC quality samples over time, reporting points per area. The "Stale after" picker sets the threshold. |

![Enterprise overview](docs/screenshots/overview.jpg)
![Equipment](docs/screenshots/equipment.jpg)
![Communication health](docs/screenshots/health.jpg)

*(Screenshots use the bundled demo data.)*

All dashboards share a **Data source** picker and are cross-linked, so they keep the time range when you switch.

**Automatic resolution.** Trends read raw readings for short ranges and switch to the
hourly rollup for buckets ≥ 1 h or ranges ≥ 7 days, so a 1-year chart on the Pi stays fast.
On TimescaleDB, `uns.trend()` fills the last hour or so that the continuous aggregate hasn't
materialised yet with raw data, merged with sample-weighted averages. On MariaDB the rollup
event already includes the current hour, at most 5 minutes behind.

## Quick start: demo on any machine

```bash
cp .env.example .env
sed -i -e 's/^UNS_PG_HOST=.*/UNS_PG_HOST=demo-db/' \
       -e 's/^UNS_MARIADB_HOST=.*/UNS_MARIADB_HOST=demo-mariadb/' .env
docker compose --profile demo up -d --wait
# http://localhost:3000  (admin / change-me)
```

The `demo` profile starts its own TimescaleDB and MariaDB (`demo-timescaledb` or
`demo-mariadb` starts just one). Each loads the historian schema and 14 days of synthetic
1-minute data: a house, garden and workshop, including a sensor with a dead battery, one
that never reported and a disabled one. New samples keep arriving every minute, from a
feed container on TimescaleDB and an `EVENT` on MariaDB. Remove it all with
`docker compose --profile demo down -v`.

## Raspberry Pi setup: TimescaleDB

1. **Install the uns layer** in your historian database. It only creates views and
   functions in schema `uns` and never touches `historian.*`:
   ```bash
   ENGINE=postgres PSQL="docker exec -i timescaledb psql -U postgres -d home_data" tools/install_uns.sh
   ```
   Re-running it is safe: it rebuilds `uns` in one transaction.

2. **Give Grafana a password** for the read-only role the schema created:
   ```bash
   docker exec -it timescaledb psql -U postgres -c "ALTER ROLE grafana PASSWORD 'something-long'"
   ```

3. **Configure** `cp .env.example .env` and set `GRAFANA_ADMIN_PASSWORD`, `UNS_PG_PASSWORD`,
   and how Grafana reaches the database (`UNS_PG_HOST`):
   - TimescaleDB publishes port 5432 on the Pi → keep `host.docker.internal`.
   - TimescaleDB is on its own docker network → `UNS_PG_HOST=timescaledb` and copy
     `compose.override.example.yml` to `compose.override.yml` with that network's name.

4. `docker compose up -d`, then open `http://<pi>:3000`.

## Raspberry Pi setup: MariaDB

1. **Create the historian** if you don't have it yet. This creates the `historian`
   database, the rollup procedure and event, and the `nodered` / `grafana` users (change
   their passwords in the file first):
   ```bash
   docker exec -i mariadb mariadb -uroot -p"$ROOT_PW" < db/source/muthur_historian_mariadb.sql
   ```
   Turn on the event scheduler so the hourly rollup stays current: add
   `command: --event-scheduler=ON` to your MariaDB container, or `event_scheduler=ON` under
   `[mysqld]` in `my.cnf`. Node-RED inserts into `historian.readings` with UTC timestamps,
   exactly like the TimescaleDB edition.

2. **Install the uns layer** (views in a separate `uns` database; `historian` is untouched):
   ```bash
   ENGINE=mariadb MARIADB="docker exec -i mariadb mariadb -uroot -p$ROOT_PW" tools/install_uns.sh
   ```

3. **Configure** `.env`: set `UNS_MARIADB_PASSWORD`, and `UNS_MARIADB_HOST` using the same
   options as for TimescaleDB above. To make MariaDB the landing page, set
   `GRAFANA_HOME_DASHBOARD=/var/lib/grafana/dashboards/uns/mariadb/uns-overview-mariadb.json`.

4. `docker compose up -d`.

All images are multi-arch (arm64), and Grafana uses about 100–150 MB of RAM.

## Continuous deployment with a self-hosted runner

- **`ci.yml`** runs on GitHub-hosted runners for every PR and push. It checks that the
  dashboard JSON matches the generator and lints the shell scripts. Then it boots the full
  demo stack (both engines) and runs **every panel query** against it as the read-only
  `grafana` user, over a 6 h raw range and a 14-day rollup range. Last, it checks that
  Grafana provisioned both data sources and all dashboards.
- **`deploy.yml`** runs on the Pi's runner (labels `self-hosted, linux, ARM64`) after CI
  passes on `main`, or manually. It rsyncs the repo to `DEPLOY_DIR` (default
  `~/uns-dashboard`) and runs `docker compose up -d --wait`. The manual run has options to
  re-install the uns layer (TimescaleDB, MariaDB or both) and to start the demo profile.

Runner setup on the Pi:

1. Repo → Settings → Actions → Runners → *New self-hosted runner* → Linux / ARM64, and
   follow the commands. Then install it as a service: `sudo ./svc.sh install && sudo ./svc.sh start`.
2. Let the runner user use Docker (`sudo usermod -aG docker <runner-user>`) and install
   `rsync` (`sudo apt install rsync`).
3. Create `~/uns-dashboard/.env` once (step 3 above). Deploys never overwrite it.
4. Optional repository **variables**: `DEPLOY_DIR`, `TIMESCALE_CONTAINER` (default
   `timescaledb`), `PG_ADMIN_USER` (default `postgres`), `MARIADB_CONTAINER` (default
   `mariadb`), `UNS_ADAPTER`. For the MariaDB install option, add the repository **secret**
   `MARIADB_ROOT_PASSWORD`.

> Security: a self-hosted runner executes workflow code on your Pi. Only `deploy.yml`
> targets it, and only for `main` or manual runs. If the repo is public, also set
> *Settings → Actions → Fork pull request workflows* to require approval.

## Supporting another schema

1. Copy `db/uns/<engine>/adapters/_template.sql` to `db/uns/<engine>/adapters/<name>.sql`
   and map your tables onto the three contract views. The PostgreSQL template documents
   every column. A source without a rollup can return an empty `uns.readings_1h`.
2. `ENGINE=<postgres|mariadb> ADAPTER=<name> tools/install_uns.sh` against that database.
3. To show several databases side by side, add a data source per database in
   `grafana/provisioning/datasources/uns.yaml` and switch with the **Data source** picker.

A new database engine needs a `db/uns/<engine>/` directory and a dialect class in
`tools/build_dashboards.py` (see `Postgres` and `MariaDB`).

The hierarchy levels are never NULL in the contract (`'(none)'` instead), so multi-select
filters keep matching devices that skip a level (e.g. no line). Those levels are also
skipped in the node graph and in `uns_path`.

## Editing dashboards

The JSON in `grafana/dashboards/` is generated from `tools/build_dashboards.py`, and
provisioned dashboards can't be saved from the UI. Change the Python file, then run:

```bash
python3 tools/build_dashboards.py                     # regenerate JSON for both engines
PGHOST=localhost PGPORT=55432 PGUSER=grafana PGPASSWORD=... PGDATABASE=home_data \
  python3 tools/check_queries.py --engine timescaledb --require-rows
MARIADB="docker exec -i uns-demo-mariadb mariadb -u grafana -p..." \
  python3 tools/check_queries.py --engine mariadb --require-rows
```

Grafana reloads the files within 30 s. To try something in the UI first, use *Save as*
to make a copy outside the UNS folders. One MariaDB-specific pitfall: Grafana's MySQL data
source treats `#` as a comment even inside string literals, which cuts the query off.
`check_queries.py` rejects it.

## Layout

```
db/source/muthur_historian_*.sql    historian schema, TimescaleDB + MariaDB editions
db/uns/<engine>/adapters/*.sql      source schema → uns contract
db/uns/<engine>/core.sql            schema-independent helpers used by the dashboards
db/demo/                            demo data + init hooks for the demo databases
grafana/provisioning/               data sources + dashboard providers (one folder per engine)
grafana/dashboards/<engine>/*.json  generated dashboards
tools/install_uns.sh                install/refresh the uns layer
tools/build_dashboards.py           dashboard generator
tools/check_queries.py              runs every panel query against a database
```

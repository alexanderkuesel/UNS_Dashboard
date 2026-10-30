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

## Raspberry Pi from scratch: MariaDB + Grafana

Starting from nothing but a clone of this repo. The repo's `docker-compose.yml` runs both
Grafana and a MariaDB historian, and MariaDB sets itself up on first start: database,
users, rollup event and dashboard views.

1. **Check the Pi runs a 64-bit OS.** `uname -m` must print `aarch64`. The database images
   have no 32-bit builds; if you see `armv7l`, reflash with *Raspberry Pi OS (64-bit)*.

2. **Install Docker** (includes `docker compose`), then log out and back in:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```

3. **Create your settings file** in the repo folder:
   ```bash
   cd UNS_Dashboard
   cp .env.example .env
   nano .env
   ```
   Change these four passwords (letters and digits only, e.g. from `openssl rand -hex 16`):
   `GRAFANA_ADMIN_PASSWORD`, `MARIADB_ROOT_PASSWORD`, `NODERED_MARIADB_PASSWORD`,
   `UNS_MARIADB_PASSWORD`. To land on the MariaDB dashboards, set
   `GRAFANA_HOME_DASHBOARD=/var/lib/grafana/dashboards/uns/mariadb/uns-overview-mariadb.json`.
   Leave everything else as it is.

4. **Start it:**
   ```bash
   docker compose up -d --wait
   ```
   The first start takes a minute or two while the images download. `docker compose ps`
   should show `uns-mariadb` and `uns-grafana` as *healthy*.

5. **Open Grafana** at `http://<pi-address>:3000` and log in as `admin` with your password.
   The dashboards are in the **UNS · MariaDB** folder. They stay empty until data arrives.
   The *UNS · TimescaleDB* folder only works if you also run TimescaleDB, so ignore it.

6. **Send data from Node-RED.** Use a MySQL node (e.g. `node-red-node-mysql`) with host
   `<pi-address>`, port `3306`, user `nodered`, your `NODERED_MARIADB_PASSWORD`, and
   database `historian`. Each signal is registered once as a *point* (topic + field + where
   it sits in the hierarchy), then values reference it:
   ```sql
   -- register the point (or refresh last_seen if it already exists)
   INSERT INTO points (source_topic, field, enterprise, site, area, line, device, measurement, unit, last_seen)
   VALUES ('home/kitchen/sensor1', 'temperature', 'home', 'house', 'kitchen', NULL, 'sensor1', 'climate', '°C',
           UTC_TIMESTAMP(3))
   ON DUPLICATE KEY UPDATE last_seen = UTC_TIMESTAMP(3);

   -- store a value (always UTC time)
   INSERT IGNORE INTO readings (time, point_id, value, quality)
   SELECT UTC_TIMESTAMP(3), point_id, 21.5, 192
   FROM points WHERE source_topic = 'home/kitchen/sensor1' AND field = 'temperature' AND enabled;
   ```
   The hierarchy columns are yours to edit later; the dashboards follow them.

Day-to-day:

| Task | Command |
|---|---|
| Update after `git pull` | `docker compose up -d --wait` |
| Refresh the dashboard views after an update | `docker compose exec mariadb sh -c 'ENGINE=mariadb MARIADB="mariadb -uroot -p$MARIADB_ROOT_PASSWORD" /uns/tools/install_uns.sh'` |
| SQL shell | `docker compose exec mariadb sh -c 'mariadb -uroot -p$MARIADB_ROOT_PASSWORD historian'` |
| Backup | `docker compose exec mariadb sh -c 'mariadb-dump -uroot -p$MARIADB_ROOT_PASSWORD --single-transaction --routines --events historian' \| gzip > historian.sql.gz` |
| Logs | `docker compose logs -f mariadb` |

Data lives in the Docker volume `<repo-folder>_mariadb-data` (e.g. `uns_dashboard_mariadb-data`). It survives restarts and
updates; only `docker compose down -v` deletes it. Passwords in `.env` are applied on the
**first** start only. After that, change them with `ALTER USER` in the SQL shell.

### Using a MariaDB you already run

Remove `COMPOSE_PROFILES=mariadb` from `.env` and point `UNS_MARIADB_HOST` at your server,
using the same options as for TimescaleDB above. Then load the schema and views once:

```bash
docker exec -i <container> mariadb -uroot -p<pw> < db/source/muthur_historian_mariadb.sql
ENGINE=mariadb MARIADB="docker exec -i <container> mariadb -uroot -p<pw>" tools/install_uns.sh
```

The server needs `event_scheduler=ON` (keeps the hourly rollup current), and Node-RED
must write UTC timestamps.

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
   `uns-mariadb`, the bundled one), `UNS_ADAPTER`. For the MariaDB install option on an
   external server, add the repository **secret** `MARIADB_ROOT_PASSWORD`; the bundled one
   reads it from `.env`.

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
db/init/                            first-start hook for the bundled MariaDB
db/demo/                            demo data + init hook for the demo TimescaleDB
grafana/provisioning/               data sources + dashboard providers (one folder per engine)
grafana/dashboards/<engine>/*.json  generated dashboards
tools/install_uns.sh                install/refresh the uns layer
tools/build_dashboards.py           dashboard generator
tools/check_queries.py              runs every panel query against a database
```

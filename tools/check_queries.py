#!/usr/bin/env python3
"""Run every SQL query in the Grafana dashboards against a live database.

Variables are resolved the way Grafana would (cascading, "All" selected),
Grafana's SQL macros are expanded per engine, and each panel query is
executed with the engine's command-line client. Connect as the read-only
dashboard user to also verify grants:

    PGHOST=localhost PGUSER=grafana PGPASSWORD=... PGDATABASE=home_data \
        python3 tools/check_queries.py --engine timescaledb [--require-rows]

    MARIADB="mariadb -h 127.0.0.1 -u grafana -p..." \
        python3 tools/check_queries.py --engine mariadb [--require-rows]

MARIADB may be any command that accepts mariadb client options, e.g.
"docker exec -i uns-demo-mariadb mariadb -u grafana -p...".

Exit status is 1 if any query fails (or returns no rows with --require-rows).
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"


def run(engine, sql):
    if engine == "timescaledb":
        cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t", "-c", sql]
    else:
        # Grafana's MySQL data source runs every session in UTC
        cmd = shlex.split(os.environ.get("MARIADB", "mariadb")) + [
            "-N", "-B", "-e", "SET time_zone = '+00:00';\n" + sql]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip())
    return [line.split("\t") for line in res.stdout.splitlines()]


def engine_of(dash):
    ds_type = next(v["query"] for v in dash["templating"]["list"] if v["type"] == "datasource")
    return "mariadb" if ds_type == "mysql" else "timescaledb"


def quote(v):
    return "'" + str(v).replace("'", "''") + "'"


class Context:
    def __init__(self, engine, hours, interval_s):
        self.engine = engine
        self.to = datetime.now(timezone.utc)
        self.frm = self.to - timedelta(hours=hours)
        self.interval_s = interval_s
        self.values = {}  # var name -> list of raw values
        self.quoted = {}  # var name -> does Grafana quote a plain $var

    def expand(self, sql):
        n = self.interval_s
        f_epoch, t_epoch = int(self.frm.timestamp()), int(self.to.timestamp())
        if self.engine == "timescaledb":
            frm, to = quote(self.frm.isoformat()), quote(self.to.isoformat())
            group = rf'to_timestamp(floor(extract(epoch FROM \1) / {n}) * {n}) AS "time"'
        else:
            frm, to = f"FROM_UNIXTIME({f_epoch})", f"FROM_UNIXTIME({t_epoch})"
            group = rf'UNIX_TIMESTAMP(\1) DIV {n} * {n} AS "time"'
        sql = re.sub(r"\$__timeFilter\(([^)]+)\)", rf"\1 BETWEEN {frm} AND {to}", sql)
        sql = re.sub(r"\$__timeGroupAlias\(([^,]+),[^)]*\)", group, sql)
        sql = sql.replace("$__timeFrom()", frm).replace("$__timeTo()", to)
        sql = sql.replace("$__unixEpochFrom()", str(f_epoch)).replace("$__unixEpochTo()", str(t_epoch))
        sql = sql.replace("$__interval_ms", str(self.interval_s * 1000))
        sql = sql.replace("$__interval", f"{self.interval_s}s")
        for name in sorted(self.values, key=len, reverse=True):
            sql = re.sub(r"\$\{" + name + r"(?::([a-z]+))?\}|\$" + name + r"\b",
                         lambda m, n=name: self.format(n, m.group(1)), sql)
        if self.engine == "mariadb" and "#" in sql:
            # Grafana's MySQL data source drops everything after '#' as a
            # comment, even inside string literals, which truncates the query.
            raise RuntimeError(f"'#' is cut off by Grafana's MySQL data source: {sql}")
        if re.search(r"\$\w|\$\{", re.sub(r"\$\$", "", sql)):
            raise RuntimeError(f"unexpanded variable in: {sql}")
        return sql

    def format(self, name, fmt):
        # Grafana's SQL data sources quote multi-value/"All" variables by
        # default but interpolate single-value ones raw; :sqlstring always quotes.
        vals = self.values[name]
        if fmt == "sqlstring" or (fmt is None and self.quoted[name]):
            return ",".join(quote(v) for v in vals) if vals else "''"
        if fmt in (None, "raw", "text"):
            return ",".join(str(v) for v in vals)
        raise RuntimeError(f"unsupported variable format {name}:{fmt}")

    def resolve(self, var):
        kind, name = var["type"], var["name"]
        self.quoted[name] = bool(var.get("multi") or var.get("includeAll"))
        if kind == "datasource":
            return
        if kind in ("custom", "textbox", "constant"):
            self.values[name] = [var.get("current", {}).get("value", "")]
            return
        rows = run(self.engine, self.expand(var["query"]))
        # Grafana uses __value when present, otherwise the first column
        vals = [r[-1] if "__value" in var["query"] else r[0] for r in rows]
        if not var.get("includeAll"):
            vals = vals[:2] if var.get("multi") else vals[:1]
        self.values[name] = vals


def check_dashboard(path, engine, ctx_args, require_rows):
    dash = json.loads(path.read_text(encoding="utf-8"))
    ctx = Context(engine, **ctx_args)
    failures = 0
    print(f"\n== {dash['title']} ({path.name})")
    for var in dash["templating"]["list"]:
        try:
            ctx.resolve(var)
            if var["type"] == "query":
                print(f"   var {var['name']:<12} {len(ctx.values[var['name']])} value(s)")
        except RuntimeError as e:
            print(f"   FAIL var {var['name']}: {e}")
            failures += 1

    def panels(items):
        for p in items:
            yield p
            yield from panels(p.get("panels", []))

    for p in panels(dash["panels"]):
        for t in p.get("targets", []):
            label = f"{p['title']} [{t['refId']}]"
            try:
                rows = run(engine, ctx.expand(t["rawSql"]))
            except RuntimeError as e:
                print(f"   FAIL {label}: {e}")
                failures += 1
                continue
            ok = rows or not require_rows
            print(f"   {'ok  ' if ok else 'FAIL'} {label}: {len(rows)} row(s)")
            failures += not ok
    return failures


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", choices=["timescaledb", "mariadb"], default="timescaledb",
                    help="which database the client connects to; only that engine's dashboards are checked")
    ap.add_argument("--require-rows", action="store_true", help="treat empty results as failures")
    args = ap.parse_args()

    paths = [p for p in sorted(DASH_DIR.rglob("*.json"))
             if engine_of(json.loads(p.read_text(encoding="utf-8"))) == args.engine]
    if not paths:
        print(f"no {args.engine} dashboards found", file=sys.stderr)
        return 1

    failures = 0
    # A short range exercises raw readings, a long one the hourly rollup path.
    for hours, interval_s in ((6, 60), (24 * 14, 3600)):
        print(f"\n### time range {hours}h, interval {interval_s}s")
        for path in paths:
            failures += check_dashboard(path, args.engine, {"hours": hours, "interval_s": interval_s},
                                        args.require_rows)
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

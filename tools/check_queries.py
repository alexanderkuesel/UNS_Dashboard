#!/usr/bin/env python3
"""Run every SQL query in the Grafana dashboards against a live database.

Variables are resolved the way Grafana would (cascading, "All" selected),
Grafana's SQL macros are expanded, and each panel query is executed with
psql. Connect as the read-only dashboard role to also verify grants:

    PGHOST=localhost PGUSER=grafana PGPASSWORD=... PGDATABASE=home_data \
        python3 tools/check_queries.py [--require-rows]

Exit status is 1 if any query fails (or returns no rows with --require-rows).
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DASH_DIR = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"


def psql(sql):
    res = subprocess.run(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t", "-c", sql],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip())
    return [line.split("\t") for line in res.stdout.splitlines()]


def quote(v):
    return "'" + str(v).replace("'", "''") + "'"


class Context:
    def __init__(self, hours, interval_s):
        self.to = datetime.now(timezone.utc)
        self.frm = self.to - timedelta(hours=hours)
        self.interval_s = interval_s
        self.values = {}  # var name -> list of raw values
        self.quoted = {}  # var name -> does Grafana quote a plain $var

    def expand(self, sql):
        frm, to = quote(self.frm.isoformat()), quote(self.to.isoformat())
        sql = re.sub(r"\$__timeFilter\(([^)]+)\)", rf"\1 BETWEEN {frm} AND {to}", sql)
        sql = re.sub(r"\$__timeGroupAlias\(([^,]+),[^)]*\)",
                     rf"""to_timestamp(floor(extract(epoch FROM \1) / {self.interval_s}) * {self.interval_s}) AS "time\"""",
                     sql)
        sql = sql.replace("$__timeFrom()", frm).replace("$__timeTo()", to)
        sql = sql.replace("$__interval_ms", str(self.interval_s * 1000))
        sql = sql.replace("$__interval", f"{self.interval_s}s")
        for name in sorted(self.values, key=len, reverse=True):
            sql = re.sub(r"\$\{" + name + r"(?::([a-z]+))?\}|\$" + name + r"\b",
                         lambda m, n=name: self.format(n, m.group(1)), sql)
        if "$" in re.sub(r"\$\$|\$\d", "", sql):
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
        rows = psql(self.expand(var["query"]))
        # Grafana uses __value when present, otherwise the first column
        vals = [r[-1] if "__value" in var["query"] else r[0] for r in rows]
        if not var.get("includeAll"):
            vals = vals[:2] if var.get("multi") else vals[:1]
        self.values[name] = vals


def check_dashboard(path, ctx_args, require_rows):
    dash = json.loads(path.read_text(encoding="utf-8"))
    ctx = Context(**ctx_args)
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
                rows = psql(ctx.expand(t["rawSql"]))
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
    ap.add_argument("--require-rows", action="store_true", help="treat empty results as failures")
    args = ap.parse_args()

    failures = 0
    # A short range exercises raw readings, a long one the hourly rollup path.
    for hours, interval_s in ((6, 60), (24 * 14, 3600)):
        print(f"\n### time range {hours}h, interval {interval_s}s")
        for path in sorted(DASH_DIR.glob("*.json")):
            failures += check_dashboard(path, {"hours": hours, "interval_s": interval_s}, args.require_rows)
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

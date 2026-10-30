#!/usr/bin/env python3
"""Generate the Grafana dashboard JSON in grafana/dashboards/<engine>/.

The dashboards only query the `uns` contract schema (see db/uns), never a
source schema directly, so the same JSON works for every adapter. Each
supported database engine gets its own copy of every dashboard: the panel
layout is shared, only the SQL dialect differs (see Postgres / MariaDB).

    python3 tools/build_dashboards.py          # write the JSON files
    python3 tools/build_dashboards.py --check  # fail if the files are stale (CI)
"""

import argparse
import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
HIERARCHY = ["enterprise", "site", "area", "line", "device"]
STALE = "${stale}"  # seconds; a single-value custom var, interpolated as a bare number


# ---------------------------------------------------------------------------
# SQL dialects
# ---------------------------------------------------------------------------

def where(levels, alias="p"):
    """Filter on the selected hierarchy variables, e.g. p.site IN ($site)."""
    return " AND ".join(f"{alias}.{lvl} IN (${lvl})" for lvl in levels) or "TRUE"


def and_(*conds):
    return " AND ".join(c for c in conds if c)


def ids(cond):
    return f"SELECT p.point_id FROM uns.points p WHERE {cond}"


class Postgres:
    """TimescaleDB / PostgreSQL: helpers live in db/uns/postgres/core.sql."""

    engine = "timescaledb"
    ds_type = "grafana-postgresql-datasource"
    ds_name, ds_uid = "UNS Historian", "uns-historian"
    uid_suffix, title_suffix = "", ""

    @staticmethod
    def q(name):
        return f'"{name}"'

    @staticmethod
    def cat(*parts):
        return " || ".join(parts)

    @staticmethod
    def count_if(cond):
        return f"count(*) FILTER (WHERE {cond})"

    @staticmethod
    def count_distinct(*cols):
        return f"count(DISTINCT ({', '.join(cols)}))" if len(cols) > 1 else f"count(DISTINCT {cols[0]})"

    @staticmethod
    def num(expr):
        return expr

    @staticmethod
    def round_(expr, digits):
        return f"round(({expr})::numeric, {digits})"

    @staticmethod
    def age_s(col):
        return f"extract(epoch FROM now() - {col})"

    @staticmethod
    def as_text(expr, digits):
        return f"round(({expr})::numeric, {digits})::text"

    @staticmethod
    def contains(col, needle):
        return f"{col} ILIKE '%' || {needle} || '%'"

    @staticmethod
    def health():
        """Per-point status incl. `state` (ok | stale | never | disabled) and `age_s`."""
        return f"uns.point_health({STALE} * interval '1 second')"

    @staticmethod
    def trend(cond):
        """Bucketed (time, point_id, avg, min, max, samples) for the points matching cond."""
        return (f"uns.trend(ARRAY({ids(cond)}), $__timeFrom(), $__timeTo(), "
                "$__interval_ms * interval '1 millisecond')")

    @staticmethod
    def nodes(cond):
        return f"""
            SELECT h.path AS id, h.name AS title,
                   h.level || ' · ' || h.points || ' points' AS subtitle,
                   h.points || ' pts' AS mainstat,
                   h.level AS "detail__Level",
                   to_char(h.last_seen, 'YYYY-MM-DD HH24:MI:SS') AS "detail__Last seen",
                   CASE WHEN h.last_seen > now() - {STALE} * interval '1 second'
                        THEN 'rgb(115, 191, 105)' ELSE 'rgb(242, 73, 92)' END AS color
            FROM uns.hierarchy h
            WHERE h.point_ids && ARRAY({ids(cond)})"""

    @staticmethod
    def edges(cond):
        return f"""
            SELECT h.parent_path || '->' || h.path AS id, h.parent_path AS source, h.path AS target
            FROM uns.hierarchy h
            WHERE h.parent_path IS NOT NULL AND h.point_ids && ARRAY({ids(cond)})"""

    @staticmethod
    def attributes(cond):
        return f"""
            SELECT DISTINCT p.device, a.key, a.value
            FROM uns.points p, jsonb_each_text(p.attributes) a
            WHERE {cond}
            ORDER BY 1, 2"""


class MariaDB:
    """MariaDB / MySQL: no table functions, arrays or LATERAL, so bucketing
    and rollup selection are inlined here (db/uns/mariadb/core.sql has the views).
    Times are UTC DATETIMEs; Grafana's MySQL data source runs sessions in UTC."""

    engine = "mariadb"
    ds_type = "mysql"
    ds_name, ds_uid = "UNS Historian (MariaDB)", "uns-historian-mariadb"
    uid_suffix, title_suffix = "-mariadb", " (MariaDB)"

    # Same rule as uns.trend() on PostgreSQL: hourly rollup for buckets >= 1h
    # or ranges >= 7 days, raw readings otherwise. Constant conditions, so
    # the optimizer drops the unused UNION branch.
    ROLLUP = "($__interval_ms >= 3600000 OR $__unixEpochTo() - $__unixEpochFrom() >= 604800)"
    RAW_BUCKET = "GREATEST(FLOOR($__interval_ms / 1000), 1)"
    HOUR_BUCKET = "GREATEST(FLOOR($__interval_ms / 1000), 3600)"

    @staticmethod
    def q(name):
        return f"`{name}`"

    @staticmethod
    def cat(*parts):
        return f"CONCAT({', '.join(parts)})"

    @staticmethod
    def count_if(cond):
        return f"COUNT(CASE WHEN {cond} THEN 1 END)"

    @staticmethod
    def count_distinct(*cols):
        return f"COUNT(DISTINCT {', '.join(cols)})"

    @staticmethod
    def num(expr):
        # SUM/ROUND return DECIMAL; keep Grafana values numeric
        return f"CAST({expr} AS DOUBLE)"

    @staticmethod
    def round_(expr, digits):
        return f"ROUND({expr}, {digits})"

    @staticmethod
    def age_s(col):
        return f"TIMESTAMPDIFF(SECOND, {col}, UTC_TIMESTAMP())"

    @staticmethod
    def as_text(expr, digits):
        return f"CAST(ROUND({expr}, {digits}) AS CHAR)"

    @staticmethod
    def contains(col, needle):
        return f"{col} LIKE CONCAT('%', {needle}, '%')"

    @staticmethod
    def health():
        return f"""(SELECT s.*,
                           CASE WHEN NOT s.enabled THEN 'disabled'
                                WHEN s.last_seen IS NULL THEN 'never'
                                WHEN s.age_s > {STALE} THEN 'stale'
                                ELSE 'ok' END AS state
                    FROM uns.point_status s)"""

    @classmethod
    def trend(cls, cond):
        rb, hb = cls.RAW_BUCKET, cls.HOUR_BUCKET
        return f"""(
            SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(r.time) / {rb}) * {rb}) AS time, r.point_id,
                   AVG(r.value) AS avg, MIN(r.value) AS min, MAX(r.value) AS max, COUNT(*) AS samples
            FROM uns.readings r
            WHERE NOT {cls.ROLLUP} AND r.point_id IN ({ids(cond)}) AND $__timeFilter(r.time)
            GROUP BY 1, 2
            UNION ALL
            SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(h.time) / {hb}) * {hb}), h.point_id,
                   SUM(h.avg * h.samples) / NULLIF(SUM(h.samples), 0), MIN(h.min), MAX(h.max),
                   CAST(SUM(h.samples) AS INTEGER)
            FROM uns.readings_1h h
            WHERE {cls.ROLLUP} AND h.point_id IN ({ids(cond)})
              AND h.time >= FROM_UNIXTIME(FLOOR($__unixEpochFrom() / 3600) * 3600)
              AND h.time < $__timeTo()
            GROUP BY 1, 2)"""

    @staticmethod
    def nodes(cond):
        return f"""
            SELECT h.path AS id, MAX(h.name) AS title,
                   CONCAT(MAX(h.level), ' · ', COUNT(*), ' points') AS subtitle,
                   CONCAT(COUNT(*), ' pts') AS mainstat,
                   MAX(h.level) AS `detail__Level`,
                   DATE_FORMAT(MAX(h.last_seen), '%Y-%m-%d %H:%i:%s') AS `detail__Last seen`,
                   CASE WHEN MAX(h.last_seen) > UTC_TIMESTAMP() - INTERVAL {STALE} SECOND
                        THEN 'rgb(115, 191, 105)' ELSE 'rgb(242, 73, 92)' END AS color
            FROM uns.hierarchy_points h
            WHERE h.point_id IN ({ids(cond)})
            GROUP BY h.path"""

    @staticmethod
    def edges(cond):
        return f"""
            SELECT DISTINCT CONCAT(h.parent_path, '->', h.path) AS id,
                   h.parent_path AS source, h.path AS target
            FROM uns.hierarchy_points h
            WHERE h.parent_path IS NOT NULL AND h.point_id IN ({ids(cond)})"""

    @staticmethod
    def attributes(cond):
        return f"""
            SELECT DISTINCT p.device, k.k AS `key`,
                   JSON_UNQUOTE(JSON_EXTRACT(p.attributes, CONCAT('$."', k.k, '"'))) AS value
            FROM uns.points p,
                 JSON_TABLE(JSON_KEYS(p.attributes), '$[*]' COLUMNS (k VARCHAR(255) PATH '$')) k
            WHERE {cond}
            ORDER BY 1, 2"""


DIALECTS = [Postgres, MariaDB]


# ---------------------------------------------------------------------------
# Dashboard building blocks (bound to one dialect)
# ---------------------------------------------------------------------------

def fixed(color):
    return {"mode": "fixed", "fixedColor": color}


def override(name, *props, regex=False):
    return {"matcher": {"id": "byRegexp" if regex else "byName", "options": name},
            "properties": [{"id": k, "value": v} for k, v in props]}


def thresholds(*steps):
    """steps: (value, color) pairs; the first value is ignored (base)."""
    return {"mode": "absolute",
            "steps": [{"value": None if i == 0 else v, "color": c} for i, (v, c) in enumerate(steps)]}


def link(title, url):
    return {"title": title, "url": url}


def stat_opts(text_mode="value_and_name", graph="none", color_mode="background"):
    return {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": graph, "textMode": text_mode,
            "justifyMode": "center", "orientation": "auto", "wideLayout": True}


def row(title, y, collapsed=False, panels=None):
    return {"type": "row", "title": title, "collapsed": collapsed,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": panels or []}


STATE_MAPPINGS = [{"type": "value", "options": {
    "ok": {"color": "green", "index": 0},
    "stale": {"color": "orange", "index": 1},
    "never": {"color": "red", "index": 2},
    "disabled": {"color": "text", "index": 3},
    "good": {"color": "green", "index": 4},
    "uncertain": {"color": "orange", "index": 5},
    "bad": {"color": "red", "index": 6},
}}]

TS_DEFAULTS = {
    "custom": {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 8, "showPoints": "never",
               "spanNulls": False, "gradientMode": "opacity"},
    "color": {"mode": "palette-classic"},
}

TS_LEGEND = {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
             "tooltip": {"mode": "multi", "sort": "desc"}}

AGE_FIELD_PROPS = (("unit", "s"), ("decimals", 0), ("displayName", "last seen (s ago)"),
                   ("custom.cellOptions", {"type": "color-text"}), ("color", {"mode": "thresholds"}),
                   ("thresholds", thresholds((0, "green"), (900, "orange"), (86400, "red"))))

TABLE_OPTS = {"showHeader": True, "cellHeight": "sm"}


class Builder:
    def __init__(self, d):
        self.d = d
        self.ds = {"type": d.ds_type, "uid": "${ds}"}
        self.tag = f"uns-{d.engine}"

    def uid(self, base):
        return base + self.d.uid_suffix

    def url(self, base, slug):
        return f"/d/{self.uid(base)}/{slug}?${{ds:queryparam}}&${{__url_time_range}}"

    # -- variables ----------------------------------------------------------

    def ds_var(self):
        return {"name": "ds", "label": "Data source", "type": "datasource",
                "query": self.d.ds_type, "current": {"text": self.d.ds_name, "value": self.d.ds_uid},
                "hide": 0, "refresh": 1, "regex": "", "options": []}

    def query_var(self, name, sql, label=None, multi=True, include_all=True, hide=0):
        return {"name": name, "label": label or name.capitalize(), "type": "query",
                "datasource": self.ds, "query": sql, "definition": sql,
                "refresh": 2,  # on time range change: picks up newly registered points
                "multi": multi, "includeAll": include_all,
                "current": {"text": ["All"], "value": ["$__all"]} if include_all else {},
                "options": [], "sort": 1, "hide": hide, "regex": ""}

    def hierarchy_vars(self, levels):
        return [self.query_var(lvl, f"SELECT DISTINCT p.{lvl} FROM uns.points p "
                                    f"WHERE {where(levels[:i])} ORDER BY 1")
                for i, lvl in enumerate(levels)]

    @staticmethod
    def stale_var():
        opts = ["5m : 300", "15m : 900", "1h : 3600", "6h : 21600", "1d : 86400"]
        return {"name": "stale", "label": "Stale after", "type": "custom", "query": ",".join(opts),
                "current": {"text": "15m", "value": "900"},
                "multi": False, "includeAll": False, "hide": 0, "options": []}

    # -- panels -------------------------------------------------------------

    def target(self, sql, fmt="table", ref="A"):
        return {"refId": ref, "datasource": self.ds, "editorMode": "code", "format": fmt,
                "rawQuery": True, "rawSql": " ".join(sql.split())}

    def panel(self, ptype, title, x, y, w, h, targets, *, desc="", defaults=None, overrides=None,
              options=None, transformations=None, **extra):
        p = {"type": ptype, "title": title, "description": desc, "datasource": self.ds,
             "gridPos": {"x": x, "y": y, "w": w, "h": h},
             "targets": targets if isinstance(targets, list) else [targets],
             "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
             "options": options or {}}
        if transformations:
            p["transformations"] = transformations
        p.update(extra)
        return p

    def dashboard(self, uid, title, desc, variables, panels, time_from="now-24h", refresh="1m"):
        for i, p in enumerate(_walk(panels), start=1):
            p["id"] = i
        return {
            "uid": self.uid(uid), "title": title + self.d.title_suffix, "description": desc,
            "tags": ["uns", "isa-95", self.d.engine, self.tag],
            "editable": True, "graphTooltip": 1, "schemaVersion": 41, "version": 1,
            "timezone": "browser", "refresh": refresh,
            "time": {"from": time_from, "to": "now"},
            "timepicker": {}, "fiscalYearStartMonth": 0, "liveNow": False,
            "templating": {"list": variables},
            "annotations": {"list": [{
                "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                "name": "Annotations & Alerts", "type": "dashboard"}]},
            "links": [{"title": "UNS", "type": "dashboards", "tags": [self.tag], "asDropdown": False,
                       "includeVars": False, "keepTime": True, "targetBlank": False,
                       "icon": "external link", "tooltip": "", "url": ""}],
            "panels": panels,
        }

    # -- shared SQL ---------------------------------------------------------

    def series_name(self):
        d = self.d
        unit = d.cat("' ['", "p.unit", "']'")  # NULL when unit is NULL
        return d.cat("p.device", "' · '", "p.field", f"COALESCE({unit}, '')")

    def trend_link(self):
        return [link("Trend ${__data.fields.uns_path}",
                     self.url("uns-trend", "uns-point-trend") + "&var-point=${__data.fields.point_id}")]

    # -----------------------------------------------------------------------
    # 1. Enterprise overview
    # -----------------------------------------------------------------------

    def overview(self):
        d, q = self.d, self.d.q
        lv = ["enterprise", "site"]
        f = where(lv)
        ok, enabled = d.count_if("p.state = 'ok'"), d.count_if("p.state <> 'disabled'")
        reporting = f"100.0 * {ok} / NULLIF({enabled}, 0)"
        equipment_url = (self.url("uns-equipment", "uns-equipment")
                         + "&var-enterprise=${__data.fields.enterprise}&var-site=${__data.fields.site}"
                         + "&var-area=${__data.fields.area}")
        panels = [
            self.panel("stat", "Model", 0, 0, 12, 4, self.target(f"""
                SELECT {d.count_distinct("p.site")} AS {q("Sites")},
                       {d.count_distinct("p.site", "p.area")} AS {q("Areas")},
                       {d.count_distinct("p.site", "p.area", "p.line", "p.device")} AS {q("Devices")},
                       {d.count_if("p.enabled")} AS {q("Points")}
                FROM uns.points p WHERE {f}"""),
                desc="Size of the selected part of the ISA-95 equipment model.",
                defaults={"color": fixed("blue")}, options=stat_opts()),
            self.panel("stat", "Communication", 12, 0, 12, 4, self.target(f"""
                SELECT {d.num(d.round_(reporting, 1))} AS {q("Reporting")},
                       {d.count_if("p.state = 'stale'")} AS {q("Stale")},
                       {d.count_if("p.state = 'never'")} AS {q("Never seen")},
                       (SELECT {d.num(d.round_(f"100.0 * {d.count_if('r.quality & 192 <> 192')} / NULLIF(COUNT(*), 0)", 2))}
                        FROM uns.readings r
                        WHERE r.point_id IN ({ids(f)}) AND $__timeFilter(r.time)) AS {q("Bad quality")}
                FROM {d.health()} p WHERE {f}"""),
                desc="Share of enabled points that reported within the stale window, and the share of "
                     "non-good OPC quality samples in the time range.",
                defaults={"color": {"mode": "thresholds"}, "thresholds": thresholds((0, "green"), (1, "orange"))},
                overrides=[override("Reporting", ("unit", "percent"),
                                    ("thresholds", thresholds((0, "red"), (80, "orange"), (99, "green")))),
                           override("Bad quality", ("unit", "percent"), ("decimals", 2),
                                    ("thresholds", thresholds((0, "green"), (0.5, "orange"), (5, "red"))))],
                options=stat_opts()),
            self.panel("nodeGraph", "Equipment hierarchy", 0, 4, 14, 14, [
                self.target(d.nodes(f), ref="nodes"),
                self.target(d.edges(f), ref="edges"),
            ], desc="Enterprise > site > area > line > device. Node is green when the node's newest sample "
                    "is younger than the stale window.",
                options={"nodes": {}, "edges": {}, "layoutAlgorithm": "layered", "zoomMode": "cooperative"}),
            self.panel("table", "Areas", 14, 4, 10, 14, self.target(f"""
                SELECT p.enterprise, p.site, p.area,
                       COUNT(DISTINCT p.device) AS devices,
                       {d.count_if("p.state = 'ok'")} AS ok,
                       {d.count_if("p.state IN ('stale', 'never')")} AS problems,
                       MIN(p.age_s) AS last_seen
                FROM {d.health()} p WHERE {f}
                GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"""),
                desc="Click an area to open it in the Equipment dashboard.",
                overrides=[
                    override("area", ("links", [link("Open ${__data.fields.area}", equipment_url)])),
                    override("problems", ("custom.cellOptions", {"type": "color-background", "mode": "basic"}),
                             ("thresholds", thresholds((0, "transparent"), (1, "red"))),
                             ("color", {"mode": "thresholds"}), ("custom.width", 85)),
                    override("last_seen", *AGE_FIELD_PROPS),
                    override("enterprise", ("custom.hidden", True)),
                    override("site", ("custom.width", 100)),
                    override("devices", ("custom.width", 75)),
                    override("ok", ("custom.width", 55)),
                ],
                options=TABLE_OPTS),
            self.panel("timeseries", "Samples by site", 0, 18, 12, 8, self.target(f"""
                SELECT t.time, p.site AS metric, {d.num("SUM(t.samples)")} AS value
                FROM {d.trend(f)} t JOIN uns.points p USING (point_id)
                GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
                desc="Stored samples per time bucket: a drop means a site stopped publishing.",
                defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "drawStyle": "bars",
                                                    "fillOpacity": 60, "stacking": {"mode": "normal"}}},
                options=TS_LEGEND),
            self.panel("timeseries", "Reporting points by site", 12, 18, 12, 8, self.target(f"""
                SELECT t.time, p.site AS metric, COUNT(DISTINCT t.point_id) AS value
                FROM {d.trend(f)} t JOIN uns.points p USING (point_id)
                GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
                desc="Distinct points with at least one sample per bucket.",
                defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "lineInterpolation": "stepAfter"},
                          "decimals": 0},
                options=TS_LEGEND),
        ]
        return self.dashboard("uns-overview", "UNS · Enterprise overview",
                              "Top of the ISA-95 model: sites, areas and their communication health.",
                              [self.ds_var(), *self.hierarchy_vars(lv), self.stale_var()], panels)

    # -----------------------------------------------------------------------
    # 2. Equipment (area / line / device)
    # -----------------------------------------------------------------------

    def equipment(self):
        d = self.d
        lv = HIERARCHY + ["measurement"]
        f = where(lv)
        meas_float = self.query_var(
            "fmeas", f"SELECT DISTINCT p.measurement FROM uns.points p WHERE {f} AND p.data_type <> 'bool' "
                     "AND p.last_seen IS NOT NULL ORDER BY 1",
            label="Float measurements", hide=2)
        panels = [
            self.panel("stat", "Live values", 0, 0, 24, 6, self.target(f"""
                SELECT {self.series_name()} AS name, p.value
                FROM uns.latest p
                WHERE {f} AND p.data_type <> 'bool' AND p.enabled
                ORDER BY p.uns_path"""),
                desc="Latest stored value per analog point.",
                defaults={"color": fixed("blue"), "decimals": 1, "displayName": "${__data.fields.name}"},
                options={**stat_opts(color_mode="value"),
                         "reduceOptions": {"calcs": [], "fields": "", "values": True}}),
            row("Trends by measurement", 6),
            self.panel("timeseries", "$fmeas", 0, 7, 12, 9, self.target(f"""
                SELECT t.time, {self.series_name()} AS metric, t.avg AS value
                FROM {d.trend(and_(f, "p.measurement IN (${fmeas:sqlstring})", "p.data_type <> 'bool'"))} t
                JOIN uns.points p USING (point_id)
                ORDER BY 1""", fmt="time_series"),
                desc="Bucketed average. Long ranges read the hourly rollup automatically.",
                defaults=TS_DEFAULTS, options=TS_LEGEND,
                repeat="fmeas", repeatDirection="h", maxPerRow=2),
            row("States", 16),
            self.panel("state-timeline", "Discrete states", 0, 17, 24, 8, self.target(f"""
                SELECT t.time, {d.cat("p.device", "' · '", "p.field")} AS metric, t.max AS value
                FROM {d.trend(and_(f, "p.data_type = 'bool'"))} t
                JOIN uns.points p USING (point_id)
                ORDER BY 1""", fmt="time_series"),
                desc="Boolean points (data_type = bool). A bucket shows ON if the signal was on at any time in it.",
                defaults={"color": {"mode": "thresholds"},
                          "custom": {"fillOpacity": 80, "lineWidth": 0},
                          "thresholds": thresholds((0, "text"), (0.5, "green")),
                          "mappings": [{"type": "value", "options": {
                              "0": {"text": "OFF", "color": "#3d3d48", "index": 0},
                              "1": {"text": "ON", "color": "green", "index": 1}}}]},
                options={"mergeValues": True, "showValue": "never", "alignValue": "left",
                         "rowHeight": 0.85, "legend": {"showLegend": False}}),
            row("Points", 25),
            self.panel("table", "Point list", 0, 26, 16, 10, self.target(f"""
                SELECT p.point_id, p.uns_path,
                       CASE WHEN p.data_type = 'bool' THEN CASE WHEN p.value > 0.5 THEN 'ON' ELSE 'OFF' END
                            ELSE {d.as_text("p.value", 2)} END AS value,
                       p.unit,
                       {d.age_s("p.value_time")} AS last_seen,
                       uns.quality_label(p.quality) AS quality,
                       p.enabled
                FROM uns.latest p WHERE {f}
                ORDER BY p.uns_path"""),
                desc="Click a UNS path to trend it.",
                overrides=[override("uns_path", ("links", self.trend_link()), ("custom.minWidth", 320)),
                           override("last_seen", *AGE_FIELD_PROPS, ("custom.width", 140)),
                           override("quality", ("custom.cellOptions", {"type": "color-text"}),
                                    ("mappings", STATE_MAPPINGS), ("custom.width", 90)),
                           override("point_id", ("custom.hidden", True)),
                           override("value", ("custom.align", "right"), ("custom.width", 90)),
                           override("unit", ("custom.width", 60)),
                           override("enabled", ("custom.width", 80))],
                options=TABLE_OPTS),
            self.panel("table", "Asset attributes", 16, 26, 8, 10, self.target(d.attributes(f)),
                desc="String attributes captured from device payloads (firmware, IP, model...).",
                transformations=[{"id": "groupingToMatrix", "options": {
                    "columnField": "key", "rowField": "device", "valueField": "value",
                    "emptyValue": "empty"}}],
                options=TABLE_OPTS),
        ]
        return self.dashboard("uns-equipment", "UNS · Equipment",
                              "Drill down the ISA-95 hierarchy to areas, lines and devices: live values, "
                              "trends and states.",
                              [self.ds_var(), *self.hierarchy_vars(lv), meas_float], panels, time_from="now-6h")

    # -----------------------------------------------------------------------
    # 3. Point trend
    # -----------------------------------------------------------------------

    def point_trend(self):
        d = self.d
        search = {"name": "search", "label": "Path contains", "type": "textbox", "query": "",
                  "current": {"text": "", "value": ""}, "hide": 0, "options": []}
        point = self.query_var(
            "point", "SELECT p.uns_path AS __text, p.point_id AS __value FROM uns.points p "
                     f"WHERE {d.contains('p.uns_path', '${search:sqlstring}')} ORDER BY 1",
            label="Point", include_all=False)
        point["current"] = {}
        sel = "p.point_id IN (${point:sqlstring})"
        panels = [
            self.panel("timeseries", "${point:text}", 0, 0, 24, 9, self.target(f"""
                SELECT t.time, t.avg, t.min, t.max
                FROM {d.trend(sel)} t
                ORDER BY 1""", fmt="time_series"),
                desc="Bucket average with the min/max envelope.",
                defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "lineWidth": 2, "fillOpacity": 0}},
                overrides=[override("max", ("custom.fillBelowTo", "min"), ("custom.lineWidth", 0),
                                    ("custom.fillOpacity", 20), ("color", fixed("#5794F2"))),
                           override("min", ("custom.lineWidth", 0), ("color", fixed("#5794F2")),
                                    ("custom.hideFrom", {"legend": True, "tooltip": False, "viz": False})),
                           override("avg", ("color", fixed("#1F60C4")))],
                options={**TS_LEGEND, "tooltip": {"mode": "multi", "sort": "none"}},
                repeat="point", repeatDirection="v"),
            self.panel("table", "Statistics", 0, 9, 24, 6, self.target(f"""
                SELECT p.uns_path, p.unit, p.data_type, p.description, p.source_ref,
                       (SELECT r2.value FROM uns.readings r2
                        WHERE r2.point_id = p.point_id AND $__timeFilter(r2.time)
                        ORDER BY r2.time DESC LIMIT 1) AS last,
                       s.min, s.max, s.avg, s.samples, s.good_pct
                FROM uns.points p
                LEFT JOIN (
                    SELECT r.point_id, MIN(r.value) AS min, MAX(r.value) AS max, AVG(r.value) AS avg,
                           COUNT(*) AS samples,
                           {d.num(f"100.0 * {d.count_if('r.quality & 192 = 192')} / NULLIF(COUNT(*), 0)")} AS good_pct
                    FROM uns.readings r
                    WHERE r.point_id IN (${{point:sqlstring}}) AND $__timeFilter(r.time)
                    GROUP BY r.point_id
                ) s ON s.point_id = p.point_id
                WHERE {sel}
                ORDER BY p.uns_path"""),
                desc="Computed from raw samples in the selected time range.",
                defaults={"decimals": 2},
                overrides=[override("uns_path", ("custom.minWidth", 320)),
                           override("good_pct", ("unit", "percent"), ("displayName", "good quality"),
                                    ("custom.cellOptions", {"type": "color-text"}), ("color", {"mode": "thresholds"}),
                                    ("thresholds", thresholds((0, "red"), (95, "orange"), (99.5, "green")))),
                           override("samples", ("decimals", 0))],
                options=TABLE_OPTS),
            self.panel("table", "Raw samples (newest 500)", 0, 15, 24, 10, self.target("""
                SELECT r.time, p.uns_path, r.value, r.quality, uns.quality_label(r.quality) AS quality_label
                FROM uns.readings r JOIN uns.points p USING (point_id)
                WHERE r.point_id IN (${point:sqlstring}) AND $__timeFilter(r.time)
                ORDER BY r.time DESC LIMIT 500"""),
                overrides=[override("uns_path", ("custom.minWidth", 360)),
                           override("quality_label", ("displayName", "status"),
                                    ("custom.cellOptions", {"type": "color-text"}), ("mappings", STATE_MAPPINGS))],
                options=TABLE_OPTS),
        ]
        return self.dashboard("uns-trend", "UNS · Point trend",
                              "Trend any point by its UNS path, with min/max envelope, statistics and raw samples.",
                              [self.ds_var(), search, point], panels, time_from="now-24h")

    # -----------------------------------------------------------------------
    # 4. Communication health
    # -----------------------------------------------------------------------

    def health(self):
        d, q = self.d, self.d.q
        lv = ["enterprise", "site", "area"]
        f = where(lv)
        panels = [
            self.panel("stat", "Point states", 0, 0, 24, 4, self.target(f"""
                SELECT {d.count_if("p.state = 'ok'")} AS {q("OK")},
                       {d.count_if("p.state = 'stale'")} AS {q("Stale")},
                       {d.count_if("p.state = 'never'")} AS {q("Never seen")},
                       {d.count_if("p.state = 'disabled'")} AS {q("Disabled")}
                FROM {d.health()} p WHERE {f}"""),
                desc="ok: reported within the stale window · stale: silent longer · never: registered but no "
                     "sample yet · disabled: storage switched off in the registry.",
                overrides=[override("OK", ("color", fixed("green"))),
                           override("Stale", ("color", fixed("orange"))),
                           override("Never seen", ("color", fixed("red"))),
                           override("Disabled", ("color", fixed("text")))],
                options=stat_opts()),
            self.panel("bargauge", "Silence per device", 0, 4, 9, 14, self.target(f"""
                SELECT {d.cat("p.site", "'/'", "p.area", "'/'", "p.device")} AS device, MIN(p.age_s) AS silent
                FROM {d.health()} p
                WHERE {f} AND p.enabled AND p.age_s IS NOT NULL
                GROUP BY 1 ORDER BY 2 DESC"""),
                desc="Time since the device's newest sample. Thresholds follow common MQTT publish rates.",
                defaults={"unit": "s", "min": 0, "color": {"mode": "thresholds"},
                          "displayName": "${__data.fields.device}",
                          "thresholds": thresholds((0, "green"), (900, "orange"), (86400, "red"))},
                options={"reduceOptions": {"calcs": [], "fields": "", "values": True},
                         "displayMode": "lcd", "orientation": "horizontal", "showUnfilled": True,
                         "valueMode": "color", "namePlacement": "left", "sizing": "auto"}),
            self.panel("table", "Points needing attention", 9, 4, 15, 14, self.target(f"""
                SELECT p.state, p.uns_path, p.source_ref, p.age_s AS last_seen, p.last_seen AS last_seen_at,
                       p.point_id
                FROM {d.health()} p WHERE {f}
                ORDER BY CASE p.state WHEN 'never' THEN 0 WHEN 'stale' THEN 1 WHEN 'ok' THEN 2 ELSE 3 END,
                         (p.age_s IS NULL) DESC, p.age_s DESC"""),
                desc="Problems first. Click a path to trend it.",
                overrides=[override("state", ("custom.cellOptions", {"type": "color-background", "mode": "basic"}),
                                    ("mappings", STATE_MAPPINGS), ("custom.width", 90)),
                           override("uns_path", ("links", self.trend_link()), ("custom.minWidth", 320)),
                           override("last_seen", *AGE_FIELD_PROPS),
                           override("point_id", ("custom.hidden", True))],
                options=TABLE_OPTS),
            self.panel("timeseries", "Non-good quality samples", 0, 18, 12, 8, self.target(f"""
                SELECT $__timeGroupAlias(r.time, $__interval), p.device AS metric,
                       {d.count_if("r.quality & 192 <> 192")} AS value
                FROM uns.readings r JOIN uns.points p USING (point_id)
                WHERE r.point_id IN ({ids(f)}) AND $__timeFilter(r.time)
                GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
                desc="Samples whose OPC quality is bad or uncertain (quality & 192 <> 192), from raw readings.",
                defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "drawStyle": "bars",
                                                    "fillOpacity": 70, "stacking": {"mode": "normal"}},
                          "decimals": 0},
                options=TS_LEGEND),
            self.panel("timeseries", "Reporting points by area", 12, 18, 12, 8, self.target(f"""
                SELECT t.time, {d.cat("p.site", "'/'", "p.area")} AS metric, COUNT(DISTINCT t.point_id) AS value
                FROM {d.trend(f)} t JOIN uns.points p USING (point_id)
                GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
                desc="Distinct points with at least one sample per bucket.",
                defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "lineInterpolation": "stepAfter"},
                          "decimals": 0},
                options=TS_LEGEND),
        ]
        return self.dashboard("uns-health", "UNS · Communication health",
                              "Which points and devices stopped reporting, and how clean the data is.",
                              [self.ds_var(), *self.hierarchy_vars(lv), self.stale_var()], panels)


def _walk(panels):
    for p in panels:
        yield p
        yield from p.get("panels", [])


DASHBOARDS = {
    "uns-overview": Builder.overview,
    "uns-equipment": Builder.equipment,
    "uns-trend": Builder.point_trend,
    "uns-health": Builder.health,
}


def render():
    out = {}
    for d in DIALECTS:
        b = Builder(d)
        for name, fn in DASHBOARDS.items():
            out[Path(d.engine) / f"{name}{d.uid_suffix}.json"] = json.dumps(fn(b), indent=2, ensure_ascii=False) + "\n"
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if committed JSON differs from the generator")
    args = ap.parse_args()

    files = render()
    stale = []
    for rel, text in files.items():
        path = OUT_DIR / rel
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(rel))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(OUT_DIR.parent.parent)}")
    # generated files that the generator no longer produces
    orphans = [p for p in OUT_DIR.rglob("*.json") if p.relative_to(OUT_DIR) not in files]
    if args.check:
        stale += [f"{p.relative_to(OUT_DIR)} (orphan)" for p in orphans]
    else:
        for p in orphans:
            p.unlink()
            print(f"removed {p.relative_to(OUT_DIR.parent.parent)}")
    if stale:
        print("stale dashboards (run tools/build_dashboards.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

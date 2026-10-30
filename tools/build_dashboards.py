#!/usr/bin/env python3
"""Generate the Grafana dashboard JSON in grafana/dashboards/.

The dashboards only query the `uns` contract schema (see db/uns), never a
source schema directly, so the same JSON works for every adapter.

    python3 tools/build_dashboards.py          # write the JSON files
    python3 tools/build_dashboards.py --check  # fail if the files are stale (CI)
"""

import argparse
import json
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
DS_TYPE = "grafana-postgresql-datasource"
DS = {"type": DS_TYPE, "uid": "${ds}"}
TAGS = ["uns", "isa-95"]

HIERARCHY = ["enterprise", "site", "area", "line", "device"]
BUCKET = "$__interval_ms * interval '1 millisecond'"
STALE = "${stale:sqlstring}"  # single-value vars are not quoted by Grafana unless asked


# ---------------------------------------------------------------------------
# SQL fragments
# ---------------------------------------------------------------------------

def where(levels, alias="p"):
    """Filter on the selected hierarchy variables, e.g. p.site IN ($site)."""
    return " AND ".join(f"{alias}.{lvl} IN (${lvl})" for lvl in levels) or "true"


def point_ids(levels, extra=""):
    cond = where(levels) + (f" AND {extra}" if extra else "")
    return f"ARRAY(SELECT p.point_id FROM uns.points p WHERE {cond})"


def trend(levels, extra=""):
    return f"uns.trend({point_ids(levels, extra)}, $__timeFrom(), $__timeTo(), {BUCKET})"


SERIES_NAME = "p.device || ' · ' || p.field || coalesce(' [' || p.unit || ']', '')"


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

def ds_var():
    return {
        "name": "ds", "label": "Data source", "type": "datasource",
        "query": DS_TYPE, "current": {"text": "UNS Historian", "value": "uns-historian"},
        "hide": 0, "refresh": 1, "regex": "", "options": [],
    }


def query_var(name, sql, label=None, multi=True, include_all=True, hide=0):
    return {
        "name": name, "label": label or name.capitalize(), "type": "query",
        "datasource": DS, "query": sql, "definition": sql,
        "refresh": 2,  # on time range change: picks up newly registered points
        "multi": multi, "includeAll": include_all,
        "current": {"text": ["All"], "value": ["$__all"]} if include_all else {},
        "options": [], "sort": 1, "hide": hide, "regex": "",
    }


def hierarchy_vars(levels):
    out = []
    for i, lvl in enumerate(levels):
        cond = where(levels[:i])
        out.append(query_var(lvl, f"SELECT DISTINCT p.{lvl} FROM uns.points p WHERE {cond} ORDER BY 1"))
    return out


def stale_var():
    opts = ["5m : 5 minutes", "15m : 15 minutes", "1h : 1 hour", "6h : 6 hours", "1d : 1 day"]
    return {
        "name": "stale", "label": "Stale after", "type": "custom",
        "query": ",".join(opts),
        "current": {"text": "15m", "value": "15 minutes"},
        "multi": False, "includeAll": False, "hide": 0, "options": [],
    }


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def target(sql, fmt="table", ref="A"):
    return {"refId": ref, "datasource": DS, "editorMode": "code", "format": fmt,
            "rawQuery": True, "rawSql": " ".join(sql.split())}


def panel(ptype, title, x, y, w, h, targets, *, desc="", defaults=None, overrides=None,
          options=None, transformations=None, **extra):
    p = {
        "type": ptype, "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets if isinstance(targets, list) else [targets],
        "fieldConfig": {"defaults": defaults or {}, "overrides": overrides or []},
        "options": options or {},
    }
    if transformations:
        p["transformations"] = transformations
    p.update(extra)
    return p


def row(title, y, collapsed=False, panels=None):
    return {"type": "row", "title": title, "collapsed": collapsed,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": panels or []}


def stat_opts(text_mode="value_and_name", graph="none", color_mode="background"):
    return {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": color_mode, "graphMode": graph, "textMode": text_mode,
            "justifyMode": "center", "orientation": "auto", "wideLayout": True}


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

EQUIPMENT_URL = ("/d/uns-equipment/uns-equipment?${ds:queryparam}&${__url_time_range}"
                 "&var-enterprise=${__data.fields.enterprise}&var-site=${__data.fields.site}")
TREND_URL = "/d/uns-trend/uns-point-trend?${ds:queryparam}&${__url_time_range}&var-point=${__data.fields.point_id}"


def dashboard(uid, title, desc, variables, panels, time_from="now-24h", refresh="1m"):
    for i, p in enumerate(_walk(panels), start=1):
        p["id"] = i
    return {
        "uid": uid, "title": title, "description": desc, "tags": TAGS,
        "editable": True, "graphTooltip": 1, "schemaVersion": 41, "version": 1,
        "timezone": "browser", "refresh": refresh,
        "time": {"from": time_from, "to": "now"},
        "timepicker": {}, "fiscalYearStartMonth": 0, "liveNow": False,
        "templating": {"list": variables},
        "annotations": {"list": [{
            "builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
            "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
            "name": "Annotations & Alerts", "type": "dashboard"}]},
        "links": [{"title": "UNS", "type": "dashboards", "tags": ["uns"], "asDropdown": False,
                   "includeVars": False, "keepTime": True, "targetBlank": False,
                   "icon": "external link", "tooltip": "", "url": ""}],
        "panels": panels,
    }


def _walk(panels):
    for p in panels:
        yield p
        yield from p.get("panels", [])


# ---------------------------------------------------------------------------
# 1. Enterprise overview
# ---------------------------------------------------------------------------

def overview():
    lv = ["enterprise", "site"]
    f = where(lv)
    panels = [
        panel("stat", "Model", 0, 0, 12, 4, target(f"""
            SELECT count(DISTINCT p.site) AS "Sites",
                   count(DISTINCT (p.site, p.area)) AS "Areas",
                   count(DISTINCT (p.site, p.area, p.line, p.device)) AS "Devices",
                   count(*) FILTER (WHERE p.enabled) AS "Points"
            FROM uns.points p WHERE {f}"""),
              desc="Size of the selected part of the ISA-95 equipment model.",
              defaults={"color": fixed("blue")}, options=stat_opts()),
        panel("stat", "Communication", 12, 0, 12, 4, target(f"""
            SELECT round(100.0 * count(*) FILTER (WHERE p.state = 'ok')
                         / nullif(count(*) FILTER (WHERE p.state <> 'disabled'), 0), 1) AS "Reporting",
                   count(*) FILTER (WHERE p.state = 'stale') AS "Stale",
                   count(*) FILTER (WHERE p.state = 'never') AS "Never seen",
                   (SELECT round(100.0 * count(*) FILTER (WHERE r.quality & 192 <> 192) / nullif(count(*), 0), 2)
                    FROM uns.readings r
                    WHERE r.point_id = ANY ({point_ids(lv)}) AND $__timeFilter(r.time)) AS "Bad quality"
            FROM uns.point_health({STALE}) p WHERE {f}"""),
              desc="Share of enabled points that reported within the stale window, and the share of "
                   "non-good OPC quality samples in the time range.",
              defaults={"color": {"mode": "thresholds"}, "thresholds": thresholds((0, "green"), (1, "orange"))},
              overrides=[override("Reporting", ("unit", "percent"),
                                  ("thresholds", thresholds((0, "red"), (80, "orange"), (99, "green")))),
                         override("Bad quality", ("unit", "percent"), ("decimals", 2),
                                  ("thresholds", thresholds((0, "green"), (0.5, "orange"), (5, "red"))))],
              options=stat_opts()),
        panel("nodeGraph", "Equipment hierarchy", 0, 4, 14, 14, [
            target(f"""
                SELECT h.path AS id, h.name AS title,
                       h.level || ' · ' || h.points || ' points' AS subtitle,
                       h.points || ' pts' AS mainstat,
                       h.level AS "detail__Level",
                       to_char(h.last_seen, 'YYYY-MM-DD HH24:MI:SS') AS "detail__Last seen",
                       CASE WHEN h.last_seen > now() - {STALE}::interval THEN '#73BF69' ELSE '#F2495C' END AS color
                FROM uns.hierarchy h
                WHERE h.point_ids && {point_ids(lv)}""", ref="nodes"),
            target(f"""
                SELECT h.parent_path || '->' || h.path AS id, h.parent_path AS source, h.path AS target
                FROM uns.hierarchy h
                WHERE h.parent_path IS NOT NULL AND h.point_ids && {point_ids(lv)}""", ref="edges"),
        ], desc="Enterprise > site > area > line > device. Node is green when the node's newest sample "
                "is younger than the stale window.",
              options={"nodes": {}, "edges": {},
                       "layoutAlgorithm": "layered", "zoomMode": "cooperative"}),
        panel("table", "Areas", 14, 4, 10, 14, target(f"""
            SELECT p.enterprise, p.site, p.area,
                   count(DISTINCT p.device) AS devices,
                   count(*) FILTER (WHERE p.state = 'ok') AS ok,
                   count(*) FILTER (WHERE p.state IN ('stale', 'never')) AS problems,
                   min(p.age_s) AS last_seen
            FROM uns.point_health({STALE}) p WHERE {f}
            GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"""),
              desc="Click an area to open it in the Equipment dashboard.",
              overrides=[
                  override("area", ("links", [link("Open ${__data.fields.area}",
                                                   EQUIPMENT_URL + "&var-area=${__data.fields.area}")])),
                  override("problems", ("custom.cellOptions", {"type": "color-background", "mode": "basic"}),
                           ("thresholds", thresholds((0, "transparent"), (1, "red"))),
                           ("color", {"mode": "thresholds"})),
                  override("last_seen", *AGE_FIELD_PROPS),
                  override("enterprise", ("custom.hidden", True)),
                  override("site", ("custom.width", 100)),
                  override("devices", ("custom.width", 75)),
                  override("ok", ("custom.width", 55)),
                  override("problems", ("custom.width", 85)),
              ],
              options={"showHeader": True, "cellHeight": "sm"}),
        panel("timeseries", "Samples by site", 0, 18, 12, 8, target(f"""
            SELECT t.time, p.site AS metric, sum(t.samples) AS value
            FROM {trend(lv)} t JOIN uns.points p USING (point_id)
            GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
              desc="Stored samples per time bucket: a drop means a site stopped publishing.",
              defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "drawStyle": "bars",
                                                  "fillOpacity": 60, "stacking": {"mode": "normal"}}},
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "desc"}}),
        panel("timeseries", "Reporting points by site", 12, 18, 12, 8, target(f"""
            SELECT t.time, p.site AS metric, count(DISTINCT t.point_id) AS value
            FROM {trend(lv)} t JOIN uns.points p USING (point_id)
            GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
              desc="Distinct points with at least one sample per bucket.",
              defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "drawStyle": "line",
                                                  "lineInterpolation": "stepAfter"}, "decimals": 0},
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "desc"}}),
    ]
    return dashboard("uns-overview", "UNS · Enterprise overview",
                     "Top of the ISA-95 model: sites, areas and their communication health.",
                     [ds_var(), *hierarchy_vars(lv), stale_var()], panels)


AGE_FIELD_PROPS = (("unit", "s"), ("decimals", 0), ("displayName", "last seen (s ago)"),
                   ("custom.cellOptions", {"type": "color-text"}), ("color", {"mode": "thresholds"}),
                   ("thresholds", thresholds((0, "green"), (900, "orange"), (86400, "red"))))


# ---------------------------------------------------------------------------
# 2. Equipment (area / line / device)
# ---------------------------------------------------------------------------

def equipment():
    lv = HIERARCHY + ["measurement"]
    f = where(lv)
    meas_float = query_var(
        "fmeas", f"SELECT DISTINCT p.measurement FROM uns.points p WHERE {f} AND p.data_type <> 'bool' "
        "AND p.last_seen IS NOT NULL ORDER BY 1",
        label="Float measurements", hide=2)
    panels = [
        panel("stat", "Live values", 0, 0, 24, 6, target(f"""
            SELECT p.device || ' · ' || p.field || coalesce(' [' || p.unit || ']', '') AS name, p.value
            FROM uns.latest p
            WHERE {f} AND p.data_type <> 'bool' AND p.enabled
            ORDER BY p.uns_path"""),
              desc="Latest stored value per analog point.",
              defaults={"color": fixed("blue"), "decimals": 1, "displayName": "${__data.fields.name}"},
              options={**stat_opts(color_mode="value"),
                       "reduceOptions": {"calcs": [], "fields": "", "values": True}}),
        row("Trends by measurement", 6),
        panel("timeseries", "$fmeas", 0, 7, 12, 9, target(f"""
            SELECT t.time, {SERIES_NAME} AS metric, t.avg AS value
            FROM {trend(lv, "p.measurement IN (${fmeas:sqlstring}) AND p.data_type <> 'bool'")} t
            JOIN uns.points p USING (point_id)
            ORDER BY 1""", fmt="time_series"),
              desc="Bucketed average. Long ranges read the hourly rollup automatically.",
              defaults=TS_DEFAULTS,
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "desc"}},
              repeat="fmeas", repeatDirection="h", maxPerRow=2),
        row("States", 16),
        panel("state-timeline", "Discrete states", 0, 17, 24, 8, target(f"""
            SELECT t.time, p.device || ' · ' || p.field AS metric, t.max AS value
            FROM {trend(lv, "p.data_type = 'bool'")} t
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
        panel("table", "Point list", 0, 26, 16, 10, target(f"""
            SELECT p.point_id, p.uns_path,
                   CASE WHEN p.data_type = 'bool' THEN CASE WHEN p.value > 0.5 THEN 'ON' ELSE 'OFF' END
                        ELSE round(p.value::numeric, 2)::text END AS value,
                   p.unit,
                   extract(epoch FROM now() - p.value_time) AS last_seen,
                   uns.quality_label(p.quality) AS quality,
                   p.enabled
            FROM uns.latest p WHERE {f}
            ORDER BY p.uns_path"""),
              desc="Click a UNS path to trend it.",
              overrides=[override("uns_path", ("links", [link("Trend ${__data.fields.uns_path}", TREND_URL)]),
                                  ("custom.minWidth", 320)),
                         override("last_seen", *AGE_FIELD_PROPS),
                         override("quality", ("custom.cellOptions", {"type": "color-text"}),
                                  ("mappings", STATE_MAPPINGS)),
                         override("point_id", ("custom.hidden", True)),
                         override("value", ("custom.align", "right"), ("custom.width", 90)),
                         override("unit", ("custom.width", 60)),
                         override("last_seen", ("custom.width", 140)),
                         override("quality", ("custom.width", 90)),
                         override("enabled", ("custom.width", 80))],
              options={"showHeader": True, "cellHeight": "sm"}),
        panel("table", "Asset attributes", 16, 26, 8, 10, target(f"""
            SELECT DISTINCT p.device, a.key, a.value
            FROM uns.points p, jsonb_each_text(p.attributes) a
            WHERE {f}
            ORDER BY 1, 2"""),
              desc="String attributes captured from device payloads (firmware, IP, model...).",
              transformations=[{"id": "groupingToMatrix", "options": {
                  "columnField": "key", "rowField": "device", "valueField": "value",
                  "emptyValue": "empty"}}],
              options={"showHeader": True, "cellHeight": "sm"}),
    ]
    return dashboard("uns-equipment", "UNS · Equipment",
                     "Drill down the ISA-95 hierarchy to areas, lines and devices: live values, trends "
                     "and states.",
                     [ds_var(), *hierarchy_vars(lv), meas_float], panels, time_from="now-6h")


# ---------------------------------------------------------------------------
# 3. Point trend
# ---------------------------------------------------------------------------

def point_trend():
    search = {"name": "search", "label": "Path contains", "type": "textbox", "query": "",
              "current": {"text": "", "value": ""}, "hide": 0, "options": []}
    point = query_var(
        "point", "SELECT p.uns_path AS __text, p.point_id AS __value FROM uns.points p "
                 "WHERE p.uns_path ILIKE '%' || ${search:sqlstring} || '%' ORDER BY 1",
        label="Point", include_all=False)
    point["current"] = {}
    ids = "ARRAY[${point:sqlstring}]::integer[]"
    panels = [
        panel("timeseries", "${point:text}", 0, 0, 24, 9, target(f"""
            SELECT t.time, t.avg, t.min, t.max
            FROM uns.trend({ids}, $__timeFrom(), $__timeTo(), {BUCKET}) t
            ORDER BY 1""", fmt="time_series"),
              desc="Bucket average with the min/max envelope.",
              defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "lineWidth": 2, "fillOpacity": 0}},
              overrides=[override("max", ("custom.fillBelowTo", "min"), ("custom.lineWidth", 0),
                                  ("custom.fillOpacity", 20), ("color", fixed("#5794F2"))),
                         override("min", ("custom.lineWidth", 0), ("color", fixed("#5794F2")),
                                  ("custom.hideFrom", {"legend": True, "tooltip": False, "viz": False})),
                         override("avg", ("color", fixed("#1F60C4")))],
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "none"}},
              repeat="point", repeatDirection="v"),
        panel("table", "Statistics", 0, 9, 24, 6, target(f"""
            SELECT p.uns_path, p.unit, p.data_type, p.description, p.source_ref,
                   s.last, s.min, s.max, s.avg, s.samples, s.good_pct
            FROM uns.points p
            LEFT JOIN LATERAL (
                SELECT (array_agg(r.value ORDER BY r.time DESC))[1] AS last,
                       min(r.value) AS min, max(r.value) AS max, avg(r.value) AS avg,
                       count(*) AS samples,
                       100.0 * count(*) FILTER (WHERE r.quality & 192 = 192) / nullif(count(*), 0) AS good_pct
                FROM uns.readings r
                WHERE r.point_id = p.point_id AND $__timeFilter(r.time)
            ) s ON true
            WHERE p.point_id = ANY ({ids})
            ORDER BY p.uns_path"""),
              desc="Computed from raw samples in the selected time range.",
              defaults={"decimals": 2},
              overrides=[override("uns_path", ("custom.minWidth", 320)),
                         override("good_pct", ("unit", "percent"), ("displayName", "good quality"),
                                  ("custom.cellOptions", {"type": "color-text"}), ("color", {"mode": "thresholds"}),
                                  ("thresholds", thresholds((0, "red"), (95, "orange"), (99.5, "green")))),
                         override("samples", ("decimals", 0))],
              options={"showHeader": True, "cellHeight": "sm"}),
        panel("table", "Raw samples (newest 500)", 0, 15, 24, 10, target(f"""
            SELECT r.time, p.uns_path, r.value, r.quality, uns.quality_label(r.quality) AS quality_label
            FROM uns.readings r JOIN uns.points p USING (point_id)
            WHERE r.point_id = ANY ({ids}) AND $__timeFilter(r.time)
            ORDER BY r.time DESC LIMIT 500"""),
              overrides=[override("uns_path", ("custom.minWidth", 360)),
                       override("quality_label", ("displayName", "status"),
                                  ("custom.cellOptions", {"type": "color-text"}), ("mappings", STATE_MAPPINGS))],
              options={"showHeader": True, "cellHeight": "sm"}),
    ]
    return dashboard("uns-trend", "UNS · Point trend",
                     "Trend any point by its UNS path, with min/max envelope, statistics and raw samples.",
                     [ds_var(), search, point], panels, time_from="now-24h")


# ---------------------------------------------------------------------------
# 4. Communication health
# ---------------------------------------------------------------------------

def health():
    lv = ["enterprise", "site", "area"]
    f = where(lv)
    panels = [
        panel("stat", "Point states", 0, 0, 24, 4, target(f"""
            SELECT count(*) FILTER (WHERE p.state = 'ok') AS "OK",
                   count(*) FILTER (WHERE p.state = 'stale') AS "Stale",
                   count(*) FILTER (WHERE p.state = 'never') AS "Never seen",
                   count(*) FILTER (WHERE p.state = 'disabled') AS "Disabled"
            FROM uns.point_health({STALE}) p WHERE {f}"""),
              desc="ok: reported within the stale window · stale: silent longer · never: registered but no "
                   "sample yet · disabled: storage switched off in the registry.",
              overrides=[override("OK", ("color", fixed("green"))),
                         override("Stale", ("color", fixed("orange"))),
                         override("Never seen", ("color", fixed("red"))),
                         override("Disabled", ("color", fixed("text")))],
              options=stat_opts()),
        panel("bargauge", "Silence per device", 0, 4, 9, 14, target(f"""
            SELECT p.site || '/' || p.area || '/' || p.device AS device, min(p.age_s) AS silent
            FROM uns.point_health({STALE}) p
            WHERE {f} AND p.enabled AND p.age_s IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC"""),
              desc="Time since the device's newest sample. Thresholds follow common MQTT publish rates.",
              defaults={"unit": "s", "min": 0, "color": {"mode": "thresholds"},
                        "displayName": "${__data.fields.device}",
                        "thresholds": thresholds((0, "green"), (900, "orange"), (86400, "red"))},
              options={"reduceOptions": {"calcs": [], "fields": "", "values": True},
                       "displayMode": "lcd", "orientation": "horizontal", "showUnfilled": True,
                       "valueMode": "color", "namePlacement": "left", "sizing": "auto"}),
        panel("table", "Points needing attention", 9, 4, 15, 14, target(f"""
            SELECT p.state, p.uns_path, p.source_ref, p.age_s AS last_seen, p.last_seen AS last_seen_at, p.point_id
            FROM uns.point_health({STALE}) p WHERE {f}
            ORDER BY CASE p.state WHEN 'never' THEN 0 WHEN 'stale' THEN 1 WHEN 'ok' THEN 2 ELSE 3 END,
                     p.age_s DESC NULLS FIRST"""),
              desc="Problems first. Click a path to trend it.",
              overrides=[override("state", ("custom.cellOptions", {"type": "color-background", "mode": "basic"}),
                                  ("mappings", STATE_MAPPINGS), ("custom.width", 90)),
                         override("uns_path", ("links", [link("Trend ${__data.fields.uns_path}", TREND_URL)]),
                                  ("custom.minWidth", 320)),
                         override("last_seen", *AGE_FIELD_PROPS),
                         override("point_id", ("custom.hidden", True))],
              options={"showHeader": True, "cellHeight": "sm"}),
        panel("timeseries", "Non-good quality samples", 0, 18, 12, 8, target(f"""
            SELECT $__timeGroupAlias(r.time, $__interval), p.device AS metric,
                   count(*) FILTER (WHERE r.quality & 192 <> 192) AS value
            FROM uns.readings r JOIN uns.points p USING (point_id)
            WHERE r.point_id = ANY ({point_ids(lv)}) AND $__timeFilter(r.time)
            GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
              desc="Samples whose OPC quality is bad or uncertain (quality & 192 <> 192), from raw readings.",
              defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "drawStyle": "bars",
                                                  "fillOpacity": 70, "stacking": {"mode": "normal"}},
                        "decimals": 0},
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "desc"}}),
        panel("timeseries", "Reporting points by area", 12, 18, 12, 8, target(f"""
            SELECT t.time, p.site || '/' || p.area AS metric, count(DISTINCT t.point_id) AS value
            FROM {trend(lv)} t JOIN uns.points p USING (point_id)
            GROUP BY 1, 2 ORDER BY 1""", fmt="time_series"),
              desc="Distinct points with at least one sample per bucket.",
              defaults={**TS_DEFAULTS, "custom": {**TS_DEFAULTS["custom"], "lineInterpolation": "stepAfter"},
                        "decimals": 0},
              options={"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                       "tooltip": {"mode": "multi", "sort": "desc"}}),
    ]
    return dashboard("uns-health", "UNS · Communication health",
                     "Which points and devices stopped reporting, and how clean the data is.",
                     [ds_var(), *hierarchy_vars(lv), stale_var()], panels, time_from="now-24h")


DASHBOARDS = {
    "uns-overview.json": overview,
    "uns-equipment.json": equipment,
    "uns-trend.json": point_trend,
    "uns-health.json": health,
}


def render():
    return {name: json.dumps(fn(), indent=2, ensure_ascii=False) + "\n" for name, fn in DASHBOARDS.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if committed JSON differs from the generator")
    args = ap.parse_args()

    stale = []
    for name, text in render().items():
        path = OUT_DIR / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(OUT_DIR.parent.parent)}")
    if stale:
        print("stale dashboards (run tools/build_dashboards.py): " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

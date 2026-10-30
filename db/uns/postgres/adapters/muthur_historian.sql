-- =====================================================================
-- UNS adapter: MUTHUR historian (historian.points + historian.readings)
--
-- An adapter maps one source schema onto the three contract views that
-- every dashboard reads:
--
--   uns.points       one row per signal, ISA-95 hierarchy + metadata
--   uns.readings     raw samples   (time, point_id, value, quality)
--   uns.readings_1h  hourly rollup (time, point_id, avg, min, max, samples)
--
-- Keep the views thin (no casts on point_id/time) so the planner can
-- push filters down to the hypertable indexes.
--
-- Load order: adapter first, then db/uns/postgres/core.sql (see tools/install_uns.sh).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS uns;

-- Hierarchy levels are never NULL in the contract: a missing level shows
-- up as '(none)' so Grafana multi-value filters (IN (...)) still match it.
CREATE OR REPLACE VIEW uns.points AS
SELECT p.point_id,
       coalesce(nullif(p.enterprise,  ''), '(none)') AS enterprise,
       coalesce(nullif(p.site,        ''), '(none)') AS site,
       coalesce(nullif(p.area,        ''), '(none)') AS area,
       coalesce(nullif(p.line,        ''), '(none)') AS line,
       coalesce(nullif(p.device,      ''), '(none)') AS device,
       coalesce(nullif(p.measurement, ''), '(none)') AS measurement,
       p.field,
       concat_ws('/', nullif(p.enterprise, ''), nullif(p.site, ''), nullif(p.area, ''),
                      nullif(p.line, ''), nullif(p.device, ''), nullif(p.measurement, ''),
                      p.field)                       AS uns_path,
       p.data_type,
       p.unit,
       p.description,
       p.attributes,
       p.enabled,
       p.last_seen,
       p.source_topic || ':' || p.field              AS source_ref
FROM historian.points p;

CREATE OR REPLACE VIEW uns.readings AS
SELECT r.time, r.point_id, r.value, r.quality
FROM historian.readings r;

CREATE OR REPLACE VIEW uns.readings_1h AS
SELECT h.bucket AS time, h.point_id, h.avg, h.min, h.max, h.samples
FROM historian.readings_1h h;

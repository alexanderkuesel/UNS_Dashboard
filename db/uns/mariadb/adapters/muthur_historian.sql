-- =====================================================================
-- UNS adapter (MariaDB): MUTHUR historian (historian.points + readings)
--
-- Maps the source schema onto the contract views every dashboard reads:
--
--   uns.points       one row per signal, ISA-95 hierarchy + metadata
--   uns.readings     raw samples   (time, point_id, value, quality)
--   uns.readings_1h  hourly rollup (time, point_id, avg, min, max, samples)
--
-- All times are UTC DATETIMEs. Keep point_id/time as plain columns so
-- filters use the (point_id, time) primary keys.
--
-- Load order: adapter first, then db/uns/mariadb/core.sql
-- (ENGINE=mariadb tools/install_uns.sh).
-- =====================================================================

-- Hierarchy levels are never NULL in the contract: a missing level shows
-- up as '(none)' so Grafana multi-value filters (IN (...)) still match it.
CREATE OR REPLACE VIEW uns.points AS
SELECT p.point_id,
       COALESCE(NULLIF(p.enterprise,  ''), '(none)') AS enterprise,
       COALESCE(NULLIF(p.site,        ''), '(none)') AS site,
       COALESCE(NULLIF(p.area,        ''), '(none)') AS area,
       COALESCE(NULLIF(p.line,        ''), '(none)') AS line,
       COALESCE(NULLIF(p.device,      ''), '(none)') AS device,
       COALESCE(NULLIF(p.measurement, ''), '(none)') AS measurement,
       p.field,
       CONCAT_WS('/', NULLIF(p.enterprise, ''), NULLIF(p.site, ''), NULLIF(p.area, ''),
                      NULLIF(p.line, ''), NULLIF(p.device, ''), NULLIF(p.measurement, ''),
                      p.field)                       AS uns_path,
       p.data_type,
       p.unit,
       p.description,
       p.attributes,
       p.enabled,
       p.last_seen,
       CONCAT(p.source_topic, ':', p.field)          AS source_ref
FROM historian.points p;

CREATE OR REPLACE VIEW uns.readings AS
SELECT r.time, r.point_id, r.value, r.quality
FROM historian.readings r;

CREATE OR REPLACE VIEW uns.readings_1h AS
SELECT h.bucket AS time, h.point_id, h.avg, h.min, h.max, h.samples
FROM historian.readings_1h h;

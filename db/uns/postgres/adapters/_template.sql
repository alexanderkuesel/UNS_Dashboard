-- =====================================================================
-- UNS adapter template. Copy to <name>.sql and fill in the SELECTs, then:
--   ADAPTER=<name> tools/install_uns.sh
--
-- Contract (column names and types must match exactly):
--
--   uns.points
--     point_id     integer      stable id, must match uns.readings.point_id
--     enterprise, site, area, line, device, measurement
--                  text NOT NULL, use '(none)' for a missing level
--     field        text         signal name within the measurement
--     uns_path     text         e.g. enterprise/site/area/line/device/measurement/field
--     data_type    text         'float' | 'bool' (bool = 0/1 values, drawn as states)
--     unit         text
--     description  text
--     attributes   jsonb        free-form key/value (fw, ip, model...), '{}' if none
--     enabled      boolean
--     last_seen    timestamptz  newest sample time (NULL = never reported)
--     source_ref   text         where the signal comes from (topic, tag path...)
--
--   uns.readings     (time timestamptz, point_id integer, value double precision, quality smallint)
--                    quality: OPC code, 192 = good. Use 192 if the source has none.
--   uns.readings_1h  (time timestamptz, point_id integer, avg/min/max double precision, samples bigint)
--                    hourly rollup. Without one, return no rows:
--                    SELECT ... FROM uns.readings WHERE false
--                    and uns.trend() reads raw data for every range.
--
-- Performance: keep point_id and time as plain columns (no casts or
-- expressions) so filters reach the source indexes and chunk exclusion.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS uns;

CREATE OR REPLACE VIEW uns.points AS
SELECT s.id::integer                              AS point_id,
       coalesce(s.enterprise, '(none)')           AS enterprise,
       coalesce(s.site, '(none)')                 AS site,
       coalesce(s.area, '(none)')                 AS area,
       coalesce(s.line, '(none)')                 AS line,
       coalesce(s.device, '(none)')               AS device,
       coalesce(s.measurement, '(none)')          AS measurement,
       s.field::text                              AS field,
       concat_ws('/', s.enterprise, s.site, s.area, s.line, s.device, s.measurement, s.field) AS uns_path,
       'float'::text                              AS data_type,
       NULL::text                                 AS unit,
       NULL::text                                 AS description,
       '{}'::jsonb                                AS attributes,
       true                                       AS enabled,
       NULL::timestamptz                          AS last_seen,
       s.topic::text                              AS source_ref
FROM my_schema.my_signals s;              -- <- your registry table

CREATE OR REPLACE VIEW uns.readings AS
SELECT v.ts AS time, v.signal_id AS point_id, v.val::double precision AS value, 192::smallint AS quality
FROM my_schema.my_values v;              -- <- your samples table

CREATE OR REPLACE VIEW uns.readings_1h AS
SELECT r.time, r.point_id,
       r.value AS avg, r.value AS min, r.value AS max, 1::bigint AS samples
FROM uns.readings r
WHERE false;                             -- no rollup available

-- =====================================================================
-- UNS adapter template (MariaDB). Copy to <name>.sql, fill in the SELECTs:
--   ENGINE=mariadb ADAPTER=<name> tools/install_uns.sh
--
-- The contract is the same as for PostgreSQL (see
-- db/uns/postgres/adapters/_template.sql for every column), with:
--   * time columns: DATETIME in UTC
--   * attributes:   JSON object ('{}' if none)
--   * no rollup?    make uns.readings_1h return no rows; the dashboards
--                   then read raw data for every range (slower for months).
-- =====================================================================

CREATE OR REPLACE VIEW uns.points AS
SELECT s.id                                       AS point_id,
       COALESCE(s.enterprise, '(none)')           AS enterprise,
       COALESCE(s.site, '(none)')                 AS site,
       COALESCE(s.area, '(none)')                 AS area,
       COALESCE(s.line, '(none)')                 AS line,
       COALESCE(s.device, '(none)')               AS device,
       COALESCE(s.measurement, '(none)')          AS measurement,
       s.field                                    AS field,
       CONCAT_WS('/', s.enterprise, s.site, s.area, s.line, s.device, s.measurement, s.field) AS uns_path,
       'float'                                    AS data_type,
       CAST(NULL AS CHAR(32))                     AS unit,
       CAST(NULL AS CHAR(512))                    AS description,
       JSON_OBJECT()                              AS attributes,
       TRUE                                       AS enabled,
       CAST(NULL AS DATETIME(3))                  AS last_seen,
       s.topic                                    AS source_ref
FROM my_db.my_signals s;                 -- <- your registry table

CREATE OR REPLACE VIEW uns.readings AS
SELECT v.ts AS time, v.signal_id AS point_id, v.val AS value, 192 AS quality
FROM my_db.my_values v;                  -- <- your samples table

CREATE OR REPLACE VIEW uns.readings_1h AS
SELECT r.time, r.point_id, r.value AS avg, r.value AS min, r.value AS max, 1 AS samples
FROM uns.readings r
WHERE FALSE;                             -- no rollup available

-- =====================================================================
-- UNS core (MariaDB): schema-independent helpers the Grafana dashboards
-- query. Depends only on the adapter contract views uns.points,
-- uns.readings and uns.readings_1h.
--
-- MariaDB has no table functions, arrays or LATERAL, so the bucketing
-- logic that uns.trend() does on PostgreSQL lives in the dashboard SQL
-- (see tools/build_dashboards.py, class MariaDB).
--
-- Load with ENGINE=mariadb tools/install_uns.sh, which substitutes
-- __READER__ with the dashboard user.
-- =====================================================================

-- ---------------------------------------------------------------------
-- OPC quality helper (192..255 good, 64..127 uncertain, 0..63 bad)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION uns.quality_label(q INT)
RETURNS VARCHAR(16) DETERMINISTIC NO SQL
RETURN CASE WHEN q IS NULL THEN NULL
            WHEN q & 192 = 192 THEN 'good'
            WHEN q & 192 = 64  THEN 'uncertain'
            ELSE 'bad' END;

-- ---------------------------------------------------------------------
-- Latest value per point: one primary-key lookup per point.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW uns.latest AS
SELECT p.point_id, p.enterprise, p.site, p.area, p.line, p.device,
       p.measurement, p.field, p.uns_path, p.data_type, p.unit,
       p.enabled, p.last_seen,
       r.time    AS value_time,
       r.value,
       r.quality
FROM uns.points p
LEFT JOIN uns.readings r
       ON r.point_id = p.point_id
      AND r.time = (SELECT MAX(r2.time) FROM uns.readings r2 WHERE r2.point_id = p.point_id);

-- ---------------------------------------------------------------------
-- Communication status per point. The stale threshold is a dashboard
-- variable, so the ok/stale/never/disabled state is derived in the query.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW uns.point_status AS
SELECT p.point_id, p.enterprise, p.site, p.area, p.line, p.device,
       p.measurement, p.field, p.uns_path, p.source_ref,
       p.enabled, p.last_seen,
       TIMESTAMPDIFF(SECOND, p.last_seen, UTC_TIMESTAMP()) AS age_s
FROM uns.points p;

-- ---------------------------------------------------------------------
-- Equipment hierarchy, one row per (point, level): enterprise > site >
-- area > line > device. Levels that are '(none)' are skipped, so a
-- device without a line hangs directly off its area. Dashboards filter
-- on point_id and GROUP BY path to get the tree nodes.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW uns.hierarchy_points AS
SELECT p.point_id, p.enabled, p.last_seen, 'enterprise' AS level, p.enterprise AS name,
       CONCAT_WS('/', NULLIF(p.enterprise, '(none)')) AS path,
       CAST(NULL AS CHAR(1024)) AS parent_path,
       (p.enterprise <> '(none)') AS depth
FROM uns.points p WHERE p.enterprise <> '(none)'
UNION ALL
SELECT p.point_id, p.enabled, p.last_seen, 'site' AS level, p.site AS name,
       CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)')) AS path,
       NULLIF(CONCAT_WS('/', NULLIF(p.enterprise, '(none)')), '') AS parent_path,
       (p.enterprise <> '(none)') + (p.site <> '(none)') AS depth
FROM uns.points p WHERE p.site <> '(none)'
UNION ALL
SELECT p.point_id, p.enabled, p.last_seen, 'area' AS level, p.area AS name,
       CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)'), NULLIF(p.area, '(none)')) AS path,
       NULLIF(CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)')), '') AS parent_path,
       (p.enterprise <> '(none)') + (p.site <> '(none)') + (p.area <> '(none)') AS depth
FROM uns.points p WHERE p.area <> '(none)'
UNION ALL
SELECT p.point_id, p.enabled, p.last_seen, 'line' AS level, p.line AS name,
       CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)'), NULLIF(p.area, '(none)'), NULLIF(p.line, '(none)')) AS path,
       NULLIF(CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)'), NULLIF(p.area, '(none)')), '') AS parent_path,
       (p.enterprise <> '(none)') + (p.site <> '(none)') + (p.area <> '(none)') + (p.line <> '(none)') AS depth
FROM uns.points p WHERE p.line <> '(none)'
UNION ALL
SELECT p.point_id, p.enabled, p.last_seen, 'device' AS level, p.device AS name,
       CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)'), NULLIF(p.area, '(none)'), NULLIF(p.line, '(none)'), NULLIF(p.device, '(none)')) AS path,
       NULLIF(CONCAT_WS('/', NULLIF(p.enterprise, '(none)'), NULLIF(p.site, '(none)'), NULLIF(p.area, '(none)'), NULLIF(p.line, '(none)')), '') AS parent_path,
       (p.enterprise <> '(none)') + (p.site <> '(none)') + (p.area <> '(none)') + (p.line <> '(none)') + (p.device <> '(none)') AS depth
FROM uns.points p WHERE p.device <> '(none)';

-- ---------------------------------------------------------------------
-- Read-only access for the dashboard user
-- ---------------------------------------------------------------------
GRANT SELECT, SHOW VIEW ON uns.* TO __READER__;
GRANT EXECUTE ON FUNCTION uns.quality_label TO __READER__;

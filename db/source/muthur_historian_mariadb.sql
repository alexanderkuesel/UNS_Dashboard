-- =====================================================================
-- MUTHUR historian schema, MariaDB edition (10.6+, tested on 11.4 LTS)
-- Same split as the TimescaleDB version: point registry (metadata) +
-- slim readings table + hourly rollup.
--
-- Run once against the server:
--   docker exec -i mariadb mariadb -uroot -p < muthur_historian_mariadb.sql
--
-- Conventions
--   * All timestamps are UTC (DATETIME has no time zone). Insert with
--     UTC_TIMESTAMP(3) or UTC values from Node-RED.
--   * The hourly rollup is maintained by an EVENT, so the server needs
--     event_scheduler=ON (my.cnf: [mysqld] event_scheduler=ON).
-- =====================================================================

CREATE DATABASE IF NOT EXISTS historian
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE historian;

-- ---------------------------------------------------------------------
-- 1. Point registry: one row per signal (topic + field)
--    Node-RED auto-registers new points; you edit the hierarchy here,
--    never on the field devices.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS points (
    point_id      INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,

    -- identity of the raw signal as it arrives over MQTT
    source_topic  VARCHAR(255) NOT NULL,
    field         VARCHAR(128) NOT NULL,

    -- ISA-95 style equipment hierarchy (defaults come from the topic,
    -- edit freely afterwards)
    enterprise    VARCHAR(128),
    site          VARCHAR(128),
    area          VARCHAR(128),
    line          VARCHAR(128),       -- work center / line / cell
    device        VARCHAR(128),
    measurement   VARCHAR(128),

    -- engineering metadata
    data_type     VARCHAR(16)  NOT NULL DEFAULT 'float',   -- float | bool
    unit          VARCHAR(32),
    description   VARCHAR(512),
    attributes    JSON         NOT NULL DEFAULT '{}',      -- string values from payloads (fw, ip...)

    enabled       BOOLEAN      NOT NULL DEFAULT TRUE,      -- false = stop storing, keep history
    created_at    DATETIME(3)  NOT NULL DEFAULT UTC_TIMESTAMP(3),
    last_seen     DATETIME(3),

    UNIQUE KEY points_signal_uk (source_topic, field),
    KEY points_hierarchy_idx (site, area, line, device)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 2. Readings: one row per value, clustered by (point_id, time) so a
--    point's history is contiguous on disk. quality uses OPC codes
--    (192 = good), same as Ignition.
--    For multi-year data consider PARTITION BY RANGE on time to drop old
--    months cheaply; the rollup below keeps the long-term trend.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings (
    time      DATETIME(3)  NOT NULL,
    point_id  INT          NOT NULL,
    value     DOUBLE,
    quality   SMALLINT     NOT NULL DEFAULT 192,
    PRIMARY KEY (point_id, time),
    KEY readings_time_idx (time),
    CONSTRAINT readings_point_fk FOREIGN KEY (point_id) REFERENCES points (point_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 3. Hourly rollup for long-range trends (MariaDB has no continuous
--    aggregates: a procedure recomputes recent buckets, an event runs it)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS readings_1h (
    bucket    DATETIME     NOT NULL,
    point_id  INT          NOT NULL,
    avg       DOUBLE,
    min       DOUBLE,
    max       DOUBLE,
    samples   BIGINT       NOT NULL,
    PRIMARY KEY (point_id, bucket),
    KEY readings_1h_bucket_idx (bucket)
) ENGINE = InnoDB;

DELIMITER //

-- Recompute every hourly bucket from p_from (rounded down to the hour)
-- up to and including the current, still-open hour.
CREATE OR REPLACE PROCEDURE refresh_readings_1h(IN p_from DATETIME)
BEGIN
    DECLARE v_from DATETIME DEFAULT DATE_FORMAT(p_from, '%Y-%m-%d %H:00:00');

    REPLACE INTO readings_1h (bucket, point_id, avg, min, max, samples)
    SELECT DATE_FORMAT(r.time, '%Y-%m-%d %H:00:00'), r.point_id,
           AVG(r.value), MIN(r.value), MAX(r.value), COUNT(*)
    FROM readings r
    WHERE r.time >= v_from
    GROUP BY 1, 2;
END //

DELIMITER ;

-- Every 5 minutes, refresh the last 3 hours (covers late-arriving data).
CREATE OR REPLACE EVENT refresh_readings_1h_event
    ON SCHEDULE EVERY 5 MINUTE
    DO CALL refresh_readings_1h(UTC_TIMESTAMP() - INTERVAL 3 HOUR);

-- ---------------------------------------------------------------------
-- 4. Views for ad-hoc queries
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_readings AS
SELECT r.time, p.point_id,
       p.enterprise, p.site, p.area, p.line, p.device,
       p.measurement, p.field, p.unit,
       r.value, r.quality
FROM readings r
JOIN points p ON p.point_id = r.point_id;

CREATE OR REPLACE VIEW v_point_status AS
SELECT point_id, site, area, device, measurement, field, enabled,
       last_seen, TIMESTAMPDIFF(SECOND, last_seen, UTC_TIMESTAMP()) AS age_s
FROM points;

-- ---------------------------------------------------------------------
-- 5. Least-privilege users (change the passwords before running)
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'nodered'@'%' IDENTIFIED BY 'CHANGE_ME_nodered';
CREATE USER IF NOT EXISTS 'grafana'@'%' IDENTIFIED BY 'CHANGE_ME_grafana';

-- Node-RED: register points, update last_seen/attributes, insert readings
GRANT SELECT, INSERT, UPDATE ON historian.points TO 'nodered'@'%';
GRANT INSERT ON historian.readings TO 'nodered'@'%';

-- Grafana reads through the uns views (see db/uns/mariadb); direct read
-- access to the historian is optional but handy for ad-hoc panels.
GRANT SELECT ON historian.* TO 'grafana'@'%';

-- =====================================================================
-- MUTHUR historian schema (TimescaleDB on PostgreSQL)
-- Pattern: point registry (metadata) + slim readings hypertable,
-- the same split used by Ignition's tag historian and PI.
--
-- Run once against the target database:
--   docker exec -i timescaledb psql -U postgres -d home_data \
--     -v ON_ERROR_STOP=1 < historian_schema.sql
--
-- Not wrapped in a transaction: continuous aggregates can't be
-- created inside one.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE SCHEMA IF NOT EXISTS historian;

-- ---------------------------------------------------------------------
-- 1. Point registry: one row per signal (topic + field)
--    Node-RED auto-registers new points; you edit the hierarchy here,
--    never on the field devices.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historian.points (
    point_id      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- identity of the raw signal as it arrives over MQTT
    source_topic  text        NOT NULL,
    field         text        NOT NULL,

    -- ISA-95 style equipment hierarchy (defaults come from the topic,
    -- edit freely afterwards)
    enterprise    text,
    site          text,
    area          text,
    line          text,       -- work center / line / cell
    device        text,
    measurement   text,

    -- engineering metadata
    data_type     text        NOT NULL DEFAULT 'float',   -- float | bool
    unit          text,
    description   text,
    attributes    jsonb       NOT NULL DEFAULT '{}',      -- string values from payloads (fw, ip...)

    enabled       boolean     NOT NULL DEFAULT true,      -- false = stop storing, keep history
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz,

    UNIQUE (source_topic, field)
);

CREATE INDEX IF NOT EXISTS points_hierarchy_idx
    ON historian.points (site, area, line, device);

-- ---------------------------------------------------------------------
-- 2. Readings: slim hypertable, one row per value
--    quality uses OPC codes (192 = good), same as Ignition
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historian.readings (
    time      timestamptz      NOT NULL,
    point_id  integer          NOT NULL REFERENCES historian.points (point_id),
    value     double precision,
    quality   smallint         NOT NULL DEFAULT 192,
    UNIQUE (point_id, time)
);

SELECT create_hypertable('historian.readings', by_range('time', INTERVAL '7 days'),
                         if_not_exists => true);

-- Compression: older chunks shrink ~90%+, grouped per point
ALTER TABLE historian.readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'point_id',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('historian.readings', INTERVAL '7 days', if_not_exists => true);

-- Retention (optional): uncomment to drop raw data older than 2 years.
-- The hourly aggregate below keeps the long-term trend.
-- SELECT add_retention_policy('historian.readings', INTERVAL '2 years', if_not_exists => true);

-- ---------------------------------------------------------------------
-- 3. Hourly rollup (continuous aggregate) for long-range trends
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS historian.readings_1h
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
       point_id,
       avg(value) AS avg,
       min(value) AS min,
       max(value) AS max,
       count(*)   AS samples
FROM historian.readings
GROUP BY bucket, point_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('historian.readings_1h',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists     => true);

-- ---------------------------------------------------------------------
-- 4. Views for Grafana / Ignition / ad-hoc queries
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW historian.v_readings AS
SELECT r.time, p.point_id,
       p.enterprise, p.site, p.area, p.line, p.device,
       p.measurement, p.field, p.unit,
       r.value, r.quality
FROM historian.readings r
JOIN historian.points p USING (point_id);

CREATE OR REPLACE VIEW historian.v_readings_1h AS
SELECT h.bucket AS time, p.point_id,
       p.site, p.area, p.line, p.device, p.measurement, p.field, p.unit,
       h.avg, h.min, h.max, h.samples
FROM historian.readings_1h h
JOIN historian.points p USING (point_id);

-- Communication health: how long since each point last reported
CREATE OR REPLACE VIEW historian.v_point_status AS
SELECT point_id, site, area, device, measurement, field, enabled,
       last_seen, now() - last_seen AS age
FROM historian.points
ORDER BY last_seen NULLS FIRST;

-- ---------------------------------------------------------------------
-- 5. Least-privilege roles (change the passwords before running)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nodered') THEN
        CREATE ROLE nodered LOGIN PASSWORD 'CHANGE_ME_nodered';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana') THEN
        CREATE ROLE grafana LOGIN PASSWORD 'CHANGE_ME_grafana';
    END IF;
END $$;

GRANT USAGE ON SCHEMA historian TO nodered, grafana;

-- Node-RED: register points, update last_seen/attributes, insert readings
GRANT SELECT, INSERT, UPDATE ON historian.points TO nodered;
GRANT INSERT ON historian.readings TO nodered;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA historian TO nodered;

-- Grafana / Ignition: read only
GRANT SELECT ON ALL TABLES IN SCHEMA historian TO grafana;
ALTER DEFAULT PRIVILEGES IN SCHEMA historian GRANT SELECT ON TABLES TO grafana;

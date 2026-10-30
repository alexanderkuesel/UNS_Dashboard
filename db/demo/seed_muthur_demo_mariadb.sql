-- =====================================================================
-- Demo data for the MUTHUR historian schema, MariaDB edition.
-- Same small home/workshop UNS as the TimescaleDB demo: ~14 days of
-- 1-minute data, plus an EVENT that keeps writing live samples.
--
-- Safe to re-run: removes previous demo points (source_topic 'demo/...').
-- Needs event_scheduler=ON for the live feed and the hourly rollup.
-- =====================================================================

USE historian;

DELETE FROM readings_1h
WHERE point_id IN (SELECT point_id FROM points WHERE source_topic LIKE 'demo/%');
DELETE FROM readings
WHERE point_id IN (SELECT point_id FROM points WHERE source_topic LIKE 'demo/%');
DELETE FROM points WHERE source_topic LIKE 'demo/%';

INSERT INTO points
    (source_topic, field, enterprise, site, area, line, device, measurement,
     data_type, unit, description, attributes)
VALUES
 -- main house
 ('demo/home/house/kitchen/climate01',   'temperature', 'home', 'house', 'kitchen',     NULL,      'climate01', 'climate', 'float', '°C',  'Kitchen air temperature', '{"fw":"1.4.2","ip":"192.168.1.41","model":"SHT31"}'),
 ('demo/home/house/kitchen/climate01',   'humidity',    'home', 'house', 'kitchen',     NULL,      'climate01', 'climate', 'float', '%',   'Kitchen relative humidity', '{"fw":"1.4.2","ip":"192.168.1.41","model":"SHT31"}'),
 ('demo/home/house/kitchen/fridge_plug', 'power',       'home', 'house', 'kitchen',     NULL,      'fridge_plug', 'energy', 'float', 'W',  'Fridge power draw', '{"fw":"20240305","ip":"192.168.1.52","model":"Shelly Plug S"}'),
 ('demo/home/house/kitchen/fridge_plug', 'relay',       'home', 'house', 'kitchen',     NULL,      'fridge_plug', 'state',  'bool',  NULL, 'Fridge relay on/off', '{"fw":"20240305","ip":"192.168.1.52","model":"Shelly Plug S"}'),
 ('demo/home/house/living/climate02',    'temperature', 'home', 'house', 'living_room', NULL,      'climate02', 'climate', 'float', '°C',  'Living room air temperature', '{"fw":"1.4.2","ip":"192.168.1.42","model":"SHT31"}'),
 ('demo/home/house/living/climate02',    'humidity',    'home', 'house', 'living_room', NULL,      'climate02', 'climate', 'float', '%',   'Living room relative humidity', '{"fw":"1.4.2","ip":"192.168.1.42","model":"SHT31"}'),
 ('demo/home/house/living/tv_plug',      'power',       'home', 'house', 'living_room', NULL,      'tv_plug',   'energy',  'float', 'W',   'TV power draw', '{"fw":"20240305","ip":"192.168.1.53","model":"Shelly Plug S"}'),
 ('demo/home/house/utility/boiler',      'flow_temp',   'home', 'house', 'utility',     'heating', 'boiler',    'temperature', 'float', '°C', 'Boiler flow temperature', '{"fw":"3.1","ip":"192.168.1.60","model":"OpenTherm GW"}'),
 ('demo/home/house/utility/boiler',      'return_temp', 'home', 'house', 'utility',     'heating', 'boiler',    'temperature', 'float', '°C', 'Boiler return temperature', '{"fw":"3.1","ip":"192.168.1.60","model":"OpenTherm GW"}'),
 ('demo/home/house/utility/boiler',      'burner_on',   'home', 'house', 'utility',     'heating', 'boiler',    'state',  'bool',  NULL, 'Burner running', '{"fw":"3.1","ip":"192.168.1.60","model":"OpenTherm GW"}'),
 ('demo/home/house/utility/heatpump',    'cop',         'home', 'house', 'utility',     'heating', 'heatpump',  'performance', 'float', NULL, 'Heat pump coefficient of performance', '{"fw":"2.0.7","ip":"192.168.1.61"}'),
 ('demo/home/house/utility/meter',       'power',       'home', 'house', 'utility',     'mains',   'meter',     'energy',  'float', 'W',  'Whole-house power (P1 meter)', '{"fw":"4.12","ip":"192.168.1.70","model":"P1 dongle"}'),
 ('demo/home/house/utility/meter',       'voltage',     'home', 'house', 'utility',     'mains',   'meter',     'electrical', 'float', 'V', 'Mains voltage L1', '{"fw":"4.12","ip":"192.168.1.70","model":"P1 dongle"}'),
 ('demo/home/house/utility/rpi',         'cpu_temp',    'home', 'house', 'utility',     NULL,      'rpi',       'system',  'float', '°C',  'Raspberry Pi CPU temperature', '{"os":"Debian 12","ip":"192.168.1.10"}'),
 ('demo/home/house/utility/rpi',         'load1',       'home', 'house', 'utility',     NULL,      'rpi',       'system',  'float', NULL,  'Raspberry Pi 1-minute load', '{"os":"Debian 12","ip":"192.168.1.10"}'),
 -- garden
 ('demo/home/garden/greenhouse/soil01',  'moisture',    'home', 'garden', 'greenhouse', NULL,      'soil01',    'soil',    'float', '%',   'Soil moisture bed 1', '{"fw":"0.9","ip":"192.168.1.81"}'),
 ('demo/home/garden/greenhouse/climate03','temperature','home', 'garden', 'greenhouse', NULL,      'climate03', 'climate', 'float', '°C',  'Greenhouse air temperature', '{"fw":"1.4.2","ip":"192.168.1.43"}'),
 ('demo/home/garden/greenhouse/pump',    'running',     'home', 'garden', 'greenhouse', 'irrigation', 'pump',   'state',   'bool',  NULL, 'Irrigation pump running', '{"fw":"1.0","ip":"192.168.1.82"}'),
 -- workshop
 ('demo/home/workshop/bench/compressor', 'pressure',    'home', 'workshop', 'bench',    'air',     'compressor','pneumatic', 'float', 'bar', 'Air receiver pressure', '{"fw":"2.2","ip":"192.168.1.90"}'),
 ('demo/home/workshop/bench/compressor', 'motor_on',    'home', 'workshop', 'bench',    'air',     'compressor','state',  'bool',  NULL, 'Compressor motor running', '{"fw":"2.2","ip":"192.168.1.90"}'),
 -- comm-health edge cases
 ('demo/home/garden/greenhouse/soil02',  'moisture',    'home', 'garden', 'greenhouse', NULL,      'soil02',    'soil',    'float', '%',   'Soil moisture bed 2 (battery died)', '{"fw":"0.9","ip":"192.168.1.84"}'),
 ('demo/home/garden/shed/lux01',         'lux',         'home', 'garden', 'shed',       NULL,      'lux01',     'light',   'float', 'lx',  'Shed light level (registered, never reported)', '{}'),
 ('demo/home/house/attic/old_sensor',    'temperature', 'home', 'house', 'attic',       NULL,      'old_sensor','climate', 'float', '°C',  'Decommissioned attic sensor', '{}');

UPDATE points SET enabled = FALSE WHERE source_topic = 'demo/home/house/attic/old_sensor';

-- ---------------------------------------------------------------------
-- Synthetic signals: daily sine + noise, duty-cycled loads, on/off states.
-- demo.signal() is shared by the history backfill and demo.tick(), which
-- the demo_tick event runs every minute to keep data live.
-- ---------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS demo;

DELIMITER //

CREATE OR REPLACE FUNCTION demo.signal(ref VARCHAR(400), t DATETIME)
RETURNS DOUBLE NOT DETERMINISTIC NO SQL
BEGIN
    DECLARE e  BIGINT DEFAULT TIMESTAMPDIFF(SECOND, '1970-01-01 00:00:00', t);  -- t is UTC
    DECLARE d  DOUBLE DEFAULT e / 86400.0;                                      -- days since epoch
    DECLARE hr INT    DEFAULT HOUR(t);
    DECLARE mi INT    DEFAULT MINUTE(t);
    RETURN CASE ref
            WHEN 'demo/home/house/kitchen/climate01:temperature'     THEN 20.5 + 1.8 * SIN(2*PI()*d) + RAND()*0.3
            WHEN 'demo/home/house/kitchen/climate01:humidity'        THEN 48 + 6 * COS(2*PI()*d) + RAND()*2
            WHEN 'demo/home/house/kitchen/fridge_plug:power'         THEN CASE WHEN (e / 60) % 40 < 14 THEN 85 + RAND()*10 ELSE 1.5 + RAND() END
            WHEN 'demo/home/house/kitchen/fridge_plug:relay'         THEN 1
            WHEN 'demo/home/house/living/climate02:temperature'      THEN 21.0 + 1.2 * SIN(2*PI()*d - 0.6) + RAND()*0.3
            WHEN 'demo/home/house/living/climate02:humidity'         THEN 45 + 5 * COS(2*PI()*d - 0.6) + RAND()*2
            WHEN 'demo/home/house/living/tv_plug:power'              THEN CASE WHEN hr BETWEEN 18 AND 22 THEN 95 + RAND()*15 ELSE 0.6 END
            WHEN 'demo/home/house/utility/boiler:flow_temp'          THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 58 + RAND()*4 ELSE 32 + RAND()*2 END
            WHEN 'demo/home/house/utility/boiler:return_temp'        THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 44 + RAND()*3 ELSE 30 + RAND()*2 END
            WHEN 'demo/home/house/utility/boiler:burner_on'          THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 1 ELSE 0 END
            WHEN 'demo/home/house/utility/heatpump:cop'              THEN 3.2 + 0.6 * SIN(2*PI()*d) + RAND()*0.2
            WHEN 'demo/home/house/utility/meter:power'               THEN 350 + 250 * GREATEST(SIN(2*PI()*(d - 0.3)), 0) + RAND()*120
            WHEN 'demo/home/house/utility/meter:voltage'             THEN 230 + RAND()*4 - 2
            WHEN 'demo/home/house/utility/rpi:cpu_temp'              THEN 48 + 4 * SIN(2*PI()*d) + RAND()*3
            WHEN 'demo/home/house/utility/rpi:load1'                 THEN 0.3 + RAND()*0.6
            WHEN 'demo/home/garden/greenhouse/soil01:moisture'       THEN 60 - 25 * ((d * 2) - FLOOR(d * 2)) + RAND()
            WHEN 'demo/home/garden/greenhouse/climate03:temperature' THEN 16 + 9 * SIN(2*PI()*(d - 0.25)) + RAND()*0.5
            WHEN 'demo/home/garden/greenhouse/pump:running'          THEN CASE WHEN hr IN (6, 18) AND mi < 10 THEN 1 ELSE 0 END
            WHEN 'demo/home/workshop/bench/compressor:pressure'      THEN 6 + 2 * ((e % 1800) / 1800.0) + RAND()*0.1
            WHEN 'demo/home/workshop/bench/compressor:motor_on'      THEN CASE WHEN e % 1800 < 300 THEN 1 ELSE 0 END
            WHEN 'demo/home/garden/greenhouse/soil02:moisture'       THEN 55 + RAND()*2
            WHEN 'demo/home/house/attic/old_sensor:temperature'      THEN 12 + RAND()
    END;
END //

-- Points that "broke": soil02's battery died 2 days ago, the attic
-- sensor was retired 9 days ago (and disabled in the registry).
CREATE OR REPLACE FUNCTION demo.alive(ref VARCHAR(400), t DATETIME)
RETURNS BOOLEAN NOT DETERMINISTIC NO SQL
RETURN NOT (ref LIKE 'demo/home/garden/greenhouse/soil02:%' AND t > UTC_TIMESTAMP() - INTERVAL 2 DAY)
   AND NOT (ref LIKE 'demo/home/house/attic/old_sensor:%'   AND t > UTC_TIMESTAMP() - INTERVAL 9 DAY) //

-- One sample per live demo point at the current minute.
CREATE OR REPLACE PROCEDURE demo.tick()
BEGIN
    DECLARE now_min DATETIME DEFAULT DATE_FORMAT(UTC_TIMESTAMP(), '%Y-%m-%d %H:%i:00');

    INSERT IGNORE INTO historian.readings (time, point_id, value, quality)
    SELECT now_min, s.point_id, s.value, IF(RAND() < 0.002, 0, 192)
    FROM (SELECT p.point_id, demo.signal(CONCAT(p.source_topic, ':', p.field), now_min) AS value
          FROM historian.points p
          WHERE p.source_topic LIKE 'demo/%' AND p.enabled
            AND demo.alive(CONCAT(p.source_topic, ':', p.field), now_min)) s
    WHERE s.value IS NOT NULL;

    UPDATE historian.points p SET p.last_seen = now_min
    WHERE p.source_topic LIKE 'demo/%' AND p.enabled
      AND demo.alive(CONCAT(p.source_topic, ':', p.field), now_min)
      AND p.source_topic NOT LIKE 'demo/home/garden/shed/%';
END //

DELIMITER ;

-- 14 days of 1-minute history (seq_0_to_N comes with MariaDB's Sequence engine)
SET @start = DATE_FORMAT(UTC_TIMESTAMP() - INTERVAL 14 DAY, '%Y-%m-%d %H:%i:00');

INSERT IGNORE INTO readings (time, point_id, value, quality)
SELECT s.t, s.point_id, s.value, IF(RAND() < 0.002, 0, 192)
FROM (SELECT ts.t, p.point_id, demo.signal(CONCAT(p.source_topic, ':', p.field), ts.t) AS value
      FROM points p
      CROSS JOIN (SELECT @start + INTERVAL seq MINUTE AS t FROM seq_0_to_20160) ts
      WHERE p.source_topic LIKE 'demo/%'
        AND demo.alive(CONCAT(p.source_topic, ':', p.field), ts.t)) s
WHERE s.value IS NOT NULL;

UPDATE points p
JOIN (SELECT point_id, MAX(time) AS last_time FROM readings GROUP BY point_id) s
  ON s.point_id = p.point_id
SET p.last_seen = s.last_time
WHERE p.source_topic LIKE 'demo/%';

-- Build the hourly rollup for the demo window (normally the
-- refresh_readings_1h_event does this every 5 minutes).
CALL refresh_readings_1h(UTC_TIMESTAMP() - INTERVAL 15 DAY);

-- Live feed: a new sample per point every minute.
CREATE OR REPLACE EVENT demo.tick_event
    ON SCHEDULE EVERY 1 MINUTE
    DO CALL demo.tick();

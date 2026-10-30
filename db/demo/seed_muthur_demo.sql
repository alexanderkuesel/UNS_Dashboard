-- =====================================================================
-- Demo data for the MUTHUR historian schema.
-- Creates a small home/workshop UNS with ~14 days of 1-minute data so
-- the dashboards have something to show before Node-RED is wired up.
--
-- Safe to re-run: removes previous demo points (source_topic 'demo/...').
-- Do NOT run against your production database unless you want demo rows.
-- =====================================================================

DELETE FROM historian.readings
WHERE point_id IN (SELECT point_id FROM historian.points WHERE source_topic LIKE 'demo/%');
DELETE FROM historian.points WHERE source_topic LIKE 'demo/%';

INSERT INTO historian.points
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

UPDATE historian.points SET enabled = false WHERE source_topic = 'demo/home/house/attic/old_sensor';

-- ---------------------------------------------------------------------
-- Synthetic signals: daily sine + noise, duty-cycled loads, on/off states.
-- demo.signal() is shared by the history backfill and demo.tick(),
-- which the demo-feed container calls every minute to keep data live.
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS demo;

CREATE OR REPLACE FUNCTION demo.signal(ref text, t timestamptz)
RETURNS double precision LANGUAGE sql VOLATILE AS $$
    SELECT CASE ref
        WHEN 'demo/home/house/kitchen/climate01:temperature'     THEN 20.5 + 1.8 * sin(2*pi()*d) + random()*0.3
        WHEN 'demo/home/house/kitchen/climate01:humidity'        THEN 48 + 6 * cos(2*pi()*d) + random()*2
        WHEN 'demo/home/house/kitchen/fridge_plug:power'         THEN CASE WHEN (e / 60) % 40 < 14 THEN 85 + random()*10 ELSE 1.5 + random() END
        WHEN 'demo/home/house/kitchen/fridge_plug:relay'         THEN 1
        WHEN 'demo/home/house/living/climate02:temperature'      THEN 21.0 + 1.2 * sin(2*pi()*d - 0.6) + random()*0.3
        WHEN 'demo/home/house/living/climate02:humidity'         THEN 45 + 5 * cos(2*pi()*d - 0.6) + random()*2
        WHEN 'demo/home/house/living/tv_plug:power'              THEN CASE WHEN hr BETWEEN 18 AND 22 THEN 95 + random()*15 ELSE 0.6 END
        WHEN 'demo/home/house/utility/boiler:flow_temp'          THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 58 + random()*4 ELSE 32 + random()*2 END
        WHEN 'demo/home/house/utility/boiler:return_temp'        THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 44 + random()*3 ELSE 30 + random()*2 END
        WHEN 'demo/home/house/utility/boiler:burner_on'          THEN CASE WHEN hr BETWEEN 5 AND 8 OR hr BETWEEN 17 AND 21 THEN 1 ELSE 0 END
        WHEN 'demo/home/house/utility/heatpump:cop'              THEN 3.2 + 0.6 * sin(2*pi()*d) + random()*0.2
        WHEN 'demo/home/house/utility/meter:power'               THEN 350 + 250 * greatest(sin(2*pi()*(d - 0.3)), 0) + random()*120
        WHEN 'demo/home/house/utility/meter:voltage'             THEN 230 + random()*4 - 2
        WHEN 'demo/home/house/utility/rpi:cpu_temp'              THEN 48 + 4 * sin(2*pi()*d) + random()*3
        WHEN 'demo/home/house/utility/rpi:load1'                 THEN 0.3 + random()*0.6
        WHEN 'demo/home/garden/greenhouse/soil01:moisture'       THEN 60 - 25 * ((d * 2) - floor(d * 2)) + random()
        WHEN 'demo/home/garden/greenhouse/climate03:temperature' THEN 16 + 9 * sin(2*pi()*(d - 0.25)) + random()*0.5
        WHEN 'demo/home/garden/greenhouse/pump:running'          THEN CASE WHEN hr IN (6, 18) AND mi < 10 THEN 1 ELSE 0 END
        WHEN 'demo/home/workshop/bench/compressor:pressure'      THEN 6 + 2 * ((e % 1800) / 1800.0) + random()*0.1
        WHEN 'demo/home/workshop/bench/compressor:motor_on'      THEN CASE WHEN e % 1800 < 300 THEN 1 ELSE 0 END
        WHEN 'demo/home/garden/greenhouse/soil02:moisture'       THEN 55 + random()*2
        WHEN 'demo/home/house/attic/old_sensor:temperature'      THEN 12 + random()
    END
    FROM (SELECT extract(epoch FROM t) / 86400.0          AS d,    -- days since epoch
                 extract(epoch FROM t)::bigint            AS e,
                 extract(hour FROM t AT TIME ZONE 'UTC')  AS hr,
                 extract(minute FROM t)                   AS mi) x
$$;

-- Points that "broke": soil02's battery died 2 days ago, the attic
-- sensor was retired 9 days ago (and disabled in the registry).
CREATE OR REPLACE FUNCTION demo.alive(ref text, t timestamptz)
RETURNS boolean LANGUAGE sql STABLE AS $$
    SELECT NOT (ref LIKE 'demo/home/garden/greenhouse/soil02:%' AND t > now() - interval '2 days')
       AND NOT (ref LIKE 'demo/home/house/attic/old_sensor:%'   AND t > now() - interval '9 days')
$$;

-- One sample per live demo point at the current minute.
CREATE OR REPLACE PROCEDURE demo.tick()
LANGUAGE sql AS $$
    INSERT INTO historian.readings (time, point_id, value, quality)
    SELECT date_trunc('minute', now()), p.point_id, demo.signal(p.source_topic || ':' || p.field, now()),
           CASE WHEN random() < 0.002 THEN 0 ELSE 192 END
    FROM historian.points p
    WHERE p.source_topic LIKE 'demo/%' AND p.enabled
      AND demo.alive(p.source_topic || ':' || p.field, now())
      AND demo.signal(p.source_topic || ':' || p.field, now()) IS NOT NULL
    ON CONFLICT (point_id, time) DO NOTHING;

    UPDATE historian.points SET last_seen = date_trunc('minute', now())
    WHERE source_topic LIKE 'demo/%' AND enabled
      AND demo.alive(source_topic || ':' || field, now())
      AND source_topic NOT LIKE 'demo/home/garden/shed/%';
$$;

-- 14 days of 1-minute history
INSERT INTO historian.readings (time, point_id, value, quality)
SELECT ts.t, p.point_id, v.value, CASE WHEN random() < 0.002 THEN 0 ELSE 192 END
FROM historian.points p
CROSS JOIN generate_series(date_trunc('minute', now()) - interval '14 days',
                           date_trunc('minute', now()), interval '1 minute') AS ts(t)
CROSS JOIN LATERAL (SELECT demo.signal(p.source_topic || ':' || p.field, ts.t) AS value) v
WHERE p.source_topic LIKE 'demo/%'
  AND v.value IS NOT NULL
  AND demo.alive(p.source_topic || ':' || p.field, ts.t)
ON CONFLICT (point_id, time) DO NOTHING;

UPDATE historian.points p
SET last_seen = s.last_time
FROM (SELECT point_id, max(time) AS last_time FROM historian.readings GROUP BY point_id) s
WHERE p.point_id = s.point_id AND p.source_topic LIKE 'demo/%';

-- Materialise the hourly rollup for the demo window (normally the
-- continuous-aggregate policy does this every 30 minutes).
CALL refresh_continuous_aggregate('historian.readings_1h', now() - interval '15 days', now() - interval '1 hour');

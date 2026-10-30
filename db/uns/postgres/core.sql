-- =====================================================================
-- UNS core: schema-independent helpers the Grafana dashboards query.
--
-- Depends only on the adapter contract views:
--   uns.points, uns.readings, uns.readings_1h
-- so it works unchanged for every source schema that has an adapter.
--
-- Load with tools/install_uns.sh, which recreates the uns schema in one
-- transaction (adapter first, then this file) and passes -v reader=<role>.
-- =====================================================================

-- ---------------------------------------------------------------------
-- OPC quality helpers (192..255 good, 64..127 uncertain, 0..63 bad)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION uns.quality_label(q integer)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT CASE WHEN q IS NULL THEN NULL
                WHEN q & 192 = 192 THEN 'good'
                WHEN q & 192 = 64  THEN 'uncertain'
                ELSE 'bad' END
$$;

CREATE OR REPLACE FUNCTION uns.quality_good(q integer)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT q & 192 = 192
$$;

-- ---------------------------------------------------------------------
-- Latest value per point (one index probe per point via LATERAL).
-- Filter on the point columns and only those points are probed.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW uns.latest AS
SELECT p.point_id, p.enterprise, p.site, p.area, p.line, p.device,
       p.measurement, p.field, p.uns_path, p.data_type, p.unit,
       p.enabled, p.last_seen,
       l.time    AS value_time,
       l.value,
       l.quality
FROM uns.points p
LEFT JOIN LATERAL (
    SELECT r.time, r.value, r.quality
    FROM uns.readings r
    WHERE r.point_id = p.point_id
    ORDER BY r.time DESC
    LIMIT 1
) l ON true;

-- ---------------------------------------------------------------------
-- Communication health per point.
--   state: ok | stale | never | disabled
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION uns.point_health(p_stale_after interval DEFAULT interval '15 minutes')
RETURNS TABLE (
    point_id    integer,
    enterprise  text, site text, area text, line text, device text,
    measurement text, field text, uns_path text, source_ref text,
    enabled     boolean,
    last_seen   timestamptz,
    age_s       double precision,
    state       text
) LANGUAGE sql STABLE AS $$
    SELECT p.point_id, p.enterprise, p.site, p.area, p.line, p.device,
           p.measurement, p.field, p.uns_path, p.source_ref,
           p.enabled, p.last_seen,
           extract(epoch FROM now() - p.last_seen)::double precision,
           CASE WHEN NOT p.enabled                       THEN 'disabled'
                WHEN p.last_seen IS NULL                 THEN 'never'
                WHEN now() - p.last_seen > p_stale_after THEN 'stale'
                ELSE 'ok' END
    FROM uns.points p
$$;

-- ---------------------------------------------------------------------
-- Equipment hierarchy as a tree of nodes (enterprise > site > area >
-- line > device). Levels that are '(none)' are skipped, so a device
-- without a line hangs directly off its area.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW uns.hierarchy AS
WITH levels AS (
    SELECT p.point_id, p.enabled, p.last_seen, u.level, u.name, u.ord
    FROM uns.points p
    CROSS JOIN LATERAL unnest(
        ARRAY['enterprise', 'site', 'area', 'line', 'device'],
        ARRAY[p.enterprise, p.site, p.area, p.line, p.device]
    ) WITH ORDINALITY AS u(level, name, ord)
    WHERE u.name <> '(none)'
), paths AS (
    SELECT l.*,
           string_agg(l.name, '/') OVER w                          AS path,
           row_number() OVER w                                     AS depth
    FROM levels l
    WINDOW w AS (PARTITION BY l.point_id ORDER BY l.ord)
), parented AS (
    SELECT p.*,
           lag(p.path) OVER (PARTITION BY p.point_id ORDER BY p.ord) AS parent_path
    FROM paths p
)
SELECT path,
       parent_path,
       level,
       name,
       depth::integer                         AS depth,
       count(*)::integer                      AS points,
       count(*) FILTER (WHERE enabled)::integer AS enabled_points,
       max(last_seen)                         AS last_seen,
       array_agg(point_id ORDER BY point_id)  AS point_ids
FROM parented
GROUP BY path, parent_path, level, name, depth;

-- ---------------------------------------------------------------------
-- Trend: bucketed avg/min/max/samples for a set of points.
--
-- Picks the source automatically:
--   * short ranges with sub-hour buckets  -> raw readings
--   * buckets >= 1h or ranges >= 7 days   -> hourly rollup, with raw
--     readings filling the tail the rollup has not materialised yet
-- Rollup and raw rows are merged with sample-weighted averages, so a
-- bucket that straddles the split point is still a single, correct row.
--
-- Grafana usage:
--   SELECT * FROM uns.trend(ARRAY[1,2,3], $__timeFrom(), $__timeTo(),
--                           $__interval_ms * interval '1 millisecond')
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION uns.trend(
    p_points integer[],
    p_from   timestamptz,
    p_to     timestamptz,
    p_bucket interval DEFAULT NULL
)
RETURNS TABLE (
    "time"   timestamptz,
    point_id integer,
    avg      double precision,
    min      double precision,
    max      double precision,
    samples  bigint
) LANGUAGE plpgsql STABLE AS $$
#variable_conflict use_column
DECLARE
    v_bucket interval := greatest(coalesce(p_bucket, (p_to - p_from) / 500), interval '1 second');
    v_split  timestamptz := '-infinity';
BEGIN
    IF v_bucket >= interval '1 hour' OR p_to - p_from >= interval '7 days' THEN
        v_bucket := greatest(v_bucket, interval '1 hour');
        SELECT max(h.time) + interval '1 hour' INTO v_split
        FROM uns.readings_1h h
        WHERE h.point_id = ANY (p_points);
        v_split := coalesce(v_split, '-infinity');
    END IF;

    RETURN QUERY
    WITH parts AS (
        SELECT h.time AS t, h.point_id AS pid,
               h.avg * h.samples AS v_sum,
               CASE WHEN h.avg IS NULL THEN 0 ELSE h.samples END AS v_n,
               h.min AS v_min, h.max AS v_max, h.samples AS n
        FROM uns.readings_1h h
        WHERE h.point_id = ANY (p_points)
          AND h.time >= time_bucket(interval '1 hour', p_from)
          AND h.time <  least(p_to, v_split)
        UNION ALL
        SELECT r.time, r.point_id,
               r.value,
               CASE WHEN r.value IS NULL THEN 0 ELSE 1 END,
               r.value, r.value, 1
        FROM uns.readings r
        WHERE r.point_id = ANY (p_points)
          AND r.time >= greatest(p_from, v_split)
          AND r.time <  p_to
    )
    SELECT time_bucket(v_bucket, parts.t),
           parts.pid,
           sum(parts.v_sum) / nullif(sum(parts.v_n), 0),
           min(parts.v_min),
           max(parts.v_max),
           sum(parts.n)::bigint
    FROM parts
    GROUP BY 1, 2
    ORDER BY 1, 2;
END
$$;

-- ---------------------------------------------------------------------
-- Read-only access for the dashboard role
-- ---------------------------------------------------------------------
GRANT USAGE ON SCHEMA uns TO :"reader";
GRANT SELECT ON ALL TABLES IN SCHEMA uns TO :"reader";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA uns TO :"reader";

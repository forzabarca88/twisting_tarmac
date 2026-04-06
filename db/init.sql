-- PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- 4.1 Core Tables

-- roads_raw
CREATE TABLE IF NOT EXISTS roads_raw (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT,
    tags JSONB,
    geom GEOMETRY(LineString, 4326),
    length_m DOUBLE PRECISION,
    source TEXT
);

-- road_segments
CREATE TABLE IF NOT EXISTS road_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    road_id BIGINT REFERENCES roads_raw(id),
    segment_index INTEGER,
    geom GEOMETRY(LineString, 4326),
    length_m DOUBLE PRECISION,
    start_node_osm BIGINT,
    end_node_osm BIGINT,
    road_class TEXT,
    maxspeed_kph INTEGER,
    lanes INTEGER,
    surface TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- segment_metrics
CREATE TABLE IF NOT EXISTS segment_metrics (
    segment_id UUID PRIMARY KEY REFERENCES road_segments(id),
    curvature_raw DOUBLE PRECISION,
    curvature_norm DOUBLE PRECISION,
    traffic_control_count INTEGER,
    traffic_control_density DOUBLE PRECISION,
    traffic_control_norm DOUBLE PRECISION,
    speed_norm DOUBLE PRECISION,
    elevation_variation_m DOUBLE PRECISION,
    elevation_norm DOUBLE PRECISION,
    surface_score DOUBLE PRECISION,
    lane_score DOUBLE PRECISION,
    composite_fun_score DOUBLE PRECISION,
    metric_version TEXT,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- cities (for filtering)
CREATE TABLE IF NOT EXISTS cities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT,
    state TEXT,
    geom GEOMETRY(Polygon, 4326),
    centroid GEOMETRY(Point, 4326)
);

-- top_roads_cache
CREATE TABLE IF NOT EXISTS top_roads_cache (
    cache_key TEXT PRIMARY KEY,
    payload JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- Spatial Indexes
CREATE INDEX IF NOT EXISTS idx_roads_raw_geom ON roads_raw USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON road_segments USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_cities_geom ON cities USING GIST (geom);

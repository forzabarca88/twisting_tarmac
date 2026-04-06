# PLAN.md

---

### Project Title
**TwistingTarmac** — a Python-first web application to identify and visualise **fun-to-drive** road stretches in Australia using local OpenStreetMap data.

---

## 1. Executive Summary

**TwistingTarmac** will ingest an Australia OpenStreetMap (OSM) PBF extract, process and store road geometry and tags locally in a PostGIS-enabled PostgreSQL instance, compute per-segment driving-fun metrics (curvature, traffic-control density, speed, elevation, surface, etc.), and expose a high-performance Python backend (FastAPI) and a Python-based frontend (Streamlit MVP) that together deliver a fast, polished UX:

- **Home page**: top 5 roads (filterable by **State** and **City**) and an interactive map pinpointing those segments.
- **Map**: interactive, viewport-limited GeoJSON or MVT vector tiles; colour-coded road segments by selected metric.
- **Search**: suburb/town search and viewport zoom; segments update dynamically.
- **Local-first**: all OSM PBF and derived data stored locally; initial scope: **Australia**.
- **Performance-first**: precomputation, spatial indexing, caching, vector tiles, and progressive loading.

---

## 2. Goals, Scope, and Non-Goals

### 2.1 Goals (what success looks like)
- **Accurate** identification of road stretches likely to be enjoyable to drive.
- **Home page** loads top 5 roads in under 500 ms from cache.
- **Interactive map** responds to pan/zoom within 200–400 ms for typical viewports.
- **Search** returns suburb centroids and highlights segments within 300 ms.
- **All data local**: PBF + derived DB on the host machine or local server.

### 2.2 Scope (initial)
- **Geographic**: Australia only (national PBF extract or state extracts).
- **Users**: motoring enthusiasts (no authentication required for read-only MVP).
- **Frontend**: Python-based (Streamlit MVP). Option to replace with a JS client later.
- **Metrics**: curvature, traffic-control density, speed-limit, elevation variation, surface quality, composite fun score.

### 2.3 Non-Goals (out of scope initially)
- Real-time traffic data integration.
- User accounts, social features, or crowdsourced photos (optional future).
- Global coverage (beyond Australia).
- Mobile native apps (responsive web only).

---

## 3. Architecture Overview

### 3.1 Logical Components
- **Data Ingest & Processing** (Python CLI scripts)
- **Database** (PostgreSQL + PostGIS)
- **Background Worker** (Celery or RQ)
- **API Server** (FastAPI)
- **Frontend** (Streamlit MVP; Leaflet/pydeck for maps)
- **Cache** (Redis)
- **Optional Tile Server** (ST_AsMVT from PostGIS or pre-generated MVT files)

---

### 3.2 Deployment Topology (local dev)
- Docker Compose with services:
  - **postgres-postgis**
  - **redis**
  - **fastapi**
  - **streamlit**
  - **worker** (Celery/RQ)
  - **ingest** (one-off CLI container)

---

### 3.3 Data Flow (high level)
1. **Acquire** Australia PBF.
2. **Parse** PBF → extract ways/nodes relevant to highways.
3. **Load** raw ways into `roads_raw`.
4. **Segment** ways into `road_segments`.
5. **Compute** metrics → `segment_metrics`.
6. **Cache** top lists and tiles.
7. **Serve** via FastAPI endpoints consumed by Streamlit frontend.

---

## 4. Data Model (schema-level detail)

> All geometry columns stored in **SRID 4326** for canonical storage; transform to **3857** for web map rendering where needed. Use **GIST** indexes on geometry columns.

### 4.1 Core Tables

#### roads_raw
- **id**: bigint (primary key)
- **osm_id**: bigint
- **tags**: jsonb
- **geom**: geometry(LineString, 4326)
- **length_m**: double precision
- **source**: text (e.g., 'pbf-2026-04-01')

#### road_segments
- **id**: uuid (primary key)
- **road_id**: bigint (foreign key to roads_raw)
- **segment_index**: integer
- **geom**: geometry(LineString, 4326)
- **length_m**: double precision
- **start_node_osm**: bigint
- **end_node_osm**: bigint
- **road_class**: text (motorway, trunk, primary, secondary, tertiary, unclassified, residential)
- **maxspeed_kph**: integer (normalized)
- **lanes**: integer
- **surface**: text
- **created_at**: timestamp

#### segment_metrics
- **segment_id**: uuid (primary key, FK to road_segments)
- **curvature_raw**: double precision (radians per meter)
- **curvature_norm**: double precision (0–1)
- **traffic_control_count**: integer
- **traffic_control_density**: double precision (per km)
- **traffic_control_norm**: double precision (0–1)
- **speed_norm**: double precision (0–1)
- **elevation_variation_m**: double precision
- **elevation_norm**: double precision (0–1)
- **surface_score**: double precision (0–1)
- **lane_score**: double precision (0–1)
- **composite_fun_score**: double precision (0–1)
- **metric_version**: text (for reproducibility)
- **computed_at**: timestamp

#### cities (for filtering)
- **id**: uuid
- **name**: text
- **state**: text
- **geom**: geometry(Polygon, 4326)
- **centroid**: geometry(Point, 4326)

#### top_roads_cache
- **cache_key**: text (e.g., `top5_state_NSW_metric_fun`)
- **payload**: jsonb (list of top roads with summary and geometry references)
- **created_at**: timestamp
- **expires_at**: timestamp

---

## 5. Data Ingest Pipeline — Detailed Steps and Implementation Notes

### 5.1 Acquire OSM PBF
- **Source**: Geofabrik or Planet OSM extracts (Australia).
- **Storage**: store PBF in a local `data/pbf/` folder with timestamped filenames.
- **Validation**: checksum and file size verification.

### 5.2 PBF Parsing (tools & approach)
- **Primary library**: `pyrosm` (Python) for extracting ways and nodes efficiently.
- **Fallback**: `osmium` Python bindings for advanced filtering.
- **Extraction query**:
  - Extract `highway` ways where `highway` in (`motorway`, `trunk`, `primary`, `secondary`, `tertiary`, `unclassified`, `residential`, `service`, `road`).
  - Keep tags: `maxspeed`, `lanes`, `surface`, `name`, `ref`, `oneway`, `junction`, `access`.
  - Extract nodes with `highway=traffic_signals`, `highway=stop`, `crossing`, `barrier` for traffic-control detection.

### 5.3 Raw Load into `roads_raw`
- Insert ways as `LineString` in `roads_raw`.
- Compute `length_m` using `ST_Length(ST_Transform(geom, 3857))`.
- Normalize `maxspeed` to integer kph (parse strings like "50 mph", "50", "national").

### 5.4 Preprocessing & Cleaning
- **Tag normalization**:
  - `maxspeed` → integer kph; unknown → infer from `road_class` default table.
  - `lanes` → integer; unknown → default by `road_class`.
  - `surface` → map to categories: sealed, unsealed, unknown.
- **Topology fixes**:
  - Snap near-identical nodes within tolerance (e.g., 0.5 m) if needed.
  - Remove degenerate ways (length < 10 m).
- **Dissolve**: merge duplicate ways with identical geometry and tags.

### 5.5 Segment Generation
- **Strategy**:
  - Split ways at junctions (nodes with degree > 2), speed-limit changes, and at fixed-length intervals (configurable, default 1,000 m).
  - Use `ST_Segmentize` and `ST_LineSubstring` or Python geometry splitting (Shapely) for deterministic segmentation.
- **Metadata**:
  - For each segment compute centroid, length, start/end node OSM ids, and bounding box.

### 5.6 Traffic Control Detection
- Build a spatial index of traffic-control nodes.
- For each segment, compute `traffic_control_count` = number of traffic-control nodes within a buffer (e.g., 20 m) of the segment.
- Compute `traffic_control_density` = `traffic_control_count` / (length_km).

### 5.7 Curvature Computation (detailed)
- **Algorithm**:
  1. Resample segment polyline to points every `d` meters (e.g., 10 m) to regularize spacing.
  2. For each triplet of consecutive points \(P_{i-1}, P_i, P_{i+1}\), compute the turning angle:
     \[
     \theta_i = \arccos\left(\frac{(v_{i-1}\cdot v_i)}{\|v_{i-1}\|\|v_i\|}\right)
     \]
     where \(v_{i-1} = P_i - P_{i-1}\), \(v_i = P_{i+1} - P_i\).
  3. Sum absolute \(\theta_i\) across the segment and divide by segment length to get **radians per meter**.
- **Normalization**:
  - Convert raw curvature to percentile across all segments and store `curvature_norm` in [0,1].
- **Implementation**:
  - Use `shapely` for geometry, `numpy` for vector math; compute in Python batch jobs and store results.

### 5.8 Elevation Processing
- **DEM source**: pre-download a DEM (SRTM or higher resolution) and store locally.
- **Sampling**:
  - Sample elevation at resampled points along each segment.
  - Compute `elevation_variation_m` = max(elev) - min(elev).
  - Compute gradient statistics (mean absolute gradient).
- **Normalization**:
  - Map to `elevation_norm` in [0,1] by percentile.

### 5.9 Surface and Lane Scoring
- **Surface_score**:
  - Map `surface` tags to scores: sealed=1.0, paved=0.9, gravel=0.4, dirt=0.2, unknown=0.6 (configurable).
- **Lane_score**:
  - Prefer single-carriageway two-lane roads for fun: lanes=2 → 1.0; lanes>2 → 0.6; lanes=1 → 0.7; unknown → 0.6.

### 5.10 Composite Fun Score
- **Default weights** (configurable in `config.yaml`):
  - curvature: **0.40**
  - traffic_control_density (inverted): **0.25**
  - speed_norm: **0.15**
  - elevation_norm: **0.10**
  - surface_score: **0.10**
- **Formula**:
  \[
  \text{fun} = 0.40\cdot\text{curvature\_norm} + 0.25\cdot(1-\text{traffic\_control\_norm}) + 0.15\cdot\text{speed\_norm} + 0.10\cdot\text{elevation\_norm} + 0.10\cdot\text{surface\_score}
  \]
- **Post-processing**:
  - Clip to [0,1], compute percentiles, and store both raw and percentile ranks.

---

## 6. API Design (detailed endpoints, parameters, responses)

> All endpoints return JSON; heavy geometry endpoints support `Accept: application/x-protobuf` for MVT and gzip compression. Use ETag and `If-Modified-Since` headers.

### 6.1 Authentication
- **MVP**: no authentication for read endpoints.
- **Admin**: `POST /api/recompute` protected by token (env var) or basic auth.

### 6.2 Endpoints

#### `GET /api/top-roads`
- **Query params**:
  - `state` (optional) — state code or name
  - `city` (optional) — city name
  - `metric` (optional) — `fun_score` or specific metric (`curvature`, `traffic_control_density`, etc.)
  - `limit` (optional, default 5)
- **Behavior**:
  - Check `top_roads_cache` for `cache_key`.
  - If cache miss, compute top N by `composite_fun_score` within filter polygon (city/state) using precomputed aggregates (e.g., group contiguous segments into roads).
- **Response**:
  - `roads`: array of objects:
    - `road_id`, `name`, `state`, `city`, `score`, `summary_metrics` (curvature_norm; traffic_control_density; length_km), `centroid` (lat/lon), `preview_geojson` (small simplified geometry).

#### `GET /api/segments`
- **Query params**:
  - `bbox` (minLon,minLat,maxLon,maxLat) OR `tile` (z/x/y)
  - `metric` (e.g., `fun_score` or `curvature`)
  - `zoom` (integer)
  - `limit` (max segments)
- **Behavior**:
  - Use bounding-box spatial query with `ST_Intersects`.
  - Return simplified geometry based on `zoom` (e.g., `ST_SimplifyPreserveTopology`).
  - Support `format=mvt` to return Mapbox Vector Tile via `ST_AsMVT`.
- **Response**:
  - GeoJSON FeatureCollection or MVT.

#### `GET /api/segment/{id}`
- **Response**:
  - Full metrics, geometry (TopoJSON/GeoJSON), nearby traffic controls, elevation profile (array of [distance_m, elevation_m]).

#### `GET /api/search`
- **Query params**:
  - `q` (string)
  - `limit` (default 10)
- **Behavior**:
  - Use `cities` table and a lightweight full-text index on `name`.
  - Return centroid and bounding box for map recentering.
- **Response**:
  - `results`: array of `{name, state, centroid, bbox}`.

#### `GET /api/legend`
- **Query params**:
  - `metric`
- **Response**:
  - `breaks`: percentile thresholds and colours (e.g., top 10% green).

#### `POST /api/recompute`
- **Auth**: admin token
- **Body**:
  - `metrics`: list to recompute or `all`
  - `region`: optional (state or city)
- **Behavior**:
  - Enqueue background job; return job id.

---

## 7. Frontend — UX & Implementation (Streamlit MVP)

> The frontend is implemented in Python using Streamlit for rapid iteration. Map rendering uses `pydeck` (WebGL) for performance and `streamlit-folium` for Leaflet fallback.

### 7.1 Pages & Components
- **Home** (`/`)
  - **Top 5 list** (left column)
    - Each item: **rank**, **road name**, **state/city**, **composite score**, **length**, **thumbnail** (small map snapshot).
    - Click item: pan map to road and open side panel.
  - **Map** (right column)
    - Base layers: OpenStreetMap raster; optional satellite.
    - Overlay: colour-coded segments (GeoJSON or MVT).
    - Pins: top 5 centroids.
    - Controls: metric selector, legend, filter (State, City), search box.
- **Map view** (`/map`)
  - Full-screen map with layer controls and heatmap toggle.
  - Click segment: open side panel with metrics, elevation chart, export GPX/GeoJSON button.
- **Search** (top bar)
  - Typeahead for suburbs/cities; selecting recentres map and loads segments.
- **Advanced** (settings modal)
  - Weighting sliders for composite score; **Apply** triggers recompute on client-side weighting (no DB recompute) for immediate visual feedback.
  - Save preferences (localStorage or server-side if user opts in).

### 7.2 Map Rendering Strategy
- **Initial load**:
  - Fetch `GET /api/top-roads` and display pins.
  - Load minimal GeoJSON for the top 5 segments (simplified).
- **Viewport-driven loading**:
  - On map move/zoom, request `GET /api/segments?bbox=...&zoom=...&metric=...`.
  - Use `zoom` to determine simplification tolerance and whether to request MVT.
- **Colouring**:
  - Client receives `score_norm` per segment and maps to colour ramp using percentiles from `GET /api/legend`.
- **Performance**:
  - Use `pydeck` for WebGL rendering of many segments.
  - Use MVT for dense zooms; GeoJSON for low-density views.
  - Debounce map move events (e.g., 200 ms) to avoid flooding API.

### 7.3 Accessibility & UX Details
- **Legend** with textual labels and colour-blind friendly palette (e.g., Viridis).
- **Tooltips** on hover: road name, score, length, key metrics.
- **Keyboard navigation**: focusable search and list items.
- **Mobile**: map-first layout; top list collapsible.

---

## 8. Performance & Scalability — Concrete Tactics

### 8.1 Precomputation & Materialised Views
- Materialised views for:
  - `segment_metrics_mv` — precomputed metrics.
  - `top_roads_mv` — aggregated top roads per city/state/metric.
- Refresh strategy:
  - Nightly full refresh.
  - Incremental refresh when PBF updated or admin triggers recompute.

### 8.2 Spatial Indexing & Query Patterns
- **Indexes**:
  - `CREATE INDEX idx_segments_geom ON road_segments USING GIST (geom);`
  - `CREATE INDEX idx_segments_length ON road_segments (length_m);`
  - `CREATE INDEX idx_cities_geom ON cities USING GIST (geom);`
- **Query patterns**:
  - Use `&&` bounding box operator for fast index usage.
  - Use `ST_Transform` only when necessary; store precomputed 3857 geometries for tile generation.

### 8.3 Vector Tiles & Payload Reduction
- Serve MVT via `ST_AsMVT` for zoom levels >= 10.
- For GeoJSON, always `ST_SimplifyPreserveTopology(geom, tolerance)` based on zoom.
- Compress responses with gzip; set `Cache-Control` headers.

### 8.4 Caching
- **Redis**:
  - Cache `top_roads_cache` keyed by `state|city|metric`.
  - Cache recent viewport queries (keyed by bbox quantized to tile grid).
- **Client-side**:
  - Cache last N viewport responses in memory; reuse when panning back.

### 8.5 Background Jobs & Rate Limiting
- Use Celery with Redis broker for heavy tasks.
- Rate-limit geometry endpoints per IP to protect local resources.

---

## 9. Operational Concerns & Maintenance

### 9.1 Data Updates
- **PBF refresh cadence**: monthly or on-demand.
- **Update pipeline**:
  - Download new PBF → run ingest in staging → compute diffs → apply incremental updates to DB.
- **Backups**:
  - Daily DB dumps; weekly PBF archive snapshots.

### 9.2 Monitoring & Logging
- **Metrics**:
  - API latency, cache hit ratio, DB query times, worker queue length.
- **Logging**:
  - Structured logs (JSON) for API requests and background jobs.
- **Alerts**:
  - High queue length, low cache hit rate, DB disk usage > 80%.

### 9.3 Security
- Local-only data by default.
- Admin endpoints protected by token.
- Sanitize all inputs (bbox, tile indices).
- Use HTTPS in production.

---

## 10. Testing Strategy (detailed)

### 10.1 Unit Tests
- Metric functions:
  - curvature computation with synthetic polylines (straight, single curve, S-curve).
  - traffic-control density calculation with synthetic node placements.
  - elevation sampling with mocked DEM.
- Tag normalization functions.

### 10.2 Integration Tests
- End-to-end ingest of a small PBF (single state) and verify:
  - `roads_raw` populated.
  - `road_segments` segmentation correctness.
  - `segment_metrics` values within expected ranges.
- API tests:
  - `GET /api/top-roads` returns expected top items for a seeded dataset.
  - `GET /api/segments` returns simplified geometry for bbox.

### 10.3 Performance Tests
- Simulate 100 concurrent viewport requests; measure 95th percentile latency.
- Test MVT generation latency for busy tiles.
- Cache warm vs cold scenarios.

### 10.4 Visual QA
- Validate colour ramps across zooms and metrics.
- Accessibility checks (contrast ratios, keyboard navigation).

---

## 11. Developer Experience & Tooling

### 11.1 Local Dev Setup (commands)
- **Prereqs**: Docker, Docker Compose, Python 3.11+, Node (optional for tooling)
- **Start dev stack**:
  ```bash
  git clone <repo>
  cp .env.example .env
  docker-compose up -d
  # run ingest in a container
  docker-compose run --rm ingest python ingest_pbf.py --pbf data/pbf/australia-latest.osm.pbf
  ```
- **Run API**:
  ```bash
  docker-compose up fastapi
  ```
- **Run frontend**:
  ```bash
  docker-compose up streamlit
  ```

### 11.2 CLI Utilities (scripts)
- `ingest_pbf.py --pbf <file> --state <optional>` — parse and load into `roads_raw`.
- `segment_generate.py --batch-size 1000` — create `road_segments`.
- `compute_metrics.py --metrics curvature,traffic,elevation --batch-size 500` — compute metrics.
- `generate_tiles.py --zoom 6-14` — pre-generate MVT tiles.
- `recompute_top_roads.py --state NSW --metric fun_score` — refresh cache.

### 11.3 Configuration
- `config.yaml`:
  - metric weights
  - segmentation length
  - curvature resample distance
  - DEM path
  - cache TTLs
  - admin token
- Environment variables for DB/Redis credentials.

---

## 12. UX Details — Home Page & Interaction Flow

### 12.1 Home Page Layout (desktop)
- **Left column (30%)**:
  - Header: app name, metric selector dropdown.
  - Filters: **State** dropdown; **City** typeahead (dependent on State).
  - **Top 5 list**: each item shows:
    - **Rank** (1–5)
    - **Road name** (bold)
    - **Score** (big numeric + small percentile)
    - **Short blurb**: e.g., "12 km; high curvature; few traffic lights"
    - **Action buttons**: Focus on map; Export GPX
- **Right column (70%)**:
  - Map canvas with pins and colour-coded segments.
  - Legend and layer controls overlayed.

### 12.2 Interaction Flow Examples
- **Filter by State**:
  - User selects `NSW` → frontend requests `GET /api/top-roads?state=NSW&limit=5` → update list and map pins.
- **Click top road**:
  - Map recentres to road; fetch `GET /api/segment/{id}` for full geometry and metrics; open side panel.
- **Search suburb**:
  - Type `Katoomba` → `GET /api/search?q=Katoomba` → recenter map to centroid and load segments in bbox.
- **Zoom in**:
  - At zoom >= 12, request MVT tiles for dense rendering; segments recolour by selected metric.

---

## 13. Colour Coding & Legend (implementation)

### 13.1 Colour Ramp & Thresholds
- Use perceptually-uniform palette (e.g., Viridis) with 5 stops:
  - **Top 10%** — deep green
  - **10–30%** — light green
  - **30–60%** — yellow
  - **60–90%** — orange
  - **Bottom 10%** — red
- Provide textual legend with metric explanation and sample values.

### 13.2 Per-metric Mode
- When user selects a single metric (e.g., curvature), compute percentiles for that metric and colour segments accordingly.

---

## 14. Extensibility & Future Work

### 14.1 Short-term Enhancements
- Add scenic score using landuse and POI tags.
- Allow user-uploaded GPX traces to refine scoring.
- Add user accounts and saved preferences.

### 14.2 Long-term
- Integrate live traffic feeds (optional).
- Expand to other countries.
- Mobile app with offline maps.

---

## 15. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---:|---|
| Large PBF size and long ingest times | High | Use state extracts; incremental ingest; run ingest on powerful machine; chunked processing |
| DB query latency for dense tiles | High | Pre-generate MVT; use materialised views; caching |
| Incorrect metric due to poor tags | Medium | Provide defaults; surface tag confidence; allow user weighting |
| UX sluggish on low-end devices | Medium | Use WebGL rendering; limit geometry sent; progressive loading |

---

## 16. Milestones, Deliverables, and Timeline (detailed)

### Phase 0 — Setup (Days 0–3)
- Repo skeleton, `README`, `config.yaml`, Docker Compose.
- Postgres+PostGIS + Redis containers.
- FastAPI skeleton with health endpoint.
- Streamlit skeleton with placeholder map.

### Phase 1 — Ingest MVP (Days 4–14)
- Acquire Australia PBF (or single state).
- Implement `ingest_pbf.py` using `pyrosm`.
- Populate `roads_raw` and `cities`.
- Unit tests for parsing and normalization.

### Phase 2 — Segmentation & Metrics MVP (Days 15–28)
- Implement segmentation logic and `road_segments`.
- Implement curvature and traffic-control density computations.
- Store results in `segment_metrics`.
- Create `compute_metrics.py` and unit tests.

### Phase 3 — API & Frontend MVP (Days 29–42)
- Implement `GET /api/top-roads`, `GET /api/segments`, `GET /api/search`.
- Streamlit home page: top 5 list + interactive map showing top segments.
- Implement caching for top lists.

### Phase 4 — Performance & Polish (Days 43–56)
- Add Redis caching, materialised views, MVT support.
- Add elevation processing and surface scoring.
- UX polish: legend, tooltips, mobile responsiveness.
- Integration tests and performance testing.

### Phase 5 — Release Candidate (Days 57–70)
- Final QA, documentation, backup scripts.
- Prepare deployment instructions for local server.

---

## 17. Deliverables (what you will get)
- `PLAN.md` (this document).
- Repo skeleton with:
  - Docker Compose
  - FastAPI skeleton and API contract
  - Streamlit frontend skeleton
  - CLI scripts: `ingest_pbf.py`, `segment_generate.py`, `compute_metrics.py`
  - `config.yaml` and `.env.example`
  - Unit tests and integration test scaffolding
- Example dataset: small state extract and precomputed sample metrics for demo.

---

## 18. Appendix

### 18.1 Example SQL snippets

**Create GIST index**
```sql
CREATE INDEX idx_road_segments_geom ON road_segments USING GIST (geom);
```

**Simplify geometry for zoom**
```sql
SELECT id, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0005)) AS geojson
FROM road_segments
WHERE geom && ST_MakeEnvelope(:minLon, :minLat, :maxLon, :maxLat, 4326)
LIMIT :limit;
```

**MVT generation (PostGIS)**
```sql
WITH mvtgeom AS (
  SELECT id, composite_fun_score AS score,
         ST_AsMVTGeom(ST_Transform(geom, 3857), TileBBox(:z, :x, :y, 3857)) AS geom
  FROM road_segments
  WHERE ST_Intersects(geom, ST_Transform(TileBBox(:z, :x, :y, 3857), 4326))
)
SELECT ST_AsMVT(mvtgeom.*, 'segments', 4096, 'geom') FROM mvtgeom;
```

### 18.2 Composite score formula (LaTeX)
\[
\text{fun} = 0.40\cdot\text{curvature\_norm} + 0.25\cdot(1-\text{traffic\_control\_norm}) + 0.15\cdot\text{speed\_norm} + 0.10\cdot\text{elevation\_norm} + 0.10\cdot\text{surface\_score}
\]

### 18.3 Configurable parameters (example `config.yaml` keys)
- `segmentation_length_m`
- `curvature_resample_m`
- `metric_weights` (curvature, traffic, speed, elevation, surface)
- `pbf_path`
- `dem_path`
- `cache_ttl_seconds`
- `admin_token`

---

## 19. Next Immediate Actions (concrete, one-command steps)

1. **Create repository skeleton** with `docker-compose.yml`, `fastapi/`, `streamlit/`, `scripts/`.
2. **Download** Australia PBF to `data/pbf/`.
3. **Run** ingest for a single state to validate pipeline:
```bash
python scripts/ingest_pbf.py --pbf data/pbf/australia-latest.osm.pbf --state NSW --limit-ways 10000
```
4. **Run** metric compute for a small batch:
```bash
python scripts/compute_metrics.py --batch-size 500 --metrics curvature,traffic
```
5. **Start** Streamlit and FastAPI and verify top-5 endpoint returns results.

---

### Contact & Ownership
- **Repository owner**: (your name or org)
- **Primary contact**: (email placeholder)
- **License**: MIT (recommended) or choose appropriate license.

---

**End of PLAN.md**

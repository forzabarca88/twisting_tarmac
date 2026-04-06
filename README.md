# 🚗 TwistingTarmac

**TwistingTarmac** is a Python-first web application designed to identify and visualize **fun-to-drive** road stretches in Australia using local OpenStreetMap (OSM) data.

It processes road geometry, curvature, traffic density, and elevation to compute a "fun score" for road segments, presenting them on an interactive map.

---

## 🏗️ Architecture

- **Backend**: FastAPI (Python) serving GeoJSON and metrics.
- **Frontend**: Streamlit (Python) for an interactive map and top-roads dashboard.
- **Database**: PostgreSQL with PostGIS for spatial data storage and queries.
- **Cache**: Redis for API response caching.
- **Data Ingest**: Custom Python scripts using `pyrosm` and `shapely`.

---

## 🚀 Quick Start

### 1. Prerequisites
- Docker and Docker Compose
- An Australia OSM PBF file (e.g., from [Geofabrik](https://download.geofabrik.de/australia-oceania/australia.html)) placed in `data/pbf/australia-latest.osm.pbf`.

### 2. Environment Setup
```bash
cp .env.example .env
```

### 3. Start the Services
```bash
docker-compose up -d
```

### 4. Run the Data Pipeline
To populate the database with a proof-of-concept dataset:

**Step 1: Ingest OSM data** (processes the first 1,000 roads)
```bash
docker-compose run --rm ingest python scripts/ingest_pbf.py --pbf data/pbf/australia-latest.osm.pbf --limit 1000
```

**Step 2: Compute Metrics** (generates scores for segments)
```bash
docker-compose run --rm ingest python scripts/compute_metrics.py
```

---

## 🌐 Accessing the App

- **Frontend Dashboard**: [http://localhost:8501](http://localhost:8501)
- **Interactive API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 📁 Project Structure

```
.
├── app/
│   ├── api/          # FastAPI backend
│   └── frontend/     # Streamlit frontend
├── db/               # SQL initialization scripts
├── docker/           # Dockerfiles for services
├── data/             # OSM PBF storage (gitignored)
├── scripts/          # Ingest and processing utilities
└── docker-compose.yml
```

---

## 🛠️ Development

To run scripts locally without Docker:
1. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
2. Install dependencies: `pip install -r requirements.txt`
3. Ensure PostGIS and Redis are running.

---

## 📄 License
MIT

from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
import os
from typing import List, Optional
from pydantic import BaseModel

app = FastAPI(title="TwistingTarmac API")

# DB Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/twisting_tarmac")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RoadSummary(BaseModel):
    id: str
    name: Optional[str]
    score: float
    length_km: float

@app.get("/")
def read_root():
    return {"message": "Welcome to TwistingTarmac API"}

@app.get("/api/top-roads", response_model=List[RoadSummary])
def get_top_roads(
    state: Optional[str] = None,
    city: Optional[str] = None,
    metric: str = "composite_fun_score",
    limit: int = 5,
    db: Session = Depends(get_db)
):
    # Proof of concept: Fetching top roads from road_segments joined with segment_metrics
    # In a real app, this would use a materialised view or the top_roads_cache
    query = text(f"""
        SELECT rs.id::text, rs.road_class as name, sm.composite_fun_score as score, rs.length_m / 1000.0 as length_km
        FROM road_segments rs
        JOIN segment_metrics sm ON rs.id = sm.segment_id
        ORDER BY sm.{metric} DESC
        LIMIT :limit
    """)
    result = db.execute(query, {"limit": limit}).fetchall()
    return [RoadSummary(id=row[0], name=row[1], score=row[2], length_km=row[3]) for row in result]

@app.get("/api/segments")
def get_segments(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat"),
    db: Session = Depends(get_db)
):
    try:
        minLon, minLat, maxLon, maxLat = map(float, bbox.split(','))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid bbox format")

    query = text("""
        SELECT rs.id, ST_AsGeoJSON(rs.geom) as geometry, sm.composite_fun_score as score
        FROM road_segments rs
        JOIN segment_metrics sm ON rs.id = sm.segment_id
        WHERE rs.geom && ST_MakeEnvelope(:minLon, :minLat, :maxLon, :maxLat, 4326)
        LIMIT 1000
    """)
    result = db.execute(query, {
        "minLon": minLon, "minLat": minLat, 
        "maxLon": maxLon, "maxLat": maxLat
    }).fetchall()
    
    features = []
    for row in result:
        import json
        features.append({
            "type": "Feature",
            "geometry": json.loads(row[1]),
            "properties": {"id": str(row[0]), "score": row[2]}
        })
    
    return {"type": "FeatureCollection", "features": features}

import argparse
import os
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
import random

def compute():
    print("Computing metrics for segments...")
    
    # DB connection
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/twisting_tarmac")
    engine = sa.create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Get all road segments
    segments = session.execute(sa.text("SELECT id FROM road_segments")).fetchall()
    
    print(f"Processing {len(segments)} segments...")
    
    count = 0
    for segment in segments:
        segment_id = segment[0]
        
        # PoC: Random metrics for demonstration
        curvature_norm = random.random()
        traffic_norm = random.random()
        speed_norm = random.random()
        elevation_norm = random.random()
        surface_score = random.random()
        
        # composite_fun_score using weights from PLAN.md
        # fun = 0.40 * curvature_norm + 0.25 * (1-traffic_norm) + 0.15 * speed_norm + 0.10 * elevation_norm + 0.10 * surface_score
        composite_fun_score = 0.40 * curvature_norm + 0.25 * (1 - traffic_norm) + 0.15 * speed_norm + 0.10 * elevation_norm + 0.10 * surface_score
        
        query = sa.text("""
            INSERT INTO segment_metrics (
                segment_id, curvature_raw, curvature_norm, 
                traffic_control_count, traffic_control_density, traffic_control_norm,
                speed_norm, elevation_variation_m, elevation_norm, 
                surface_score, lane_score, composite_fun_score, metric_version
            )
            VALUES (
                :segment_id, :curv_raw, :curv_norm, 
                0, 0, :traffic_norm,
                :speed_norm, 0, :elev_norm, 
                :surface_score, 1.0, :fun_score, 'poc-v1'
            )
            ON CONFLICT (segment_id) DO UPDATE SET
                composite_fun_score = EXCLUDED.composite_fun_score,
                curvature_norm = EXCLUDED.curvature_norm,
                traffic_control_norm = EXCLUDED.traffic_control_norm,
                speed_norm = EXCLUDED.speed_norm,
                elevation_norm = EXCLUDED.elevation_norm,
                surface_score = EXCLUDED.surface_score,
                computed_at = CURRENT_TIMESTAMP
        """)
        
        session.execute(query, {
            "segment_id": segment_id,
            "curv_raw": curvature_norm,
            "curv_norm": curvature_norm,
            "traffic_norm": traffic_norm,
            "speed_norm": speed_norm,
            "elev_norm": elevation_norm,
            "surface_score": surface_score,
            "fun_score": composite_fun_score
        })
        
        count += 1
        if count % 100 == 0:
            print(f"Computed {count} segments...")
            session.commit()

    session.commit()
    print(f"Successfully computed metrics for {count} segments.")
    session.close()

if __name__ == "__main__":
    compute()

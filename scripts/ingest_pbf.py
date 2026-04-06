import argparse
from pyrosm import OSM, get_data
import os
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from shapely.geometry import LineString
import json

def ingest(pbf_path, limit=1000):
    print(f"Ingesting {pbf_path} (limit={limit})...")
    
    osm = OSM(pbf_path)
    # Extract highways
    # Keep motorways, primary, secondary, tertiary etc
    drive_net = osm.get_network(network_type="driving")
    
    if drive_net is None:
        print("No driving network found.")
        return
        
    print(f"Extracted {len(drive_net)} road segments.")
    
    # DB connection
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/twisting_tarmac")
    engine = sa.create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Clear existing data
    session.execute(sa.text("TRUNCATE TABLE roads_raw CASCADE"))
    session.execute(sa.text("TRUNCATE TABLE road_segments CASCADE"))
    session.execute(sa.text("TRUNCATE TABLE segment_metrics CASCADE"))
    session.commit()

    # Insert into roads_raw
    count = 0
    for idx, row in drive_net.iterrows():
        if count >= limit:
            break
            
        geom = row.geometry
        if not isinstance(geom, LineString):
            continue
            
        tags = row.to_dict()
        # remove keys that are not tags or geometry
        tags.pop('geometry', None)
        tags.pop('id', None)
        
        # Prepare for DB
        # SQLAlchemy with PostGIS
        # Using raw SQL for the PoC to avoid complexity with GeoAlchemy2
        query = sa.text("""
            INSERT INTO roads_raw (osm_id, tags, geom, length_m, source)
            VALUES (:osm_id, :tags, ST_GeomFromText(:geom_wkt, 4326), :length, :source)
            RETURNING id
        """)
        
        # Compute length in meters using ST_Length(ST_Transform(geom, 3857))
        # For PoC, just use rough estimate or let DB compute it
        res = session.execute(query, {
            "osm_id": row.id if hasattr(row, 'id') else idx,
            "tags": json.dumps(tags),
            "geom_wkt": geom.wkt,
            "length": 0.0, # Will compute later
            "source": pbf_path
        })
        road_id = res.scalar()
        
        # Create a segment in road_segments for each road_raw
        # Simple PoC: 1 raw road = 1 segment
        seg_query = sa.text("""
            INSERT INTO road_segments (road_id, segment_index, geom, length_m, road_class, maxspeed_kph)
            VALUES (:road_id, 0, ST_GeomFromText(:geom_wkt, 4326), :length, :road_class, :maxspeed)
            RETURNING id
        """)
        
        session.execute(seg_query, {
            "road_id": road_id,
            "geom_wkt": geom.wkt,
            "length": 0.0,
            "road_class": tags.get('highway', 'unknown'),
            "maxspeed": int(tags.get('maxspeed', '0')) if str(tags.get('maxspeed')).isdigit() else 0
        })
        
        count += 1
        if count % 100 == 0:
            print(f"Ingested {count} roads...")
            session.commit()

    session.commit()
    print(f"Successfully ingested {count} roads.")
    session.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pbf", default="data/pbf/australia-latest.osm.pbf")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    
    # Check if file exists
    if not os.path.exists(args.pbf):
        print(f"PBF file not found: {args.pbf}")
    else:
        ingest(args.pbf, args.limit)

import argparse
import os
import osmium
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from shapely.geometry import LineString
import json

class RoadHandler(osmium.SimpleHandler):
    def __init__(self, session, limit=1000):
        super(RoadHandler, self).__init__()
        self.session = session
        self.limit = limit
        self.count = 0
        self.roads = []

    def way(self, w):
        if self.count >= self.limit:
            return

        if 'highway' in w.tags:
            try:
                # Build coordinates from nodes
                coords = []
                for node in w.nodes:
                    coords.append((node.lon, node.lat))
                
                if len(coords) < 2:
                    return

                geom = LineString(coords)
                tags = {tag.k: tag.v for tag in w.tags}
                
                # Insert into roads_raw
                query = sa.text("""
                    INSERT INTO roads_raw (osm_id, tags, geom, length_m, source)
                    VALUES (:osm_id, :tags, ST_GeomFromText(:geom_wkt, 4326), :length, :source)
                    RETURNING id
                """)
                
                res = self.session.execute(query, {
                    "osm_id": w.id,
                    "tags": json.dumps(tags),
                    "geom_wkt": geom.wkt,
                    "length": 0.0,
                    "source": "pbf"
                })
                road_id = res.scalar()
                
                # Create a segment
                seg_query = sa.text("""
                    INSERT INTO road_segments (road_id, segment_index, geom, length_m, road_class, maxspeed_kph)
                    VALUES (:road_id, 0, ST_GeomFromText(:geom_wkt, 4326), :length, :road_class, :maxspeed)
                """)
                
                maxspeed = 0
                if 'maxspeed' in tags:
                    speed_str = tags['maxspeed'].split(' ')[0]
                    if speed_str.isdigit():
                        maxspeed = int(speed_str)

                self.session.execute(seg_query, {
                    "road_id": road_id,
                    "geom_wkt": geom.wkt,
                    "length": 0.0,
                    "road_class": tags.get('highway', 'unknown'),
                    "maxspeed": maxspeed
                })

                self.count += 1
                if self.count % 100 == 0:
                    print(f"Ingested {self.count} roads...")
                    self.session.commit()

            except Exception as e:
                print(f"Error processing way {w.id}: {e}")

def ingest(pbf_path, limit=1000):
    print(f"Ingesting {pbf_path} (limit={limit}) using osmium...")
    
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

    # Process PBF
    handler = RoadHandler(session, limit)
    # Important: Apply locations to ways to get node coordinates
    handler.apply_file(pbf_path, locations=True)
    
    session.commit()
    print(f"Successfully ingested {handler.count} roads.")
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

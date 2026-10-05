from __future__ import annotations

import argparse

from sqlalchemy import text
from wildfire_core.config import load_settings
from wildfire_core.db.session import create_db_engine


def seed_offline() -> None:
    settings = load_settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    bbox = settings.aoi_bbox
    polygon = (
        f"POLYGON(({bbox.west} {bbox.south}, {bbox.east} {bbox.south}, "
        f"{bbox.east} {bbox.north}, {bbox.west} {bbox.north}, "
        f"{bbox.west} {bbox.south}))"
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO areas_of_interest (name, geom, config)
                SELECT :name, ST_GeomFromText(:polygon, 4326), CAST(:config AS jsonb)
                WHERE NOT EXISTS (SELECT 1 FROM areas_of_interest WHERE name = :name)
                """
            ),
            {
                "name": settings.aoi_name,
                "polygon": polygon,
                "config": f'{{"pilot_cluster_id": "{settings.pilot_cluster_id}"}}',
            },
        )
    print(f"seeded offline AOI {settings.aoi_name} with cluster {settings.pilot_cluster_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.offline:
        parser.error("only --offline seed mode is supported in Phase 1")
    seed_offline()


if __name__ == "__main__":
    main()

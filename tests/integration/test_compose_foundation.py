from __future__ import annotations

import os

import pytest
from api_gateway.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from wildfire_core.config import load_settings


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_compose_foundation() -> None:
    client = TestClient(create_app(load_settings()))
    assert client.get("/api/v1/health/live").json() == {"status": "alive"}
    ready = client.get("/api/v1/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    projection = client.get("/api/v1/config").json()
    assert projection["aoi"]["bbox"] == {
        "west": 76.0,
        "south": 11.5,
        "east": 77.3,
        "north": 12.4,
    }
    assert "database_url" not in str(projection)
    assert projection["pilot_cluster_id"] == "bandipur"


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_phase_one_schema_boundary() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    phase_one_tables = {
        "areas_of_interest",
        "hotspots",
        "weather_observations",
        "settlements",
        "incidents",
        "hotspot_clusters",
        "triggers",
        "fire_runs",
        "agent_runs",
        "agent_messages",
        "shared_state_snapshots",
        "audit_log",
    }
    assert phase_one_tables <= tables
    # Phase 3 migration 0006 adds shelters; review and vehicle tables arrive in later phases.
    assert "shelters" in tables
    assert not tables & {"plans", "plan_reviews", "vehicles"}

    for table_name, column_name in (
        ("areas_of_interest", "geom"),
        ("hotspots", "geom"),
        ("settlements", "geom"),
        ("hotspot_clusters", "centroid"),
    ):
        indexes = inspector.get_indexes(table_name)
        assert any(
            index["name"].endswith(f"{table_name}_{column_name}")
            or column_name in index.get("column_names", [])
            for index in indexes
        )

    for table_name, column_name in (
        ("hotspots", "cluster_id"),
        ("incidents", "aoi_id"),
        ("agent_messages", "run_id"),
        ("shared_state_snapshots", "incident_id"),
    ):
        indexes = inspector.get_indexes(table_name)
        assert any(column_name in index.get("column_names", []) for index in indexes)

    with engine.connect() as connection:
        geometry_rows = connection.execute(
            text(
                """
                SELECT f_table_name, f_geometry_column, srid
                FROM geometry_columns
                WHERE f_table_name IN (
                    'areas_of_interest', 'hotspots', 'settlements', 'hotspot_clusters'
                )
                """
            )
        ).all()
        assert geometry_rows
        assert all(row.srid == 4326 for row in geometry_rows)
        vector_columns = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE udt_name = 'vector'
                """
            )
        ).scalar_one()
        assert vector_columns == 0
    engine.dispose()

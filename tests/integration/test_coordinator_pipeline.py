from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from wildfire_core.config import load_settings
from wildfire_core.db.session import create_db_engine

load_dotenv()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("COMPOSE_SMOKE") != "1" or not os.getenv("GROQ_API_KEY"),
        reason="requires Compose PostgreSQL and GROQ_API_KEY",
    ),
]


@pytest.fixture
def seeded_incident() -> Iterator[dict[str, str]]:
    settings = load_settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    now = datetime.now(UTC)
    incident_id = uuid4()
    run_id = uuid4()
    hotspot_ids = [uuid4() for _ in range(5)]

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO incidents (id, code, status, origin, summary)
                VALUES (:id, :code, 'open', 'replay', 'Coordinator integration fixture')
                """
            ),
            {"id": incident_id, "code": f"TEST-{incident_id.hex[:10]}"},
        )
        for index, hotspot_id in enumerate(hotspot_ids):
            latitude = 11.72 + (index - 2) * 0.001
            longitude = 76.64 + (index - 2) * 0.001
            connection.execute(
                text(
                    """
                    INSERT INTO hotspots
                        (id, source, acq_datetime, lat, lon, geom, frp, origin,
                         freshness_status, ingested_at)
                    VALUES
                        (:id, 'VIIRS_SNPP_NRT', :observed_at, :lat, :lon,
                         ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 20.0,
                         'replay', 'fresh', :observed_at)
                    """
                ),
                {
                    "id": hotspot_id,
                    "observed_at": now,
                    "lat": latitude,
                    "lon": longitude,
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO triggers (incident_id, type, details, detected_at)
                VALUES (:incident_id, 'new_hotspot', CAST(:details AS jsonb), :detected_at)
                """
            ),
            {
                "incident_id": incident_id,
                "details": json.dumps({"hotspot_ids": [str(item) for item in hotspot_ids]}),
                "detected_at": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO weather_observations
                    (provider, lat, lon, valid_time, issued_at, is_forecast,
                     temperature_c, rh_pct, wind_speed_ms, wind_dir_deg,
                     origin, freshness_status)
                VALUES
                    ('open-meteo', 11.72, 76.64, :valid_time, :issued_at, false,
                     34.0, 30.0, 5.0, 45.0, 'replay', 'fresh')
                """
            ),
            {"valid_time": now, "issued_at": now},
        )

    try:
        yield {"incident_id": str(incident_id), "run_id": str(run_id)}
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM agent_runs WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            connection.execute(
                text("DELETE FROM plan_versions WHERE incident_id = :incident_id"),
                {"incident_id": incident_id},
            )
            connection.execute(
                text("DELETE FROM triggers WHERE incident_id = :incident_id"),
                {"incident_id": incident_id},
            )
            connection.execute(
                text("DELETE FROM hotspots WHERE id = ANY(:ids)"),
                {"ids": hotspot_ids},
            )
            connection.execute(
                text("DELETE FROM weather_observations WHERE valid_time = :valid_time"),
                {"valid_time": now},
            )
            connection.execute(
                text("DELETE FROM incidents WHERE id = :incident_id"),
                {"incident_id": incident_id},
            )
        engine.dispose()


def test_full_pipeline_produces_draft_plan(
    seeded_incident: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from coordinator.runner import run_coordinator

    fixture_path = Path("tests/fixtures/osm/bandipur_stub.graphml").resolve()
    monkeypatch.setenv("OSM_CACHE_PATH", str(fixture_path))
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    state = run_coordinator(seeded_incident["incident_id"], seeded_incident["run_id"])

    assert state["error"] is None
    assert len(state["audit_entries"]) == 8
    assert len(state["clusters"]) >= 1
    assert len(state["fire_results"]) == len(state["clusters"])
    assert state["rationale"]
    rationale_entry = next(
        entry for entry in state["audit_entries"] if entry["node_name"] == "generate_rationale"
    )
    assert state["is_llm_fallback"] is False, (
        f"Groq call fell back: {rationale_entry['model_metadata']}"
    )

    settings = load_settings()
    engine = create_db_engine(settings.database_url.get_secret_value())
    with engine.connect() as connection:
        plan = connection.execute(
            text(
                """
                SELECT id, status::text AS status, plan_data
                FROM plan_versions WHERE incident_id = :incident_id
                """
            ),
            {"incident_id": seeded_incident["incident_id"]},
        ).mappings().one()
        audit_count = connection.execute(
            text("SELECT count(*) FROM agent_runs WHERE run_id = :run_id"),
            {"run_id": seeded_incident["run_id"]},
        ).scalar_one()
        rationale_metadata = connection.execute(
            text(
                "SELECT model_metadata FROM agent_runs "
                "WHERE run_id = :run_id AND node_name = 'generate_rationale'"
            ),
            {"run_id": seeded_incident["run_id"]},
        ).scalar_one()
    assert rationale_metadata is not None
    if isinstance(rationale_metadata, str):
        rationale_metadata = json.loads(rationale_metadata)
    assert rationale_metadata["model"] == settings.llm_model
    assert rationale_metadata["is_fallback"] is False
    assert rationale_metadata["llm_called"] is True
    plan_data = plan["plan_data"]
    if isinstance(plan_data, str):
        plan_data = json.loads(plan_data)
    assert len(plan_data["fire_results"]) == len(plan_data["clusters"])
    assert plan["status"] == "draft"
    assert str(plan["id"]) == plan_data["plan_id"]
    assert audit_count == 8
    engine.dispose()
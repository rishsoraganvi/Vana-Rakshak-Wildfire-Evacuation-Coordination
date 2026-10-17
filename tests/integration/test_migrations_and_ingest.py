from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dotenv import load_dotenv
from ingest_worker.firms.parser import parse_firms_csv
from ingest_worker.firms.service import ingest_hotspots
from ingest_worker.triggers import record_new_hotspot_trigger
from sqlalchemy import create_engine, text
from wildfire_core.clock import SimClock
from wildfire_core.db.repositories import save_shared_state
from wildfire_core.schemas.state import SharedState, StateReference

load_dotenv()


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_firms_fixture_upsert_is_idempotent() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    payload = Path("tests/fixtures/firms/hotspot_sample.csv").read_text()
    observations = parse_firms_csv(
        payload, SimClock(datetime(2026, 1, 1, 12, tzinfo=UTC)), origin="replay"
    )
    assert ingest_hotspots(engine, observations) == 2
    assert ingest_hotspots(engine, observations) == 2
    # Scope to the fixture's upsert keys; other runs may share the database.
    rows = []
    with engine.connect() as connection:
        for observation in observations:
            rows += connection.execute(
                text(
                    """
                    SELECT raw, origin, freshness_status FROM hotspots
                    WHERE source = :source AND acq_datetime = :acq_datetime
                      AND lat = :lat AND lon = :lon
                    """
                ),
                {
                    "source": observation.source,
                    "acq_datetime": observation.acq_datetime,
                    "lat": observation.lat,
                    "lon": observation.lon,
                },
            ).all()
    assert len(rows) == 2
    assert all(
        row.raw is not None and row.origin == "replay" and row.freshness_status == "fresh"
        for row in rows
    )
    engine.dispose()


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_trigger_debounce_and_shared_state_are_durable() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    # Debounce looks back from detected_at with no upper bound, so start after every
    # existing trigger to keep earlier runs from being treated as the previous one.
    with engine.connect() as connection:
        latest = connection.execute(text("SELECT MAX(detected_at) FROM triggers")).scalar_one()
    detected_at = max(latest or datetime(2026, 1, 1, tzinfo=UTC), datetime.now(UTC)) + timedelta(
        days=1
    )
    detected_times = [detected_at, detected_at + timedelta(minutes=4)]
    try:
        first = record_new_hotspot_trigger(
            engine, count=3, threshold=3, detected_at=detected_times[0]
        )
        second = record_new_hotspot_trigger(
            engine, count=4, threshold=3, detected_at=detected_times[1]
        )
        assert first.crossed and second.crossed
        with engine.connect() as connection:
            own = connection.execute(
                text(
                    """
                    SELECT incident_id, coalesced_into FROM triggers
                    WHERE type = 'new_hotspot' AND detected_at = ANY(:times)
                    ORDER BY detected_at
                    """
                ),
                {"times": detected_times},
            ).all()
        assert len({row.incident_id for row in own}) == 2
        assert [row.coalesced_into is not None for row in own] == [False, True]
        incident_id = own[0].incident_id

        save_shared_state(
            engine,
            SharedState(
                incident_id=str(incident_id),
                version=1,
                references=(StateReference(kind="hotspot", identifier="hotspot-1"),),
            ),
        )
        with engine.connect() as connection:
            snapshot = connection.execute(
                text(
                    "SELECT version, state FROM shared_state_snapshots "
                    "WHERE incident_id = :incident_id"
                ),
                {"incident_id": incident_id},
            ).first()
        assert snapshot is not None and snapshot.version == 1
    finally:
        # Future-dated triggers would debounce every later real trigger; remove them.
        with engine.begin() as connection:
            incident_ids = connection.execute(
                text("SELECT incident_id FROM triggers WHERE detected_at = ANY(:times)"),
                {"times": detected_times},
            ).scalars().all()
            connection.execute(
                text("DELETE FROM shared_state_snapshots WHERE incident_id = ANY(:ids)"),
                {"ids": incident_ids},
            )
            connection.execute(
                text("DELETE FROM triggers WHERE detected_at = ANY(:times)"),
                {"times": detected_times},
            )
            connection.execute(
                text("DELETE FROM incidents WHERE id = ANY(:ids)"), {"ids": incident_ids}
            )
        engine.dispose()

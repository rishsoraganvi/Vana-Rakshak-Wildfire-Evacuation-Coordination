from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingest_worker.firms.parser import parse_firms_csv
from ingest_worker.firms.service import ingest_hotspots
from ingest_worker.triggers import record_new_hotspot_trigger
from sqlalchemy import create_engine, text
from wildfire_core.clock import SimClock
from wildfire_core.db.repositories import save_shared_state
from wildfire_core.schemas.state import SharedState, StateReference


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
    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM hotspots")).scalar_one()
        raw = connection.execute(
            text("SELECT raw, origin, freshness_status FROM hotspots LIMIT 1")
        ).first()
    assert count == 2
    assert raw is not None and raw.origin == "replay" and raw.freshness_status == "fresh"
    engine.dispose()


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_trigger_debounce_and_shared_state_are_durable() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    detected_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    first = record_new_hotspot_trigger(
        engine, count=3, threshold=3, detected_at=detected_at
    )
    second = record_new_hotspot_trigger(
        engine, count=4, threshold=3, detected_at=detected_at.replace(minute=4)
    )
    assert first.crossed and second.crossed
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM incidents")).scalar_one() == 2
        assert connection.execute(
            text("SELECT COUNT(*) FROM triggers WHERE coalesced_into IS NOT NULL")
        ).scalar_one() == 1
        incident_id = connection.execute(text("SELECT id FROM incidents LIMIT 1")).scalar_one()

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
            text("SELECT version, state FROM shared_state_snapshots")
        ).first()
    assert snapshot is not None and snapshot.version == 1
    engine.dispose()

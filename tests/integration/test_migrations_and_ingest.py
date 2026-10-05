from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingest_worker.firms.parser import parse_firms_csv
from ingest_worker.firms.service import ingest_hotspots
from sqlalchemy import create_engine, text
from wildfire_core.clock import SimClock


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
        raw = connection.execute(text("SELECT raw, origin FROM hotspots LIMIT 1")).first()
    assert count == 2
    assert raw is not None and raw.origin == "replay"
    engine.dispose()

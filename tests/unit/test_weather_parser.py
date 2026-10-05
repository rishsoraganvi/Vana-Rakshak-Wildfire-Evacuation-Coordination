import json
from datetime import UTC, datetime
from pathlib import Path

from ingest_worker.weather.parser import parse_open_meteo
from wildfire_core.clock import SimClock


def test_open_meteo_fixture_normalizes_hourly_records() -> None:
    payload = json.loads(Path("tests/fixtures/open_meteo/forecast_sample.json").read_text())
    observations = parse_open_meteo(
        payload, SimClock(datetime(2026, 1, 1, 6, 30, tzinfo=UTC)), origin="replay"
    )
    assert len(observations) == 2
    assert observations[0].provider == "open-meteo"
    assert observations[0].temperature_c == 31.2
    assert observations[0].meta.freshness.status == "fresh"
    assert observations[0].meta.raw_payload == payload

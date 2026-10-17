import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_weather.agent import build_snapshot_query
from ingest_worker.weather.parser import parse_open_meteo
from sqlalchemy.dialects import postgresql
from wildfire_core.clock import SimClock

FIXTURES = Path("tests/fixtures/open_meteo")


def test_open_meteo_fixture_normalizes_hourly_records() -> None:
    payload = json.loads((FIXTURES / "forecast_sample.json").read_text())
    observations = parse_open_meteo(
        payload, SimClock(datetime(2026, 1, 1, 6, 30, tzinfo=UTC)), origin="replay"
    )
    assert len(observations) == 2
    assert observations[0].provider == "open-meteo"
    assert observations[0].temperature_c == 31.2
    assert observations[0].meta.freshness.status == "fresh"
    assert observations[0].meta.raw_payload == payload
    # Every hour is after issued_at (06:00), so these are forecasts.
    assert all(o.is_forecast is True for o in observations)


def test_observation_fixture_is_stored_as_live_observation() -> None:
    payload = json.loads((FIXTURES / "observation_sample.json").read_text())
    observations = parse_open_meteo(
        payload, SimClock(datetime(2026, 1, 1, 9, 30, tzinfo=UTC)), origin="live"
    )
    assert len(observations) == 2
    assert all(o.is_forecast is False for o in observations)
    assert all(o.meta.origin == "live" for o in observations)


def test_hours_straddling_issued_at_are_split_into_observation_and_forecast() -> None:
    payload = json.loads((FIXTURES / "observation_sample.json").read_text())
    payload["issued_at"] = "2026-01-01T07:30:00Z"
    observations = parse_open_meteo(
        payload, SimClock(datetime(2026, 1, 1, 9, 30, tzinfo=UTC)), origin="live"
    )
    assert [o.is_forecast for o in observations] == [False, True]
    # valid_time == issued_at is an observation (<=), not a forecast.
    payload["issued_at"] = "2026-01-01T08:00:00Z"
    observations = parse_open_meteo(
        payload, SimClock(datetime(2026, 1, 1, 9, 30, tzinfo=UTC)), origin="live"
    )
    assert [o.is_forecast for o in observations] == [False, False]


def test_origin_is_required_and_validated() -> None:
    payload = json.loads((FIXTURES / "observation_sample.json").read_text())
    clock = SimClock(datetime(2026, 1, 1, 9, 30, tzinfo=UTC))
    with pytest.raises(TypeError):
        parse_open_meteo(payload, clock)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        parse_open_meteo(payload, clock, origin="bogus")


def test_parsed_live_observation_satisfies_scoped_weather_query() -> None:
    payload = json.loads((FIXTURES / "observation_sample.json").read_text())
    now = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
    observation = parse_open_meteo(payload, SimClock(now), origin="live")[-1]

    stmt = build_snapshot_query(
        11.72, 76.64, origin="live", provider="open-meteo", max_distance_km=50.0, now=now
    )
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "is_forecast IS false" in sql
    assert "'live'" in sql

    # The row must satisfy every predicate the compiled query applies.
    assert observation.is_forecast is False
    assert observation.meta.origin == "live"
    assert observation.provider == "open-meteo"
    assert observation.valid_time <= now
    assert abs(observation.lat - 11.72) <= 50.0 / 111.32
    assert abs(observation.lon - 76.64) <= 50.0 / 111.32 / 0.97
    for value in (
        observation.wind_speed_ms,
        observation.wind_dir_deg,
        observation.rh_pct,
        observation.temperature_c,
    ):
        assert value is not None


def test_forecast_rows_cannot_satisfy_scoped_weather_query() -> None:
    payload = json.loads((FIXTURES / "forecast_sample.json").read_text())
    now = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
    rows = parse_open_meteo(payload, SimClock(now), origin="live")
    # Query requires is_forecast IS false; forecast rows are excluded (T-03-03-01).
    assert all(row.is_forecast for row in rows)

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agent_weather.agent import build_snapshot_query, get_weather_snapshot
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from wildfire_core.config import load_settings
from wildfire_core.db.session import create_db_engine

load_dotenv()

FIXED = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConnection:
    def __init__(self, row):
        self._row = row
        self.statements: list[object] = []

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return _FakeResult(self._row)


def _row(valid_time: datetime) -> dict:
    return {
        "valid_time": valid_time,
        "wind_speed_ms": 4.5,
        "wind_dir_deg": 270.0,
        "rh_pct": 35.0,
        "temperature_c": 31.0,
    }


def _compile(**kwargs):
    query = build_snapshot_query(11.72, 76.64, max_distance_km=50.0, now=FIXED, **kwargs)
    return query.compile(dialect=postgresql.dialect())


def test_snapshot_query_filters_location_provider_origin_and_time() -> None:
    compiled = _compile(origin="replay", provider="open-meteo")
    sql = str(compiled)
    for fragment in (
        "weather_observations.origin =",
        "weather_observations.provider =",
        "weather_observations.valid_time <=",
        "weather_observations.lat BETWEEN",
        "weather_observations.lon BETWEEN",
        "weather_observations.wind_speed_ms IS NOT NULL",
        "weather_observations.wind_dir_deg IS NOT NULL",
        "weather_observations.rh_pct IS NOT NULL",
        "weather_observations.temperature_c IS NOT NULL",
        "ORDER BY",
    ):
        assert fragment in sql, fragment
    values = list(compiled.params.values())
    assert "replay" in values
    assert "open-meteo" in values
    assert FIXED in values
    delta = 50.0 / 111.32
    floats = [value for value in values if isinstance(value, float)]
    assert any(abs(value - (11.72 - delta)) < 1e-6 for value in floats)
    assert any(abs(value - (11.72 + delta)) < 1e-6 for value in floats)


def test_snapshot_query_without_origin_or_provider() -> None:
    sql = str(_compile(origin=None, provider=None))
    assert "weather_observations.origin =" not in sql
    assert "weather_observations.provider =" not in sql


def test_snapshot_uses_row_values_without_coercion() -> None:
    connection = _FakeConnection(_row(FIXED - timedelta(minutes=10)))
    snapshot = get_weather_snapshot(11.72, 76.64, connection, now=FIXED)
    assert snapshot.wind_speed_ms == 4.5
    assert snapshot.wind_dir_deg == 270.0
    assert snapshot.rh_pct == 35.0
    assert snapshot.temperature_c == 31.0
    assert snapshot.is_stale is False
    assert snapshot.stale_age_min is None
    assert snapshot.age_min == 10  # always set, stale or not


def test_snapshot_marks_stale_rows() -> None:
    connection = _FakeConnection(_row(FIXED - timedelta(minutes=180)))
    snapshot = get_weather_snapshot(11.72, 76.64, connection, now=FIXED)
    assert snapshot.is_stale is True
    assert snapshot.stale_age_min == 180
    assert snapshot.age_min == 180


def test_snapshot_age_is_never_negative() -> None:
    connection = _FakeConnection(_row(FIXED + timedelta(seconds=30)))
    snapshot = get_weather_snapshot(11.72, 76.64, connection, now=FIXED)
    assert snapshot.age_min == 0


def test_snapshot_raises_lookup_error_when_no_complete_row() -> None:
    connection = _FakeConnection(None)
    with pytest.raises(LookupError) as excinfo:
        get_weather_snapshot(
            11.72, 76.64, connection, origin="replay", provider="open-meteo", now=FIXED
        )
    assert "replay" in str(excinfo.value)
    assert "open-meteo" in str(excinfo.value)


@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose PostgreSQL")
def test_live_query_prefers_matching_origin_and_location() -> None:
    engine = create_db_engine(load_settings().database_url.get_secret_value())
    provider = f"test-weather-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    rows = (
        ("replay", 11.72, 76.64, 4.0, now - timedelta(minutes=10)),
        ("live", 11.72, 76.64, 9.0, now - timedelta(minutes=5)),
        ("replay", 20.0, 80.0, 7.0, now - timedelta(minutes=1)),
    )
    try:
        with engine.begin() as connection:
            for origin, lat, lon, wind, valid_time in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO weather_observations
                            (provider, lat, lon, valid_time, issued_at, is_forecast,
                             temperature_c, rh_pct, wind_speed_ms, wind_dir_deg,
                             origin, freshness_status)
                        VALUES
                            (:provider, :lat, :lon, :valid_time, :valid_time, false,
                             30.0, 40.0, :wind, 90.0, CAST(:origin AS data_origin), 'fresh')
                        """
                    ),
                    {
                        "provider": provider,
                        "lat": lat,
                        "lon": lon,
                        "valid_time": valid_time,
                        "wind": wind,
                        "origin": origin,
                    },
                )
        snapshot = get_weather_snapshot(
            11.72, 76.64, engine, origin="replay", provider=provider
        )
        assert snapshot.wind_speed_ms == 4.0
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM weather_observations WHERE provider = :provider"),
                {"provider": provider},
            )
        engine.dispose()

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_weather.agent import get_weather_snapshot
from dotenv import load_dotenv
from ingest_worker.weather.parser import parse_open_meteo
from ingest_worker.weather.service import ingest_weather
from sqlalchemy import create_engine, text
from wildfire_core.clock import SimClock

load_dotenv()

LAT, LON = 11.72, 76.64


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_live_observation_flows_from_parser_to_scoped_snapshot() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    now = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
    payload = json.loads(Path("tests/fixtures/open_meteo/observation_sample.json").read_text())
    observations = parse_open_meteo(payload, SimClock(now), origin="live")
    valid_times = [o.valid_time for o in observations]
    try:
        assert ingest_weather(engine, observations) == 2
        snapshot = get_weather_snapshot(
            LAT, LON, engine, origin="live", provider="open-meteo", now=now
        )
        assert snapshot.valid_time == datetime(2026, 1, 1, 8, tzinfo=UTC)
        assert snapshot.wind_speed_ms == 3.8
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM weather_observations
                    WHERE provider = 'open-meteo' AND lat = :lat AND lon = :lon
                      AND valid_time = ANY(:times)
                    """
                ),
                {"lat": LAT, "lon": LON, "times": valid_times},
            )
        engine.dispose()

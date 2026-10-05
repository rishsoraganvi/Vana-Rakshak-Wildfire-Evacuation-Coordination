from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.engine import Engine
from wildfire_core.db.repositories import upsert_weather
from wildfire_core.schemas.monitoring import WeatherObservation


def ingest_weather(engine: Engine, observations: Iterable[WeatherObservation]) -> int:
    count = 0
    for observation in observations:
        upsert_weather(engine, observation)
        count += 1
    return count

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.engine import Connection, Engine
from wildfire_core.db.models import weather_observations
from wildfire_core.schemas.phase2 import WeatherSnapshot


def get_weather_snapshot(
    lat: float,
    lon: float,
    connection_or_engine: Connection | Engine | None = None,
) -> WeatherSnapshot:
    stmt = (
        select(weather_observations)
        .where(weather_observations.c.is_forecast.is_(False))
        .order_by(desc(weather_observations.c.valid_time))
        .limit(1)
    )

    if connection_or_engine is None:
        from wildfire_core.config import load_settings
        from wildfire_core.db.session import create_db_engine

        settings = load_settings()
        engine = create_db_engine(settings.database_url.get_secret_value())
        with engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
    elif isinstance(connection_or_engine, Engine):
        with connection_or_engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
    else:
        row = connection_or_engine.execute(stmt).mappings().first()

    if row is None:
        raise RuntimeError("No weather observations found")

    valid_time: datetime = row["valid_time"]
    if valid_time.tzinfo is None:
        valid_time = valid_time.replace(tzinfo=UTC)

    now_utc = datetime.now(UTC)
    age_min = (now_utc - valid_time).total_seconds() / 60.0
    is_stale = age_min > 90

    return WeatherSnapshot(
        valid_time=valid_time,
        wind_speed_ms=float(row["wind_speed_ms"] or 0.0),
        wind_dir_deg=float(row["wind_dir_deg"] or 0.0),
        rh_pct=float(row["rh_pct"] or 0.0),
        temperature_c=float(row["temperature_c"] or 0.0),
        is_stale=is_stale,
        stale_age_min=int(age_min) if is_stale else None,
    )

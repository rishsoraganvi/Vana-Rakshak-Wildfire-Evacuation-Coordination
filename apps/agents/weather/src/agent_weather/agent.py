from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, desc, func, select
from sqlalchemy.engine import Connection, Engine
from wildfire_core.db.models import weather_observations
from wildfire_core.schemas.phase2 import WeatherSnapshot

DEFAULT_MAX_DISTANCE_KM = 50.0
_KM_PER_DEGREE = 111.32
_STALE_AFTER_MIN = 90


def build_snapshot_query(
    lat: float,
    lon: float,
    *,
    origin: str | None,
    provider: str | None,
    max_distance_km: float,
    now: datetime,
) -> Select[Any]:
    """Newest complete, non-future observation nearest to (lat, lon).

    Rows with any NULL measurement are skipped rather than zero-filled.
    """
    obs = weather_observations
    dlat = max_distance_km / _KM_PER_DEGREE
    dlon = dlat / max(math.cos(math.radians(lat)), 0.01)
    stmt = (
        select(obs)
        .where(
            obs.c.is_forecast.is_(False),
            obs.c.valid_time <= now,
            obs.c.lat.between(lat - dlat, lat + dlat),
            obs.c.lon.between(lon - dlon, lon + dlon),
            obs.c.wind_speed_ms.is_not(None),
            obs.c.wind_dir_deg.is_not(None),
            obs.c.rh_pct.is_not(None),
            obs.c.temperature_c.is_not(None),
        )
        .order_by(
            (obs.c.lat - lat) * (obs.c.lat - lat)
            + ((obs.c.lon - lon) * func.cos(func.radians(obs.c.lat)))
            * ((obs.c.lon - lon) * func.cos(func.radians(obs.c.lat))),
            desc(obs.c.valid_time),
        )
        .limit(1)
    )
    if provider is not None:
        stmt = stmt.where(obs.c.provider == provider)
    if origin is not None:
        stmt = stmt.where(obs.c.origin == origin)
    return stmt


def get_weather_snapshot(
    lat: float,
    lon: float,
    connection_or_engine: Connection | Engine | None = None,
    *,
    origin: str | None = None,
    provider: str | None = None,
    max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    now: datetime | None = None,
) -> WeatherSnapshot:
    now_utc = now if now is not None else datetime.now(UTC)
    stmt = build_snapshot_query(
        lat,
        lon,
        origin=origin,
        provider=provider,
        max_distance_km=max_distance_km,
        now=now_utc,
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
        raise LookupError(
            f"No complete weather observation within {max_distance_km} km of "
            f"({lat:.4f}, {lon:.4f}) for origin={origin!r}, provider={provider!r}"
        )

    valid_time: datetime = row["valid_time"]
    if valid_time.tzinfo is None:
        valid_time = valid_time.replace(tzinfo=UTC)

    age_min = (now_utc - valid_time).total_seconds() / 60.0
    is_stale = age_min > _STALE_AFTER_MIN

    return WeatherSnapshot(
        valid_time=valid_time,
        wind_speed_ms=float(row["wind_speed_ms"]),
        wind_dir_deg=float(row["wind_dir_deg"]),
        rh_pct=float(row["rh_pct"]),
        temperature_c=float(row["temperature_c"]),
        is_stale=is_stale,
        stale_age_min=int(age_min) if is_stale else None,
        age_min=max(0, int(age_min)),
    )

from __future__ import annotations

from sqlalchemy import Engine, func, text
from sqlalchemy.dialects.postgresql import insert

from wildfire_core.schemas.monitoring import HotspotObservation, WeatherObservation

from .models import hotspots, weather_observations


def upsert_hotspot(engine: Engine, observation: HotspotObservation) -> None:
    values = {
        "source": observation.source,
        "acq_datetime": observation.acq_datetime,
        "lat": observation.lat,
        "lon": observation.lon,
        "brightness": observation.brightness,
        "frp": observation.frp,
        "confidence": observation.confidence,
        "daynight": observation.daynight,
        "scan": observation.scan,
        "track": observation.track,
        "origin": observation.meta.origin,
        "raw": observation.meta.raw_payload,
        "ingested_at": observation.meta.ingested_at,
        "geom": func.ST_SetSRID(func.ST_MakePoint(observation.lon, observation.lat), 4326),
    }
    statement = insert(hotspots).values(**values).on_conflict_do_update(
        index_elements=["source", "acq_datetime", "lat", "lon"],
        set_={key: values[key] for key in ("raw", "origin", "ingested_at", "frp", "brightness")},
    )
    with engine.begin() as connection:
        connection.execute(statement)


def upsert_weather(engine: Engine, observation: WeatherObservation) -> None:
    values = {
        "provider": observation.provider,
        "lat": observation.lat,
        "lon": observation.lon,
        "valid_time": observation.valid_time,
        "issued_at": observation.issued_at,
        "is_forecast": observation.is_forecast,
        "temperature_c": observation.temperature_c,
        "rh_pct": observation.rh_pct,
        "wind_speed_ms": observation.wind_speed_ms,
        "wind_dir_deg": observation.wind_dir_deg,
        "wind_gust_ms": observation.wind_gust_ms,
        "precip_mm": observation.precip_mm,
        "origin": observation.meta.origin,
    }
    statement = insert(weather_observations).values(**values).on_conflict_do_update(
        index_elements=["provider", "lat", "lon", "valid_time", "issued_at"],
        set_={key: values[key] for key in ("origin", "temperature_c", "rh_pct", "wind_speed_ms")},
    )
    with engine.begin() as connection:
        connection.execute(statement)


def count_rows(engine: Engine, table_name: str) -> int:
    allowed = {"hotspots", "weather_observations", "incidents", "triggers"}
    if table_name not in allowed:
        raise ValueError("unsupported table")
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())

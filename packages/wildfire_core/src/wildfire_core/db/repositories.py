from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import Engine, func, text
from sqlalchemy.dialects.postgresql import insert

from wildfire_core.schemas.monitoring import HotspotObservation, WeatherObservation
from wildfire_core.schemas.state import SharedState
from wildfire_core.seed import ShelterSeedRow

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
        "freshness_status": observation.meta.freshness.status,
        "freshness_age_seconds": observation.meta.freshness.age_seconds,
        "freshness_threshold_seconds": observation.meta.freshness.threshold_seconds,
        "ingested_at": observation.meta.ingested_at,
        "geom": func.ST_SetSRID(func.ST_MakePoint(observation.lon, observation.lat), 4326),
    }
    statement = insert(hotspots).values(**values).on_conflict_do_update(
        index_elements=["source", "acq_datetime", "lat", "lon"],
        set_={
            key: values[key]
            for key in (
                "raw", "origin", "ingested_at", "frp", "brightness",
                "freshness_status", "freshness_age_seconds", "freshness_threshold_seconds",
            )
        },
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
        "raw": observation.meta.raw_payload,
        "freshness_status": observation.meta.freshness.status,
        "freshness_age_seconds": observation.meta.freshness.age_seconds,
        "freshness_threshold_seconds": observation.meta.freshness.threshold_seconds,
    }
    statement = insert(weather_observations).values(**values).on_conflict_do_update(
        index_elements=["provider", "lat", "lon", "valid_time", "issued_at"],
        set_={
            key: values[key]
            for key in (
                "origin", "temperature_c", "rh_pct", "wind_speed_ms", "raw",
                "freshness_status", "freshness_age_seconds", "freshness_threshold_seconds",
            )
        },
    )
    with engine.begin() as connection:
        connection.execute(statement)


def count_rows(engine: Engine, table_name: str) -> int:
    allowed = {"hotspots", "weather_observations", "incidents", "triggers"}
    if table_name not in allowed:
        raise ValueError("unsupported table")
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())


def save_shared_state(engine: Engine, state: SharedState) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO shared_state_snapshots (incident_id, version, state)
                VALUES (:incident_id, :version, CAST(:state AS jsonb))
                """
            ),
            {
                "incident_id": state.incident_id,
                "version": state.version,
                "state": state.model_dump_json(),
            },
        )


_UPSERT_SHELTERS_SQL = """
    INSERT INTO shelters (
        external_ref, name, kind, geom, capacity, usable_factor,
        capacity_source, is_simulated, metadata
    )
    VALUES (
        :external_ref, :name, :kind,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
        :capacity, :usable_factor, :capacity_source, :is_simulated,
        CAST(:metadata AS jsonb)
    )
    ON CONFLICT (external_ref) DO UPDATE SET
        name = EXCLUDED.name,
        kind = EXCLUDED.kind,
        geom = EXCLUDED.geom,
        capacity = EXCLUDED.capacity,
        usable_factor = EXCLUDED.usable_factor,
        capacity_source = EXCLUDED.capacity_source,
        is_simulated = EXCLUDED.is_simulated,
        metadata = EXCLUDED.metadata,
        updated_at = now()
"""


def upsert_shelters(engine: Engine, rows: Sequence[ShelterSeedRow]) -> int:
    """Idempotently load shelter seed rows keyed on external_ref.

    Occupancy is deliberately absent from the update set: it changes only through
    ``agent_shelter.registry.update_occupancy`` (D-03).
    """
    with engine.begin() as connection:
        for row in rows:
            connection.execute(
                text(_UPSERT_SHELTERS_SQL),
                {
                    "external_ref": row.external_ref,
                    "name": row.name,
                    "kind": row.kind,
                    "lat": row.lat,
                    "lon": row.lon,
                    "capacity": row.capacity,
                    "usable_factor": row.usable_factor,
                    "capacity_source": row.capacity_source,
                    "is_simulated": row.is_simulated,
                    "metadata": json.dumps({"notes": row.notes}),
                },
            )
    return len(rows)

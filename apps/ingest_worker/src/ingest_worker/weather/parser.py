from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from wildfire_core.clock import Clock
from wildfire_core.schemas.metadata import Freshness
from wildfire_core.schemas.monitoring import WeatherObservation

DATA_ORIGINS = frozenset({"live", "replay", "simulated", "manual"})


def parse_open_meteo(
    payload: dict[str, Any],
    clock: Clock,
    *,
    origin: str,
) -> list[WeatherObservation]:
    """Normalise an Open-Meteo hourly payload.

    Hours at or before ``issued_at`` are observations (``is_forecast`` False); later
    hours are forecasts. ``origin`` is mandatory so no caller silently labels live
    data as replay (WR-03).
    """
    if origin not in DATA_ORIGINS:
        raise ValueError(f"origin must be one of {sorted(DATA_ORIGINS)}, got {origin!r}")
    hourly = payload["hourly"]
    times = hourly["time"]
    issued_at = datetime.fromisoformat(payload.get("issued_at", clock.now_utc().isoformat()))
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    issued_at = issued_at.astimezone(UTC)
    ingested_at = clock.now_utc()
    result: list[WeatherObservation] = []
    for index, raw_time in enumerate(times):
        valid_time = datetime.fromisoformat(raw_time)
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=UTC)
        valid_time = valid_time.astimezone(UTC)
        result.append(
            WeatherObservation(
                meta={
                    "provider": "open-meteo",
                    "origin": origin,
                    "observed_at": valid_time,
                    "issued_at": issued_at,
                    "valid_time": valid_time,
                    "ingested_at": ingested_at,
                    "freshness": Freshness(status="fresh", age_seconds=0).model_dump(),
                    "raw_payload": payload,
                },
                provider="open-meteo",
                lat=float(payload["latitude"]),
                lon=float(payload["longitude"]),
                valid_time=valid_time,
                issued_at=issued_at,
                is_forecast=valid_time > issued_at,
                temperature_c=_value(hourly, "temperature_2m", index),
                rh_pct=_value(hourly, "relative_humidity_2m", index),
                wind_speed_ms=_value(hourly, "wind_speed_10m", index),
                wind_dir_deg=_value(hourly, "wind_direction_10m", index),
                wind_gust_ms=_value(hourly, "wind_gusts_10m", index),
                precip_mm=_value(hourly, "precipitation", index),
            )
        )
    return result


def _value(hourly: dict[str, Any], key: str, index: int) -> float | None:
    values = hourly.get(key)
    if values is None or values[index] is None:
        return None
    return float(values[index])

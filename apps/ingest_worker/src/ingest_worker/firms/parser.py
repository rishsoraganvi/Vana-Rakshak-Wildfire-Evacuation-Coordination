from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

from wildfire_core.clock import Clock
from wildfire_core.schemas.metadata import Freshness
from wildfire_core.schemas.monitoring import HotspotObservation


def _number(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "").strip()
    return float(value) if value else None


def parse_firms_csv(
    payload: str,
    clock: Clock,
    *,
    origin: str = "replay",
) -> list[HotspotObservation]:
    observations: list[HotspotObservation] = []
    ingested_at = clock.now_utc()
    for row in csv.DictReader(io.StringIO(payload)):
        acq_datetime = datetime.strptime(
            f"{row['acq_date']} {row['acq_time']}", "%Y-%m-%d %H%M"
        ).replace(tzinfo=UTC)
        meta = {
            "provider": "firms",
            "origin": origin,
            "observed_at": acq_datetime,
            "ingested_at": ingested_at,
            "freshness": Freshness(status="fresh", age_seconds=0).model_dump(),
            "raw_payload": dict(row),
        }
        observations.append(
            HotspotObservation(
                meta=meta,
                source=row["satellite"],
                acq_datetime=acq_datetime,
                lat=float(row["latitude"]),
                lon=float(row["longitude"]),
                brightness=_number(row, "bright_ti4"),
                frp=_number(row, "frp"),
                confidence=row.get("confidence") or None,
                daynight=row.get("daynight") or None,
                scan=_number(row, "scan"),
                track=_number(row, "track"),
            )
        )
    return observations

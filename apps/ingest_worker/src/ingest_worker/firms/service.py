from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.engine import Engine
from wildfire_core.db.repositories import upsert_hotspot
from wildfire_core.schemas.monitoring import HotspotObservation

from .dedupe import deduplicate


def ingest_hotspots(engine: Engine, observations: Iterable[HotspotObservation]) -> int:
    unique = deduplicate(observations)
    for observation in unique:
        upsert_hotspot(engine, observation)
    return len(unique)

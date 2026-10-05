from __future__ import annotations

from collections.abc import Iterable

from wildfire_core.schemas.monitoring import HotspotObservation


def deduplicate(observations: Iterable[HotspotObservation]) -> list[HotspotObservation]:
    unique: dict[tuple[object, ...], HotspotObservation] = {}
    for observation in observations:
        unique[observation.dedupe_key] = observation
    return list(unique.values())

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from .schemas.metadata import Freshness
from .schemas.state import SharedState


def classify_freshness(
    observed_at: datetime | None, now: datetime, threshold_seconds: float
) -> Freshness:
    if observed_at is None:
        return Freshness(status="unavailable", threshold_seconds=threshold_seconds)
    if observed_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("freshness timestamps must be timezone-aware")
    age_seconds = max(
        0.0, (now.astimezone(UTC) - observed_at.astimezone(UTC)).total_seconds()
    )
    status: Literal["fresh", "stale"] = "fresh" if age_seconds <= threshold_seconds else "stale"
    return Freshness(status=status, age_seconds=age_seconds, threshold_seconds=threshold_seconds)


class SnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, int], SharedState] = {}

    def put(self, state: SharedState) -> None:
        self._snapshots[(state.incident_id, state.version)] = state

    def latest(self, incident_id: str) -> SharedState | None:
        versions = [state for (key, _), state in self._snapshots.items() if key == incident_id]
        return max(versions, key=lambda item: item.version) if versions else None

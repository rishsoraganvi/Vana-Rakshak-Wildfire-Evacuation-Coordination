from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...


class RealClock:
    def now_utc(self) -> datetime:
        return datetime.now(UTC)


class SimClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("SimClock requires a timezone-aware datetime")
        self._current = current.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta

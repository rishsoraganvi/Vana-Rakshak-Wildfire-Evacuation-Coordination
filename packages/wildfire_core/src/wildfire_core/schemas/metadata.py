from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Origin = Literal["live", "replay", "simulated", "manual"]
FreshnessStatus = Literal["fresh", "stale", "unavailable"]


class Freshness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FreshnessStatus
    age_seconds: float | None = Field(default=None, ge=0)
    threshold_seconds: float | None = Field(default=None, gt=0)


class ObservationMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    origin: Origin
    observed_at: datetime
    issued_at: datetime | None = None
    valid_time: datetime | None = None
    ingested_at: datetime
    freshness: Freshness
    schema_version: str = "1.0"
    raw_payload: dict[str, Any] | None = None

    @field_validator("observed_at", "issued_at", "valid_time", "ingested_at")
    @classmethod
    def require_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC) if value is not None else None

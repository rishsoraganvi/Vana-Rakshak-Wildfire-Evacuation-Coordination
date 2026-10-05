from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .metadata import ObservationMeta


class HotspotObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: ObservationMeta
    source: str
    acq_datetime: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    brightness: float | None = None
    frp: float | None = None
    confidence: str | None = None
    daynight: str | None = None
    scan: float | None = None
    track: float | None = None

    @field_validator("acq_datetime")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("acquisition time must be timezone-aware")
        return value

    @property
    def dedupe_key(self) -> tuple[str, datetime, float, float]:
        return self.source, self.acq_datetime, self.lat, self.lon


class WeatherObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: ObservationMeta
    provider: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    valid_time: datetime
    issued_at: datetime
    is_forecast: bool
    temperature_c: float | None = None
    rh_pct: float | None = Field(default=None, ge=0, le=100)
    wind_speed_ms: float | None = Field(default=None, ge=0)
    wind_dir_deg: float | None = Field(default=None, ge=0, le=360)
    wind_gust_ms: float | None = Field(default=None, ge=0)
    precip_mm: float | None = Field(default=None, ge=0)

    @property
    def dedupe_key(self) -> tuple[str, float, float, datetime, datetime]:
        return self.provider, self.lat, self.lon, self.valid_time, self.issued_at

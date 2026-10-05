from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .metadata import Freshness


class FireRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    aoi_reference: str = Field(min_length=1)
    hotspot_references: tuple[str, ...] = Field(min_length=1)
    weather_references: tuple[str, ...] = Field(min_length=1)
    horizons_min: tuple[int, ...] = (60, 180, 360)
    parameters: dict[str, float]
    seed: int

    @model_validator(mode="after")
    def validate_horizons(self) -> FireRunInput:
        if self.horizons_min != (60, 180, 360):
            raise ValueError("horizons must be exactly 60, 180, 360 minutes")
        return self


class FirePerimeter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["current", "forecast_p50", "forecast_p90"]
    horizon_min: int = Field(ge=0)
    geometry_wkt: str = Field(min_length=1)
    area_ha: float = Field(ge=0)
    spread_rate_m_per_h: float | None = Field(default=None, ge=0)
    spread_dir_deg: float | None = Field(default=None, ge=0, le=360)
    freshness: Freshness


class SettlementRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_id: str
    exposure: Literal["inside_p50", "inside_p90", "buffer_only"]
    eta_minutes: int | None = Field(default=None, ge=0)
    population_at_risk: int | None = Field(default=None, ge=0)


class FireRunOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    seed: int
    perimeters: tuple[FirePerimeter, ...] = Field(min_length=1)
    confidence_label: Literal["low", "medium", "high"]
    settlement_risks: tuple[SettlementRisk, ...] = ()

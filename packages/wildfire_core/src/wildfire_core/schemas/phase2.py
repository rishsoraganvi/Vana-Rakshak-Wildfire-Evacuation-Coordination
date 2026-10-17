from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HotspotCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    centroid_lat: float = Field(ge=-90, le=90)
    centroid_lon: float = Field(ge=-180, le=180)
    point_count: int = Field(ge=1)
    mean_frp: float | None = Field(default=None, ge=0)
    bbox_west: float
    bbox_south: float
    bbox_east: float
    bbox_north: float
    hotspot_ids: tuple[str, ...] = ()


class WeatherSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_time: datetime
    wind_speed_ms: float = Field(ge=0)
    wind_dir_deg: float = Field(ge=0, le=360)
    rh_pct: float = Field(ge=0, le=100)
    temperature_c: float
    is_stale: bool = False
    stale_age_min: int | None = None


class SettlementRisk2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_id: str
    settlement_name: str
    exposure: Literal[
        "inside_p50_1h",
        "inside_p50_3h",
        "inside_p50_6h",
        "inside_p90_1h",
        "inside_p90_3h",
        "inside_p90_6h",
        "buffer_only",
    ]
    eta_minutes: int | None = Field(default=None, ge=0)
    population_estimate: int | None = Field(default=None, ge=0)


class FireSpreadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    cluster_id: str
    seeds_used: tuple[int, ...] = (42, 43, 44)
    current_perimeter_wkt: str
    p50_1h_wkt: str
    p50_3h_wkt: str
    p50_6h_wkt: str
    p90_1h_wkt: str
    p90_3h_wkt: str
    p90_6h_wkt: str
    affected_area_km2: float = Field(ge=0)
    spread_direction_deg: float | None = Field(
        ge=0,
        le=360,
        description=(
            "Bearing of P50 front movement; "
            "None when the P50 centroid shift is below one grid cell"
        ),
    )
    spread_rate_m_per_h: float = Field(ge=0)
    confidence: Literal["low", "medium", "high"]
    settlements_at_risk: tuple[SettlementRisk2, ...] = ()


class RouteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    group_id: str
    origin_settlement_id: str | None = None
    origin_cluster_id: str | None = None
    destination_shelter_id: str | None = None
    osm_node_path: tuple[int, ...] = Field(min_length=2)
    total_distance_m: float = Field(ge=0)
    estimated_travel_time_s: float = Field(ge=0)
    safety_classification: Literal["safe", "caution", "blocked"]
    fire_penalty_edges: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_origin(self) -> Self:
        if (self.origin_settlement_id is None) == (self.origin_cluster_id is None):
            raise ValueError("exactly one of origin_settlement_id or origin_cluster_id is required")
        return self


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    run_id: str
    node_name: str
    inputs_json: str
    outputs_json: str
    latency_ms: int = Field(ge=0)
    model_metadata: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CoordinatorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    run_id: str
    status: Literal["draft", "failed"] = "draft"
    fire_result: FireSpreadResult
    weather_snapshot: WeatherSnapshot
    clusters: tuple[HotspotCluster, ...]
    routes: tuple[RouteResult, ...]
    rationale_md: str
    is_llm_fallback: bool = False
    warnings: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

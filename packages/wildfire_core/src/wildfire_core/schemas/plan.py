"""Phase 3 typed contracts: groups, shelters, routes, validators and the integrated plan.

Plan-level models are frozen (immutable in the app layer, PLAN-08), forbid unknown fields and
use tuples for collections. Phase 2 ``CoordinatorPlan`` stays only for legacy ``plan_data``
readers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot

Horizon = Literal[1, 3, 6]
StrategyName = Literal["next_path", "rematch", "split"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SettlementRecord(_Frozen):
    settlement_id: str
    external_ref: str | None = None
    name: str
    kind: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    population: int | None = Field(default=None, ge=0)
    pop_source: str | None = None
    buffer_m: int = Field(ge=0)
    is_simulated: bool = False


class ShelterRecord(_Frozen):
    shelter_id: str
    external_ref: str | None = None
    name: str
    kind: Literal["school", "community_hall", "other"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    capacity: int = Field(gt=0)
    usable_factor: float | None = Field(default=None, gt=0, le=1)
    occupancy: int = Field(ge=0)
    capacity_source: str = Field(min_length=1)
    is_active: bool = True
    is_simulated: bool = False


class ShelterCandidate(_Frozen):
    shelter_id: str
    name: str
    kind: Literal["school", "community_hall", "other"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    usable_capacity: int = Field(ge=0)
    occupancy: int = Field(ge=0)
    available: int = Field(ge=0)
    capacity_source: str = Field(min_length=1)
    is_simulated: bool = False
    node: int | None = None

    @model_validator(mode="after")
    def available_matches_capacity(self) -> Self:
        expected = max(0, self.usable_capacity - self.occupancy)
        if self.available != expected:
            raise ValueError(
                f"available must equal max(0, usable_capacity - occupancy) = {expected}"
            )
        return self


class ExcludedShelter(_Frozen):
    shelter_id: str
    reason: Literal["inactive", "inside_exclusion_zone", "no_capacity", "off_network"]


class EvacueeGroup(_Frozen):
    group_id: str
    settlement_id: str
    settlement_name: str
    persons: int = Field(ge=1)
    priority: int = Field(ge=1, le=3)
    eta_min: float = Field(ge=0)
    exposure: Literal["buffer_in_current", "inside_p50_1h", "inside_p50_3h", "inside_p50_6h"]
    origin_node: int | None = None
    is_simulated: bool = False
    pop_source: str | None = None

    @model_validator(mode="after")
    def group_keyed_on_settlement(self) -> Self:
        if self.group_id != self.settlement_id:
            raise ValueError("group_id must equal settlement_id")
        return self


class PlanAlert(_Frozen):
    kind: Literal[
        "needs_rescue_response",
        "p90_only_exposure",
        "population_unknown",
        "weather_unavailable",
        "specialist_unavailable",
        "unroutable_group",
    ]
    message: str
    settlement_id: str | None = None
    # Named when ``message`` mentions a settlement that has no evacuee group (rescue / P90-only),
    # so V8 grounding treats that name as a plan fact (grounding.NAME_KEYS).
    settlement_name: str | None = None
    cluster_id: str | None = None


class EdgeStatusEntry(_Frozen):
    u: int
    v: int
    key: int
    status: Literal["open", "congested", "unsafe", "blocked"]


class PlanRoute(_Frozen):
    route_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    group_id: str
    shelter_id: str
    persons: int = Field(ge=0)
    origin_node: int
    destination_node: int
    osm_node_path: tuple[int, ...] = Field(min_length=2)
    osm_edge_keys: tuple[int, ...]
    path_lonlat: tuple[tuple[float, float], ...] = ()
    total_distance_m: float = Field(ge=0)
    free_flow_time_s: float = Field(ge=0)
    congested_time_s: float = Field(ge=0)
    eta_min: float = Field(ge=0)
    horizon_h: Horizon
    path_rank: int = Field(ge=1)
    risk_score: float = Field(ge=0, le=1)
    safety_classification: Literal["safe", "caution"]
    p90_flag_edge_indices: tuple[int, ...] = ()
    edge_status_snapshot: tuple[EdgeStatusEntry, ...] = ()

    @model_validator(mode="after")
    def edge_keys_match_path(self) -> Self:
        if len(self.osm_edge_keys) != len(self.osm_node_path) - 1:
            raise ValueError("osm_edge_keys must have len(osm_node_path) - 1 entries")
        return self


class ShelterAssignment(_Frozen):
    shelter_id: str
    shelter_name: str
    group_id: str
    persons: int = Field(ge=0)
    usable_capacity: int = Field(ge=0)
    available_before: int = Field(ge=0)


class Dispatch(_Frozen):
    vehicle_id: str
    task: Literal["evacuate", "suppress", "medical_standby"]
    group_id: str | None = None
    eta_min: float = Field(ge=0)


class ViolationRecord(_Frozen):
    code: str
    detail: str
    group_id: str | None = None
    shelter_id: str | None = None
    edge: EdgeStatusEntry | None = None


class ValidationResult(_Frozen):
    validator_id: Literal["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"]
    status: Literal["pass", "fail", "flag", "replaced"]
    reasons: tuple[str, ...] = ()
    violations: tuple[ViolationRecord, ...] = ()

    @model_validator(mode="after")
    def status_allowed_for_validator(self) -> Self:
        if self.status == "replaced" and self.validator_id != "V8":
            raise ValueError("status 'replaced' is only valid for V8")
        if self.status == "flag" and self.validator_id != "V3":
            raise ValueError("status 'flag' is only valid for V3")
        if self.status == "fail" and not self.reasons:
            raise ValueError("a failing validator needs at least one reason")
        return self


_V1_TO_V7 = ("V1", "V2", "V3", "V4", "V5", "V6", "V7")
_V1_TO_V8 = (*_V1_TO_V7, "V8")


def _no_failing_validator(validation: tuple[ValidationResult, ...]) -> None:
    failing = [item.validator_id for item in validation if item.status == "fail"]
    if failing:
        raise ValueError(f"validators failing: {', '.join(failing)}")


class ClusterRisk(_Frozen):
    cluster_id: str
    affected_area_ha: float = Field(ge=0)
    spread_dir_deg: float | None = Field(default=None, ge=0, le=360)
    spread_rate_m_per_h: float = Field(ge=0)
    confidence: Literal["low", "medium", "high"]


class ShelterSnapshot(_Frozen):
    shelter_id: str
    occupancy: int = Field(ge=0)
    usable_capacity: int = Field(ge=0)
    is_active: bool
    capacity_source: str


class ForecastFootprint(_Frozen):
    current_wkt: str
    p50_1h_wkt: str
    p50_3h_wkt: str
    p50_6h_wkt: str
    p90_1h_wkt: str
    p90_3h_wkt: str
    p90_6h_wkt: str
    fire_run_ids: tuple[str, ...] = ()
    cluster_ids: tuple[str, ...] = ()


class PlanFreshness(_Frozen):
    computed_at: datetime
    firms_age_min: int | None = Field(default=None, ge=0)
    weather_age_min_by_cluster: dict[str, int] = Field(default_factory=dict)
    weather_age_min_max: int | None = Field(default=None, ge=0)
    graph_built_at: datetime | None = None
    stale_inputs: tuple[str, ...] = ()


class PlanProvenance(_Frozen):
    run_id: str
    trigger_id: str | None = None
    state_version: int = Field(ge=0)
    hotspot_ids: tuple[str, ...] = ()
    cluster_ids: tuple[str, ...] = ()
    fire_run_ids: tuple[str, ...] = ()
    fire_seeds: tuple[int, ...] = ()
    weather_valid_times: dict[str, datetime] = Field(default_factory=dict)
    weather_provider: str
    graph_source: str
    graph_mtime: datetime | None = None
    graph_node_count: int = Field(ge=0)
    graph_edge_count: int = Field(ge=0)
    shelter_snapshot: tuple[ShelterSnapshot, ...] = ()
    settlement_sources: dict[str, str] = Field(default_factory=dict)
    params: dict[str, float | int | str | list[str]] = Field(default_factory=dict)
    llm_metadata: dict[str, Any] | None = None


class ResolverStep(_Frozen):
    loop: int = Field(ge=1, le=3)
    strategy: StrategyName
    chosen_by: Literal["deterministic", "llm"]
    target_group_ids: tuple[str, ...] = ()
    outcome: Literal["resolved", "still_failing", "not_applicable"]


class PlanDraft(_Frozen):
    incident_id: str
    run_id: str
    outcome: Literal["valid", "failed"]
    clusters: tuple[HotspotCluster, ...] = ()
    fire_results: tuple[FireSpreadResult, ...] = ()
    weather_by_cluster: dict[str, WeatherSnapshot] = Field(default_factory=dict)
    footprint: ForecastFootprint
    risk: tuple[ClusterRisk, ...] = ()
    groups: tuple[EvacueeGroup, ...] = ()
    routes: tuple[PlanRoute, ...] = ()
    shelter_assignments: tuple[ShelterAssignment, ...] = ()
    dispatches: tuple[Dispatch, ...] = ()
    alerts: tuple[PlanAlert, ...] = ()
    warnings: tuple[str, ...] = ()
    validation: tuple[ValidationResult, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    used_fallback: bool = False
    resolver_steps: tuple[ResolverStep, ...] = ()
    congestion_passes_used: int = Field(default=0, ge=0)
    max_vc_ratio: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def outcome_invariants(self) -> Self:
        if self.outcome == "valid":
            present = {item.validator_id for item in self.validation}
            missing = [vid for vid in _V1_TO_V7 if vid not in present]
            if missing:
                raise ValueError(f"valid draft is missing validators: {', '.join(missing)}")
            _no_failing_validator(self.validation)
        else:
            if not self.failure_reasons:
                raise ValueError("failed draft needs at least one failure reason")
            if self.routes or self.shelter_assignments:
                raise ValueError("failed draft must carry no routes or shelter assignments")
        return self


class IntegratedPlan(_Frozen):
    plan_schema_version: Literal["3.0"] = "3.0"
    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    incident_id: str
    run_id: str
    version: int | None = Field(default=None, ge=1)
    parent_plan_id: str | None = None
    status: Literal["pending_review", "failed"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_until: datetime
    freshness: PlanFreshness
    provenance: PlanProvenance
    risk: tuple[ClusterRisk, ...] = ()
    clusters: tuple[HotspotCluster, ...] = ()
    fire_results: tuple[FireSpreadResult, ...] = ()
    weather_by_cluster: dict[str, WeatherSnapshot] = Field(default_factory=dict)
    footprint: ForecastFootprint
    groups: tuple[EvacueeGroup, ...] = ()
    routes: tuple[PlanRoute, ...] = ()
    shelter_assignments: tuple[ShelterAssignment, ...] = ()
    dispatches: tuple[Dispatch, ...] = ()
    alerts: tuple[PlanAlert, ...] = ()
    warnings: tuple[str, ...] = ()
    validation: tuple[ValidationResult, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    used_fallback: bool = False
    resolver_steps: tuple[ResolverStep, ...] = ()
    congestion_passes_used: int = Field(default=0, ge=0)
    max_vc_ratio: float = Field(default=0.0, ge=0)
    rationale_md: str = ""
    rationale_source: Literal["llm", "template"] = "template"
    is_llm_fallback: bool = False
    is_simulated: bool = False

    @model_validator(mode="after")
    def status_invariants(self) -> Self:
        if self.status == "pending_review":
            # S5: no plan reaches review unless V1..V8 all ran, in order, and none failed.
            if tuple(item.validator_id for item in self.validation) != _V1_TO_V8:
                raise ValueError("pending_review requires exactly validators V1..V8 in order")
            _no_failing_validator(self.validation)
            if self.failure_reasons:
                raise ValueError("pending_review must have no failure_reasons")
        else:
            # D-11: a failed plan carries nothing approvable.
            if self.routes or self.shelter_assignments:
                raise ValueError("failed plan must carry no routes or shelter assignments")
            if not self.failure_reasons:
                raise ValueError("failed plan needs at least one failure reason")
        return self


class PlanDiff(_Frozen):
    assignments_added: tuple[str, ...] = ()
    assignments_removed: tuple[str, ...] = ()
    assignments_changed: tuple[str, ...] = ()
    routes_changed: tuple[str, ...] = ()
    validators_changed: dict[str, tuple[str, str]] = Field(default_factory=dict)
    status_changed: tuple[str, str] | None = None
    is_material: bool = False

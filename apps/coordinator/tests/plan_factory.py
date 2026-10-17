"""Shared builders for plan assembly tests (drafts, freshness, provenance)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ForecastFootprint,
    PlanAlert,
    PlanDraft,
    PlanFreshness,
    PlanProvenance,
    PlanRoute,
    ShelterAssignment,
    ValidationResult,
    ViolationRecord,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EMPTY = "POLYGON EMPTY"
VALIDATOR_IDS = ("V1", "V2", "V3", "V4", "V5", "V6", "V7")


@dataclass(frozen=True)
class Spec:
    name: str
    persons: int
    shelter: str
    eta: float
    horizon: int = 3


def footprint() -> ForecastFootprint:
    return ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )


def validation(**overrides: ValidationResult) -> tuple[ValidationResult, ...]:
    return tuple(
        overrides.get(vid, ValidationResult(validator_id=vid, status="pass"))  # type: ignore[arg-type]
        for vid in VALIDATOR_IDS
    )


def route(group_id: str, shelter_id: str, persons: int, eta: float, horizon: int) -> PlanRoute:
    return PlanRoute(
        group_id=group_id,
        shelter_id=shelter_id,
        persons=persons,
        origin_node=11,
        destination_node=22,
        osm_node_path=(11, 33, 22),
        osm_edge_keys=(0, 0),
        path_lonlat=((76.6, 11.7), (76.7, 11.8), (76.8, 11.9)),
        total_distance_m=4321.5,
        free_flow_time_s=500.0,
        congested_time_s=600.0,
        eta_min=eta,
        horizon_h=horizon,  # type: ignore[arg-type]
        path_rank=1,
        risk_score=0.25,
        safety_classification="safe",
    )


def valid_draft(
    specs: Sequence[Spec] | None = None,
    *,
    alerts: Sequence[PlanAlert] = (),
    warnings: Sequence[str] = (),
    pop_source: str | None = None,
) -> PlanDraft:
    specs = specs or (
        Spec("Mudumalai", 120, "Gudalur School", 38.42, 3),
        Spec("Kargudi", 80, "Masinagudi Hall", 22.0, 1),
    )
    groups = tuple(
        EvacueeGroup(
            group_id=f"g{i}",
            settlement_id=f"g{i}",
            settlement_name=spec.name,
            persons=spec.persons,
            priority=1,
            eta_min=spec.eta,
            exposure="inside_p50_1h",
            pop_source=pop_source,
        )
        for i, spec in enumerate(specs)
    )
    assignments = tuple(
        ShelterAssignment(
            shelter_id=f"s{i}",
            shelter_name=spec.shelter,
            group_id=f"g{i}",
            persons=spec.persons,
            usable_capacity=spec.persons + 50,
            available_before=spec.persons + 40,
        )
        for i, spec in enumerate(specs)
    )
    routes = tuple(
        route(f"g{i}", f"s{i}", spec.persons, spec.eta, spec.horizon)
        for i, spec in enumerate(specs)
    )
    return PlanDraft(
        incident_id="inc-1",
        run_id="run-1",
        outcome="valid",
        footprint=footprint(),
        groups=groups,
        routes=routes,
        shelter_assignments=assignments,
        alerts=tuple(alerts),
        warnings=tuple(warnings),
        validation=validation(),
    )


def failed_draft(*, reasons: Sequence[str], results: Sequence[ValidationResult] = ()) -> PlanDraft:
    groups = (
        EvacueeGroup(
            group_id="g0",
            settlement_id="g0",
            settlement_name="Mudumalai",
            persons=120,
            priority=1,
            eta_min=10.0,
            exposure="inside_p50_1h",
        ),
    )
    return PlanDraft(
        incident_id="inc-1",
        run_id="run-1",
        outcome="failed",
        footprint=footprint(),
        groups=groups,
        validation=tuple(results),
        failure_reasons=tuple(reasons),
    )


def failing(vid: str, code: str, detail: str, **ids: Any) -> ValidationResult:
    return ValidationResult(
        validator_id=vid,  # type: ignore[arg-type]
        status="fail",
        reasons=(f"{code}",),
        violations=(ViolationRecord(code=code, detail=detail, **ids),),
    )


def freshness(**overrides: Any) -> PlanFreshness:
    values: dict[str, Any] = {"computed_at": NOW, "firms_age_min": 20}
    values.update(overrides)
    return PlanFreshness(**values)


def provenance(**overrides: Any) -> PlanProvenance:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "state_version": 3,
        "weather_provider": "open_meteo",
        "graph_source": "osm",
        "graph_node_count": 100,
        "graph_edge_count": 250,
    }
    values.update(overrides)
    return PlanProvenance(**values)


def valid_until() -> datetime:
    return NOW + timedelta(minutes=60)

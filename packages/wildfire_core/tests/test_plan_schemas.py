from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from wildfire_core.schemas.phase2 import AuditEntry, WeatherSnapshot
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ForecastFootprint,
    IntegratedPlan,
    PlanDraft,
    PlanFreshness,
    PlanProvenance,
    PlanRoute,
    ShelterAssignment,
    ShelterCandidate,
    ValidationResult,
)
from wildfire_core.schemas.tools import ToolError, ToolResult

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EMPTY = "POLYGON EMPTY"
VALIDATOR_IDS = ("V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8")


def _footprint() -> ForecastFootprint:
    return ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )


def _validation(**overrides: str) -> tuple[ValidationResult, ...]:
    return tuple(
        ValidationResult(validator_id=vid, status=overrides.get(vid, "pass"))  # type: ignore[arg-type]
        for vid in VALIDATOR_IDS
    )


def _group() -> EvacueeGroup:
    return EvacueeGroup(
        group_id="s1",
        settlement_id="s1",
        settlement_name="Village",
        persons=10,
        priority=1,
        eta_min=30,
        exposure="inside_p50_1h",
    )


def _route(**overrides: Any) -> PlanRoute:
    values: dict[str, Any] = {
        "group_id": "s1",
        "shelter_id": "sh1",
        "persons": 10,
        "origin_node": 1,
        "destination_node": 3,
        "osm_node_path": (1, 2, 3),
        "osm_edge_keys": (0, 0),
        "total_distance_m": 100.0,
        "free_flow_time_s": 10.0,
        "congested_time_s": 12.0,
        "eta_min": 0.2,
        "horizon_h": 1,
        "path_rank": 1,
        "risk_score": 0.1,
        "safety_classification": "safe",
    }
    values.update(overrides)
    return PlanRoute(**values)


def _assignment() -> ShelterAssignment:
    return ShelterAssignment(
        shelter_id="sh1",
        shelter_name="School",
        group_id="s1",
        persons=10,
        usable_capacity=60,
        available_before=60,
    )


def _plan(**overrides: Any) -> IntegratedPlan:
    values: dict[str, Any] = {
        "incident_id": "inc",
        "run_id": "run",
        "status": "pending_review",
        "valid_until": NOW + timedelta(minutes=60),
        "created_at": NOW,
        "freshness": PlanFreshness(computed_at=NOW),
        "provenance": PlanProvenance(
            run_id="run",
            state_version=1,
            weather_provider="open-meteo",
            graph_source="synthetic",
            graph_node_count=1,
            graph_edge_count=1,
        ),
        "footprint": _footprint(),
        "groups": (_group(),),
        "routes": (_route(),),
        "shelter_assignments": (_assignment(),),
        "validation": _validation(),
    }
    values.update(overrides)
    return IntegratedPlan(**values)


def test_valid_pending_review_plan_builds() -> None:
    plan = _plan()
    assert plan.plan_schema_version == "3.0"
    assert plan.status == "pending_review"


def test_pending_review_requires_v8() -> None:
    with pytest.raises(ValidationError):
        _plan(validation=_validation()[:7])


def test_pending_review_requires_order_v1_to_v8() -> None:
    with pytest.raises(ValidationError):
        _plan(validation=tuple(reversed(_validation())))


def test_pending_review_rejects_failing_validator() -> None:
    failing = tuple(
        ValidationResult(validator_id=v.validator_id, status="fail", reasons=("bad",))
        if v.validator_id == "V4"
        else v
        for v in _validation()
    )
    with pytest.raises(ValidationError):
        _plan(validation=failing)


def test_pending_review_rejects_failure_reasons() -> None:
    with pytest.raises(ValidationError):
        _plan(failure_reasons=("oops",))


def test_failed_plan_valid_without_content() -> None:
    plan = _plan(
        status="failed",
        routes=(),
        shelter_assignments=(),
        validation=(),
        failure_reasons=("no capacity",),
    )
    assert plan.status == "failed"


def test_failed_plan_rejects_routes_or_assignments() -> None:
    with pytest.raises(ValidationError):
        _plan(status="failed", shelter_assignments=(), failure_reasons=("x",))
    with pytest.raises(ValidationError):
        _plan(status="failed", routes=(), failure_reasons=("x",))


def test_failed_plan_requires_failure_reason() -> None:
    with pytest.raises(ValidationError):
        _plan(status="failed", routes=(), shelter_assignments=())


@pytest.mark.parametrize("missing", ["freshness", "provenance"])
def test_freshness_and_provenance_are_required(missing: str) -> None:
    values: dict[str, Any] = {
        "incident_id": "inc",
        "run_id": "run",
        "status": "failed",
        "valid_until": NOW,
        "footprint": _footprint(),
        "failure_reasons": ("x",),
        "freshness": PlanFreshness(computed_at=NOW),
        "provenance": _plan().provenance,
    }
    del values[missing]
    with pytest.raises(ValidationError):
        IntegratedPlan(**values)


def test_plan_is_frozen_and_forbids_extras() -> None:
    plan = _plan()
    with pytest.raises(ValidationError):
        plan.status = "failed"
    with pytest.raises(ValidationError):
        _plan(surprise=1)


def test_plan_json_round_trip() -> None:
    plan = _plan()
    assert IntegratedPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    ("validator_id", "status", "reasons", "ok"),
    [
        ("V8", "replaced", (), True),
        ("V3", "replaced", (), False),
        ("V3", "flag", (), True),
        ("V4", "flag", (), False),
        ("V4", "fail", ("why",), True),
        ("V4", "fail", (), False),
        ("V4", "pass", (), True),
    ],
)
def test_validation_result_rules(
    validator_id: str, status: str, reasons: tuple[str, ...], ok: bool
) -> None:
    kwargs: dict[str, Any] = {"validator_id": validator_id, "status": status, "reasons": reasons}
    if ok:
        ValidationResult(**kwargs)
    else:
        with pytest.raises(ValidationError):
            ValidationResult(**kwargs)


def test_evacuee_group_rules() -> None:
    with pytest.raises(ValidationError):
        EvacueeGroup(
            group_id="g",
            settlement_id="s",
            settlement_name="n",
            persons=5,
            priority=1,
            eta_min=1,
            exposure="inside_p50_1h",
        )
    with pytest.raises(ValidationError):
        EvacueeGroup(
            group_id="s",
            settlement_id="s",
            settlement_name="n",
            persons=0,
            priority=1,
            eta_min=1,
            exposure="inside_p50_1h",
        )


def _candidate(**overrides: Any) -> ShelterCandidate:
    values: dict[str, Any] = {
        "shelter_id": "sh",
        "name": "School",
        "kind": "school",
        "lat": 11.7,
        "lon": 76.6,
        "usable_capacity": 60,
        "occupancy": 10,
        "available": 50,
        "capacity_source": "seed",
    }
    values.update(overrides)
    return ShelterCandidate(**values)


def test_shelter_candidate_available_rule() -> None:
    assert _candidate().available == 50
    assert _candidate(occupancy=90, available=0).available == 0
    with pytest.raises(ValidationError):
        _candidate(available=51)
    with pytest.raises(ValidationError):
        _candidate(occupancy=90, available=5)


def test_plan_route_edge_key_rule_and_classification() -> None:
    with pytest.raises(ValidationError):
        _route(osm_edge_keys=(0,))
    with pytest.raises(ValidationError):
        _route(safety_classification="blocked")


def test_tool_result_ok_matches_error() -> None:
    assert ToolResult(tool="t", ok=True, data={"a": 1}, latency_ms=3).ok
    err = ToolError(code="E", message="boom", retryable=False)
    assert not ToolResult(tool="t", ok=False, error=err, latency_ms=1).ok
    with pytest.raises(ValidationError):
        ToolResult(tool="t", ok=True, error=err, latency_ms=1)
    with pytest.raises(ValidationError):
        ToolResult(tool="t", ok=False, latency_ms=1)
    with pytest.raises(ValidationError):
        ToolResult(tool="t", ok=True, latency_ms=-1)


def test_weather_snapshot_age_min_optional() -> None:
    base: dict[str, Any] = {
        "valid_time": NOW,
        "wind_speed_ms": 1.0,
        "wind_dir_deg": 90.0,
        "rh_pct": 40.0,
        "temperature_c": 30.0,
    }
    assert WeatherSnapshot(**base).age_min is None
    assert WeatherSnapshot(**base, age_min=12).age_min == 12
    with pytest.raises(ValidationError):
        WeatherSnapshot(**base, age_min=-1)


def test_audit_entry_agent_default_and_enum() -> None:
    base: dict[str, Any] = {
        "incident_id": "i",
        "run_id": "r",
        "node_name": "n",
        "inputs_json": "{}",
        "outputs_json": "{}",
        "latency_ms": 0,
    }
    assert AuditEntry(**base).agent == "coordinator"
    assert AuditEntry(**base, agent="traffic_routing").agent == "traffic_routing"
    with pytest.raises(ValidationError):
        AuditEntry(**{**base, "agent": "nonsense"})


def test_plan_draft_invariants() -> None:
    validation = _validation()[:7]
    base: dict[str, Any] = {"incident_id": "i", "run_id": "r", "footprint": _footprint()}
    PlanDraft(**base, outcome="valid", validation=validation, routes=(_route(),))
    with pytest.raises(ValidationError):
        PlanDraft(**base, outcome="valid", validation=validation[:6])
    with pytest.raises(ValidationError):
        PlanDraft(
            **base,
            outcome="valid",
            validation=(
                *validation[:3],
                ValidationResult(validator_id="V4", status="fail", reasons=("x",)),
                *validation[4:],
            ),
        )
    PlanDraft(**base, outcome="failed", failure_reasons=("x",))
    with pytest.raises(ValidationError):
        PlanDraft(**base, outcome="failed")
    with pytest.raises(ValidationError):
        PlanDraft(**base, outcome="failed", failure_reasons=("x",), routes=(_route(),))

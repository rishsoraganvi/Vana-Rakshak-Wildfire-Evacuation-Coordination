"""Unit tests for the structural validators V1-V7 and the fire risk tool wiring."""

from __future__ import annotations

from agent_fire.risk import assess_risk
from coordinator.validators.capacity_checks import (
    check_v4_capacity,
    check_v5_complete,
    check_v6_dispatches,
)
from coordinator.validators.integrity_checks import check_v7_entities
from coordinator.validators.route_checks import check_v1_paths, check_v2_blocked, check_v3_forecast
from coordinator.validators.runner import (
    has_blocking_failure,
    run_structural_validators,
    violation_summary,
)
from validator_factory import (
    FIRE_PATH,
    NODE_1,
    NODE_8,
    NODE_36,
    SAFE_PATH,
    footprint,
    make_assignment,
    make_candidate,
    make_ctx,
    make_group,
    make_route,
    square,
)
from wildfire_core.schemas.plan import Dispatch, SettlementRecord, ValidationResult


def test_forecast_to_group_to_route_verdict() -> None:
    """Tracer: a settlement inside the 3h P50 becomes a group, and routes get verdicts."""
    risk_fp = footprint(p50_1h_wkt=square(NODE_36, 0.002), p50_3h_wkt=square(NODE_8, 0.003))
    settlement = SettlementRecord(
        settlement_id="g1",
        name="Hamlet",
        lat=NODE_1[1],
        lon=NODE_1[0],
        population=40,
        buffer_m=2000,
    )
    assessment = assess_risk([settlement], risk_fp, spread_rate_m_per_h=500.0)
    assert len(assessment.groups) == 1
    group = assessment.groups[0]
    assert group.group_id == "g1"
    assert group.priority == 2
    assert 60 <= group.eta_min <= 180
    assert group.exposure == "inside_p50_3h"

    ctx = make_ctx(footprint(p50_1h_wkt=square(NODE_8, 0.002)))
    results = run_structural_validators(
        groups=[make_group()],
        routes=[make_route(SAFE_PATH)],
        assignments=[make_assignment()],
        dispatches=[],
        unassigned_reasons={},
        ctx=ctx,
        clusters_referenced=["c1"],
    )
    assert [item.validator_id for item in results] == ["V1", "V2", "V3", "V4", "V5", "V6", "V7"]
    assert [item.status for item in results] == ["pass"] * 7


def test_v3_fails_route_crossing_p50_within_first_hour() -> None:
    ctx = make_ctx(footprint(p50_1h_wkt=square(NODE_8, 0.002)))
    result = check_v3_forecast([make_route(FIRE_PATH)], ctx)
    assert result.status == "fail"
    assert {item.code for item in result.violations} == {"p50_before_arrival"}
    assert all(item.group_id == "g1" and item.shelter_id == "s1" for item in result.violations)
    assert all(item.edge is not None for item in result.violations)
    assert any("g1" in reason for reason in result.reasons)


def test_v2_fails_route_through_current_perimeter() -> None:
    ctx = make_ctx(footprint(current_wkt=square(NODE_8, 0.002)))
    result = check_v2_blocked([make_route(FIRE_PATH)], ctx)
    assert result.status == "fail"
    assert {item.code for item in result.violations} == {"enters_current_perimeter"}
    assert check_v2_blocked([make_route(SAFE_PATH)], ctx).status == "pass"


def test_v2_fails_route_on_blocked_or_unsafe_edge() -> None:
    ctx = make_ctx(
        footprint(),
        edge_status={(2, 3, 0): "blocked", (3, 9, 0): "unsafe", (9, 15, 0): "congested"},
    )
    result = check_v2_blocked([make_route(SAFE_PATH)], ctx)
    assert result.status == "fail"
    assert [item.code for item in result.violations] == ["blocked_edge", "blocked_edge"]


def test_v1_fails_route_with_missing_edge() -> None:
    ctx = make_ctx(footprint(), candidates=[make_candidate(node=3)])
    result = check_v1_paths([make_route((1, 2, 3), keys=(0, 5))], ctx)
    assert result.status == "fail"
    assert [item.code for item in result.violations] == ["missing_edge"]
    assert result.violations[0].edge is not None
    assert result.violations[0].edge.key == 5


def test_v1_fails_wrong_origin_or_destination() -> None:
    ctx = make_ctx(footprint())
    wrong_origin = make_route((2, 3, 9, 15), origin=2)
    wrong_destination = make_route((1, 2, 3, 9), destination=9)
    result = check_v1_paths([wrong_origin, wrong_destination], ctx)
    assert result.status == "fail"
    assert [item.code for item in result.violations] == ["origin_mismatch", "destination_mismatch"]


def test_v3_flags_p90_hit_without_failing() -> None:
    ctx = make_ctx(footprint(p90_1h_wkt=square(NODE_8, 0.002)))
    result = check_v3_forecast([make_route(FIRE_PATH)], ctx)
    assert result.status == "flag"
    assert {item.code for item in result.violations} == {"p90_before_arrival"}


def test_v4_passes_within_capacity_and_fails_over_capacity() -> None:
    ctx = make_ctx(footprint(), candidates=[make_candidate(available=100)])
    route = make_route(SAFE_PATH, persons=100)
    ok = check_v4_capacity([make_assignment(persons=100)], [route], ctx)
    assert ok.status == "pass"

    groups = [make_group("g1", 70), make_group("g2", 60)]
    ctx = make_ctx(footprint(), groups=groups, candidates=[make_candidate(available=100)])
    routes = [
        make_route(SAFE_PATH, group_id="g1", persons=70),
        make_route(SAFE_PATH, group_id="g2", persons=60),
    ]
    over = check_v4_capacity(
        [make_assignment("g1", persons=70), make_assignment("g2", persons=60)], routes, ctx
    )
    assert over.status == "fail"
    assert [item.code for item in over.violations] == ["over_capacity"]
    assert over.violations[0].shelter_id == "s1"
    assert "s1" in over.reasons[0]


def test_v4_fails_for_non_candidate_shelter_and_route_mismatch() -> None:
    ctx = make_ctx(footprint(), candidates=[make_candidate("s1")])
    stray = check_v4_capacity(
        [make_assignment(shelter_id="zz", persons=10)],
        [make_route(SAFE_PATH, shelter_id="zz", persons=10)],
        ctx,
    )
    assert stray.status == "fail"
    assert [item.code for item in stray.violations] == ["not_a_candidate"]

    mismatch = check_v4_capacity(
        [make_assignment(persons=40)], [make_route(SAFE_PATH, persons=30)], ctx
    )
    assert mismatch.status == "fail"
    assert [item.code for item in mismatch.violations] == ["route_assignment_mismatch"]


def test_v5_passes_when_every_group_is_fully_assigned() -> None:
    groups = [make_group("g1", 40), make_group("g2", 25)]
    split = [
        make_assignment("g1", "s1", 30),
        make_assignment("g1", "s2", 10),
        make_assignment("g2", "s1", 25),
    ]
    assert check_v5_complete(groups, split, {}).status == "pass"


def test_v5_names_unassigned_groups_with_residual_and_reason() -> None:
    groups = [make_group("g1", 40), make_group("g2", 25)]
    result = check_v5_complete(
        groups,
        [make_assignment("g1", persons=30)],
        {"g1": "no_safe_route"},
    )
    assert result.status == "fail"
    by_group = {item.group_id: item for item in result.violations}
    assert set(by_group) == {"g1", "g2"}
    assert {item.code for item in result.violations} == {"group_unassigned"}
    assert "10 persons" in by_group["g1"].detail and "no_safe_route" in by_group["g1"].detail
    assert "25 persons" in by_group["g2"].detail
    assert "insufficient_capacity" in by_group["g2"].detail


def test_v5_fails_over_assignment() -> None:
    result = check_v5_complete([make_group("g1", 40)], [make_assignment("g1", persons=45)], {})
    assert result.status == "fail"
    assert [item.code for item in result.violations] == ["group_over_assigned"]


def test_v6_empty_dispatches_pass_and_duplicate_vehicle_fails() -> None:
    assert check_v6_dispatches([]).status == "pass"
    first = Dispatch(vehicle_id="bus-1", task="evacuate", group_id="g1", eta_min=10)
    second = Dispatch(vehicle_id="bus-2", task="evacuate", group_id="g2", eta_min=12)
    assert check_v6_dispatches([first, second]).status == "pass"
    clash = Dispatch(vehicle_id="bus-1", task="medical_standby", eta_min=5)
    result = check_v6_dispatches([first, second, clash])
    assert result.status == "fail"
    assert [item.code for item in result.violations] == ["vehicle_double_booked"]
    assert "bus-1" in result.reasons[0]


def test_v7_passes_for_known_entities() -> None:
    ctx = make_ctx(footprint())
    result = check_v7_entities(
        groups=[make_group()],
        routes=[make_route(SAFE_PATH)],
        assignments=[make_assignment()],
        clusters_referenced=["c1"],
        ctx=ctx,
    )
    assert result.status == "pass"


def test_v7_fails_unknown_settlement_shelter_node_cluster_and_orphan_route() -> None:
    ctx = make_ctx(footprint())
    result = check_v7_entities(
        groups=[make_group("ghost")],
        routes=[
            make_route(SAFE_PATH, shelter_id="nowhere"),
            make_route((1, 2, 999), keys=(0, 0), destination=999),
        ],
        assignments=[make_assignment(shelter_id="nowhere")],
        clusters_referenced=["c1", "c-ghost"],
        ctx=ctx,
    )
    assert result.status == "fail"
    codes = {item.code for item in result.violations}
    assert codes == {
        "unknown_settlement",
        "unknown_shelter",
        "unknown_node",
        "unknown_cluster",
        "route_without_assignment",
    }


def test_runner_returns_v1_to_v7_in_order_and_flags_blocking_failures() -> None:
    ctx = make_ctx(footprint(p50_1h_wkt=square(NODE_8, 0.002)))
    results = run_structural_validators(
        groups=[make_group()],
        routes=[make_route(FIRE_PATH)],
        assignments=[make_assignment()],
        dispatches=[],
        unassigned_reasons={},
        ctx=ctx,
        clusters_referenced=["c1"],
    )
    assert [item.validator_id for item in results] == ["V1", "V2", "V3", "V4", "V5", "V6", "V7"]
    assert has_blocking_failure(results)
    assert not has_blocking_failure([ValidationResult(validator_id="V3", status="flag")])
    assert not has_blocking_failure([ValidationResult(validator_id="V1", status="pass")])


def test_violation_summary_counts_codes_and_carries_no_ids() -> None:
    ctx = make_ctx(footprint(p50_1h_wkt=square(NODE_8, 0.002)))
    results = run_structural_validators(
        groups=[make_group("grp-uuid-123e4567")],
        routes=[make_route(FIRE_PATH, group_id="grp-uuid-123e4567")],
        assignments=[make_assignment("grp-uuid-123e4567")],
        dispatches=[],
        unassigned_reasons={},
        ctx=ctx,
        clusters_referenced=["c1"],
    )
    summary = violation_summary(results)
    assert summary["V3:p50_before_arrival"] >= 1
    flat = " ".join(summary)
    assert "grp-uuid" not in flat and "s1" not in flat and "Settlement" not in flat
    assert all(isinstance(count, int) and count > 0 for count in summary.values())

"""Unit tests for the fire risk tool wiring and structural validators on the synthetic graph."""

from __future__ import annotations

from collections.abc import Sequence

from agent_fire.risk import assess_risk
from coordinator.validators.route_checks import check_v1_paths, check_v2_blocked, check_v3_forecast
from coordinator.validators.runner import ValidationContext, run_structural_validators
from shapely.geometry import box
from wildfire_core.geo.footprint import load_footprint
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ForecastFootprint,
    PlanRoute,
    SettlementRecord,
    ShelterCandidate,
)

from tests.fixtures.graphs import build_synthetic_graph

EMPTY = "POLYGON EMPTY"
NODE_1 = (76.60, 11.68)
NODE_8 = (76.61, 11.69)
NODE_36 = (76.65, 11.73)


def square(center: tuple[float, float], half_deg: float) -> str:
    lon, lat = center
    return box(lon - half_deg, lat - half_deg, lon + half_deg, lat + half_deg).wkt


def footprint(**overrides: str) -> ForecastFootprint:
    base = {
        "current_wkt": EMPTY,
        "p50_1h_wkt": EMPTY,
        "p50_3h_wkt": EMPTY,
        "p50_6h_wkt": EMPTY,
        "p90_1h_wkt": EMPTY,
        "p90_3h_wkt": EMPTY,
        "p90_6h_wkt": EMPTY,
    }
    base.update(overrides)
    return ForecastFootprint(**base)


def make_route(
    path: Sequence[int],
    keys: Sequence[int] | None = None,
    *,
    group_id: str = "g1",
    shelter_id: str = "s1",
    persons: int = 40,
    origin: int | None = None,
    destination: int | None = None,
) -> PlanRoute:
    return PlanRoute(
        group_id=group_id,
        shelter_id=shelter_id,
        persons=persons,
        origin_node=path[0] if origin is None else origin,
        destination_node=path[-1] if destination is None else destination,
        osm_node_path=tuple(path),
        osm_edge_keys=tuple(keys) if keys is not None else (0,) * (len(path) - 1),
        total_distance_m=1000.0,
        free_flow_time_s=100.0,
        congested_time_s=100.0,
        eta_min=2.0,
        horizon_h=1,
        path_rank=1,
        risk_score=0.0,
        safety_classification="safe",
    )


def make_group(group_id: str = "g1", persons: int = 40, origin: int | None = 1) -> EvacueeGroup:
    return EvacueeGroup(
        group_id=group_id,
        settlement_id=group_id,
        settlement_name=f"Settlement {group_id}",
        persons=persons,
        priority=1,
        eta_min=30.0,
        exposure="inside_p50_1h",
        origin_node=origin,
    )


def make_candidate(
    shelter_id: str = "s1", node: int | None = 15, available: int = 100
) -> ShelterCandidate:
    return ShelterCandidate(
        shelter_id=shelter_id,
        name=f"Shelter {shelter_id}",
        kind="school",
        lat=11.70,
        lon=76.62,
        usable_capacity=available,
        occupancy=0,
        available=available,
        capacity_source="test",
        node=node,
    )


def make_ctx(
    fp: ForecastFootprint,
    *,
    edge_status: dict[tuple[int, int, int], str] | None = None,
    groups: Sequence[EvacueeGroup] | None = None,
    candidates: Sequence[ShelterCandidate] | None = None,
    clusters: frozenset[str] = frozenset({"c1"}),
) -> ValidationContext:
    group_list = [make_group()] if groups is None else list(groups)
    candidate_list = [make_candidate()] if candidates is None else list(candidates)
    return ValidationContext(
        graph=build_synthetic_graph(),
        footprint=load_footprint(fp),
        edge_status=edge_status or {},
        groups={item.group_id: item for item in group_list},
        candidates={item.shelter_id: item for item in candidate_list},
        known_settlement_ids=frozenset(item.group_id for item in group_list),
        known_shelter_ids=frozenset(item.shelter_id for item in candidate_list),
        fire_cluster_ids=clusters,
    )


SAFE_PATH = (1, 2, 3, 9, 15)
FIRE_PATH = (1, 7, 8, 9, 15)


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

    route_fp = footprint(p50_1h_wkt=square(NODE_8, 0.002))
    ctx = make_ctx(route_fp)
    results = run_structural_validators(routes=[make_route(SAFE_PATH)], ctx=ctx)
    assert [item.status for item in results] == ["pass", "pass", "pass"]


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

"""Tracer: two groups, three shelters, safe congestion-aware routes inside capacity (PLAN-03/04)."""

from __future__ import annotations

from collections import defaultdict

from coordinator.planning.params import PlanningParams
from coordinator.planning.plan_core import (
    NO_GROUPS_WARNING,
    Constraints,
    build_assignment,
    plan_draft,
)
from planning_factory import (
    group,
    make_inputs,
    make_params,
    make_routing_ctx,
    shelter,
)
from validator_factory import footprint, square
from wildfire_core.config import load_settings

CANDIDATES = (shelter("s36", 36, 120), shelter("s6", 6, 100), shelter("s30", 30, 200))
GROUPS = (group("A", 150, 1), group("B", 80, 31))


def _two_groups():
    return make_inputs(GROUPS, CANDIDATES)


def test_happy_path_is_valid_complete_and_within_capacity() -> None:
    outcome = plan_draft(_two_groups(), make_routing_ctx(), make_params())
    draft = outcome.draft

    assert draft.outcome == "valid"
    assert draft.used_fallback is False
    assert draft.resolver_steps == ()
    assert 1 <= draft.congestion_passes_used <= 3

    placed: dict[str, int] = defaultdict(int)
    per_shelter: dict[str, int] = defaultdict(int)
    for item in draft.shelter_assignments:
        placed[item.group_id] += item.persons
        per_shelter[item.shelter_id] += item.persons
    assert placed == {"A": 150, "B": 80}
    available = {c.shelter_id: c.available for c in CANDIDATES}
    assert all(total <= available[shelter_id] for shelter_id, total in per_shelter.items())
    assert {r.validator_id for r in draft.validation} == {f"V{i}" for i in range(1, 8)}
    assert all(r.status in {"pass", "flag"} for r in draft.validation)
    for route in draft.routes:
        assert route.osm_node_path[0] in {1, 31}
        assert route.eta_min >= 1
        assert len(route.path_lonlat) == len(route.osm_node_path)


def test_a_p50_square_across_the_direct_corridor_moves_the_route() -> None:
    free = plan_draft(_two_groups(), make_routing_ctx(), make_params()).draft
    # Cover the primary corridor along the south row (nodes 1..6) for every horizon.
    block = square((76.625, 11.68), 0.004)
    fp = footprint(p50_1h_wkt=block, p50_3h_wkt=block, p50_6h_wkt=block)
    burning = plan_draft(_two_groups(), make_routing_ctx(fp), make_params()).draft

    assert burning.outcome == "valid"
    by_group_free = {(r.group_id, r.shelter_id): r for r in free.routes}
    by_group_fire = {(r.group_id, r.shelter_id): r for r in burning.routes}
    changed = [
        pair
        for pair, route in by_group_fire.items()
        if pair not in by_group_free
        or by_group_free[pair].osm_node_path != route.osm_node_path
        or route.path_rank > 1
    ]
    assert changed, "the fire should have changed at least one route"
    assert all(item.status != "fail" for item in burning.validation)


def test_preflight_failure_fails_closed_with_the_named_reason() -> None:
    inputs = make_inputs(GROUPS, CANDIDATES, preflight_failures=("weather_unavailable:c1",))
    draft = plan_draft(inputs, make_routing_ctx(), make_params()).draft

    assert draft.outcome == "failed"
    assert draft.failure_reasons == ("weather_unavailable:c1",)
    assert draft.routes == () and draft.shelter_assignments == ()


def test_unsnappable_group_origin_fails_before_matching() -> None:
    inputs = make_inputs((group("A", 150, None), group("B", 80, 31)), CANDIDATES)
    draft = plan_draft(inputs, make_routing_ctx(), make_params()).draft

    assert draft.outcome == "failed"
    assert draft.failure_reasons == ("origin_unsnappable:A",)


def test_zero_groups_is_a_valid_draft_with_the_forecast_warning() -> None:
    draft = plan_draft(make_inputs((), CANDIDATES), make_routing_ctx(), make_params()).draft

    assert draft.outcome == "valid"
    assert draft.routes == () and draft.shelter_assignments == ()
    assert NO_GROUPS_WARNING in draft.warnings
    assert {r.validator_id for r in draft.validation} == {f"V{i}" for i in range(1, 8)}


def test_build_assignment_never_mutates_the_callers_graph() -> None:
    ctx = make_routing_ctx()
    before = {(u, v, k): dict(data) for u, v, k, data in ctx.graph.edges(keys=True, data=True)}
    result = build_assignment(ctx, GROUPS, CANDIDATES, make_params(), Constraints())

    after = {(u, v, k): dict(data) for u, v, k, data in ctx.graph.edges(keys=True, data=True)}
    assert before == after
    assert result.graph is not ctx.graph


def test_congestion_loop_is_bounded_by_the_configured_passes() -> None:
    # Heavy demand so the BPR flows change the costs between passes.
    big = (group("A", 380, 1), group("B", 380, 31))
    candidates = (shelter("s36", 36, 400), shelter("s6", 6, 400))
    ctx = make_routing_ctx()
    for passes in (1, 2, 3):
        result = build_assignment(
            ctx, big, candidates, make_params(congestion_passes=passes), Constraints()
        )
        assert 1 <= result.passes_used <= passes


def test_params_snapshot_is_flat_sorted_and_provenance_shaped() -> None:
    params = PlanningParams.from_settings(load_settings())
    snapshot = params.snapshot()

    assert list(snapshot) == sorted(snapshot)
    assert snapshot["lane_capacity_vph.primary"] == 1400.0
    assert snapshot["fix_menu_order"] == ["next_path", "rematch", "split"]
    assert snapshot["conflict_max_loops"] == 3
    for value in snapshot.values():
        assert isinstance(value, (int, float, str, list))

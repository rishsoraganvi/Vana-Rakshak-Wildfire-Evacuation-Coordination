"""Greedy fallback planner: a different algorithm from the flow loop (TechSpec 6.2, D-11, D-12)."""

from __future__ import annotations

from collections import defaultdict

from coordinator.planning.fallback_planner import greedy_fallback
from coordinator.planning.plan_core import plan_draft, validate_assignment
from coordinator.validators.runner import has_blocking_failure
from planning_factory import group, make_inputs, make_params, make_routing_ctx, shelter
from validator_factory import footprint, square

BLOCK_36 = square((76.65, 11.73), 0.003)


def _fire_at_36():
    fp = footprint(p50_1h_wkt=BLOCK_36, p50_3h_wkt=BLOCK_36, p50_6h_wkt=BLOCK_36)
    params = make_params(p50_mult=1.0, p90_mult=1.0)
    return make_routing_ctx(fp, params=params), params


def test_groups_are_served_by_priority_then_persons_and_split_greedily() -> None:
    ctx = make_routing_ctx()
    inputs = make_inputs(
        (group("P", 100, 1, priority=2), group("Q", 60, 1, priority=1)),
        (shelter("s6", 6, 100), shelter("s30", 30, 60)),
    )
    result = greedy_fallback(inputs, ctx, make_params())

    assert result.legs == {("Q", "s6"): 60, ("P", "s6"): 40, ("P", "s30"): 60}
    assert result.unassigned == {}
    assert result.passes_used == 1
    assert not has_blocking_failure(validate_assignment(inputs, ctx, result))


def test_the_fallback_picks_a_strictly_safe_shelter_and_path() -> None:
    ctx, params = _fire_at_36()
    inputs = make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100), shelter("s6", 6, 100)))
    result = greedy_fallback(inputs, ctx, params)

    assert set(result.legs) == {("A", "s6")}
    assert not has_blocking_failure(validate_assignment(inputs, ctx, result))


def test_a_group_with_no_safe_shelter_is_named_with_its_reason() -> None:
    ctx, params = _fire_at_36()
    inputs = make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100),))
    result = greedy_fallback(inputs, ctx, params)

    assert result.legs == {}
    assert result.unassigned == {"A": 50}
    assert result.unplaceable_reasons == {"A": "no_safe_route"}


def test_capacity_shortfall_is_reported_as_insufficient_capacity() -> None:
    inputs = make_inputs((group("A", 150, 1),), (shelter("s6", 6, 100),))
    result = greedy_fallback(inputs, make_routing_ctx(), make_params())

    assert result.legs == {("A", "s6"): 100}
    assert result.unassigned == {"A": 50}
    assert result.unplaceable_reasons == {"A": "insufficient_capacity"}


def test_the_fallback_never_overbooks_a_shelter() -> None:
    inputs = make_inputs(
        (group("A", 90, 1), group("B", 90, 31), group("C", 90, 6)),
        (shelter("s36", 36, 100), shelter("s6", 6, 70), shelter("s30", 30, 100)),
    )
    result = greedy_fallback(inputs, make_routing_ctx(), make_params())

    per_shelter: dict[str, int] = defaultdict(int)
    for (_, shelter_id), persons in result.legs.items():
        per_shelter[shelter_id] += persons
    assert per_shelter["s36"] <= 100 and per_shelter["s6"] <= 70 and per_shelter["s30"] <= 100


def test_plan_draft_flags_used_fallback_when_the_resolver_is_exhausted() -> None:
    ctx, params = _fire_at_36()
    params = params.model_copy(update={"conflict_max_loops": 1})
    inputs = make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100), shelter("s6", 6, 100)))
    draft = plan_draft(inputs, ctx, params).draft

    assert draft.outcome == "valid"
    assert draft.used_fallback is True
    assert len(draft.resolver_steps) == 1
    assert draft.resolver_steps[0].outcome == "still_failing"
    assert {a.shelter_id for a in draft.shelter_assignments} == {"s6"}
    assert all(item.status != "fail" for item in draft.validation)


def test_when_both_planners_fail_the_failed_draft_carries_no_approvable_content() -> None:
    ctx, params = _fire_at_36()
    inputs = make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100),))
    draft = plan_draft(inputs, ctx, params).draft

    assert draft.outcome == "failed"
    assert draft.used_fallback is False
    assert draft.routes == () and draft.shelter_assignments == ()
    assert len(draft.resolver_steps) <= 3
    assert any("group A" in reason for reason in draft.failure_reasons)
    assert any(
        reason.startswith("fallback planner: V5") and "no_safe_route" in reason
        for reason in draft.failure_reasons
    )

"""Hypothesis invariants over the whole planning core (PLAN-04 end-to-end capacity evidence).

Instances are small (1-4 groups, 1-4 shelters on the 6x6 synthetic grid, an optional fire) so the
heavier pipeline stays fast. Every producer (flow, resolver, fallback) must go through the same
``run_structural_validators`` (assumption-delta decision), checked by a spy.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import pytest
from coordinator.planning import plan_core
from coordinator.planning.plan_core import PlanInputs, RoutingContext, plan_draft
from coordinator.validators.runner import has_blocking_failure
from hypothesis import event, given, settings
from hypothesis import strategies as st
from planning_factory import group, make_inputs, make_params, make_routing_ctx, shelter
from validator_factory import footprint, square
from wildfire_core.schemas.plan import PlanDraft

_LON0, _LAT0, _STEP = 76.60, 11.68, 0.01
_GRID = 6


def _center(node: int) -> tuple[float, float]:
    row, col = divmod(node - 1, _GRID)
    return _LON0 + _STEP * col, _LAT0 + _STEP * row


@dataclass(frozen=True)
class Instance:
    inputs: PlanInputs
    ctx: RoutingContext
    p50_mult: float
    loops: int


@st.composite
def instances(draw: st.DrawFn) -> Instance:
    n_groups = draw(st.integers(min_value=1, max_value=4))
    groups = tuple(
        group(
            f"g{i}",
            draw(st.integers(min_value=1, max_value=250)),
            draw(st.integers(min_value=1, max_value=36)),
            priority=draw(st.integers(min_value=1, max_value=3)),
        )
        for i in range(n_groups)
    )
    n_shelters = draw(st.integers(min_value=1, max_value=4))
    candidates = tuple(
        shelter(
            f"s{j}",
            draw(st.integers(min_value=1, max_value=36)),
            draw(st.one_of(st.just(0), st.integers(min_value=40, max_value=500))),
        )
        for j in range(n_shelters)
    )
    overrides: dict[str, str] = {}
    if draw(st.booleans()):
        block = square(
            _center(draw(st.integers(min_value=1, max_value=36))),
            draw(st.sampled_from([0.002, 0.006, 0.012])),
        )
        overrides["p50_1h_wkt"] = block
        if draw(st.booleans()):
            overrides["p50_3h_wkt"] = block
            overrides["p50_6h_wkt"] = block
    if draw(st.booleans()) and draw(st.booleans()):
        overrides["current_wkt"] = square(
            _center(draw(st.integers(min_value=1, max_value=36))), 0.002
        )
    p50_mult = draw(st.sampled_from([1.0, 10.0]))
    loops = draw(st.integers(min_value=1, max_value=3))
    params = make_params(p50_mult=p50_mult, p90_mult=1.0)
    ctx = make_routing_ctx(footprint(**overrides), params=params)
    return Instance(make_inputs(groups, candidates), ctx, p50_mult, loops)


def _plan(instance: Instance) -> PlanDraft:
    params = make_params(
        p50_mult=instance.p50_mult, p90_mult=1.0, conflict_max_loops=instance.loops
    )
    return plan_draft(instance.inputs, instance.ctx, params).draft


@settings(max_examples=60, deadline=None)
@given(instances())
def test_valid_drafts_stay_within_capacity_and_assign_every_group(inst: Instance) -> None:
    draft = _plan(inst)
    event(f"outcome={draft.outcome}")
    event(f"fallback={draft.used_fallback}")
    event(f"resolver_steps={len(draft.resolver_steps)}")
    if draft.outcome != "valid":
        return
    available = {c.shelter_id: c.available for c in inst.inputs.candidates}
    per_shelter: dict[str, int] = defaultdict(int)
    per_group: dict[str, int] = defaultdict(int)
    for item in draft.shelter_assignments:
        per_shelter[item.shelter_id] += item.persons
        per_group[item.group_id] += item.persons
    for shelter_id, total in per_shelter.items():
        assert total <= available[shelter_id]
    for g in inst.inputs.groups:
        assert per_group[g.group_id] == g.persons
    assert {(r.group_id, r.shelter_id) for r in draft.routes} == {
        (a.group_id, a.shelter_id) for a in draft.shelter_assignments
    }
    assert not any(item.status == "fail" for item in draft.validation)


@settings(max_examples=60, deadline=None)
@given(instances())
def test_failed_drafts_carry_nothing_and_name_a_reason(inst: Instance) -> None:
    draft = _plan(inst)
    if draft.outcome != "failed":
        return
    assert draft.routes == ()
    assert draft.shelter_assignments == ()
    assert len(draft.failure_reasons) >= 1
    assert all(reason.strip() for reason in draft.failure_reasons)


@settings(max_examples=60, deadline=None)
@given(instances())
def test_resolver_loops_never_exceed_the_cap(inst: Instance) -> None:
    draft = _plan(inst)
    assert len(draft.resolver_steps) <= inst.loops <= 3
    assert [s.loop for s in draft.resolver_steps] == list(range(1, len(draft.resolver_steps) + 1))
    if draft.used_fallback:
        assert draft.outcome == "valid"
        assert draft.resolver_steps and draft.resolver_steps[-1].outcome != "resolved"


@settings(max_examples=30, deadline=None)
@given(instances())
def test_plan_draft_is_deterministic(inst: Instance) -> None:
    def stable(draft: PlanDraft) -> dict[str, Any]:
        dump = draft.model_dump(mode="json")
        for route in dump["routes"]:
            route.pop("route_id")
        return dump

    assert stable(_plan(inst)) == stable(_plan(inst))


@settings(max_examples=30, deadline=None)
@given(instances())
def test_every_valid_draft_was_validated_before_acceptance(inst: Instance) -> None:
    calls: list[tuple[tuple[Any, ...], tuple[Any, ...], bool]] = []
    real = plan_core.run_structural_validators

    def spy(**kwargs: Any) -> Any:
        results = real(**kwargs)
        calls.append(
            (tuple(kwargs["routes"]), tuple(kwargs["assignments"]), has_blocking_failure(results))
        )
        return results

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(plan_core, "run_structural_validators", spy)
        draft = _plan(inst)

    assert calls, "the draft must have been validated at least once"
    if draft.outcome == "valid":
        routes, assignments, blocked = calls[-1]
        assert blocked is False
        assert routes == draft.routes and assignments == draft.shelter_assignments
    else:
        assert draft.routes == () and draft.shelter_assignments == ()


# -- the spy invariant on hand-built producers ----------------------------------------------


def _spied(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], bool]]:
    calls: list[tuple[tuple[Any, ...], bool]] = []
    real = plan_core.run_structural_validators

    def spy(**kwargs: Any) -> Any:
        results = real(**kwargs)
        calls.append((tuple(kwargs["routes"]), has_blocking_failure(results)))
        return results

    monkeypatch.setattr(plan_core, "run_structural_validators", spy)
    return calls


def _fire_at_36() -> tuple[RoutingContext, Any]:
    block = square((76.65, 11.73), 0.003)
    params = make_params(p50_mult=1.0, p90_mult=1.0)
    fp = footprint(p50_1h_wkt=block, p50_3h_wkt=block, p50_6h_wkt=block)
    return make_routing_ctx(fp, params=params), params


def _scenario() -> PlanInputs:
    return make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100), shelter("s6", 6, 100)))


def test_flow_result_is_validated_once_before_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spied(monkeypatch)
    inputs = make_inputs((group("A", 50, 1),), (shelter("s6", 6, 100),))
    draft = plan_draft(inputs, make_routing_ctx(), make_params()).draft

    assert draft.outcome == "valid" and len(calls) == 1
    assert calls[0] == (draft.routes, False)


def test_each_resolver_loop_and_the_accepted_result_are_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spied(monkeypatch)
    ctx, params = _fire_at_36()
    draft = plan_draft(_scenario(), ctx, params).draft

    assert draft.outcome == "valid" and draft.used_fallback is False
    # flow, next_path loop, rematch loop
    assert [blocked for _, blocked in calls] == [True, True, False]
    assert calls[-1][0] == draft.routes


def test_the_fallback_result_is_validated_before_it_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spied(monkeypatch)
    ctx, params = _fire_at_36()
    draft = plan_draft(_scenario(), ctx, params.model_copy(update={"conflict_max_loops": 1})).draft

    assert draft.outcome == "valid" and draft.used_fallback is True
    # flow, one resolver loop, then the fallback planner
    assert [blocked for _, blocked in calls] == [True, True, False]
    assert calls[-1][0] == draft.routes


def test_a_draft_that_no_producer_can_fix_is_never_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spied(monkeypatch)
    ctx, params = _fire_at_36()
    inputs = make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100),))
    draft = plan_draft(inputs, ctx, params).draft

    assert draft.outcome == "failed"
    assert calls and all(blocked for _, blocked in calls[:-1])
    assert calls[-1][1] is True

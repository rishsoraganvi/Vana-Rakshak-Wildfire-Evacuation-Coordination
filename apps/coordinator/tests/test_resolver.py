"""Bounded conflict resolver: fixed menu order, validated LLM choice, loop cap (D-09, D-10)."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest
from coordinator.llm.groq_adapter import FixStrategyChoice
from coordinator.planning import resolver
from coordinator.planning.plan_core import (
    Constraints,
    PlanInputs,
    build_assignment,
    plan_draft,
    validate_assignment,
)
from coordinator.planning.resolver import (
    ChooserDecision,
    _apply_next_path,
    _apply_rematch,
    _apply_split,
    deterministic_chooser,
    llm_chooser,
)
from planning_factory import group, make_inputs, make_params, make_routing_ctx, shelter
from validator_factory import footprint, square
from wildfire_core.config import load_settings
from wildfire_core.schemas.plan import EdgeStatusEntry, ValidationResult, ViolationRecord

ORDER = ("next_path", "rematch", "split")
BLOCK_36 = square((76.65, 11.73), 0.003)


def _fire_at_36():
    """A P50 square over node 36 with no cost penalty: the flow still prefers shelter s36."""
    fp = footprint(p50_1h_wkt=BLOCK_36, p50_3h_wkt=BLOCK_36, p50_6h_wkt=BLOCK_36)
    params = make_params(p50_mult=1.0, p90_mult=1.0)
    return make_routing_ctx(fp, params=params), params


def _scenario_inputs() -> PlanInputs:
    return make_inputs((group("A", 50, 31),), (shelter("s36", 36, 100), shelter("s6", 6, 100)))


def _violation(group_id: str, shelter_id: str, *, code: str = "p50_before_arrival", edge=None):
    return ViolationRecord(
        code=code, detail="x", group_id=group_id, shelter_id=shelter_id, edge=edge
    )


def _fail(validator_id: str, *violations: ViolationRecord) -> tuple[ValidationResult, ...]:
    return (
        ValidationResult(
            validator_id=validator_id,  # type: ignore[arg-type]
            status="fail",
            reasons=("x",),
            violations=violations,
        ),
    )


# -- choosers -------------------------------------------------------------------------------


def test_deterministic_chooser_follows_the_fixed_order() -> None:
    chooser = deterministic_chooser(ORDER)
    picks = [chooser(loop, ORDER, {}) for loop in range(3)]

    assert [p.strategy for p in picks] == ["next_path", "rematch", "split"]
    assert {p.chosen_by for p in picks} == {"deterministic"}
    assert all(p.model_metadata is None for p in picks)


def test_llm_chooser_returns_the_models_strategy_and_collects_metadata(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake(**kwargs: Any) -> FixStrategyChoice:
        seen.update(kwargs)
        return FixStrategyChoice("split", False, {"llm_called": True})

    monkeypatch.setattr(resolver, "choose_fix_strategy", fake)
    settings = load_settings()
    decision = llm_chooser(settings, ORDER)(0, ORDER, {"V3:p50_before_arrival": 2})

    assert decision == ChooserDecision("split", "llm", {"llm_called": True})
    assert seen["allowed"] == ORDER
    assert seen["violation_counts"] == {"V3:p50_before_arrival": 2}
    assert seen["settings"] is settings


def test_llm_chooser_falls_back_to_the_deterministic_choice(monkeypatch) -> None:
    meta = {"llm_called": False, "fallback_reason": "llm_disabled"}
    monkeypatch.setattr(
        resolver, "choose_fix_strategy", lambda **_: FixStrategyChoice(None, True, meta)
    )
    decision = llm_chooser(load_settings(), ORDER)(1, ORDER, {})

    assert decision.strategy == "rematch"
    assert decision.chosen_by == "deterministic"
    assert decision.model_metadata == meta


def test_llm_chooser_rejects_a_strategy_outside_the_menu(monkeypatch) -> None:
    monkeypatch.setattr(
        resolver,
        "choose_fix_strategy",
        lambda **_: FixStrategyChoice("mark_unassigned", False, {"llm_called": True}),
    )
    decision = llm_chooser(load_settings(), ORDER)(0, ORDER, {})

    assert decision.strategy == "next_path"
    assert decision.chosen_by == "deterministic"


# -- resolver loop --------------------------------------------------------------------------


def test_p50_at_the_nearest_shelter_is_resolved_in_menu_order() -> None:
    ctx, params = _fire_at_36()
    outcome = plan_draft(_scenario_inputs(), ctx, params)
    draft = outcome.draft

    assert draft.outcome == "valid"
    assert draft.used_fallback is False
    assert [s.strategy for s in draft.resolver_steps] == ["next_path", "rematch"]
    assert [s.outcome for s in draft.resolver_steps] == ["still_failing", "resolved"]
    assert {s.chosen_by for s in draft.resolver_steps} == {"deterministic"}
    assert [s.loop for s in draft.resolver_steps] == [1, 2]
    assert draft.resolver_steps[0].target_group_ids == ("A",)
    assert {a.shelter_id for a in draft.shelter_assignments} == {"s6"}
    assert outcome.llm_calls == ()


def test_the_llm_may_pick_the_menu_item_and_every_call_is_audited(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> FixStrategyChoice:
        calls.append(kwargs)
        return FixStrategyChoice("rematch", False, {"llm_called": True, "prompt_version": "v1"})

    monkeypatch.setattr(resolver, "choose_fix_strategy", fake)
    ctx, params = _fire_at_36()
    outcome = plan_draft(
        _scenario_inputs(), ctx, params, chooser=llm_chooser(load_settings(), params.fix_menu_order)
    )

    assert outcome.draft.outcome == "valid"
    assert [(s.strategy, s.chosen_by, s.outcome) for s in outcome.draft.resolver_steps] == [
        ("rematch", "llm", "resolved")
    ]
    assert outcome.llm_calls == ({"llm_called": True, "prompt_version": "v1"},)
    assert len(calls) == 1


def test_the_llm_payload_carries_only_menu_names_and_violation_codes(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> FixStrategyChoice:
        calls.append(kwargs)
        return FixStrategyChoice(None, True, {"llm_called": False})

    monkeypatch.setattr(resolver, "choose_fix_strategy", fake)
    ctx, params = _fire_at_36()
    plan_draft(
        _scenario_inputs(), ctx, params, chooser=llm_chooser(load_settings(), params.fix_menu_order)
    )

    assert calls
    for call in calls:
        assert tuple(call["allowed"]) == ORDER
        assert set(call) == {"loop", "allowed", "violation_counts", "settings"}
        for key in call["violation_counts"]:
            assert re.fullmatch(r"V[1-8]:[a-z_]+", key)
            assert "A" not in key.split(":")[1] and "s36" not in key


def test_an_unresolvable_instance_stops_at_the_loop_cap_and_fails_with_named_groups() -> None:
    ctx = make_routing_ctx()
    inputs = make_inputs(
        (group("A", 150, 1), group("B", 80, 31)), (shelter("s6", 6, 60), shelter("s36", 36, 40))
    )
    draft = plan_draft(inputs, ctx, make_params()).draft

    assert draft.outcome == "failed"
    assert 1 <= len(draft.resolver_steps) <= 3
    assert {s.outcome for s in draft.resolver_steps} == {"not_applicable"}
    assert draft.used_fallback is False
    assert draft.routes == () and draft.shelter_assignments == ()
    joined = "\n".join(draft.failure_reasons)
    assert "insufficient_capacity" in joined
    assert "group A" in joined and "group B" in joined


@pytest.mark.parametrize("loops", [1, 2, 3])
def test_resolver_never_exceeds_the_configured_loop_cap(loops: int) -> None:
    inputs = make_inputs((group("A", 150, 1),), (shelter("s6", 6, 20),))
    draft = plan_draft(inputs, make_routing_ctx(), make_params(conflict_max_loops=loops)).draft

    assert draft.outcome == "failed"
    assert len(draft.resolver_steps) == loops


# -- appliers -------------------------------------------------------------------------------


def _scenario_result():
    ctx, params = _fire_at_36()
    inputs = _scenario_inputs()
    result = build_assignment(ctx, inputs.groups, inputs.candidates, params, Constraints())
    return ctx, params, inputs, result


def test_next_path_advances_the_rank_floor_of_the_violating_leg() -> None:
    _, _, _, result = _scenario_result()
    assert result.paths_available[("A", "s36")] == 3
    validation = _fail("V3", _violation("A", "s36"))

    constraints, targets = _apply_next_path(Constraints(), result, validation)

    assert constraints.rank_floor == {("A", "s36"): 2}
    assert targets == ("A",)


def test_next_path_excludes_failing_edges_when_no_further_path_exists() -> None:
    _, _, _, result = _scenario_result()
    exhausted = dataclasses.replace(result, paths_available={("A", "s36"): 1})
    path = result.routes[0].osm_node_path
    key = result.routes[0].osm_edge_keys[-1]
    entry = EdgeStatusEntry(u=path[-2], v=path[-1], key=key, status="open")
    validation = _fail("V3", _violation("A", "s36", edge=entry))

    constraints, targets = _apply_next_path(
        Constraints(rank_floor={("A", "s36"): 2}), exhausted, validation
    )

    assert constraints.excluded_edges == {(path[-2], path[-1], key)}
    assert ("A", "s36") not in constraints.rank_floor
    assert targets == ("A",)


def test_rematch_bans_only_the_violating_pairs_and_ignores_v5_alone() -> None:
    constraints, targets = _apply_rematch(
        Constraints(), _fail("V2", _violation("A", "s36", code="blocked_edge"))
    )
    assert constraints.banned == {("A", "s36")}
    assert targets == ("A",)

    unchanged, none = _apply_rematch(
        Constraints(),
        _fail("V5", ViolationRecord(code="group_unassigned", detail="x", group_id="A")),
    )
    assert unchanged == Constraints()
    assert none == ()


def test_split_halves_the_per_pair_cap_of_violating_groups_only() -> None:
    inputs = make_inputs((group("A", 51, 31), group("B", 1, 1)), (shelter("s6", 6, 100),))
    validation = _fail("V3", _violation("A", "s36"), _violation("B", "s6"))

    constraints, targets = _apply_split(Constraints(), validation, inputs.groups)

    assert constraints.per_pair_cap == {"A": 26}  # B has one person: a cap of 1 changes nothing
    assert targets == ("A",)
    again, _ = _apply_split(constraints, validation, inputs.groups)
    assert again.per_pair_cap == {"A": 13}


def test_the_appliers_ignore_p90_flags_which_do_not_block() -> None:
    _, _, _, result = _scenario_result()
    flag = ValidationResult(
        validator_id="V3",
        status="flag",
        violations=(_violation("A", "s36", code="p90_before_arrival"),),
    )
    constraints, targets = _apply_next_path(Constraints(), result, (flag,))
    assert constraints == Constraints() and targets == ()


def test_validate_assignment_matches_the_resolver_result() -> None:
    ctx, params, inputs, result = _scenario_result()
    validation = validate_assignment(inputs, ctx, result)
    assert any(item.status == "fail" for item in validation)

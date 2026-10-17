"""Bounded conflict resolver: a fixed three-strategy menu, optional LLM choice (D-09, D-10).

``resolve`` is a plain ``for loop in range(params.conflict_max_loops)``, not a LangGraph cycle, so
Hypothesis can exercise it and the loop count can never exceed the configured cap (TechSpec 6.2).
Each loop applies exactly one menu strategy (``next_path``, ``rematch`` or ``split``), rebuilds the
assignment and re-validates with the same V1-V7. "Mark unassigned" is never a strategy (D-09).

The strategy may come from the optional LLM, but only as an enum value. The targets (which leg,
which pair, which group) always come from the sorted violations, so the model can never name an id.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from wildfire_core.config import Settings
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ResolverStep,
    ValidationResult,
    ViolationRecord,
)

from coordinator.llm.groq_adapter import choose_fix_strategy
from coordinator.planning.params import PlanningParams
from coordinator.planning.plan_core import (
    AssignmentResult,
    Constraints,
    PlanInputs,
    RoutingContext,
    build_assignment,
    validate_assignment,
)
from coordinator.validators.runner import has_blocking_failure, violation_summary

ChosenBy = Literal["deterministic", "llm"]

# A P90 hit is a reviewer flag, not a failure, so it is never a repair target.
_NON_BLOCKING_CODES = frozenset({"p90_before_arrival"})
_ROUTE_VALIDATORS = frozenset({"V1", "V2", "V3"})
_PAIR_VALIDATORS = frozenset({"V1", "V2", "V3", "V4"})


@dataclass(frozen=True)
class ChooserDecision:
    strategy: str
    chosen_by: ChosenBy
    model_metadata: dict[str, Any] | None = None


StrategyChooser = Callable[[int, Sequence[str], Mapping[str, int]], ChooserDecision]


@dataclass(frozen=True)
class ResolverOutcome:
    result: AssignmentResult
    validation: tuple[ValidationResult, ...]
    steps: tuple[ResolverStep, ...]
    resolved: bool
    llm_calls: tuple[dict[str, Any], ...]


def deterministic_chooser(order: Sequence[str]) -> StrategyChooser:
    """Pick ``order[loop % len(order)]`` (the fixed default, D-10)."""
    menu = tuple(order)

    def choose(loop: int, _allowed: Sequence[str], _counts: Mapping[str, int]) -> ChooserDecision:
        return ChooserDecision(menu[loop % len(menu)], "deterministic", None)

    return choose


def llm_chooser(settings: Settings, order: Sequence[str]) -> StrategyChooser:
    """Ask the optional LLM for a menu item; fall back to the fixed order on any problem.

    The model metadata is always returned so every call (even a gated or failed one) is audited.
    """
    menu = tuple(order)

    def choose(loop: int, _allowed: Sequence[str], counts: Mapping[str, int]) -> ChooserDecision:
        choice = choose_fix_strategy(
            loop=loop + 1, allowed=menu, violation_counts=counts, settings=settings
        )
        if choice.strategy is not None and choice.strategy in menu:
            return ChooserDecision(choice.strategy, "llm", choice.model_metadata)
        return ChooserDecision(menu[loop % len(menu)], "deterministic", choice.model_metadata)

    return choose


def _blocking_violations(
    validation: Sequence[ValidationResult], validators: frozenset[str]
) -> list[ViolationRecord]:
    """Violations of failing validators in ``validators``, sorted so targets are deterministic."""
    found = [
        violation
        for result in validation
        if result.validator_id in validators and result.status == "fail"
        for violation in result.violations
        if violation.code not in _NON_BLOCKING_CODES
    ]
    return sorted(found, key=lambda v: (v.group_id or "", v.shelter_id or "", v.code))


def _apply_next_path(
    constraints: Constraints, result: AssignmentResult, validation: Sequence[ValidationResult]
) -> tuple[Constraints, tuple[str, ...]]:
    """Move each violating leg to its next path; exclude the failing edge when none is left."""
    routes = {(r.group_id, r.shelter_id): r for r in result.routes}
    floor = dict(constraints.rank_floor)
    excluded = set(constraints.excluded_edges)
    targets: set[str] = set()
    for violation in _blocking_violations(validation, _ROUTE_VALIDATORS):
        if violation.group_id is None or violation.shelter_id is None:
            continue
        pair = (violation.group_id, violation.shelter_id)
        route = routes.get(pair)
        if route is None:
            continue
        if route.path_rank < result.paths_available.get(pair, 0):
            floor[pair] = max(floor.get(pair, 1), route.path_rank + 1)
            targets.add(violation.group_id)
        elif violation.edge is not None:
            edge = (violation.edge.u, violation.edge.v, violation.edge.key)
            if result.graph.has_edge(*edge):
                excluded.add(edge)
                floor.pop(pair, None)  # ranks restart on the reduced graph
                targets.add(violation.group_id)
    updated = Constraints(
        banned=constraints.banned,
        per_pair_cap=constraints.per_pair_cap,
        rank_floor=floor,
        excluded_edges=frozenset(excluded),
    )
    return updated, tuple(sorted(targets))


def _apply_rematch(
    constraints: Constraints, validation: Sequence[ValidationResult]
) -> tuple[Constraints, tuple[str, ...]]:
    """Ban every violating (group, shelter) pair so the flow picks another shelter."""
    banned = set(constraints.banned)
    targets: set[str] = set()
    for violation in _blocking_violations(validation, _PAIR_VALIDATORS):
        if violation.group_id is not None and violation.shelter_id is not None:
            banned.add((violation.group_id, violation.shelter_id))
            targets.add(violation.group_id)
    updated = Constraints(
        banned=frozenset(banned),
        per_pair_cap=constraints.per_pair_cap,
        rank_floor=constraints.rank_floor,
        excluded_edges=constraints.excluded_edges,
    )
    return updated, tuple(sorted(targets))


def _apply_split(
    constraints: Constraints,
    validation: Sequence[ValidationResult],
    groups: Sequence[EvacueeGroup],
) -> tuple[Constraints, tuple[str, ...]]:
    """Cap each violating group's persons per leg at half, forcing two or more shelters."""
    persons = {g.group_id: g.persons for g in groups}
    caps = dict(constraints.per_pair_cap)
    targets: set[str] = set()
    for violation in _blocking_violations(validation, _PAIR_VALIDATORS):
        group_id = violation.group_id
        if group_id is None or group_id not in persons or group_id in targets:
            continue
        current = caps.get(group_id, persons[group_id])
        halved = max(1, math.ceil(current / 2))
        if halved < current:
            caps[group_id] = halved
            targets.add(group_id)
    updated = Constraints(
        banned=constraints.banned,
        per_pair_cap=caps,
        rank_floor=constraints.rank_floor,
        excluded_edges=constraints.excluded_edges,
    )
    return updated, tuple(sorted(targets))


def _step(
    loop: int,
    strategy: str,
    chosen_by: ChosenBy,
    targets: tuple[str, ...],
    outcome: Literal["resolved", "still_failing", "not_applicable"],
) -> ResolverStep:
    return ResolverStep(
        loop=loop + 1,
        strategy=strategy,  # type: ignore[arg-type]
        chosen_by=chosen_by,
        target_group_ids=targets,
        outcome=outcome,
    )


def resolve(
    inputs: PlanInputs,
    ctx: RoutingContext,
    params: PlanningParams,
    first: AssignmentResult,
    first_validation: tuple[ValidationResult, ...],
    chooser: StrategyChooser,
) -> ResolverOutcome:
    """Run at most ``conflict_max_loops`` menu repairs, re-validating after each (D-09, D-10)."""
    order = tuple(params.fix_menu_order)
    constraints = Constraints()
    result, validation = first, first_validation
    steps: list[ResolverStep] = []
    llm_calls: list[dict[str, Any]] = []
    resolved = False

    for loop in range(params.conflict_max_loops):
        decision = chooser(loop, order, violation_summary(validation))
        if decision.model_metadata is not None:
            llm_calls.append(dict(decision.model_metadata))
        strategy, chosen_by = decision.strategy, decision.chosen_by
        if strategy not in order:
            strategy, chosen_by = order[loop % len(order)], "deterministic"

        if strategy == "next_path":
            updated, targets = _apply_next_path(constraints, result, validation)
        elif strategy == "rematch":
            updated, targets = _apply_rematch(constraints, validation)
        else:
            updated, targets = _apply_split(constraints, validation, inputs.groups)

        if updated == constraints:
            steps.append(_step(loop, strategy, chosen_by, (), "not_applicable"))
            continue

        constraints = updated
        result = build_assignment(ctx, inputs.groups, inputs.candidates, params, constraints)
        validation = validate_assignment(inputs, ctx, result)
        if has_blocking_failure(validation):
            steps.append(_step(loop, strategy, chosen_by, targets, "still_failing"))
            continue
        steps.append(_step(loop, strategy, chosen_by, targets, "resolved"))
        resolved = True
        break

    return ResolverOutcome(result, validation, tuple(steps), resolved, tuple(llm_calls))

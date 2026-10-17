"""Deterministic min-cost-flow matching of evacuee groups to shelters (TechSpec 7.4, D-04).

The flow network is source S -> group nodes -> shelter nodes -> sink T. A diagnostic node
``"U"`` with a prohibitive integer cost absorbs persons that cannot be placed, so the matcher
names the exact group that is left over instead of failing with an opaque infeasibility error.
All weights are integer deciseconds because ``networkx.min_cost_flow`` is not guaranteed to work
with floating-point weights.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

REASON_NO_REACHABLE = "no_reachable_shelter"
REASON_INSUFFICIENT_CAPACITY = "insufficient_capacity"

_SOURCE = "S"
_SINK = "T"
_UNASSIGNED = "U"


@dataclass(frozen=True)
class MatchResult:
    """Outcome of one matching call.

    Attributes:
        legs: ``(group_id, shelter_id) -> persons`` assigned on that leg (persons, > 0).
        unassigned: ``group_id -> residual persons`` that could not be placed.
        unplaceable_reasons: ``group_id -> reason`` for every unassigned group, either
            ``"no_reachable_shelter"`` or ``"insufficient_capacity"``.
        total_cost_ds: Sum over legs of persons times travel cost, in integer deciseconds
            (0.1 s). Diagnostic penalties are excluded.
    """

    legs: dict[tuple[str, str], int] = field(default_factory=dict)
    unassigned: dict[str, int] = field(default_factory=dict)
    unplaceable_reasons: dict[str, str] = field(default_factory=dict)
    total_cost_ds: int = 0


def _usable(cost_s: float | None) -> bool:
    return cost_s is not None and math.isfinite(cost_s)


def match_groups_to_shelters(
    groups: Mapping[str, int],
    available: Mapping[str, int],
    costs: Mapping[tuple[str, str], float | None],
    *,
    banned: AbstractSet[tuple[str, str]] = frozenset(),
    per_pair_cap: Mapping[str, int] | None = None,
) -> MatchResult:
    """Assign evacuee groups to shelters at minimum total travel cost.

    Args:
        groups: ``group_id -> persons`` (persons, each at least 1).
        available: ``shelter_id -> available capacity`` in persons (usable minus occupancy).
            Negative values are treated as 0.
        costs: ``(group_id, shelter_id) -> route cost`` in seconds. ``None``, NaN or infinite
            costs mean the pair is unreachable and it is never used.
        banned: ``(group_id, shelter_id)`` pairs that must not be used.
        per_pair_cap: Optional ``group_id -> max persons`` on any single leg of that group,
            which forces a split across shelters when below the group's persons.

    Returns:
        A :class:`MatchResult`. Every person is either on a leg or reported as unassigned.

    Raises:
        ValueError: If any group has fewer than 1 person.
    """
    for group_id, persons in groups.items():
        if persons < 1:
            raise ValueError(f"group {group_id!r} must have at least 1 person, got {persons}")
    if not groups:
        return MatchResult()

    pairs = sorted(
        (g, s)
        for (g, s), c in costs.items()
        if g in groups and s in available and _usable(c) and (g, s) not in banned
    )
    weights = {(g, s): round(float(costs[(g, s)] or 0.0) * 10) for g, s in pairs}
    max_weight = max(weights.values(), default=0)
    total = sum(groups.values())
    big = (len(groups) + len(available) + 1) * (max_weight + 1) + 1

    graph: nx.DiGraph[Any] = nx.DiGraph()
    graph.add_node(_SOURCE, demand=-total)
    graph.add_node(_SINK, demand=total)
    graph.add_edge(_UNASSIGNED, _SINK, capacity=total, weight=0)
    for group_id, persons in sorted(groups.items()):
        graph.add_edge(_SOURCE, ("g", group_id), capacity=persons, weight=0)
        graph.add_edge(("g", group_id), _UNASSIGNED, capacity=persons, weight=big)
    for shelter_id, free in sorted(available.items()):
        graph.add_edge(("s", shelter_id), _SINK, capacity=max(0, free), weight=0)
    caps = per_pair_cap or {}
    for group_id, shelter_id in pairs:
        persons = groups[group_id]
        leg_cap = max(0, min(persons, caps.get(group_id, persons)))
        graph.add_edge(
            ("g", group_id),
            ("s", shelter_id),
            capacity=leg_cap,
            weight=weights[(group_id, shelter_id)],
        )

    flow = nx.min_cost_flow(graph)

    legs: dict[tuple[str, str], int] = {}
    unassigned: dict[str, int] = {}
    total_cost_ds = 0
    for group_id in sorted(groups):
        for node, amount in flow[("g", group_id)].items():
            if amount <= 0:
                continue
            if node == _UNASSIGNED:
                unassigned[group_id] = int(amount)
            elif isinstance(node, tuple):
                shelter_id = str(node[1])
                legs[(group_id, shelter_id)] = int(amount)
                total_cost_ds += int(amount) * weights[(group_id, shelter_id)]

    groups_with_pair = {g for g, _ in pairs}
    reasons = {
        g: REASON_INSUFFICIENT_CAPACITY if g in groups_with_pair else REASON_NO_REACHABLE
        for g in unassigned
    }
    return MatchResult(
        legs=legs,
        unassigned=unassigned,
        unplaceable_reasons=reasons,
        total_cost_ds=total_cost_ds,
    )

"""Hypothesis invariants for matching: capacity, conservation, determinism (PLAN-04, D-03)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from agent_shelter import match_groups_to_shelters
from hypothesis import given, settings
from hypothesis import strategies as st


@dataclass(frozen=True)
class Instance:
    groups: dict[str, int]
    available: dict[str, int]
    costs: dict[tuple[str, str], float | None]
    banned: frozenset[tuple[str, str]]


@st.composite
def instances(draw: st.DrawFn) -> Instance:
    n_groups = draw(st.integers(min_value=1, max_value=8))
    n_shelters = draw(st.integers(min_value=1, max_value=8))
    groups = {f"g{i}": draw(st.integers(min_value=1, max_value=500)) for i in range(n_groups)}
    available: dict[str, int] = {}
    for j in range(n_shelters):
        capacity = draw(st.integers(min_value=0, max_value=600))
        occupancy = draw(st.integers(min_value=0, max_value=capacity))
        usable_factor = draw(st.sampled_from([0.4, 0.6, 0.8]))
        # D-03: usable capacity is a fraction of nominal; available = usable - occupancy.
        available[f"s{j}"] = math.floor(capacity * usable_factor) - occupancy
    pairs = [(g, s) for g in groups for s in available]
    costs: dict[tuple[str, str], float | None] = {}
    for pair in pairs:
        unreachable = draw(st.booleans()) and draw(st.booleans())
        costs[pair] = None if unreachable else draw(st.floats(min_value=1.0, max_value=5000.0))
    banned = frozenset(draw(st.lists(st.sampled_from(pairs), max_size=len(pairs), unique=True)))
    return Instance(groups, available, costs, banned)


@settings(max_examples=200, deadline=None)
@given(instances())
def test_capacity_is_never_exceeded(inst: Instance) -> None:
    result = match_groups_to_shelters(inst.groups, inst.available, inst.costs, banned=inst.banned)
    for shelter, free in inst.available.items():
        placed = sum(p for (_, s), p in result.legs.items() if s == shelter)
        assert placed <= max(0, free)
    for pair in result.legs:
        assert pair not in inst.banned
        assert inst.costs[pair] is not None


@settings(max_examples=200, deadline=None)
@given(instances())
def test_every_person_is_assigned_once_or_reported_unassigned(inst: Instance) -> None:
    result = match_groups_to_shelters(inst.groups, inst.available, inst.costs, banned=inst.banned)
    for group, persons in inst.groups.items():
        placed = sum(p for (g, _), p in result.legs.items() if g == group)
        assert placed + result.unassigned.get(group, 0) == persons
    assert set(result.unassigned) == set(result.unplaceable_reasons)
    assert all(v > 0 for v in result.legs.values())
    assert set(result.unassigned) <= set(inst.groups)


@settings(max_examples=200, deadline=None)
@given(instances())
def test_matching_is_deterministic(
    inst: Instance,
) -> None:
    first = match_groups_to_shelters(inst.groups, inst.available, inst.costs, banned=inst.banned)
    second = match_groups_to_shelters(inst.groups, inst.available, inst.costs, banned=inst.banned)
    assert first == second


@settings(max_examples=200, deadline=None)
@given(instances())
def test_nothing_unassigned_when_capacity_suffices_and_all_pairs_finite(
    inst: Instance,
) -> None:
    finite = {pair: 100.0 for pair in inst.costs}
    result = match_groups_to_shelters(inst.groups, inst.available, finite)
    total_available = sum(max(0, a) for a in inst.available.values())
    if total_available >= sum(inst.groups.values()):
        assert result.unassigned == {}
    else:
        assert sum(result.unassigned.values()) == sum(inst.groups.values()) - total_available


@settings(max_examples=200, deadline=None)
@given(instances(), st.integers(min_value=1, max_value=200))
def test_per_pair_cap_limits_every_leg(inst: Instance, cap: int) -> None:
    caps = {g: cap for g in inst.groups}
    result = match_groups_to_shelters(
        inst.groups, inst.available, inst.costs, banned=inst.banned, per_pair_cap=caps
    )
    assert all(persons <= cap for persons in result.legs.values())
    for group, persons in inst.groups.items():
        placed = sum(p for (g, _), p in result.legs.items() if g == group)
        assert placed + result.unassigned.get(group, 0) == persons

from __future__ import annotations

import networkx as nx
import pytest
from agent_shelter import match_groups_to_shelters

from tests.fixtures.graphs import CORNER_NE, CORNER_SW, build_synthetic_graph

SHELTER_NODES = {"s36": CORNER_NE, "s6": 6}


def _min_parallel_time(_u: int, _v: int, edge_data: dict[int, dict[str, float]]) -> float:
    return min(attrs["travel_time"] for attrs in edge_data.values())


def test_tracer_one_group_goes_to_cheapest_shelter_with_capacity() -> None:
    graph = build_synthetic_graph()
    times = nx.single_source_dijkstra_path_length(graph, CORNER_SW, weight=_min_parallel_time)
    costs = {("g1", sid): times[node] for sid, node in SHELTER_NODES.items()}
    # Node 6 is closer to node 1 than node 36 along the primary edges, so capacity decides.
    assert costs[("g1", "s6")] < costs[("g1", "s36")]

    result = match_groups_to_shelters({"g1": 120}, {"s36": 200, "s6": 50}, costs)

    assert result.unassigned == {}
    assert sum(result.legs.values()) == 120
    assert result.legs == {("g1", "s6"): 50, ("g1", "s36"): 70}


def test_single_group_prefers_cheapest_shelter_when_it_fits() -> None:
    costs: dict[tuple[str, str], float | None] = {("g", "near"): 100.0, ("g", "far"): 900.0}
    result = match_groups_to_shelters({"g": 80}, {"near": 100, "far": 500}, costs)
    assert result.legs == {("g", "near"): 80}
    assert result.unassigned == {}
    assert result.total_cost_ds == 80 * 1000


def test_group_splits_across_two_shelters_when_none_can_hold_it() -> None:
    costs: dict[tuple[str, str], float | None] = {("g", "a"): 10.0, ("g", "b"): 20.0}
    result = match_groups_to_shelters({"g": 300}, {"a": 200, "b": 150}, costs)
    assert result.legs == {("g", "a"): 200, ("g", "b"): 100}
    assert sum(result.legs.values()) == 300
    assert result.unassigned == {}


def test_per_pair_cap_forces_a_split() -> None:
    costs: dict[tuple[str, str], float | None] = {("g", "a"): 10.0, ("g", "b"): 20.0}
    result = match_groups_to_shelters(
        {"g": 100}, {"a": 500, "b": 500}, costs, per_pair_cap={"g": 60}
    )
    assert result.legs == {("g", "a"): 60, ("g", "b"): 40}


def test_banned_and_none_cost_pairs_are_never_used() -> None:
    costs: dict[tuple[str, str], float | None] = {
        ("g", "a"): 10.0,
        ("g", "b"): None,
        ("g", "c"): 50.0,
        ("g", "d"): float("inf"),
    }
    result = match_groups_to_shelters(
        {"g": 40}, {"a": 100, "b": 100, "c": 100, "d": 100}, costs, banned={("g", "a")}
    )
    assert result.legs == {("g", "c"): 40}


def test_group_with_no_reachable_shelter_is_named_unassigned() -> None:
    costs: dict[tuple[str, str], float | None] = {
        ("ok", "a"): 10.0,
        ("lost", "a"): None,
        ("lost", "b"): float("nan"),
    }
    result = match_groups_to_shelters({"ok": 30, "lost": 25}, {"a": 100, "b": 100}, costs)
    assert result.legs == {("ok", "a"): 30}
    assert result.unassigned == {"lost": 25}
    assert result.unplaceable_reasons == {"lost": "no_reachable_shelter"}


def test_capacity_shortfall_reports_residual_with_insufficient_capacity() -> None:
    costs: dict[tuple[str, str], float | None] = {("g", "a"): 10.0, ("g", "b"): 20.0}
    result = match_groups_to_shelters({"g": 300}, {"a": 100, "b": 50}, costs)
    assert sum(result.legs.values()) == 150
    assert result.unassigned == {"g": 150}
    assert result.unplaceable_reasons == {"g": "insufficient_capacity"}


def test_negative_available_is_treated_as_zero() -> None:
    costs: dict[tuple[str, str], float | None] = {("g", "a"): 10.0, ("g", "b"): 20.0}
    result = match_groups_to_shelters({"g": 10}, {"a": -5, "b": 30}, costs)
    assert result.legs == {("g", "b"): 10}


def test_group_with_zero_persons_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1 person"):
        match_groups_to_shelters({"g": 0}, {"a": 10}, {("g", "a"): 1.0})


def test_empty_groups_return_empty_result() -> None:
    result = match_groups_to_shelters({}, {"a": 10}, {})
    assert result.legs == {} and result.unassigned == {}


def test_identical_inputs_give_identical_results() -> None:
    groups = {"g1": 120, "g2": 80, "g3": 200}
    available = {"a": 150, "b": 150, "c": 150}
    costs: dict[tuple[str, str], float | None] = {
        (g, s): float(10 * (i + 1) + 7 * j)
        for i, g in enumerate(groups)
        for j, s in enumerate(available)
    }
    first = match_groups_to_shelters(groups, available, costs)
    second = match_groups_to_shelters(groups, available, costs)
    assert first == second

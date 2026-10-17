from __future__ import annotations

import networkx as nx
from agent_shelter import match_groups_to_shelters

from tests.fixtures.graphs import CORNER_NE, CORNER_SW, build_synthetic_graph

SHELTER_NODES = {"s36": CORNER_NE, "s6": 6}


def _min_parallel_time(_u: int, _v: int, edge_data: dict[int, dict[str, float]]) -> float:
    return min(attrs["travel_time"] for attrs in edge_data.values())


def test_tracer_one_group_goes_to_cheapest_shelter_with_capacity() -> None:
    graph = build_synthetic_graph()
    times = nx.single_source_dijkstra_path_length(graph, CORNER_SW, weight=_min_parallel_time)
    costs = {("g1", sid): times[node] for sid, node in SHELTER_NODES.items()}
    # Node 6 is closer to node 1 than node 36 along the primary edges, so make capacity decide.
    assert costs[("g1", "s6")] < costs[("g1", "s36")]

    result = match_groups_to_shelters({"g1": 120}, {"s36": 200, "s6": 50}, costs)

    assert result.unassigned == {}
    assert sum(result.legs.values()) == 120
    assert result.legs == {("g1", "s6"): 50, ("g1", "s36"): 70}

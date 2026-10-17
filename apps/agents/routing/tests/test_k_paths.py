from __future__ import annotations

import networkx as nx
from agent_routing import apply_horizon_costs, collapse_to_digraph, k_shortest_paths
from wildfire_core.schemas.plan import ForecastFootprint

from tests.fixtures.graphs import CORNER_NE, CORNER_SW, DEAD_END, build_synthetic_graph

EMPTY = "POLYGON EMPTY"


def _graph(edge_status: dict[tuple[int, int, int], str] | None = None) -> nx.MultiDiGraph:
    footprint = ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )
    return apply_horizon_costs(
        build_synthetic_graph(), footprint, p50_mult=10.0, p90_mult=3.0, edge_status=edge_status
    )


def test_collapse_keeps_cheaper_parallel_edge() -> None:
    collapsed = collapse_to_digraph(_graph(), "cost_h1")

    assert isinstance(collapsed, nx.DiGraph)
    assert not collapsed.is_multigraph()
    assert collapsed[2][3]["key"] == 0
    assert collapsed[3][2]["key"] == 0
    assert collapsed[2][3]["w"] == build_synthetic_graph()[2][3][0]["travel_time"]
    assert collapsed.nodes[CORNER_SW]["x"] == 76.60


def test_collapse_drops_blocked_edges_and_falls_back_to_other_parallel_key() -> None:
    graph = _graph({(1, 2, 0): "blocked", (2, 3, 0): "blocked"})

    collapsed = collapse_to_digraph(graph, "cost_h1")

    assert not collapsed.has_edge(1, 2)
    assert collapsed.has_edge(2, 1)
    assert collapsed[2][3]["key"] == 1  # key 0 blocked, the slower parallel edge remains


def test_k_paths_returns_three_distinct_loopless_paths_with_non_decreasing_costs() -> None:
    result = k_shortest_paths(
        _graph(), CORNER_SW, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=60.0
    )

    assert len(result.paths) == 3
    assert len(set(result.paths)) == 3
    assert all(len(set(path)) == len(path) for path in result.paths)
    assert all(path[0] == CORNER_SW and path[-1] == CORNER_NE for path in result.paths)
    assert list(result.costs) == sorted(result.costs)
    assert result.truncated is False
    pairs = zip(result.paths, result.edge_keys, strict=True)
    assert all(len(keys) == len(path) - 1 for path, keys in pairs)


def test_k_paths_never_uses_blocked_edges() -> None:
    graph = _graph({(1, 2, 0): "blocked", (1, 7, 0): "blocked"})

    result = k_shortest_paths(graph, CORNER_SW, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=60)

    assert result.paths == ()  # both exits of the SW corner are blocked


def test_k_paths_returns_fewer_paths_when_alternatives_are_scarce() -> None:
    result = k_shortest_paths(
        _graph(), CORNER_NE, DEAD_END, weight_attr="cost_h1", k=3, max_leg_s=60.0
    )

    assert result.paths == ((CORNER_NE, DEAD_END),)
    assert result.edge_keys == ((0,),)
    assert result.truncated is False


def test_k_paths_zero_budget_returns_first_path_and_flags_truncation() -> None:
    result = k_shortest_paths(
        _graph(), CORNER_SW, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=0.0
    )

    assert len(result.paths) == 1
    assert result.truncated is True


def test_k_paths_unknown_node_or_no_path_gives_empty_result() -> None:
    graph = _graph()

    missing = k_shortest_paths(graph, 9999, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=1.0)
    status = {(CORNER_NE, DEAD_END, 0): "blocked"}
    cut = k_shortest_paths(
        _graph(status), CORNER_SW, DEAD_END, weight_attr="cost_h1", k=3, max_leg_s=1.0
    )

    assert missing.paths == () and missing.truncated is False
    assert cut.paths == () and cut.costs == ()


def test_k_paths_is_deterministic_and_accepts_prebuilt_digraph() -> None:
    graph = _graph()
    digraph = collapse_to_digraph(graph, "cost_h1")

    first = k_shortest_paths(graph, CORNER_SW, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=60)
    second = k_shortest_paths(
        graph, CORNER_SW, CORNER_NE, weight_attr="cost_h1", k=3, max_leg_s=60, digraph=digraph
    )

    assert first == second

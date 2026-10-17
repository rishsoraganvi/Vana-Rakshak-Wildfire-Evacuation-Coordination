from __future__ import annotations

import networkx as nx

from tests.fixtures.graphs import CORNER_NE, CORNER_SW, DEAD_END, build_synthetic_graph, node_lonlat


def _simple_digraph(graph: nx.MultiDiGraph) -> nx.DiGraph:
    return nx.DiGraph(graph)


def test_at_least_three_simple_paths_between_opposite_corners() -> None:
    simple = _simple_digraph(build_synthetic_graph())
    paths = nx.shortest_simple_paths(simple, CORNER_SW, CORNER_NE)
    found = [next(paths) for _ in range(3)]
    assert len({tuple(p) for p in found}) == 3


def test_nodes_two_and_three_have_parallel_edges() -> None:
    graph = build_synthetic_graph()
    for u, v in ((2, 3), (3, 2)):
        assert set(graph[u][v]) == {0, 1}
        assert graph[u][v][1]["travel_time"] > graph[u][v][0]["travel_time"]


def test_lane_tag_formats_cover_list_string_and_missing() -> None:
    graph = build_synthetic_graph()
    lanes = [data.get("lanes") for _, _, data in graph.edges(data=True)]
    assert "['1', '2']" in lanes
    assert None in lanes
    assert graph[15][16][0]["lanes"] == "1"
    assert graph[15][16][0]["highway"] == "track"


def test_dead_end_has_exactly_one_neighbour() -> None:
    graph = build_synthetic_graph()
    assert set(graph.successors(DEAD_END)) == {CORNER_NE}
    assert set(graph.predecessors(DEAD_END)) == {CORNER_NE}


def test_all_edges_and_nodes_have_required_attributes() -> None:
    graph = build_synthetic_graph()
    for _, _, data in graph.edges(data=True):
        assert data["length"] > 0
        assert data["travel_time"] > 0
    for node in graph.nodes:
        lon, lat = node_lonlat(graph, node)
        assert isinstance(lon, float) and isinstance(lat, float)
    assert graph.graph["crs"] == "EPSG:4326"


def test_builds_are_identical() -> None:
    def edges(graph: nx.MultiDiGraph) -> list[tuple[int, int, int, list[tuple[str, object]]]]:
        return sorted(
            (u, v, k, sorted(d.items())) for u, v, k, d in graph.edges(keys=True, data=True)
        )

    assert edges(build_synthetic_graph()) == edges(build_synthetic_graph())

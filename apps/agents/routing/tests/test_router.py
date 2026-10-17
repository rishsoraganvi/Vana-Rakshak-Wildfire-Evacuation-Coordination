from math import inf
from pathlib import Path

import networkx as nx
import osmnx as ox
import pytest
from agent_routing import (
    apply_fire_penalties,
    compute_route,
    load_or_download_graph,
    nearest_node,
    nearest_node_outside,
)
from agent_routing import graph as graph_module
from shapely.geometry import LineString


def make_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=0.0)
    graph.add_node(3, x=2.0, y=0.0)
    graph.add_edge(1, 2, key=7, length=100.0, travel_time=10.0, penalised_cost=10.0)
    graph.add_edge(2, 3, key=8, length=100.0, travel_time=10.0, penalised_cost=10.0)
    return graph


def test_compute_route_finds_safe_path_and_cluster_origin() -> None:
    route = compute_route(
        make_graph(),
        1,
        3,
        group_id="group-1",
        origin_cluster_id="cluster-1",
    )

    assert route is not None
    assert route.osm_node_path == (1, 2, 3)
    assert route.total_distance_m == 200.0
    assert route.estimated_travel_time_s == 20.0
    assert route.safety_classification == "safe"
    assert route.origin_cluster_id == "cluster-1"
    assert route.origin_settlement_id is None


def test_compute_route_caution_with_penalty_edge() -> None:
    graph = make_graph()
    graph[1][2][7]["penalised_cost"] = 50.0

    route = compute_route(
        graph,
        1,
        3,
        group_id="group-1",
        origin_settlement_id="settlement-1",
    )

    assert route is not None
    assert route.safety_classification == "caution"
    assert route.fire_penalty_edges == (7,)


def test_compute_route_classifies_blocked_path() -> None:
    graph = make_graph()
    graph[1][2][7]["penalised_cost"] = inf

    route = compute_route(
        graph,
        1,
        3,
        group_id="group-1",
        origin_cluster_id="cluster-1",
    )

    assert route is not None
    assert route.safety_classification == "blocked"
    assert route.fire_penalty_edges == (7,)


def test_compute_route_returns_none_when_disconnected() -> None:
    graph = make_graph()
    graph.remove_edge(2, 3, 8)

    route = compute_route(
        graph,
        1,
        3,
        group_id="group-1",
        origin_cluster_id="cluster-1",
    )

    assert route is None


def test_compute_route_requires_one_origin_identifier() -> None:
    with pytest.raises(ValueError, match="exactly one route origin"):
        compute_route(make_graph(), 1, 3, group_id="group-1")


def test_apply_fire_penalties_blocks_inside_current_perimeter() -> None:
    graph = make_graph()
    current_perimeter = "POLYGON ((0.4 -0.5, 0.6 -0.5, 0.6 0.5, 0.4 0.5, 0.4 -0.5))"

    penalized_graph = apply_fire_penalties(graph, current_perimeter, "POLYGON EMPTY")

    assert penalized_graph[1][2][7]["penalised_cost"] == inf
    assert graph[1][2][7]["penalised_cost"] == 10.0


def test_apply_fire_penalties_increases_cost_inside_p50_perimeter() -> None:
    graph = make_graph()
    p50_perimeter = "POLYGON ((0.4 -0.5, 0.6 -0.5, 0.6 0.5, 0.4 0.5, 0.4 -0.5))"

    penalized_graph = apply_fire_penalties(graph, "POLYGON EMPTY", p50_perimeter)

    assert penalized_graph[1][2][7]["penalised_cost"] == 50.0
    assert penalized_graph[2][3][8]["penalised_cost"] == 10.0


def test_apply_fire_penalties_safe_outside_perimeters() -> None:
    graph = make_graph()

    penalized_graph = apply_fire_penalties(graph, "POLYGON EMPTY", "POLYGON EMPTY")

    assert penalized_graph[1][2][7]["penalised_cost"] == 10.0
    assert penalized_graph[2][3][8]["penalised_cost"] == 10.0


def _square(x0: float, y0: float, x1: float, y1: float) -> str:
    return f"POLYGON (({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


def test_apply_fire_penalties_blocks_edge_with_endpoint_inside_perimeter() -> None:
    perimeter = _square(-0.1, -0.1, 0.2, 0.1)  # contains node 1, not the (1,2) midpoint

    penalized = apply_fire_penalties(make_graph(), perimeter, "POLYGON EMPTY")

    assert penalized[1][2][7]["penalised_cost"] == inf
    assert penalized[2][3][8]["penalised_cost"] == 10.0


def test_apply_fire_penalties_blocks_edge_crossing_perimeter_with_midpoint_outside() -> None:
    perimeter = _square(0.1, -0.5, 0.3, 0.5)  # strip crossing edge (1,2) away from midpoint

    penalized = apply_fire_penalties(make_graph(), perimeter, "POLYGON EMPTY")

    assert penalized[1][2][7]["penalised_cost"] == inf


def test_apply_fire_penalties_blocks_edge_touching_perimeter_boundary() -> None:
    perimeter = "POLYGON ((1 0, 1.1 0.3, 0.9 0.3, 1 0))"  # touches node 2 at the vertex only

    penalized = apply_fire_penalties(make_graph(), perimeter, "POLYGON EMPTY")

    assert penalized[1][2][7]["penalised_cost"] == inf
    assert penalized[2][3][8]["penalised_cost"] == inf


def test_apply_fire_penalties_uses_edge_geometry_when_present() -> None:
    graph = make_graph()
    graph[2][3][8]["geometry"] = LineString([(1, 0), (1.5, 0.5), (2, 0)])
    p50 = _square(1.4, 0.4, 1.6, 0.6)  # the straight chord never touches this

    penalized = apply_fire_penalties(graph, "POLYGON EMPTY", p50)

    assert penalized[2][3][8]["penalised_cost"] == 50.0
    assert penalized[1][2][7]["penalised_cost"] == 10.0


def test_bundled_fixture_route_through_active_fire_is_not_safe() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "tests"
        / "fixtures"
        / "osm"
        / "bandipur_stub.graphml"
    )
    graph = load_or_download_graph(fixture_path, (11.74, 11.70, 76.66, 76.62))
    perimeter = _square(76.6366313, 11.7166313, 76.6433687, 11.7233687)

    penalized = apply_fire_penalties(graph, perimeter, "POLYGON EMPTY")
    route = compute_route(
        penalized,
        1000002,
        1000003,
        group_id="g",
        origin_cluster_id="c",
    )

    assert route is not None
    assert route.safety_classification == "blocked"
    assert route.fire_penalty_edges


def test_load_or_download_graph_uses_cache(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "cached.graphml"
    cache_path.write_text("cached", encoding="utf-8")
    graph = make_graph()
    monkeypatch.setattr(ox, "load_graphml", lambda _path: graph)
    monkeypatch.setattr(
        ox,
        "graph_from_bbox",
        lambda *_args, **_kwargs: pytest.fail("unexpected download"),
    )
    monkeypatch.setattr(ox, "add_edge_speeds", lambda cached_graph: cached_graph)
    monkeypatch.setattr(ox, "add_edge_travel_times", lambda cached_graph: cached_graph)

    result = load_or_download_graph(cache_path, (12.0, 11.0, 77.0, 76.0))

    assert result is graph


def test_bundled_graphml_fixture_loads_with_travel_times() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4]
        / "tests"
        / "fixtures"
        / "osm"
        / "bandipur_stub.graphml"
    )

    graph = load_or_download_graph(fixture_path, (11.74, 11.70, 76.66, 76.62))

    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 4
    assert all(data["travel_time"] > 0 for _, _, data in graph.edges(data=True))


def test_load_or_download_graph_converts_bbox_and_saves_cache(tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "nested" / "road.graphml"
    graph = make_graph()
    calls: dict[str, object] = {}

    def graph_from_bbox(
        bbox: tuple[float, float, float, float], network_type: str
    ) -> nx.MultiDiGraph:
        calls["bbox"] = bbox
        calls["network_type"] = network_type
        return graph

    def save_graphml(saved_graph: nx.MultiDiGraph, filepath: Path) -> None:
        calls["saved_graph"] = saved_graph
        calls["filepath"] = filepath
        filepath.write_text("cached", encoding="utf-8")

    monkeypatch.setattr(ox, "graph_from_bbox", graph_from_bbox)
    monkeypatch.setattr(ox, "save_graphml", save_graphml)
    monkeypatch.setattr(ox, "add_edge_speeds", lambda cached_graph: cached_graph)
    monkeypatch.setattr(ox, "add_edge_travel_times", lambda cached_graph: cached_graph)

    result = load_or_download_graph(cache_path, (12.0, 11.0, 77.0, 76.0), "drive")

    assert result is graph
    assert calls["bbox"] == (76.0, 11.0, 77.0, 12.0)
    assert calls["network_type"] == "drive"
    assert calls["filepath"] == cache_path
    assert cache_path.is_file()


def test_nearest_node_passes_longitude_as_x(monkeypatch) -> None:
    calls: dict[str, float] = {}

    def nearest_nodes(_graph: nx.MultiDiGraph, *, X: float, Y: float) -> int:
        calls["X"] = X
        calls["Y"] = Y
        return 42

    monkeypatch.setattr(graph_module.ox, "nearest_nodes", nearest_nodes)

    result = nearest_node(make_graph(), lat=11.72, lon=76.64)

    assert result == 42
    assert calls == {"X": 76.64, "Y": 11.72}


def _add_edge(
    graph: nx.MultiDiGraph,
    u: int,
    v: int,
    cost: float,
    *,
    key: int = 0,
    travel_time: float | None = None,
    length: float | None = None,
) -> None:
    tt = cost if travel_time is None else travel_time
    graph.add_edge(
        u,
        v,
        key=key,
        length=length if length is not None else tt,
        travel_time=tt,
        penalised_cost=cost,
    )


def test_compute_route_least_blocked_fallback_minimises_blocked_exposure() -> None:
    graph = nx.MultiDiGraph()
    _add_edge(graph, 1, 2, inf, travel_time=100.0, length=100.0)
    _add_edge(graph, 1, 3, inf, travel_time=10.0, length=10.0)
    _add_edge(graph, 2, 4, 10.0, travel_time=10.0, length=10.0)
    _add_edge(graph, 3, 4, 10.0, travel_time=10.0, length=10.0)

    route = compute_route(graph, 1, 4, group_id="g", origin_cluster_id="c")

    assert route is not None
    assert route.osm_node_path == (1, 3, 4)
    assert route.safety_classification == "blocked"
    assert len(route.fire_penalty_edges) == 1


def test_compute_route_prefers_unblocked_detour() -> None:
    graph = nx.MultiDiGraph()
    _add_edge(graph, 1, 2, inf, travel_time=10.0)
    _add_edge(graph, 2, 4, 10.0, travel_time=10.0)
    _add_edge(graph, 1, 3, 50.0, travel_time=50.0)
    _add_edge(graph, 3, 4, 50.0, travel_time=50.0)

    route = compute_route(graph, 1, 4, group_id="g", origin_cluster_id="c")

    assert route is not None
    assert route.osm_node_path == (1, 3, 4)
    assert route.safety_classification == "safe"


def test_compute_route_mixed_parallel_edges_uses_finite_edge() -> None:
    graph = nx.MultiDiGraph()
    _add_edge(graph, 1, 2, inf, key=0, travel_time=10.0)
    _add_edge(graph, 1, 2, 20.0, key=1, travel_time=20.0)

    route = compute_route(graph, 1, 2, group_id="g", origin_cluster_id="c")

    assert route is not None
    assert route.safety_classification != "blocked"
    assert 0 not in route.fire_penalty_edges


def _node_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=0.1, y=0.0)
    graph.add_node(3, x=0.3, y=0.0)
    return graph


def test_nearest_node_outside_skips_covered_nodes() -> None:
    perimeter = _square(-0.05, -0.05, 0.05, 0.05)

    assert nearest_node_outside(_node_graph(), 0.0, 0.0, perimeter) == 2


def test_nearest_node_outside_empty_perimeter_returns_nearest() -> None:
    assert nearest_node_outside(_node_graph(), 0.0, 0.0, "POLYGON EMPTY") == 1


def test_nearest_node_outside_returns_none_when_all_covered() -> None:
    perimeter = _square(-1.0, -1.0, 1.0, 1.0)

    assert nearest_node_outside(_node_graph(), 0.0, 0.0, perimeter) is None


def test_nearest_node_outside_boundary_counts_as_covered() -> None:
    perimeter = _square(-0.05, -0.05, 0.1, 0.05)  # node 2 sits on the boundary

    assert nearest_node_outside(_node_graph(), 0.0, 0.0, perimeter) == 3


def test_nearest_node_outside_ties_go_to_smallest_id() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(5, x=0.2, y=0.0)
    graph.add_node(3, x=-0.2, y=0.0)
    graph.add_node(9, x=0.0, y=0.0)
    perimeter = _square(-0.05, -0.05, 0.05, 0.05)

    assert nearest_node_outside(graph, 0.0, 0.0, perimeter) == 3

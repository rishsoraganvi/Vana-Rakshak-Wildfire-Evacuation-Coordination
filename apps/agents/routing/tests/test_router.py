from math import inf
from pathlib import Path

import networkx as nx
import osmnx as ox
import pytest
from agent_routing import apply_fire_penalties, compute_route, load_or_download_graph, nearest_node
from agent_routing import graph as graph_module


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

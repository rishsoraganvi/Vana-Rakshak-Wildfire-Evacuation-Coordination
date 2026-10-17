import networkx as nx
from coordinator.graph import _aoi_boundary_exit_nodes
from coordinator.runner import build_graph
from shapely import wkt


def test_graph_has_all_eight_nodes() -> None:
    graph = build_graph().compile().get_graph()

    assert {
        "ingest_trigger",
        "run_weather",
        "cluster_hotspots",
        "run_fire_ca",
        "compute_route",
        "generate_rationale",
        "assemble_plan",
        "write_audit",
    }.issubset(graph.nodes)


def test_graph_entry_point_is_ingest_trigger() -> None:
    graph = build_graph().compile().get_graph()

    assert any(
        edge.source == "__start__" and edge.target == "ingest_trigger"
        for edge in graph.edges
    )


def test_route_destinations_are_safe_nodes_nearest_each_aoi_boundary() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.05, y=5.0)
    graph.add_node(2, x=9.95, y=5.0)
    graph.add_node(3, x=5.0, y=0.05)
    graph.add_node(4, x=5.0, y=9.95)
    graph.add_node(5, x=5.0, y=5.0)
    graph.add_node(6, x=0.5, y=5.0)
    current_perimeter = wkt.loads("POLYGON ((0 4, 0.2 4, 0.2 6, 0 6, 0 4))")

    exits = _aoi_boundary_exit_nodes(graph, (0.0, 0.0, 10.0, 10.0), current_perimeter)

    assert exits == [6, 2, 3, 4]
    assert 1 not in exits
    assert 5 not in exits
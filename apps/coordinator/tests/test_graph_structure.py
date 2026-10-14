from coordinator.runner import build_graph


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
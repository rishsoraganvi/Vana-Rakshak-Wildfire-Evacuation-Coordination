from coordinator.graph import NODE_ORDER
from coordinator.repository import InMemoryPlanningRepository
from coordinator.runner import build_graph
from pipeline_factory import make_deps, make_settings

EXPECTED_ORDER = [
    "ingest_trigger",
    "cluster_hotspots",
    "run_weather",
    "run_fire_ca",
    "assess_risk",
    "dispatch_specialists",
    "plan_evacuation",
    "generate_rationale",
    "assemble_plan",
    "write_audit",
]


def _compiled_graph():
    deps = make_deps(InMemoryPlanningRepository(), make_settings())
    return build_graph(deps).compile().get_graph()


def test_graph_has_exactly_the_ten_phase3_nodes() -> None:
    graph = _compiled_graph()

    assert list(NODE_ORDER) == EXPECTED_ORDER
    assert {name for name in graph.nodes if not name.startswith("__")} == set(EXPECTED_ORDER)


def test_graph_entry_point_is_ingest_trigger() -> None:
    graph = _compiled_graph()

    assert any(
        edge.source == "__start__" and edge.target == "ingest_trigger" for edge in graph.edges
    )


def test_edges_run_weather_before_fire_then_risk_then_specialists() -> None:
    graph = _compiled_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    for current, following in zip(EXPECTED_ORDER, EXPECTED_ORDER[1:], strict=False):
        assert (current, following) in edges
    assert ("write_audit", "__end__") in edges
    position = {name: index for index, name in enumerate(EXPECTED_ORDER)}
    assert position["cluster_hotspots"] < position["run_weather"] < position["run_fire_ca"]
    assert position["run_fire_ca"] < position["assess_risk"] < position["dispatch_specialists"]

from __future__ import annotations

from typing import cast

from langgraph.graph import END, StateGraph

from coordinator.graph import (
    assemble_plan,
    cluster_hotspots_node,
    compute_route_node,
    generate_rationale_node,
    ingest_trigger,
    run_fire_ca,
    run_weather,
    write_audit,
)
from coordinator.state import CoordinatorState

CoordinatorGraph = StateGraph[CoordinatorState, None, CoordinatorState, CoordinatorState]


def build_graph() -> CoordinatorGraph:
    graph = StateGraph(CoordinatorState)
    graph.add_node("ingest_trigger", ingest_trigger)
    graph.add_node("run_weather", run_weather)
    graph.add_node("cluster_hotspots", cluster_hotspots_node)
    graph.add_node("run_fire_ca", run_fire_ca)
    graph.add_node("compute_route", compute_route_node)
    graph.add_node("generate_rationale", generate_rationale_node)
    graph.add_node("assemble_plan", assemble_plan)
    graph.add_node("write_audit", write_audit)

    graph.set_entry_point("ingest_trigger")
    graph.add_edge("ingest_trigger", "run_weather")
    graph.add_edge("run_weather", "cluster_hotspots")
    graph.add_edge("cluster_hotspots", "run_fire_ca")
    graph.add_edge("run_fire_ca", "compute_route")
    graph.add_edge("compute_route", "generate_rationale")
    graph.add_edge("generate_rationale", "assemble_plan")
    graph.add_edge("assemble_plan", "write_audit")
    graph.add_edge("write_audit", END)
    return graph


def run_coordinator(incident_id: str, run_id: str) -> CoordinatorState:
    initial_state: CoordinatorState = {
        "incident_id": incident_id,
        "run_id": run_id,
        "hotspot_ids": [],
        "hotspots": [],
        "weather_snapshot": None,
        "clusters": [],
        "fire_result": None,
        "routes": [],
        "rationale": "",
        "is_llm_fallback": False,
        "audit_entries": [],
        "warnings": [],
        "error": None,
    }
    return cast(CoordinatorState, build_graph().compile().invoke(initial_state))
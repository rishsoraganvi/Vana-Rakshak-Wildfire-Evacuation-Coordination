from __future__ import annotations

from math import inf
from typing import Any, Literal

import networkx as nx
import osmnx as ox
from wildfire_core.schemas.phase2 import RouteResult


def nearest_node(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]], lat: float, lon: float
) -> int:
    return int(ox.nearest_nodes(graph, X=lon, Y=lat))


def compute_route(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    origin_node: int,
    dest_node: int,
    weight: str = "penalised_cost",
    *,
    group_id: str,
    origin_cluster_id: str | None = None,
    origin_settlement_id: str | None = None,
) -> RouteResult | None:
    if (origin_cluster_id is None) == (origin_settlement_id is None):
        raise ValueError("exactly one route origin identifier is required")

    try:
        node_path = nx.dijkstra_path(graph, origin_node, dest_node, weight=weight)
    except nx.NetworkXNoPath:
        return None

    if len(node_path) < 2:
        return None

    selected_edges: list[tuple[int, float, float, float]] = []
    for origin, destination in zip(node_path, node_path[1:], strict=False):
        parallel_edges = graph.get_edge_data(origin, destination)
        if not parallel_edges:
            raise RuntimeError(f"Dijkstra path contains missing edge: {origin} -> {destination}")
        edge_key, edge_data = min(
            parallel_edges.items(),
            key=lambda item: float(item[1].get(weight, 1.0)),
        )
        if not isinstance(edge_key, int):
            raise TypeError(f"OSM edge key must be an integer, got {type(edge_key).__name__}")
        penalized_cost = float(edge_data[weight])
        travel_time = float(edge_data["travel_time"])
        length = float(edge_data["length"])
        selected_edges.append((edge_key, penalized_cost, travel_time, length))

    safety_classification: Literal["safe", "caution", "blocked"]
    if any(penalized_cost == inf for _, penalized_cost, _, _ in selected_edges):
        safety_classification = "blocked"
    elif any(penalized_cost > travel_time for _, penalized_cost, travel_time, _ in selected_edges):
        safety_classification = "caution"
    else:
        safety_classification = "safe"

    return RouteResult(
        group_id=group_id,
        origin_cluster_id=origin_cluster_id,
        origin_settlement_id=origin_settlement_id,
        osm_node_path=tuple(int(node) for node in node_path),
        total_distance_m=sum(length for _, _, _, length in selected_edges),
        estimated_travel_time_s=sum(travel_time for _, _, travel_time, _ in selected_edges),
        safety_classification=safety_classification,
        fire_penalty_edges=tuple(
            edge_key
            for edge_key, penalized_cost, travel_time, _ in selected_edges
            if penalized_cost > travel_time
        ),
    )
from __future__ import annotations

from collections.abc import Callable
from math import cos, inf, isfinite, radians
from typing import Any, Literal

import networkx as nx
import osmnx as ox
from shapely import wkt
from shapely.geometry import Point
from wildfire_core.schemas.phase2 import RouteResult

# An infinite penalty (D-06) cannot be ranked by Dijkstra. When every path is
# blocked, blocked edges are weighted by this factor x travel_time so the
# least-exposure path is chosen deterministically.
BLOCKED_FALLBACK_COST_FACTOR = 1_000_000.0

_WeightFn = Callable[[int, int, dict[Any, dict[str, Any]]], float | None]


def nearest_node(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]], lat: float, lon: float
) -> int:
    return int(ox.nearest_nodes(graph, X=lon, Y=lat))


def nearest_node_outside(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    lat: float,
    lon: float,
    perimeter_wkt: str,
) -> int | None:
    """Closest node not covered by the perimeter (boundary counts as covered).

    Ties go to the smallest node id. Returns None when every node is covered.
    """
    perimeter = wkt.loads(perimeter_wkt)
    lon_scale = cos(radians(lat))
    best: tuple[float, int] | None = None
    for node, data in graph.nodes(data=True):
        x = float(data["x"])
        y = float(data["y"])
        if not perimeter.is_empty and perimeter.covers(Point(x, y)):
            continue
        distance = ((x - lon) * lon_scale) ** 2 + (y - lat) ** 2
        candidate = (distance, int(node))
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[1]


def _edge_cost(attr: dict[str, Any], weight: str, *, fallback: bool) -> float | None:
    cost = float(attr.get(weight, 1.0))
    if isfinite(cost):
        return cost
    if not fallback:
        return None
    return BLOCKED_FALLBACK_COST_FACTOR * max(float(attr["travel_time"]), 1.0)


def _unblocked_weight(weight: str) -> _WeightFn:
    def weight_fn(_u: int, _v: int, parallel_edges: dict[Any, dict[str, Any]]) -> float | None:
        costs = [_edge_cost(attr, weight, fallback=False) for attr in parallel_edges.values()]
        finite = [cost for cost in costs if cost is not None]
        return min(finite) if finite else None

    return weight_fn


def _least_blocked_weight(weight: str) -> _WeightFn:
    def weight_fn(_u: int, _v: int, parallel_edges: dict[Any, dict[str, Any]]) -> float | None:
        costs = [_edge_cost(attr, weight, fallback=True) for attr in parallel_edges.values()]
        return min(cost for cost in costs if cost is not None)

    return weight_fn


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

    # Phase 1: hide blocked (inf) edges so Dijkstra ranks every unblocked path.
    fallback = False
    try:
        node_path = nx.dijkstra_path(
            graph, origin_node, dest_node, weight=_unblocked_weight(weight)
        )
    except nx.NetworkXNoPath:
        # Phase 2: no unblocked path; return the least-blocked path.
        fallback = True
        try:
            node_path = nx.dijkstra_path(
                graph, origin_node, dest_node, weight=_least_blocked_weight(weight)
            )
        except nx.NetworkXNoPath:
            return None

    if len(node_path) < 2:
        return None

    selected_edges: list[tuple[int, float, float, float]] = []
    for origin, destination in zip(node_path, node_path[1:], strict=False):
        parallel_edges = graph.get_edge_data(origin, destination)
        if not parallel_edges:
            raise RuntimeError(f"Dijkstra path contains missing edge: {origin} -> {destination}")
        candidates = [
            (cost, item)
            for item in parallel_edges.items()
            if (cost := _edge_cost(item[1], weight, fallback=fallback)) is not None
        ]
        if not candidates:
            raise RuntimeError(f"Dijkstra path hop has no usable edge: {origin} -> {destination}")
        _, (edge_key, edge_data) = min(candidates, key=lambda candidate: candidate[0])
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

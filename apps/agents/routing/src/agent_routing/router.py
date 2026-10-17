from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import asin, cos, inf, isfinite, radians, sin, sqrt
from typing import Any, Literal

import networkx as nx
import osmnx as ox
from shapely import wkt
from shapely.geometry import Point
from wildfire_core.geo.horizons import HORIZONS_H, nearest_horizon_h
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


_EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_M * asin(sqrt(a))


def snap_points(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    points: Mapping[str, tuple[float, float]],
    *,
    perimeter_wkt: str,
    max_snap_m: float,
) -> dict[str, int | None]:
    """Snap (lat, lon) points to the nearest node outside the perimeter.

    A point farther than ``max_snap_m`` (haversine) from its snap node gives None.
    """
    snapped: dict[str, int | None] = {}
    for point_id in sorted(points):
        lat, lon = points[point_id]
        node = nearest_node_outside(graph, lat, lon, perimeter_wkt)
        if node is None:
            snapped[point_id] = None
            continue
        data = graph.nodes[node]
        distance = _haversine_m(lat, lon, float(data["y"]), float(data["x"]))
        snapped[point_id] = node if distance <= max_snap_m else None
    return snapped


@dataclass(frozen=True)
class LegCost:
    """Cost of one settlement-to-shelter leg and the horizon that priced it (D-07)."""

    cost_s: float
    free_flow_s: float
    horizon_h: int


def _not_blocked_weight(weight: str) -> _WeightFn:
    """Cheapest finite parallel edge that is not blocked; None hides the hop."""

    def weight_fn(_u: int, _v: int, parallel_edges: dict[Any, dict[str, Any]]) -> float | None:
        costs = [
            float(attr[weight])
            for attr in parallel_edges.values()
            if not attr.get("blocked", False) and isfinite(float(attr[weight]))
        ]
        return min(costs) if costs else None

    return weight_fn


def route_cost_matrix(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    origins: Mapping[str, int],
    targets: Mapping[str, int],
    *,
    time_attr: str = "congested_time",
) -> dict[tuple[str, str], LegCost | None]:
    """Origin-to-target cost matrix using the horizon nearest each leg's free-flow time.

    One Dijkstra per origin over ``time_attr`` and one per horizon cost attribute (D-07).
    """
    free_weight = _not_blocked_weight(time_attr)
    horizon_weights = {h: _unblocked_weight(f"cost_h{h}") for h in HORIZONS_H}
    matrix: dict[tuple[str, str], LegCost | None] = {}
    for origin_id in sorted(origins):
        origin_node = origins[origin_id]
        free_flow = nx.single_source_dijkstra_path_length(graph, origin_node, weight=free_weight)
        by_horizon = {
            h: nx.single_source_dijkstra_path_length(graph, origin_node, weight=weight_fn)
            for h, weight_fn in horizon_weights.items()
        }
        for target_id in sorted(targets):
            target_node = targets[target_id]
            if target_node == origin_node:
                matrix[(origin_id, target_id)] = LegCost(0.0, 0.0, 1)
                continue
            free_flow_s = free_flow.get(target_node)
            if free_flow_s is None:
                matrix[(origin_id, target_id)] = None
                continue
            horizon = int(nearest_horizon_h(free_flow_s / 60.0))
            cost = by_horizon[horizon].get(target_node)
            matrix[(origin_id, target_id)] = (
                None if cost is None else LegCost(float(cost), float(free_flow_s), horizon)
            )
    return matrix


def build_route_edges(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    node_path: Sequence[int],
    weight_attr: str,
) -> tuple[int, ...]:
    """Key of the cheapest finite, unblocked parallel edge for each hop of ``node_path``."""
    keys: list[int] = []
    for origin, destination in zip(node_path, node_path[1:], strict=False):
        parallel_edges = graph.get_edge_data(origin, destination)
        if not parallel_edges:
            raise RuntimeError(f"path contains missing edge: {origin} -> {destination}")
        candidates = [
            (cost, key)
            for key, attr in parallel_edges.items()
            if not attr.get("blocked", False)
            and isfinite(cost := float(attr.get(weight_attr, 1.0)))
        ]
        if not candidates:
            raise RuntimeError(f"path hop has no usable edge: {origin} -> {destination}")
        _, edge_key = min(candidates, key=lambda candidate: candidate[0])
        if not isinstance(edge_key, int):
            raise TypeError(f"OSM edge key must be an integer, got {type(edge_key).__name__}")
        keys.append(edge_key)
    return tuple(keys)


@dataclass(frozen=True)
class PathEvaluation:
    """Per-edge fire exposure of a path under the shared nearest-horizon rule (D-21)."""

    arrival_end_s: tuple[float, ...]
    horizons: tuple[int, ...]
    zones: tuple[str, ...]
    blocked_idx: tuple[int, ...]
    p50_idx: tuple[int, ...]
    p90_idx: tuple[int, ...]
    total_time_s: float
    distance_m: float
    risk_score: float
    safe: bool


def evaluate_path(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    node_path: Sequence[int],
    edge_keys: Sequence[int],
    *,
    time_attr: str = "congested_time",
) -> PathEvaluation:
    """Evaluate each edge at its (conservative) end-of-edge arrival time."""
    hops = list(zip(node_path, node_path[1:], strict=False))
    if len(edge_keys) != len(hops):
        raise ValueError("edge_keys must have one key per hop")
    elapsed = 0.0
    distance = 0.0
    exposed_time = 0.0
    arrivals: list[float] = []
    horizons: list[int] = []
    zones: list[str] = []
    for (origin, destination), key in zip(hops, edge_keys, strict=True):
        data = graph[origin][destination][key]
        edge_time = float(data[time_attr])
        elapsed += edge_time
        distance += float(data["length"])
        horizon = int(nearest_horizon_h(elapsed / 60.0))
        zone = str(data[f"zone_h{horizon}"])
        if zone in ("p50", "p90"):
            exposed_time += edge_time
        arrivals.append(elapsed)
        horizons.append(horizon)
        zones.append(zone)
    blocked_idx = tuple(i for i, zone in enumerate(zones) if zone == "blocked")
    p50_idx = tuple(i for i, zone in enumerate(zones) if zone == "p50")
    p90_idx = tuple(i for i, zone in enumerate(zones) if zone == "p90")
    risk = min(exposed_time / elapsed, 1.0) if elapsed > 0 else 0.0
    return PathEvaluation(
        arrival_end_s=tuple(arrivals),
        horizons=tuple(horizons),
        zones=tuple(zones),
        blocked_idx=blocked_idx,
        p50_idx=p50_idx,
        p90_idx=p90_idx,
        total_time_s=elapsed,
        distance_m=distance,
        risk_score=risk,
        safe=not blocked_idx and not p50_idx,
    )

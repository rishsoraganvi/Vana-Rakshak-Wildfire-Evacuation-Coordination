from __future__ import annotations

from collections.abc import Mapping
from math import inf
from typing import Any

import networkx as nx
import shapely
from shapely import wkt
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from wildfire_core.geo.horizons import HORIZONS_H
from wildfire_core.schemas.plan import ForecastFootprint

FIRE_PENALTY_SAFE = 1.0
FIRE_PENALTY_NEAR = 5.0
FIRE_PENALTY_BLOCKED = inf


def edge_geometry(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    origin: int,
    destination: int,
    data: dict[str, Any],
) -> LineString:
    """Edge LineString: the OSM geometry when present, else the chord between endpoints."""
    geometry = data.get("geometry")
    if isinstance(geometry, LineString):
        return geometry
    origin_data = graph.nodes[origin]
    destination_data = graph.nodes[destination]
    return LineString(
        [
            (float(origin_data["x"]), float(origin_data["y"])),
            (float(destination_data["x"]), float(destination_data["y"])),
        ]
    )


def apply_fire_penalties(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    current_perimeter_wkt: str,
    p50_perimeter_wkt: str,
    penalty_near: float = FIRE_PENALTY_NEAR,
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Return a graph copy whose edges are weighted by fire exposure.

    Exposure is tested on the full edge geometry (OSM LineString when present,
    otherwise the straight chord between endpoints). ``intersects`` covers
    contained endpoints, crossings and boundary touches.
    """
    current_perimeter = wkt.loads(current_perimeter_wkt)
    p50_perimeter = wkt.loads(p50_perimeter_wkt)
    if not current_perimeter.is_empty:
        shapely.prepare(current_perimeter)
    if not p50_perimeter.is_empty:
        shapely.prepare(p50_perimeter)
    penalized_graph = graph.copy()

    for origin, destination, _key, data in penalized_graph.edges(keys=True, data=True):
        geometry = edge_geometry(penalized_graph, origin, destination, data)
        travel_time = float(data["travel_time"])

        if not current_perimeter.is_empty and current_perimeter.intersects(geometry):
            data["penalised_cost"] = FIRE_PENALTY_BLOCKED
        elif not p50_perimeter.is_empty and p50_perimeter.intersects(geometry):
            data["penalised_cost"] = penalty_near * travel_time
        else:
            data["penalised_cost"] = FIRE_PENALTY_SAFE * travel_time

    return penalized_graph


_BLOCKING_STATUSES = frozenset({"blocked", "unsafe"})


def _intersecting_indices(tree: shapely.STRtree, wkt_text: str) -> set[int]:
    perimeter: BaseGeometry = wkt.loads(wkt_text)
    if perimeter.is_empty:
        return set()
    return {int(index) for index in tree.query(perimeter, predicate="intersects")}


def apply_horizon_costs(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    footprint: ForecastFootprint,
    *,
    p50_mult: float,
    p90_mult: float,
    edge_status: Mapping[tuple[int, int, int], str] | None = None,
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Return a graph copy carrying per-horizon fire costs on every edge (D-07, D-21).

    Zone precedence per horizon is blocked > p50 > p90 > safe. An edge is blocked when it
    intersects the current perimeter or its status is blocked/unsafe. ``cost_h{h}`` is the
    congested time times the horizon's fire multiplier (inf when blocked).
    """
    result = graph.copy()
    status_by_edge = edge_status or {}
    edges = list(result.edges(keys=True, data=True))
    geometries = [edge_geometry(result, u, v, data) for u, v, _key, data in edges]
    tree = shapely.STRtree(geometries)

    current_hits = _intersecting_indices(tree, footprint.current_wkt)
    p50_hits = {
        1: _intersecting_indices(tree, footprint.p50_1h_wkt),
        3: _intersecting_indices(tree, footprint.p50_3h_wkt),
        6: _intersecting_indices(tree, footprint.p50_6h_wkt),
    }
    p90_hits = {
        1: _intersecting_indices(tree, footprint.p90_1h_wkt),
        3: _intersecting_indices(tree, footprint.p90_3h_wkt),
        6: _intersecting_indices(tree, footprint.p90_6h_wkt),
    }

    for index, (u, v, key, data) in enumerate(edges):
        status = status_by_edge.get((u, v, key), "open")
        blocked = index in current_hits or status in _BLOCKING_STATUSES
        data["edge_status"] = status
        data["blocked"] = blocked
        for h in HORIZONS_H:
            zone, mult = _zone_and_mult(
                blocked=blocked,
                in_p50=index in p50_hits[h],
                in_p90=index in p90_hits[h],
                p50_mult=p50_mult,
                p90_mult=p90_mult,
            )
            data[f"zone_h{h}"] = zone
            data[f"fire_mult_h{h}"] = mult
        data["congested_time"] = float(data["travel_time"])
        data["vc_ratio"] = 0.0
    refresh_horizon_costs(result)
    return result


def _zone_and_mult(
    *, blocked: bool, in_p50: bool, in_p90: bool, p50_mult: float, p90_mult: float
) -> tuple[str, float]:
    if blocked:
        return "blocked", inf
    if in_p50:
        return "p50", p50_mult
    if in_p90:
        return "p90", p90_mult
    return "safe", 1.0


def refresh_horizon_costs(graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]) -> None:
    """Recompute ``cost_h*`` in place from ``congested_time`` and ``fire_mult_h*``."""
    for _u, _v, data in graph.edges(data=True):
        congested = float(data["congested_time"])
        for h in HORIZONS_H:
            mult = float(data[f"fire_mult_h{h}"])
            data[f"cost_h{h}"] = inf if mult == inf else congested * mult

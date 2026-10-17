from __future__ import annotations

from math import inf
from typing import Any

import networkx as nx
import shapely
from shapely import wkt
from shapely.geometry import LineString

FIRE_PENALTY_SAFE = 1.0
FIRE_PENALTY_NEAR = 5.0
FIRE_PENALTY_BLOCKED = inf


def _edge_geometry(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    origin: int,
    destination: int,
    data: dict[str, Any],
) -> LineString:
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
        geometry = _edge_geometry(penalized_graph, origin, destination, data)
        travel_time = float(data["travel_time"])

        if not current_perimeter.is_empty and current_perimeter.intersects(geometry):
            data["penalised_cost"] = FIRE_PENALTY_BLOCKED
        elif not p50_perimeter.is_empty and p50_perimeter.intersects(geometry):
            data["penalised_cost"] = penalty_near * travel_time
        else:
            data["penalised_cost"] = FIRE_PENALTY_SAFE * travel_time

    return penalized_graph

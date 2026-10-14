from __future__ import annotations

from math import inf
from typing import Any

import networkx as nx
from shapely import wkt
from shapely.geometry import Point

FIRE_PENALTY_SAFE = 1.0
FIRE_PENALTY_NEAR = 5.0
FIRE_PENALTY_BLOCKED = inf


def apply_fire_penalties(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    current_perimeter_wkt: str,
    p50_perimeter_wkt: str,
    penalty_near: float = FIRE_PENALTY_NEAR,
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Return a graph copy whose edges are weighted by fire exposure."""
    current_perimeter = wkt.loads(current_perimeter_wkt)
    p50_perimeter = wkt.loads(p50_perimeter_wkt)
    penalized_graph = graph.copy()

    for origin, destination, _key, data in penalized_graph.edges(keys=True, data=True):
        origin_data = penalized_graph.nodes[origin]
        destination_data = penalized_graph.nodes[destination]
        midpoint = Point(
            (float(origin_data["x"]) + float(destination_data["x"])) / 2,
            (float(origin_data["y"]) + float(destination_data["y"])) / 2,
        )
        travel_time = float(data["travel_time"])

        if not current_perimeter.is_empty and current_perimeter.contains(midpoint):
            data["penalised_cost"] = FIRE_PENALTY_BLOCKED
        elif not p50_perimeter.is_empty and p50_perimeter.contains(midpoint):
            data["penalised_cost"] = penalty_near * travel_time
        else:
            data["penalised_cost"] = FIRE_PENALTY_SAFE * travel_time

    return penalized_graph
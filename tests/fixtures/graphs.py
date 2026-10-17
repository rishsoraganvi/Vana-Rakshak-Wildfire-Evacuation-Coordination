"""Deterministic synthetic road network used by CI instead of OSM data (D-05).

The graph is a 6x6 lattice around the pilot centre (about 11.72 N, 76.64 E) with a parallel
edge, a single-lane bottleneck, mixed ``lanes`` tag formats and one dead-end node. It uses no
random numbers, so every build is identical.
"""

from __future__ import annotations

import math

import networkx as nx

GRID_SIZE = 6
CORNER_SW = 1
CORNER_NE = GRID_SIZE * GRID_SIZE
DEAD_END = CORNER_NE + 1

_LON0 = 76.60
_LAT0 = 11.68
_STEP_DEG = 0.01
_EARTH_RADIUS_M = 6_371_000.0
_SPEED_KMH = {"primary": 60.0, "secondary": 40.0, "residential": 25.0, "track": 25.0}


def _node_id(row: int, col: int) -> int:
    return row * GRID_SIZE + col + 1


def _length_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Equirectangular distance in metres between two lon/lat points in degrees."""
    mean_lat = math.radians((lat1 + lat2) / 2.0)
    dx = math.radians(lon2 - lon1) * math.cos(mean_lat) * _EARTH_RADIUS_M
    dy = math.radians(lat2 - lat1) * _EARTH_RADIUS_M
    return math.hypot(dx, dy)


def _highway(row_a: int, col_a: int, row_b: int, col_b: int) -> str:
    if (row_a == row_b == 0) or (col_a == col_b == 0):
        return "primary"
    if (row_a == row_b == GRID_SIZE - 1) or (col_a == col_b == GRID_SIZE - 1):
        return "secondary"
    return "residential"


def node_lonlat(graph: nx.MultiDiGraph, node: int) -> tuple[float, float]:
    """Return ``(lon, lat)`` in degrees of ``node``."""
    data = graph.nodes[node]
    return float(data["x"]), float(data["y"])


def _add_pair(
    graph: nx.MultiDiGraph,
    u: int,
    v: int,
    highway: str,
    lanes: str | None,
    slowdown: float = 1.0,
    key: int = 0,
) -> None:
    lon1, lat1 = node_lonlat(graph, u)
    lon2, lat2 = node_lonlat(graph, v)
    length = _length_m(lon1, lat1, lon2, lat2)
    travel_time = length / (_SPEED_KMH[highway] / 3.6) * slowdown
    for a, b in ((u, v), (v, u)):
        attrs: dict[str, object] = {
            "length": length,
            "highway": highway,
            "travel_time": travel_time,
        }
        if lanes is not None:
            attrs["lanes"] = lanes
        graph.add_edge(a, b, key=key, **attrs)


def build_synthetic_graph() -> nx.MultiDiGraph:
    """Build the deterministic 6x6 lattice road graph (lengths in m, times in s)."""
    graph: nx.MultiDiGraph = nx.MultiDiGraph()
    graph.graph["crs"] = "EPSG:4326"
    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            graph.add_node(
                _node_id(row, col),
                x=_LON0 + _STEP_DEG * col,
                y=_LAT0 + _STEP_DEG * row,
            )
    graph.add_node(DEAD_END, x=76.66, y=11.74)

    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            for d_row, d_col in ((0, 1), (1, 0)):
                n_row, n_col = row + d_row, col + d_col
                if n_row >= GRID_SIZE or n_col >= GRID_SIZE:
                    continue
                u, v = _node_id(row, col), _node_id(n_row, n_col)
                highway = _highway(row, col, n_row, n_col)
                lanes = {"primary": "2", "secondary": "['1', '2']"}.get(highway)
                if {u, v} == {15, 16}:
                    highway, lanes = "track", "1"
                _add_pair(graph, u, v, highway, lanes)

    # Parallel edge (key 1) between nodes 2 and 3, 1.5 times slower than key 0.
    _add_pair(graph, 2, 3, "primary", "2", slowdown=1.5, key=1)
    # Dead end hanging off the NE corner.
    _add_pair(graph, CORNER_NE, DEAD_END, "residential", None)
    return graph

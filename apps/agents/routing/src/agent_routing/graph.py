"""Road graph loading (load-only at runtime) and the explicit OSM build (D-05, D-06, D-19).

The runtime never reaches the network: ``load_graph`` raises ``GraphNotBuiltError`` when the
cache file is absent. The pilot graph is built once by ``scripts/build_osm_graph.py``, which
calls ``build_graph_for_area``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox
from shapely.geometry import Point
from wildfire_core.geo.footprint import buffer_metric

logger = logging.getLogger(__name__)

# OSMnx would otherwise create ./cache in the current directory (RESEARCH Pitfall 1).
OSM_CACHE_FOLDER = "data/osm/cache"
BUILD_COMMAND = "uv run python scripts/build_osm_graph.py"
# Used only when the graph has no maxspeed tags to impute from (a sparse rural extract).
FALLBACK_SPEED_KPH = 30.0

_GRAPH_CACHE: dict[tuple[str, int], nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]] = {}


class GraphNotBuiltError(FileNotFoundError):
    """The cached road graph does not exist; it must be built explicitly by a human."""


def _has_travel_times(graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]) -> bool:
    return all("travel_time" in data for _u, _v, data in graph.edges(data=True))


def _with_travel_times(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    try:
        graph = ox.add_edge_speeds(graph)
    except ValueError:
        # OSMnx cannot impute speeds when no edge carries a maxspeed tag at all.
        graph = ox.add_edge_speeds(graph, fallback=FALLBACK_SPEED_KPH)
    return ox.add_edge_travel_times(graph)


def load_graph(
    cache_path: str | Path,
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Load the cached OSMnx GraphML graph. Never downloads (D-05, D-19).

    The parsed graph is cached in-process under (resolved path, mtime), so it reloads when the
    file changes. The returned object is shared: callers must copy before mutating
    (``apply_horizon_costs`` already copies).
    """
    path = Path(cache_path).resolve()
    if not path.is_file():
        raise GraphNotBuiltError(
            f"OSM road graph not found at {path}. Build it once with: {BUILD_COMMAND}"
        )
    key = (str(path), path.stat().st_mtime_ns)
    cached = _GRAPH_CACHE.get(key)
    if cached is not None:
        return cached

    graph = ox.load_graphml(path)
    if not _has_travel_times(graph):
        graph = _with_travel_times(graph)
    for stale in [item for item in _GRAPH_CACHE if item[0] == key[0]]:
        del _GRAPH_CACHE[stale]
    _GRAPH_CACHE[key] = graph
    logger.info("Loaded OSM road graph from cache: %s", path)
    return graph


def load_or_download_graph(
    cache_path: str | Path,
    bbox: tuple[float, float, float, float],
    network_type: str = "drive",
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Deprecated compatibility wrapper around ``load_graph``; it never downloads.

    ``bbox`` and ``network_type`` are ignored. The Phase 2 coordinator imports this name until
    plan 03-10 rewires it.
    """
    del bbox, network_type
    return load_graph(cache_path)


def build_graph_for_area(
    center_lat: float,
    center_lon: float,
    buffer_m: float,
    cache_path: str | Path,
    *,
    network_type: str = "drive",
    cache_folder: str | Path = OSM_CACHE_FOLDER,
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Download and save the drive graph for a metric buffer around a centre (D-06).

    This is the only network path. It is called by ``scripts/build_osm_graph.py`` and never at
    plan time. The file is written atomically, so a failure leaves no partial graph.
    """
    ox.settings.cache_folder = Path(cache_folder).as_posix()
    ox.settings.use_cache = True

    polygon = buffer_metric(Point(center_lon, center_lat), buffer_m)
    graph = ox.graph_from_polygon(polygon, network_type=network_type, simplify=True)
    graph = ox.truncate.largest_component(graph, strongly=True)
    graph = _with_travel_times(graph)

    target = Path(cache_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".tmp")
    try:
        ox.save_graphml(graph, filepath=partial)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    logger.info("Built and cached OSM road graph: %s", target)
    return graph

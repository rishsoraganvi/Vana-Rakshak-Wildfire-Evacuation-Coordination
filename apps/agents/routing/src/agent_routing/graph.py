from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import networkx as nx
import osmnx as ox

logger = logging.getLogger(__name__)


def load_or_download_graph(
    cache_path: str | Path,
    bbox: tuple[float, float, float, float],
    network_type: str = "drive",
) -> nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]:
    """Load a cached OSMnx GraphML graph or download and cache one.

    ``bbox`` uses north, south, east, west ordering; OSMnx 2 expects
    west, south, east, north.
    """
    cache_file = Path(cache_path)
    if cache_file.exists():
        graph = ox.load_graphml(cache_file)
        logger.info("Loaded OSM road graph from cache: %s", cache_file)
    else:
        north, south, east, west = bbox
        graph = ox.graph_from_bbox(
            (west, south, east, north),
            network_type=network_type,
        )
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        ox.save_graphml(graph, filepath=cache_file)
        logger.info("Downloaded and cached OSM road graph: %s", cache_file)

    graph = ox.add_edge_speeds(graph)
    graph = ox.add_edge_travel_times(graph)
    return graph
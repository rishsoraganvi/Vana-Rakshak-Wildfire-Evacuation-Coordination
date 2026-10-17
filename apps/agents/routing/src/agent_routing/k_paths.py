"""Lazy k-shortest loopless paths on a collapsed DiGraph (RESEARCH Pattern 2).

``nx.shortest_simple_paths`` rejects MultiDiGraph input, so parallel edges are collapsed to the
cheapest finite one first. Blocked (infinite) edges never enter the collapsed graph.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from math import isfinite
from typing import Any

import networkx as nx


@dataclass(frozen=True)
class KPaths:
    paths: tuple[tuple[int, ...], ...]
    edge_keys: tuple[tuple[int, ...], ...]
    costs: tuple[float, ...]
    truncated: bool


def collapse_to_digraph(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]], weight_attr: str
) -> nx.DiGraph[int]:
    """Collapse parallel edges to the cheapest finite, unblocked one (attrs ``w`` and ``key``)."""
    collapsed: nx.DiGraph[int] = nx.DiGraph()
    for node, data in graph.nodes(data=True):
        collapsed.add_node(node, x=data.get("x"), y=data.get("y"))
    for u, v, key, data in sorted(graph.edges(keys=True, data=True), key=lambda e: e[:3]):
        if data.get("blocked", False):
            continue
        cost = float(data[weight_attr])
        if not isfinite(cost):
            continue
        if collapsed.has_edge(u, v) and collapsed[u][v]["w"] <= cost:
            continue
        collapsed.add_edge(u, v, w=cost, key=key)
    return collapsed


def k_shortest_paths(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    source: int,
    target: int,
    *,
    weight_attr: str,
    k: int,
    max_leg_s: float,
    digraph: nx.DiGraph[int] | None = None,
) -> KPaths:
    """Up to ``k`` distinct loopless paths, stopping early once ``max_leg_s`` is exceeded.

    Truncation only applies once at least one path exists, so a feasible leg always yields
    its best path.
    """
    collapsed = digraph if digraph is not None else collapse_to_digraph(graph, weight_attr)
    started = time.monotonic()
    paths: list[tuple[int, ...]] = []
    truncated = False
    try:
        generator = nx.shortest_simple_paths(collapsed, source, target, weight="w")
        for path in itertools.islice(generator, k):
            paths.append(tuple(int(node) for node in path))
            if len(paths) < k and time.monotonic() - started >= max_leg_s:
                truncated = True
                break
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        if not paths:
            return KPaths((), (), (), False)
    edge_keys = tuple(
        tuple(int(collapsed[u][v]["key"]) for u, v in zip(path, path[1:], strict=False))
        for path in paths
    )
    costs = tuple(
        float(sum(collapsed[u][v]["w"] for u, v in zip(path, path[1:], strict=False)))
        for path in paths
    )
    return KPaths(tuple(paths), edge_keys, costs, truncated)

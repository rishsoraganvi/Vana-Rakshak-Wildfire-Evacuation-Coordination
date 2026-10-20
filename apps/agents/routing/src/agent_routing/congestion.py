"""BPR congestion from assigned evacuation flow, with MSA damping (D-08).

``t = t0 * (1 + alpha * (v / c) ** beta)``. Capacity comes from the OSM ``highway`` and
``lanes`` tags, which GraphML loads as strings (possibly list-strings such as ``"['1', '2']"``).
All coefficients are parameters supplied from config (Rules 10).
"""

from __future__ import annotations

import ast
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import networkx as nx

from .costs import refresh_horizon_costs

EdgeKey = tuple[int, int, int]

_TRUTHY = frozenset({"true", "yes", "1"})


def parse_tag(value: object) -> list[str]:
    """Normalise an OSM tag value to a list of strings; never raises.

    Only strings starting with ``[`` go through ``ast.literal_eval`` (never ``eval``). A
    malformed list-string is returned as a single value.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    text = str(value)
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
            return [text]
        if isinstance(parsed, (list, tuple)):
            return [str(item) for item in parsed]
        return [text]
    return [text]


def _lanes(value: object) -> int:
    """Lane count from a tag; the lowest listed value (conservative), default one lane."""
    counts: list[int] = []
    for item in parse_tag(value):
        try:
            counts.append(int(float(item)))
        except ValueError:
            continue
    positive = [count for count in counts if count >= 1]
    return min(positive) if positive else 1


def _is_oneway(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return any(item.strip().lower() in _TRUTHY for item in parse_tag(value))


def _class_capacity(highway: str, lane_capacity: Mapping[str, float], link_factor: float) -> float:
    is_link = highway.endswith("_link")
    base = highway.removesuffix("_link")
    capacity = float(lane_capacity.get(base, lane_capacity["default"]))
    return capacity * link_factor if is_link else capacity


def edge_capacity_vph(
    data: Mapping[str, Any], *, lane_capacity: Mapping[str, float], link_factor: float
) -> float:
    """Edge capacity in vehicles per hour for one direction of travel.

    Per-lane capacity of the lowest-capacity highway class listed, times lanes in this
    direction (all lanes when one-way, otherwise half rounded up, minimum one).
    """
    classes = parse_tag(data.get("highway")) or ["default"]
    per_lane = min(_class_capacity(item, lane_capacity, link_factor) for item in classes)
    lanes = _lanes(data.get("lanes"))
    lanes_in_direction = lanes if _is_oneway(data.get("oneway")) else max(math.ceil(lanes / 2), 1)
    return per_lane * lanes_in_direction


def bpr_time(
    t0_s: float, flow_vph: float, capacity_vph: float, *, alpha: float, beta: float
) -> float:
    """Bureau of Public Roads link travel time in seconds."""
    if capacity_vph <= 0:
        raise ValueError(f"capacity_vph must be positive, got {capacity_vph!r}")
    return t0_s * (1.0 + alpha * math.pow(flow_vph / capacity_vph, beta))


def edge_flows_vph(
    legs: Iterable[tuple[Sequence[EdgeKey], int]],
    *,
    persons_per_vehicle: float,
    evac_window_h: float,
) -> dict[EdgeKey, float]:
    """Vehicles per hour on each edge: persons / persons-per-vehicle / evacuation window."""
    flows: dict[EdgeKey, float] = {}
    for edges, persons in legs:
        vehicles_per_hour = persons / persons_per_vehicle / evac_window_h
        for edge in edges:
            flows[edge] = flows.get(edge, 0.0) + vehicles_per_hour
    return flows


def msa_blend(
    previous: Mapping[EdgeKey, float], new: Mapping[EdgeKey, float], iteration: int
) -> dict[EdgeKey, float]:
    """Method of successive averages: ``prev + (new - prev) / iteration`` over the key union."""
    if iteration < 1:
        raise ValueError(f"iteration must be >= 1, got {iteration!r}")
    if iteration == 1:
        return dict(new)
    keys = sorted(set(previous) | set(new))
    return {
        key: previous.get(key, 0.0) + (new.get(key, 0.0) - previous.get(key, 0.0)) / iteration
        for key in keys
    }


def apply_congestion(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    flows: Mapping[EdgeKey, float],
    *,
    alpha: float,
    beta: float,
    lane_capacity: Mapping[str, float],
    link_factor: float,
) -> float:
    """Set ``congested_time`` and ``vc_ratio`` on every edge, refresh ``cost_h*``.

    Mutates the per-run graph copy. Returns the maximum v/c ratio (0.0 for no edges).
    """
    max_vc = 0.0
    for u, v, key, data in graph.edges(keys=True, data=True):
        capacity = edge_capacity_vph(data, lane_capacity=lane_capacity, link_factor=link_factor)
        if capacity <= 0:
            raise ValueError(f"edge ({u}, {v}, {key}) has non-positive capacity {capacity!r} vph")
        flow = float(flows.get((u, v, key), 0.0))
        free_flow = float(data["travel_time"])
        data["vc_ratio"] = flow / capacity
        data["congested_time"] = (
            free_flow
            if flow == 0.0
            else bpr_time(free_flow, flow, capacity, alpha=alpha, beta=beta)
        )
        max_vc = max(max_vc, data["vc_ratio"])
    refresh_horizon_costs(graph)
    return max_vc

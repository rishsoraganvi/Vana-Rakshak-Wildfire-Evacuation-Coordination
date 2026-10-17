"""Validators V1-V3: route existence, blocked edges and forecast exposure (TechSpec section 8).

V2 and V3 test the edge geometry directly instead of the routing zone attributes, so they stay
independent of the code that produced the routes. V3 shares the nearest-horizon rule with
routing (D-21).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from agent_routing.costs import edge_geometry
from wildfire_core.geo.horizons import nearest_horizon_h
from wildfire_core.schemas.plan import (
    EdgeStatusEntry,
    PlanRoute,
    ValidationResult,
    ViolationRecord,
)

from coordinator.validators._common import build_result

if TYPE_CHECKING:
    from coordinator.validators.runner import ValidationContext

_BLOCKING_STATUSES = frozenset({"blocked", "unsafe"})


def _hops(route: PlanRoute) -> list[tuple[int, int, int]]:
    path = route.osm_node_path
    return [
        (u, v, key)
        for (u, v), key in zip(zip(path, path[1:], strict=False), route.osm_edge_keys, strict=False)
    ]


def check_v1_paths(routes: Sequence[PlanRoute], ctx: ValidationContext) -> ValidationResult:
    """Every hop exists in the graph and the path joins the group origin to the shelter node."""
    violations: list[ViolationRecord] = []
    for route in routes:
        for u, v, key in _hops(route):
            if not ctx.graph.has_edge(u, v, key):
                violations.append(
                    ViolationRecord(
                        code="missing_edge",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"uses edge ({u}, {v}, {key}) that is not in the road graph"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                        edge=EdgeStatusEntry(u=u, v=v, key=key, status="open"),
                    )
                )
        group = ctx.groups.get(route.group_id)
        expected_origins = {route.origin_node}
        if group is not None and group.origin_node is not None:
            expected_origins.add(group.origin_node)
        first = route.osm_node_path[0]
        if expected_origins != {first}:
            violations.append(
                ViolationRecord(
                    code="origin_mismatch",
                    detail=(
                        f"route for group {route.group_id} starts at node {first}, "
                        f"expected {sorted(expected_origins)}"
                    ),
                    group_id=route.group_id,
                    shelter_id=route.shelter_id,
                )
            )
        candidate = ctx.candidates.get(route.shelter_id)
        expected_destinations = {route.destination_node}
        if candidate is not None and candidate.node is not None:
            expected_destinations.add(candidate.node)
        last = route.osm_node_path[-1]
        if expected_destinations != {last}:
            violations.append(
                ViolationRecord(
                    code="destination_mismatch",
                    detail=(
                        f"route for group {route.group_id} ends at node {last}, "
                        f"expected shelter {route.shelter_id} at {sorted(expected_destinations)}"
                    ),
                    group_id=route.group_id,
                    shelter_id=route.shelter_id,
                )
            )
    return build_result("V1", violations)


def check_v2_blocked(routes: Sequence[PlanRoute], ctx: ValidationContext) -> ValidationResult:
    """No hop uses a blocked/unsafe edge or crosses the current fire perimeter."""
    violations: list[ViolationRecord] = []
    current = ctx.footprint.current
    for route in routes:
        for u, v, key in _hops(route):
            if not ctx.graph.has_edge(u, v, key):
                continue  # V1 reports it
            status = ctx.edge_status.get((u, v, key), "open")
            if status in _BLOCKING_STATUSES:
                violations.append(
                    ViolationRecord(
                        code="blocked_edge",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"uses {status} edge ({u}, {v}, {key})"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                        edge=EdgeStatusEntry(
                            u=u,
                            v=v,
                            key=key,
                            status="blocked" if status == "blocked" else "unsafe",
                        ),
                    )
                )
                continue
            geometry = edge_geometry(ctx.graph, u, v, ctx.graph[u][v][key])
            if not current.is_empty and current.intersects(geometry):
                violations.append(
                    ViolationRecord(
                        code="enters_current_perimeter",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"enters the current fire perimeter on edge ({u}, {v}, {key})"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                        edge=EdgeStatusEntry(u=u, v=v, key=key, status="blocked"),
                    )
                )
    return build_result("V2", violations)


def check_v3_forecast(routes: Sequence[PlanRoute], ctx: ValidationContext) -> ValidationResult:
    """P50 hit at the per-edge nearest horizon fails; a P90 hit raises a flag (D-21)."""
    fails: list[ViolationRecord] = []
    flags: list[ViolationRecord] = []
    for route in routes:
        elapsed_s = 0.0
        for u, v, key in _hops(route):
            if not ctx.graph.has_edge(u, v, key):
                continue  # V1 reports it
            data = ctx.graph[u][v][key]
            elapsed_s += float(data.get(ctx.time_attr, data["travel_time"]))
            horizon = int(nearest_horizon_h(elapsed_s / 60.0))
            geometry = edge_geometry(ctx.graph, u, v, data)
            p50 = ctx.footprint.p50[horizon]
            p90 = ctx.footprint.p90[horizon]
            if not p50.is_empty and p50.intersects(geometry):
                fails.append(
                    ViolationRecord(
                        code="p50_before_arrival",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"reaches edge ({u}, {v}, {key}) at {elapsed_s / 60.0:.0f} min "
                            f"inside the {horizon}h P50 forecast"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                        edge=EdgeStatusEntry(u=u, v=v, key=key, status="open"),
                    )
                )
            elif not p90.is_empty and p90.intersects(geometry):
                flags.append(
                    ViolationRecord(
                        code="p90_before_arrival",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"reaches edge ({u}, {v}, {key}) at {elapsed_s / 60.0:.0f} min "
                            f"inside the {horizon}h P90 forecast"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                        edge=EdgeStatusEntry(u=u, v=v, key=key, status="open"),
                    )
                )
    if fails:
        return build_result("V3", [*fails, *flags])
    return build_result("V3", flags, flag_only=True)

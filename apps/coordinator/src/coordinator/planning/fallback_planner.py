"""Greedy fallback planner, a different algorithm from the min-cost-flow loop (RESEARCH Pattern 5).

Groups are served in (priority, -persons, group_id) order. Each takes the cheapest strictly safe
(shelter, path) that still has capacity and splits greedily across shelters when one is not enough.
Because it does not share the flow's global optimisation or the resolver's constraints, it can
succeed where the flow loop failed. It runs a single congestion evaluation so V3 sees realistic
travel times. Its result is validated by the same ``run_structural_validators`` as every producer.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from agent_routing.k_paths import KPaths, collapse_to_digraph, k_shortest_paths
from agent_routing.router import LegCost, evaluate_path
from agent_shelter.matching import REASON_INSUFFICIENT_CAPACITY, REASON_NO_REACHABLE

from coordinator.planning.params import PlanningParams
from coordinator.planning.plan_core import (
    REASON_NO_SAFE_ROUTE,
    AssignmentResult,
    EdgeKey,
    Pair,
    PlanInputs,
    RoutingContext,
    build_assignments,
    build_route,
    congest,
    edge_keys_of,
    leg_costs,
    usable_candidates,
)


def _safe_option(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    found: KPaths,
) -> tuple[float, int] | None:
    """(cost, index) of the cheapest path that is strictly safe, or None."""
    for index, path in enumerate(found.paths):
        if evaluate_path(graph, path, found.edge_keys[index]).safe:
            return found.costs[index], index
    return None


def greedy_fallback(
    inputs: PlanInputs, ctx: RoutingContext, params: PlanningParams
) -> AssignmentResult:
    """Assign groups greedily to the cheapest strictly safe shelter and path (D-11)."""
    graph = ctx.graph.copy()
    usable = usable_candidates(graph, inputs.candidates)
    by_shelter = {c.shelter_id: c for c in usable}
    ordered = sorted(inputs.groups, key=lambda g: (g.priority, -g.persons, g.group_id))
    matrix: dict[Pair, LegCost | None] = leg_costs(graph, ordered, usable)
    remaining = {c.shelter_id: c.available for c in usable}
    digraphs: dict[int, nx.DiGraph[int]] = {}
    searched: dict[Pair, KPaths] = {}
    chosen: dict[Pair, tuple[int, tuple[int, ...], tuple[int, ...], int, int]] = {}
    unassigned: dict[str, int] = {}
    reasons: dict[str, str] = {}
    warnings: set[str] = set()

    def paths_for(group_id: str, origin: int, shelter_id: str, leg: LegCost) -> KPaths:
        pair = (group_id, shelter_id)
        if pair not in searched:
            if leg.horizon_h not in digraphs:
                digraphs[leg.horizon_h] = collapse_to_digraph(graph, f"cost_h{leg.horizon_h}")
            searched[pair] = k_shortest_paths(
                graph,
                origin,
                int(by_shelter[shelter_id].node or 0),
                weight_attr=f"cost_h{leg.horizon_h}",
                k=params.k_paths,
                max_leg_s=params.k_paths_max_leg_s,
                digraph=digraphs[leg.horizon_h],
            )
            if searched[pair].truncated:
                warnings.add(
                    f"Path search for {group_id} to {shelter_id} stopped at its time budget; "
                    "fewer alternative routes were considered"
                )
        return searched[pair]

    for group in ordered:
        origin = group.origin_node
        left = group.persons
        reachable = False
        while left > 0 and origin is not None:
            options: list[tuple[float, str, int, int]] = []
            capacity_and_route = False
            for candidate in usable:
                leg = matrix.get((group.group_id, candidate.shelter_id))
                if leg is None:
                    continue
                reachable = True
                if remaining[candidate.shelter_id] <= 0:
                    continue
                capacity_and_route = True
                found = paths_for(group.group_id, origin, candidate.shelter_id, leg)
                safe = _safe_option(graph, found)
                if safe is not None:
                    options.append((safe[0], candidate.shelter_id, safe[1], leg.horizon_h))
            if not options:
                reasons[group.group_id] = (
                    REASON_NO_SAFE_ROUTE if capacity_and_route else REASON_INSUFFICIENT_CAPACITY
                )
                break
            _, shelter_id, index, horizon = min(options)
            pair = (group.group_id, shelter_id)
            found = searched[pair]
            take = min(left, remaining[shelter_id])
            chosen[pair] = (take, found.paths[index], found.edge_keys[index], index + 1, horizon)
            remaining[shelter_id] -= take
            left -= take
        if left > 0:
            unassigned[group.group_id] = left
            if origin is None or not reachable:
                reasons[group.group_id] = REASON_NO_REACHABLE

    legs = {pair: item[0] for pair, item in sorted(chosen.items())}
    flow_legs: list[tuple[list[EdgeKey], int]] = [
        (edge_keys_of(item[1], item[2]), item[0]) for _, item in sorted(chosen.items())
    ]
    _, max_vc = congest(graph, flow_legs, params)
    routes = tuple(
        build_route(
            ctx,
            graph,
            pair=pair,
            persons=item[0],
            path=item[1],
            keys=item[2],
            rank=item[3],
            horizon=item[4],
        )
        for pair, item in sorted(chosen.items())
    )
    return AssignmentResult(
        legs=legs,
        routes=routes,
        assignments=build_assignments(legs, by_shelter),
        unassigned=unassigned,
        unplaceable_reasons=reasons,
        passes_used=1,
        max_vc=max_vc,
        warnings=tuple(sorted(warnings)),
        graph=graph,
        paths_available={pair: len(searched[pair].paths) for pair in sorted(chosen)},
    )

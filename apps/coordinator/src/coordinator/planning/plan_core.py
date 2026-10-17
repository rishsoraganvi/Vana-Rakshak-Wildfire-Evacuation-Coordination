"""Deterministic planning core: capacity-aware assignment, safe routing, validation (PLAN-03/04/07).

This module is a pure library (no LangGraph, no database). ``build_assignment`` matches groups to
shelters by min-cost flow over ETA-aware costs, picks each leg's path as the first of up to ``k``
paths that is safe under per-edge evaluation, and re-routes for a bounded number of BPR congestion
passes with MSA damping (D-07, D-08). ``plan_draft`` validates the result with V1-V7, then runs the
bounded resolver and the greedy fallback planner when validation fails (D-09 to D-12).

Determinism: every iteration over groups, shelters, legs and edges is sorted and ties go to the
smallest id. The graph a caller passes in is never mutated; congestion and attempt-local edge
exclusions work on a per-run copy.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from math import inf
from typing import TYPE_CHECKING, Any

import networkx as nx
from agent_routing.congestion import apply_congestion, edge_flows_vph, msa_blend
from agent_routing.costs import refresh_horizon_costs
from agent_routing.k_paths import collapse_to_digraph, k_shortest_paths
from agent_routing.router import LegCost, evaluate_path, route_cost_matrix
from agent_shelter.matching import REASON_NO_REACHABLE, match_groups_to_shelters
from wildfire_core.geo.footprint import LoadedFootprint
from wildfire_core.geo.horizons import HORIZONS_H
from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot
from wildfire_core.schemas.plan import (
    ClusterRisk,
    EdgeStatusEntry,
    EvacueeGroup,
    ExcludedShelter,
    ForecastFootprint,
    PlanAlert,
    PlanDraft,
    PlanRoute,
    ResolverStep,
    ShelterAssignment,
    ShelterCandidate,
    ValidationResult,
)

from coordinator.planning.params import PlanningParams
from coordinator.validators.runner import (
    ValidationContext,
    has_blocking_failure,
    run_structural_validators,
)

if TYPE_CHECKING:
    from coordinator.planning.resolver import StrategyChooser

EdgeKey = tuple[int, int, int]
Pair = tuple[str, str]

NO_GROUPS_WARNING = (
    "No settlement buffer intersects the P50 forecast; no evacuation assignments proposed"
)
REASON_NO_SAFE_ROUTE = "no_safe_route"


@dataclass(frozen=True)
class RoutingContext:
    """Per-run routing inputs. ``graph`` already carries the horizon costs for this footprint."""

    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]
    footprint: ForecastFootprint
    loaded: LoadedFootprint
    edge_status: Mapping[EdgeKey, str]
    graph_source: str = "unknown"
    graph_mtime: datetime | None = None


@dataclass(frozen=True)
class PlanInputs:
    """Everything the planning core needs besides the road graph and the coefficients."""

    incident_id: str
    run_id: str
    groups: tuple[EvacueeGroup, ...]
    candidates: tuple[ShelterCandidate, ...]
    excluded: tuple[ExcludedShelter, ...] = ()
    alerts: tuple[PlanAlert, ...] = ()
    warnings: tuple[str, ...] = ()
    preflight_failures: tuple[str, ...] = ()
    clusters: tuple[HotspotCluster, ...] = ()
    fire_results: tuple[FireSpreadResult, ...] = ()
    weather_by_cluster: Mapping[str, WeatherSnapshot] = field(default_factory=dict)
    cluster_risk: tuple[ClusterRisk, ...] = ()
    known_settlement_ids: frozenset[str] | None = None
    known_shelter_ids: frozenset[str] | None = None


@dataclass(frozen=True)
class Constraints:
    """Attempt-local restrictions the resolver adds between loops (D-09)."""

    banned: frozenset[Pair] = frozenset()
    per_pair_cap: Mapping[str, int] = field(default_factory=dict)
    rank_floor: Mapping[Pair, int] = field(default_factory=dict)
    excluded_edges: frozenset[EdgeKey] = frozenset()


@dataclass(frozen=True)
class AssignmentResult:
    """One candidate plan body. ``graph`` is the final congested per-run copy."""

    legs: dict[Pair, int]
    routes: tuple[PlanRoute, ...]
    assignments: tuple[ShelterAssignment, ...]
    unassigned: dict[str, int]
    unplaceable_reasons: dict[str, str]
    passes_used: int
    max_vc: float
    warnings: tuple[str, ...]
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]
    paths_available: dict[Pair, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanOutcome:
    draft: PlanDraft
    llm_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class _Selection:
    pair: Pair
    persons: int
    path: tuple[int, ...]
    keys: tuple[int, ...]
    rank: int
    horizon: int
    n_paths: int


# --------------------------------------------------------------------------------------------
# Shared helpers (also used by the resolver and the fallback planner)
# --------------------------------------------------------------------------------------------


def apply_exclusions(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]], excluded: frozenset[EdgeKey]
) -> None:
    """Mark attempt-local excluded edges as blocked on a per-run graph copy."""
    for u, v, key in sorted(excluded):
        if not graph.has_edge(u, v, key):
            continue
        data = graph[u][v][key]
        data["blocked"] = True
        for horizon in HORIZONS_H:
            data[f"zone_h{horizon}"] = "blocked"
            data[f"fire_mult_h{horizon}"] = inf
    if excluded:
        refresh_horizon_costs(graph)


def usable_candidates(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    candidates: Sequence[ShelterCandidate],
) -> list[ShelterCandidate]:
    """Candidates snapped onto a graph node, sorted by id."""
    return sorted(
        (c for c in candidates if c.node is not None and c.node in graph),
        key=lambda c: c.shelter_id,
    )


def leg_costs(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    groups: Sequence[EvacueeGroup],
    candidates: Sequence[ShelterCandidate],
) -> dict[Pair, LegCost | None]:
    """ETA-aware cost matrix. Co-located origin and shelter nodes are unroutable.

    A ``PlanRoute`` needs at least two nodes, so a settlement snapped onto its shelter's node
    cannot be represented and is treated as unreachable.
    """
    origins = {
        g.group_id: g.origin_node
        for g in groups
        if g.origin_node is not None and g.origin_node in graph
    }
    targets = {c.shelter_id: c.node for c in candidates if c.node is not None and c.node in graph}
    matrix = route_cost_matrix(graph, origins, targets)
    return {
        pair: (None if leg is None or origins[pair[0]] == targets[pair[1]] else leg)
        for pair, leg in matrix.items()
    }


def edge_keys_of(path: Sequence[int], keys: Sequence[int]) -> list[EdgeKey]:
    return [(u, v, k) for (u, v), k in zip(zip(path, path[1:], strict=False), keys, strict=True)]


def build_route(
    ctx: RoutingContext,
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    *,
    pair: Pair,
    persons: int,
    path: Sequence[int],
    keys: Sequence[int],
    rank: int,
    horizon: int,
) -> PlanRoute:
    """Assemble a ``PlanRoute`` evaluated on ``graph`` (the final congested copy)."""
    evaluation = evaluate_path(graph, path, keys)
    free_flow_s = sum(float(graph[u][v][k]["travel_time"]) for u, v, k in edge_keys_of(path, keys))
    snapshot = tuple(
        EdgeStatusEntry(u=u, v=v, key=k, status=ctx.edge_status[(u, v, k)])  # type: ignore[arg-type]
        for u, v, k in edge_keys_of(path, keys)
        if ctx.edge_status.get((u, v, k), "open") != "open"
    )
    exposed = bool(evaluation.p50_idx or evaluation.p90_idx or evaluation.blocked_idx)
    return PlanRoute(
        group_id=pair[0],
        shelter_id=pair[1],
        persons=persons,
        origin_node=int(path[0]),
        destination_node=int(path[-1]),
        osm_node_path=tuple(int(node) for node in path),
        osm_edge_keys=tuple(int(k) for k in keys),
        path_lonlat=tuple(
            (float(graph.nodes[node]["x"]), float(graph.nodes[node]["y"])) for node in path
        ),
        total_distance_m=evaluation.distance_m,
        free_flow_time_s=free_flow_s,
        congested_time_s=evaluation.total_time_s,
        eta_min=float(math.ceil(evaluation.total_time_s / 60.0)),
        horizon_h=horizon,  # type: ignore[arg-type]
        path_rank=rank,
        risk_score=evaluation.risk_score,
        safety_classification="caution" if exposed else "safe",
        p90_flag_edge_indices=evaluation.p90_idx,
        edge_status_snapshot=snapshot,
    )


def build_assignments(
    legs: Mapping[Pair, int], candidates: Mapping[str, ShelterCandidate]
) -> tuple[ShelterAssignment, ...]:
    result: list[ShelterAssignment] = []
    for group_id, shelter_id in sorted(legs):
        candidate = candidates[shelter_id]
        result.append(
            ShelterAssignment(
                shelter_id=shelter_id,
                shelter_name=candidate.name,
                group_id=group_id,
                persons=legs[(group_id, shelter_id)],
                usable_capacity=candidate.usable_capacity,
                available_before=candidate.available,
            )
        )
    return tuple(result)


def congest(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    legs: Sequence[tuple[Sequence[EdgeKey], int]],
    params: PlanningParams,
    *,
    previous: Mapping[EdgeKey, float] | None = None,
    iteration: int = 1,
) -> tuple[dict[EdgeKey, float], float]:
    """Compute flows, blend with the previous pass (MSA), apply BPR; return flows, max v/c."""
    new = edge_flows_vph(
        legs,
        persons_per_vehicle=params.persons_per_vehicle,
        evac_window_h=params.evac_window_h,
    )
    flows = msa_blend(previous or {}, new, iteration)
    max_vc = apply_congestion(
        graph,
        flows,
        alpha=params.bpr_alpha,
        beta=params.bpr_beta,
        lane_capacity=params.lane_capacity_vph,
        link_factor=params.link_capacity_factor,
    )
    return flows, max_vc


# --------------------------------------------------------------------------------------------
# Flow-based assignment
# --------------------------------------------------------------------------------------------


def _select_paths(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    legs: Mapping[Pair, int],
    matrix: Mapping[Pair, LegCost | None],
    origins: Mapping[str, int],
    targets: Mapping[str, int],
    params: PlanningParams,
    constraints: Constraints,
    warnings: set[str],
) -> tuple[list[_Selection], dict[str, int]]:
    """First safe path of up to k for every leg, starting at the leg's rank floor (D-07)."""
    digraphs: dict[int, nx.DiGraph[int]] = {}
    selection: list[_Selection] = []
    unroutable: dict[str, int] = {}
    for pair in sorted(legs):
        leg = matrix[pair]
        if leg is None:
            unroutable[pair[0]] = unroutable.get(pair[0], 0) + legs[pair]
            continue
        if leg.horizon_h not in digraphs:
            digraphs[leg.horizon_h] = collapse_to_digraph(graph, f"cost_h{leg.horizon_h}")
        found = k_shortest_paths(
            graph,
            origins[pair[0]],
            targets[pair[1]],
            weight_attr=f"cost_h{leg.horizon_h}",
            k=params.k_paths,
            max_leg_s=params.k_paths_max_leg_s,
            digraph=digraphs[leg.horizon_h],
        )
        if found.truncated:
            warnings.add(
                f"Path search for {pair[0]} to {pair[1]} stopped at its time budget; "
                "fewer alternative routes were considered"
            )
        if not found.paths:
            unroutable[pair[0]] = unroutable.get(pair[0], 0) + legs[pair]
            continue
        start = min(max(constraints.rank_floor.get(pair, 1), 1) - 1, len(found.paths) - 1)
        chosen = start
        for index in range(start, len(found.paths)):
            if evaluate_path(graph, found.paths[index], found.edge_keys[index]).safe:
                chosen = index
                break
        selection.append(
            _Selection(
                pair=pair,
                persons=legs[pair],
                path=found.paths[chosen],
                keys=found.edge_keys[chosen],
                rank=chosen + 1,
                horizon=leg.horizon_h,
                n_paths=len(found.paths),
            )
        )
    return selection, unroutable


def build_assignment(
    ctx: RoutingContext,
    groups: Sequence[EvacueeGroup],
    candidates: Sequence[ShelterCandidate],
    params: PlanningParams,
    constraints: Constraints,
) -> AssignmentResult:
    """Match, route and congest for up to ``params.congestion_passes`` passes (D-07, D-08)."""
    graph = ctx.graph.copy()
    apply_exclusions(graph, constraints.excluded_edges)
    ordered_groups = sorted(groups, key=lambda g: g.group_id)
    if not ordered_groups:
        return AssignmentResult({}, (), (), {}, {}, 0, 0.0, (), graph)

    usable = usable_candidates(graph, candidates)
    by_shelter = {c.shelter_id: c for c in usable}
    persons = {g.group_id: g.persons for g in ordered_groups}
    available = {c.shelter_id: c.available for c in usable}
    origins = {
        g.group_id: int(g.origin_node)
        for g in ordered_groups
        if g.origin_node is not None and g.origin_node in graph
    }
    targets = {c.shelter_id: int(c.node) for c in usable if c.node is not None}

    warnings: set[str] = set()
    selection: list[_Selection] = []
    unassigned: dict[str, int] = {}
    reasons: dict[str, str] = {}
    previous_flows: dict[EdgeKey, float] = {}
    previous_signature: tuple[tuple[str, str, int, tuple[int, ...]], ...] | None = None
    passes_used = 0
    max_vc = 0.0

    for index in range(params.congestion_passes):
        matrix = leg_costs(graph, ordered_groups, usable)
        match = match_groups_to_shelters(
            persons,
            available,
            {pair: None if leg is None else leg.cost_s for pair, leg in matrix.items()},
            banned=constraints.banned,
            per_pair_cap=dict(constraints.per_pair_cap),
        )
        selection, unroutable = _select_paths(
            graph, match.legs, matrix, origins, targets, params, constraints, warnings
        )
        unassigned = dict(match.unassigned)
        reasons = dict(match.unplaceable_reasons)
        for group_id, residual in sorted(unroutable.items()):
            unassigned[group_id] = unassigned.get(group_id, 0) + residual
            reasons.setdefault(group_id, REASON_NO_REACHABLE)

        passes_used = index + 1
        flows, max_vc = congest(
            graph,
            [(edge_keys_of(item.path, item.keys), item.persons) for item in selection],
            params,
            previous=previous_flows,
            iteration=index + 1,
        )
        previous_flows = flows
        signature = tuple(sorted((*item.pair, item.persons, item.path) for item in selection))
        if signature == previous_signature:
            break
        previous_signature = signature

    legs = {item.pair: item.persons for item in selection}
    routes = tuple(
        build_route(
            ctx,
            graph,
            pair=item.pair,
            persons=item.persons,
            path=item.path,
            keys=item.keys,
            rank=item.rank,
            horizon=item.horizon,
        )
        for item in sorted(selection, key=lambda s: s.pair)
    )
    return AssignmentResult(
        legs=legs,
        routes=routes,
        assignments=build_assignments(legs, by_shelter),
        unassigned=unassigned,
        unplaceable_reasons=reasons,
        passes_used=passes_used,
        max_vc=max_vc,
        warnings=tuple(sorted(warnings)),
        graph=graph,
        paths_available={item.pair: item.n_paths for item in selection},
    )


# --------------------------------------------------------------------------------------------
# Validation and draft assembly
# --------------------------------------------------------------------------------------------


def validate_assignment(
    inputs: PlanInputs, ctx: RoutingContext, result: AssignmentResult
) -> tuple[ValidationResult, ...]:
    """Run V1-V7 on a candidate. Every producer (flow, resolver, fallback) goes through here."""
    cluster_ids = frozenset(
        {r.cluster_id for r in inputs.fire_results}
        | {c.cluster_id for c in inputs.clusters}
        | set(ctx.footprint.cluster_ids)
    )
    known_settlements = (
        inputs.known_settlement_ids
        if inputs.known_settlement_ids is not None
        else frozenset(g.settlement_id for g in inputs.groups)
    )
    known_shelters = (
        inputs.known_shelter_ids
        if inputs.known_shelter_ids is not None
        else frozenset(c.shelter_id for c in inputs.candidates)
    )
    vctx = ValidationContext(
        graph=result.graph,
        footprint=ctx.loaded,
        edge_status=ctx.edge_status,
        groups={g.group_id: g for g in inputs.groups},
        candidates={c.shelter_id: c for c in inputs.candidates},
        known_settlement_ids=known_settlements,
        known_shelter_ids=known_shelters,
        fire_cluster_ids=cluster_ids,
    )
    return run_structural_validators(
        groups=sorted(inputs.groups, key=lambda g: g.group_id),
        routes=result.routes,
        assignments=result.assignments,
        dispatches=(),
        unassigned_reasons=result.unplaceable_reasons,
        ctx=vctx,
        clusters_referenced=sorted({r.cluster_id for r in inputs.cluster_risk}),
    )


def violation_lines(
    validation: Sequence[ValidationResult], groups: Sequence[EvacueeGroup]
) -> list[str]:
    """One readable line per failing violation, in the same format finalize_plan uses."""
    names = {g.group_id: g.settlement_name for g in groups}
    lines: list[str] = []
    for result in validation:
        if result.status != "fail":
            continue
        if not result.violations:
            lines.extend(f"{result.validator_id} {reason}" for reason in result.reasons)
            continue
        for violation in result.violations:
            if violation.group_id:
                name = names.get(violation.group_id, violation.group_id)
                subject = f"{name} ({violation.group_id}) "
            elif violation.shelter_id:
                subject = f"shelter {violation.shelter_id} "
            else:
                subject = ""
            lines.append(f"{result.validator_id} {violation.code}: {subject}{violation.detail}")
    return lines


def _draft_warnings(
    inputs: PlanInputs, result: AssignmentResult, *, no_groups: bool = False
) -> tuple[str, ...]:
    extra = list(result.warnings)
    if result.max_vc > 1.0:
        extra.append(
            f"Congestion: peak flow is {result.max_vc:.2f} times road capacity on at least one "
            "segment, so travel times are likely longer than free flow"
        )
    if no_groups:
        extra.append(NO_GROUPS_WARNING)
    return tuple(dict.fromkeys([*inputs.warnings, *extra]))


def _valid_draft(
    inputs: PlanInputs,
    ctx: RoutingContext,
    result: AssignmentResult,
    validation: tuple[ValidationResult, ...],
    *,
    used_fallback: bool,
    steps: tuple[ResolverStep, ...],
    no_groups: bool = False,
) -> PlanDraft:
    return PlanDraft(
        incident_id=inputs.incident_id,
        run_id=inputs.run_id,
        outcome="valid",
        clusters=inputs.clusters,
        fire_results=inputs.fire_results,
        weather_by_cluster=dict(inputs.weather_by_cluster),
        footprint=ctx.footprint,
        risk=inputs.cluster_risk,
        groups=tuple(sorted(inputs.groups, key=lambda g: g.group_id)),
        routes=result.routes,
        shelter_assignments=result.assignments,
        alerts=inputs.alerts,
        warnings=_draft_warnings(inputs, result, no_groups=no_groups),
        validation=validation,
        used_fallback=used_fallback,
        resolver_steps=steps,
        congestion_passes_used=result.passes_used,
        max_vc_ratio=result.max_vc,
    )


def _failed_draft(
    inputs: PlanInputs,
    ctx: RoutingContext,
    reasons: Sequence[str],
    *,
    validation: tuple[ValidationResult, ...] = (),
    result: AssignmentResult | None = None,
    steps: tuple[ResolverStep, ...] = (),
) -> PlanDraft:
    return PlanDraft(
        incident_id=inputs.incident_id,
        run_id=inputs.run_id,
        outcome="failed",
        clusters=inputs.clusters,
        fire_results=inputs.fire_results,
        weather_by_cluster=dict(inputs.weather_by_cluster),
        footprint=ctx.footprint,
        risk=inputs.cluster_risk,
        groups=tuple(sorted(inputs.groups, key=lambda g: g.group_id)),
        alerts=inputs.alerts,
        warnings=tuple(inputs.warnings) if result is None else _draft_warnings(inputs, result),
        validation=validation,
        failure_reasons=tuple(dict.fromkeys(reasons)),
        used_fallback=False,
        resolver_steps=steps,
        congestion_passes_used=0 if result is None else result.passes_used,
        max_vc_ratio=0.0 if result is None else result.max_vc,
    )


def _origin_failures(inputs: PlanInputs, ctx: RoutingContext) -> list[str]:
    return [
        f"origin_unsnappable:{g.group_id}"
        for g in sorted(inputs.groups, key=lambda g: g.group_id)
        if g.origin_node is None or g.origin_node not in ctx.graph
    ]


def plan_draft(
    inputs: PlanInputs,
    ctx: RoutingContext,
    params: PlanningParams,
    *,
    chooser: StrategyChooser | None = None,
) -> PlanOutcome:
    """Preflight, assign, validate, then resolve, fall back or fail closed (D-11, D-12, D-21)."""
    failures = [*inputs.preflight_failures, *_origin_failures(inputs, ctx)]
    if failures:
        return PlanOutcome(_failed_draft(inputs, ctx, failures))

    if not inputs.groups:
        empty = build_assignment(ctx, (), inputs.candidates, params, Constraints())
        validation = validate_assignment(inputs, ctx, empty)
        draft = _valid_draft(
            inputs, ctx, empty, validation, used_fallback=False, steps=(), no_groups=True
        )
        return PlanOutcome(draft)

    first = build_assignment(ctx, inputs.groups, inputs.candidates, params, Constraints())
    first_validation = validate_assignment(inputs, ctx, first)
    if not has_blocking_failure(first_validation):
        return PlanOutcome(
            _valid_draft(inputs, ctx, first, first_validation, used_fallback=False, steps=())
        )

    reasons = violation_lines(first_validation, inputs.groups)
    return PlanOutcome(
        _failed_draft(inputs, ctx, reasons, validation=first_validation, result=first, steps=())
    )


__all__ = [
    "AssignmentResult",
    "Constraints",
    "PlanInputs",
    "PlanOutcome",
    "RoutingContext",
    "build_assignment",
    "plan_draft",
    "validate_assignment",
]

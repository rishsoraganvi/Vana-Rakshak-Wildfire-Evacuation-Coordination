"""Validation context and the ordered structural validator runner (V1..V7)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import networkx as nx
from wildfire_core.geo.footprint import LoadedFootprint
from wildfire_core.schemas.plan import (
    Dispatch,
    EvacueeGroup,
    PlanRoute,
    ShelterAssignment,
    ShelterCandidate,
    ValidationResult,
)

from coordinator.validators.capacity_checks import (
    check_v4_capacity,
    check_v5_complete,
    check_v6_dispatches,
)
from coordinator.validators.integrity_checks import check_v7_entities
from coordinator.validators.route_checks import check_v1_paths, check_v2_blocked, check_v3_forecast


@dataclass(frozen=True)
class ValidationContext:
    """Everything the pure validators need; built once per candidate plan."""

    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]]
    footprint: LoadedFootprint
    edge_status: Mapping[tuple[int, int, int], str]
    groups: Mapping[str, EvacueeGroup]
    candidates: Mapping[str, ShelterCandidate]
    known_settlement_ids: frozenset[str]
    known_shelter_ids: frozenset[str]
    fire_cluster_ids: frozenset[str]
    time_attr: str = "congested_time"


def run_structural_validators(
    *,
    groups: Sequence[EvacueeGroup],
    routes: Sequence[PlanRoute],
    assignments: Sequence[ShelterAssignment],
    dispatches: Sequence[Dispatch],
    unassigned_reasons: Mapping[str, str],
    ctx: ValidationContext,
    clusters_referenced: Sequence[str] = (),
) -> tuple[ValidationResult, ...]:
    """Run V1..V7 in order. V8 (grounding) runs later, once the rationale exists (D-13)."""
    return (
        check_v1_paths(routes, ctx),
        check_v2_blocked(routes, ctx),
        check_v3_forecast(routes, ctx),
        check_v4_capacity(assignments, routes, ctx),
        check_v5_complete(groups, assignments, unassigned_reasons),
        check_v6_dispatches(dispatches),
        check_v7_entities(
            groups=groups,
            routes=routes,
            assignments=assignments,
            clusters_referenced=clusters_referenced,
            ctx=ctx,
        ),
    )


def has_blocking_failure(results: Sequence[ValidationResult]) -> bool:
    """True iff some validator failed (a V3 flag does not block)."""
    return any(item.status == "fail" for item in results)


def violation_summary(results: Sequence[ValidationResult]) -> dict[str, int]:
    """Counts keyed like ``V3:p50_before_arrival``; carries no ids or names (D-10)."""
    counts: Counter[str] = Counter()
    for result in results:
        for violation in result.violations:
            counts[f"{result.validator_id}:{violation.code}"] += 1
    return dict(sorted(counts.items()))

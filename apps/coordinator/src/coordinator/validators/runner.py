"""Validation context and the ordered structural validator runner."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import networkx as nx
from wildfire_core.geo.footprint import LoadedFootprint
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    PlanRoute,
    ShelterCandidate,
    ValidationResult,
)

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
    *, routes: Sequence[PlanRoute], ctx: ValidationContext
) -> tuple[ValidationResult, ...]:
    """Run the route validators in order (V4..V7 are added with the capacity checks)."""
    return (
        check_v1_paths(routes, ctx),
        check_v2_blocked(routes, ctx),
        check_v3_forecast(routes, ctx),
    )

"""Validator V7: every referenced id exists in the registries, graph and fire clusters."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from wildfire_core.schemas.plan import (
    EvacueeGroup,
    PlanRoute,
    ShelterAssignment,
    ValidationResult,
    ViolationRecord,
)

from coordinator.validators._common import build_result

if TYPE_CHECKING:
    from coordinator.validators.runner import ValidationContext


def check_v7_entities(
    *,
    groups: Sequence[EvacueeGroup],
    routes: Sequence[PlanRoute],
    assignments: Sequence[ShelterAssignment],
    clusters_referenced: Sequence[str],
    ctx: ValidationContext,
) -> ValidationResult:
    """Fail on unknown settlement, shelter, node or cluster ids and on unassigned routes."""
    violations: list[ViolationRecord] = []

    def unknown_settlement(group_id: str, where: str) -> None:
        if group_id not in ctx.known_settlement_ids:
            violations.append(
                ViolationRecord(
                    code="unknown_settlement",
                    detail=f"{where} references unknown settlement {group_id}",
                    group_id=group_id,
                )
            )

    def unknown_shelter(shelter_id: str, group_id: str | None, where: str) -> None:
        if shelter_id not in ctx.known_shelter_ids:
            violations.append(
                ViolationRecord(
                    code="unknown_shelter",
                    detail=f"{where} references unknown shelter {shelter_id}",
                    group_id=group_id,
                    shelter_id=shelter_id,
                )
            )

    for group in groups:
        unknown_settlement(group.settlement_id, "group")
    assigned_pairs = {(item.group_id, item.shelter_id) for item in assignments}
    for assignment in assignments:
        unknown_settlement(assignment.group_id, "assignment")
        unknown_shelter(assignment.shelter_id, assignment.group_id, "assignment")
    for route in routes:
        unknown_settlement(route.group_id, "route")
        unknown_shelter(route.shelter_id, route.group_id, "route")
        for node in dict.fromkeys(route.osm_node_path):
            if node not in ctx.graph:
                violations.append(
                    ViolationRecord(
                        code="unknown_node",
                        detail=(
                            f"route for group {route.group_id} to shelter {route.shelter_id} "
                            f"uses node {node} that is not in the road graph"
                        ),
                        group_id=route.group_id,
                        shelter_id=route.shelter_id,
                    )
                )
        if (route.group_id, route.shelter_id) not in assigned_pairs:
            violations.append(
                ViolationRecord(
                    code="route_without_assignment",
                    detail=(
                        f"route for group {route.group_id} to shelter {route.shelter_id} "
                        "has no matching shelter assignment"
                    ),
                    group_id=route.group_id,
                    shelter_id=route.shelter_id,
                )
            )
    for cluster_id in dict.fromkeys(clusters_referenced):
        if cluster_id not in ctx.fire_cluster_ids:
            violations.append(
                ViolationRecord(
                    code="unknown_cluster",
                    detail=f"plan references unknown fire cluster {cluster_id}",
                )
            )
    return build_result("V7", violations)

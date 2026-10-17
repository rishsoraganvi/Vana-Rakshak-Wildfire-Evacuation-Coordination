"""Validators V4-V6: shelter capacity, complete assignment and vehicle double-booking."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from wildfire_core.schemas.plan import (
    Dispatch,
    EvacueeGroup,
    PlanRoute,
    ShelterAssignment,
    ValidationResult,
    ViolationRecord,
)

from coordinator.validators._common import build_result

if TYPE_CHECKING:
    from coordinator.validators.runner import ValidationContext

DEFAULT_UNASSIGNED_REASON = "insufficient_capacity"


def check_v4_capacity(
    assignments: Sequence[ShelterAssignment],
    routes: Sequence[PlanRoute],
    ctx: ValidationContext,
) -> ValidationResult:
    """Assigned persons stay within each shelter's available capacity and match the routes."""
    violations: list[ViolationRecord] = []
    per_shelter: dict[str, int] = defaultdict(int)
    per_pair: dict[tuple[str, str], int] = defaultdict(int)
    for assignment in assignments:
        per_shelter[assignment.shelter_id] += assignment.persons
        per_pair[(assignment.group_id, assignment.shelter_id)] += assignment.persons
    routed: dict[tuple[str, str], int] = defaultdict(int)
    for route in routes:
        routed[(route.group_id, route.shelter_id)] += route.persons

    for shelter_id in sorted(per_shelter):
        candidate = ctx.candidates.get(shelter_id)
        if candidate is None:
            violations.append(
                ViolationRecord(
                    code="not_a_candidate",
                    detail=f"shelter {shelter_id} is not an eligible candidate shelter",
                    shelter_id=shelter_id,
                )
            )
        elif per_shelter[shelter_id] > candidate.available:
            violations.append(
                ViolationRecord(
                    code="over_capacity",
                    detail=(
                        f"shelter {shelter_id} is assigned {per_shelter[shelter_id]} persons "
                        f"but only {candidate.available} are available"
                    ),
                    shelter_id=shelter_id,
                )
            )
    for (group_id, shelter_id), persons in sorted(per_pair.items()):
        if routed[(group_id, shelter_id)] != persons:
            violations.append(
                ViolationRecord(
                    code="route_assignment_mismatch",
                    detail=(
                        f"group {group_id} to shelter {shelter_id}: assignment has {persons} "
                        f"persons but routes carry {routed[(group_id, shelter_id)]}"
                    ),
                    group_id=group_id,
                    shelter_id=shelter_id,
                )
            )
    return build_result("V4", violations)


def check_v5_complete(
    groups: Sequence[EvacueeGroup],
    assignments: Sequence[ShelterAssignment],
    unassigned_reasons: Mapping[str, str],
) -> ValidationResult:
    """Every group is fully assigned; a shortfall names the group, residual and reason (D-12)."""
    assigned: dict[str, int] = defaultdict(int)
    for assignment in assignments:
        assigned[assignment.group_id] += assignment.persons
    violations: list[ViolationRecord] = []
    for group in groups:
        total = assigned[group.group_id]
        if total < group.persons:
            reason = unassigned_reasons.get(group.group_id, DEFAULT_UNASSIGNED_REASON)
            violations.append(
                ViolationRecord(
                    code="group_unassigned",
                    detail=(
                        f"group {group.group_id} ({group.settlement_name}) has "
                        f"{group.persons - total} persons not assigned: {reason}"
                    ),
                    group_id=group.group_id,
                )
            )
        elif total > group.persons:
            violations.append(
                ViolationRecord(
                    code="group_over_assigned",
                    detail=(
                        f"group {group.group_id} ({group.settlement_name}) is assigned "
                        f"{total} persons but has {group.persons}"
                    ),
                    group_id=group.group_id,
                )
            )
    return build_result("V5", violations)


def check_v6_dispatches(dispatches: Sequence[Dispatch]) -> ValidationResult:
    """No vehicle appears twice; an empty dispatch list passes trivially."""
    seen: set[str] = set()
    duplicated: list[str] = []
    for dispatch in dispatches:
        if dispatch.vehicle_id in seen and dispatch.vehicle_id not in duplicated:
            duplicated.append(dispatch.vehicle_id)
        seen.add(dispatch.vehicle_id)
    violations = [
        ViolationRecord(
            code="vehicle_double_booked",
            detail=f"vehicle {vehicle_id} is dispatched more than once",
        )
        for vehicle_id in duplicated
    ]
    return build_result("V6", violations)

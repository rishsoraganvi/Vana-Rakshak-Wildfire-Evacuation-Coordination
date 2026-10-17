"""Material-change signature and plan diff (D-16, RESEARCH Pattern 7).

A re-plan only becomes a new plan version when the *decision content* changed: who goes to which
shelter, along which road path, and which validators passed. Everything volatile (uuid ids,
timestamps, rationale text, warnings, ETA and congestion noise) is deliberately excluded, so two
runs over the same world never create a version churn.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from wildfire_core.schemas.plan import IntegratedPlan, PlanDiff

_SCHEMA_VERSION = "3.0"
_ABSENT = "absent"

Signature = dict[str, Any]


def _as_mapping(plan_like: IntegratedPlan | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(plan_like, IntegratedPlan):
        return plan_like.model_dump(mode="json")
    return plan_like


def _pair(group_id: Any, shelter_id: Any) -> str:
    return f"{group_id}->{shelter_id}"


def _assignments(data: Mapping[str, Any]) -> dict[str, int]:
    """(group, shelter) pair to persons, summed if a pair repeats."""
    pairs: dict[str, int] = {}
    for item in data.get("shelter_assignments") or ():
        key = _pair(item["group_id"], item["shelter_id"])
        pairs[key] = pairs.get(key, 0) + int(item["persons"])
    return dict(sorted(pairs.items()))


def _paths(data: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    """(group, shelter) pair to the node path of its best-ranked route."""
    best: dict[str, tuple[int, tuple[int, ...]]] = {}
    for item in data.get("routes") or ():
        key = _pair(item["group_id"], item["shelter_id"])
        rank = int(item.get("path_rank", 1))
        path = tuple(int(node) for node in item["osm_node_path"])
        if key not in best or rank < best[key][0]:
            best[key] = (rank, path)
    return {key: best[key][1] for key in sorted(best)}


def _validators(data: Mapping[str, Any]) -> dict[str, str]:
    result = {item["validator_id"]: str(item["status"]) for item in data.get("validation") or ()}
    return dict(sorted(result.items()))


def material_signature(plan_like: IntegratedPlan | Mapping[str, Any]) -> Signature:
    """Deterministic, order-independent decision content of a plan.

    Holds sorted (group, shelter, persons) tuples, the node path per (group, shelter), validator
    statuses and the plan status. Accepts an ``IntegratedPlan`` or its stored ``plan_data``.
    """
    data = _as_mapping(plan_like)
    assignments = tuple((pair, persons) for pair, persons in _assignments(data).items())
    return {
        "assignments": assignments,
        "routes": _paths(data),
        "validators": _validators(data),
        "status": data.get("status"),
    }


def _is_phase3(previous: Mapping[str, Any]) -> bool:
    return previous.get("plan_schema_version") == _SCHEMA_VERSION


def is_material_change(previous: Mapping[str, Any] | None, new: IntegratedPlan) -> bool:
    """True when ``new`` must become a new version of the incident's plan.

    No predecessor, or a Phase 2 ``plan_data`` (no ``plan_schema_version`` "3.0"), always counts as
    material (D-16).
    """
    if previous is None or not _is_phase3(previous):
        return True
    return material_signature(previous) != material_signature(new)


def plan_diff(previous: Mapping[str, Any] | None, new: IntegratedPlan) -> PlanDiff:
    """What changed between the stored predecessor and ``new`` (stored on the new version)."""
    material = is_material_change(previous, new)
    new_data = _as_mapping(new)
    old_data: Mapping[str, Any] = previous if previous is not None else {}

    old_assignments = _assignments(old_data)
    new_assignments = _assignments(new_data)
    old_paths = _paths(old_data)
    new_paths = _paths(new_data)

    old_validators = _validators(old_data)
    new_validators = _validators(new_data)
    validators_changed = {
        vid: (old_validators.get(vid, _ABSENT), new_validators.get(vid, _ABSENT))
        for vid in sorted(set(old_validators) | set(new_validators))
        if old_validators.get(vid) != new_validators.get(vid) and old_validators
    }

    old_status = old_data.get("status")
    new_status = new_data.get("status")
    status_changed = (
        (str(old_status), str(new_status))
        if old_status is not None and old_status != new_status
        else None
    )

    return PlanDiff(
        assignments_added=tuple(sorted(set(new_assignments) - set(old_assignments))),
        assignments_removed=tuple(sorted(set(old_assignments) - set(new_assignments))),
        assignments_changed=tuple(
            sorted(
                pair
                for pair in set(old_assignments) & set(new_assignments)
                if old_assignments[pair] != new_assignments[pair]
            )
        ),
        routes_changed=tuple(
            sorted(
                pair
                for pair in set(old_paths) & set(new_paths)
                if old_paths[pair] != new_paths[pair]
            )
        ),
        validators_changed=validators_changed,
        status_changed=status_changed,
        is_material=material,
    )

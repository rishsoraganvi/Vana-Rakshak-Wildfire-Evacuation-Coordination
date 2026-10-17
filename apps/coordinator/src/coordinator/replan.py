"""On-demand re-planning (D-14, D-15, D-16; no background worker in Phase 3).

``check_and_replan`` compares fresh evidence (a new fire perimeter, road edge statuses, shelter
states) with the incident's latest plan and, for every Phase 3 trigger that crossed its
threshold, calls ``replan_incident``. ``replan_incident`` records the trigger (debounced per
incident and type, so identical triggers within ``trigger_debounce_s`` coalesce) and, when it is
not coalesced, runs the coordinator. The coordinator's material-change gate then either writes
version n+1 (with ``parent_plan_id`` and a diff) or records ``replan_no_change`` and writes
nothing.

Phase 3 has no approved plan (approval arrives in Phase 4), so every comparison is against the
latest non-superseded plan: ``pending_review`` or ``failed``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from ingest_worker.triggers import (
    PHASE3_TRIGGER_TYPES,
    TriggerDecision,
    detect_perimeter_change,
)
from pydantic import BaseModel, ConfigDict
from wildfire_core.config import Settings
from wildfire_core.schemas.plan import EdgeStatusEntry, IntegratedPlan, ShelterSnapshot

from coordinator.deps import CoordinatorDeps
from coordinator.runner import run_coordinator

REPLAN_TRIGGER_TYPES = PHASE3_TRIGGER_TYPES
_CONFLICT = "state_version_conflict"


class ReplanObservation(BaseModel):
    """Fresh evidence about an incident; every field is optional and compared on its own."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    new_perimeter_wkt: str | None = None
    edge_statuses: tuple[EdgeStatusEntry, ...] = ()
    shelter_states: tuple[ShelterSnapshot, ...] = ()


@dataclass(frozen=True)
class DetectedTrigger:
    trigger_type: str
    decision: TriggerDecision
    details: dict[str, Any]


class ReplanOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["coalesced", "new_version", "no_change", "conflict"]
    trigger_id: str
    coalesced_into: str | None = None
    plan_id: str | None = None
    version: int | None = None
    plan_status: str | None = None


def _json_safe(details: Mapping[str, Any]) -> dict[str, Any]:
    """jsonb rejects NaN and Infinity (an infinite growth ratio), so those become null."""
    return {
        key: None if isinstance(value, float) and not math.isfinite(value) else value
        for key, value in details.items()
    }


def detect_replan_triggers(
    observation: ReplanObservation, latest_plan: IntegratedPlan, settings: Settings
) -> list[DetectedTrigger]:
    """Triggers that crossed their thresholds against ``latest_plan``, sorted by type."""
    detected: list[DetectedTrigger] = []

    if observation.new_perimeter_wkt is not None:
        decision = detect_perimeter_change(
            latest_plan.footprint.current_wkt,
            observation.new_perimeter_wkt,
            iou_threshold=settings.perimeter_iou_threshold,
            growth_threshold=settings.perimeter_growth_threshold,
        )
        if decision.crossed:
            detected.append(
                DetectedTrigger("perimeter_change", decision, _json_safe(decision.details))
            )

    return sorted(detected, key=lambda item: item.trigger_type)


def replan_incident(
    incident_id: str,
    trigger_type: str,
    details: Mapping[str, Any],
    *,
    deps: CoordinatorDeps,
) -> ReplanOutcome:
    """Record the trigger and, unless it coalesced, run the coordinator once (D-15, D-16)."""
    if trigger_type not in REPLAN_TRIGGER_TYPES:
        raise ValueError(
            f"trigger_type must be one of {sorted(REPLAN_TRIGGER_TYPES)}, got {trigger_type!r}"
        )
    recorded = deps.repository.record_trigger(
        incident_id,
        trigger_type,
        _json_safe(details),
        deps.clock.now_utc(),
        debounce_s=deps.settings.trigger_debounce_s,
    )
    if recorded.coalesced_into is not None:
        return ReplanOutcome(
            status="coalesced",
            trigger_id=recorded.trigger_id,
            coalesced_into=recorded.coalesced_into,
        )

    state = run_coordinator(incident_id, str(uuid4()), trigger_id=recorded.trigger_id, deps=deps)
    if state["error"] == _CONFLICT:  # shared state moved mid-run: one bounded retry (Rules 2.8)
        state = run_coordinator(
            incident_id, str(uuid4()), trigger_id=recorded.trigger_id, deps=deps
        )
    persist = state["persist"]
    if persist is None:
        if state["error"] == _CONFLICT:
            return ReplanOutcome(status="conflict", trigger_id=recorded.trigger_id)
        raise RuntimeError(f"re-plan produced no plan: {state['error'] or 'unknown error'}")
    return ReplanOutcome(
        status="new_version" if persist["created"] else "no_change",
        trigger_id=recorded.trigger_id,
        plan_id=persist["plan_id"],
        version=persist["version"],
        plan_status=persist["status"],
    )


def check_and_replan(
    observation: ReplanObservation, *, deps: CoordinatorDeps
) -> list[ReplanOutcome]:
    """Detect crossed triggers against the latest plan and re-plan once per crossed type."""
    stored = deps.repository.latest_plan(observation.incident_id)
    if stored is None:
        return []  # nothing to compare with: the first plan comes from the new_hotspot trigger
    latest = IntegratedPlan.model_validate(stored.plan_data)
    return [
        replan_incident(observation.incident_id, item.trigger_type, item.details, deps=deps)
        for item in detect_replan_triggers(observation, latest, deps.settings)
    ]


__all__ = [
    "REPLAN_TRIGGER_TYPES",
    "DetectedTrigger",
    "ReplanObservation",
    "ReplanOutcome",
    "check_and_replan",
    "detect_replan_triggers",
    "replan_incident",
]

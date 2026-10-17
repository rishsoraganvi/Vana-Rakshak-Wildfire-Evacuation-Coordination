"""Deterministic rationale text and the compact summary sent to the optional LLM.

Every number and name below is read from plan data, so the V8 grounding check passes by
construction (D-13). Node paths, coordinates and WKT are never included (Groq 8k TPM).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from wildfire_core.schemas.plan import (
    IntegratedPlan,
    PlanDraft,
    PlanFreshness,
    PlanRoute,
)

PlanLike = PlanDraft | IntegratedPlan

TEMPLATE_MARKER = "[DETERMINISTIC TEMPLATE]"
FAILED_MARKER = "[PLAN FAILED]"


def _best_route(plan: PlanLike, group_id: str, shelter_id: str) -> PlanRoute | None:
    matching = [
        route
        for route in plan.routes
        if route.group_id == group_id and route.shelter_id == shelter_id
    ]
    return min(matching, key=lambda route: route.path_rank) if matching else None


def _alert_lines(plan: PlanLike) -> list[str]:
    return [f"- ALERT [{alert.kind}]: {alert.message}" for alert in plan.alerts]


def template_rationale(plan: PlanLike) -> str:
    group_names = {group.group_id: group.settlement_name for group in plan.groups}
    group_eta = {group.group_id: group.eta_min for group in plan.groups}
    assignments = sorted(plan.shelter_assignments, key=lambda a: (a.group_id, a.shelter_id))
    total_persons = sum(item.persons for item in assignments)
    shelter_count = len({item.shelter_id for item in assignments})
    lines = [
        f"{TEMPLATE_MARKER} {len(plan.groups)} group(s), {total_persons} persons assigned to "
        f"{shelter_count} shelter(s) along {len(plan.routes)} route(s)."
    ]
    for item in assignments:
        route = _best_route(plan, item.group_id, item.shelter_id)
        name = group_names.get(item.group_id, item.group_id)
        if route is not None:
            timing = f"ETA {route.eta_min:.1f} min (forecast horizon {route.horizon_h} h)"
        else:
            timing = f"ETA {group_eta.get(item.group_id, 0.0):.1f} min"
        lines.append(f"- {name}: {item.persons} persons -> {item.shelter_name}, {timing}")
    lines.extend(_alert_lines(plan))
    lines.append("Human review required. Decision support only.")
    return "\n".join(lines)


def template_failure_rationale(
    plan: PlanLike, *, failure_reasons: Sequence[str] | None = None
) -> str:
    reasons = tuple(failure_reasons) if failure_reasons is not None else plan.failure_reasons
    lines = [f"{FAILED_MARKER} The run did not produce an approvable plan."]
    lines.extend(f"- {reason}" for reason in reasons)
    lines.extend(_alert_lines(plan))
    lines.append("No approvable content. Human review required.")
    return "\n".join(lines)


def compact_plan_summary(plan: PlanLike, freshness: PlanFreshness | None = None) -> dict[str, Any]:
    """Settlement-level summary for the LLM rationale call: no paths, coordinates or WKT."""
    summary: dict[str, Any] = {
        "groups": [
            {
                "group_id": group.group_id,
                "settlement_name": group.settlement_name,
                "persons": group.persons,
                "priority": group.priority,
                "eta_min": group.eta_min,
            }
            for group in plan.groups
        ],
        "assignments": [
            {
                "group_id": item.group_id,
                "shelter_id": item.shelter_id,
                "shelter_name": item.shelter_name,
                "persons": item.persons,
                "usable_capacity": item.usable_capacity,
            }
            for item in plan.shelter_assignments
        ],
        "routes": [
            {
                "group_id": route.group_id,
                "shelter_id": route.shelter_id,
                "eta_min": route.eta_min,
                "horizon_h": route.horizon_h,
                "risk_score": route.risk_score,
                "safety_classification": route.safety_classification,
                "path_rank": route.path_rank,
            }
            for route in plan.routes
        ],
        "alerts": [alert.message for alert in plan.alerts],
        "warning_count": len(plan.warnings),
        "cluster_risk": [
            {
                "cluster_id": risk.cluster_id,
                "affected_area_ha": risk.affected_area_ha,
                "spread_rate_m_per_h": risk.spread_rate_m_per_h,
                "confidence": risk.confidence,
            }
            for risk in plan.risk
        ],
        "validators": {item.validator_id: item.status for item in plan.validation},
    }
    if freshness is not None:
        summary["freshness"] = {
            "firms_age_min": freshness.firms_age_min,
            "weather_age_min_max": freshness.weather_age_min_max,
            "stale_inputs": list(freshness.stale_inputs),
        }
    return summary

"""LangGraph state for the Phase 3 coordinator.

Every value is JSON-serializable so the state can be checkpointed in Phase 4. Objects that are not
serializable (the routed road graph, the parsed footprint) live in run-scoped scratch on
``CoordinatorDeps.scratch`` keyed by ``run_id``, never in this state.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CoordinatorState(TypedDict):
    incident_id: str
    run_id: str
    trigger_id: str | None
    incident_origin: str | None
    state_version: int
    hotspot_ids: list[str]
    hotspots: list[dict[str, Any]]
    clusters: list[dict[str, Any]]
    weather_by_cluster: dict[str, dict[str, Any]]
    weather_missing: list[str]
    fire_results: list[dict[str, Any]]
    footprint: dict[str, Any] | None
    groups: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    risk_failures: list[str]
    candidates: list[dict[str, Any]]
    excluded_shelters: list[dict[str, Any]]
    shelter_snapshot: list[dict[str, Any]]
    specialist_results: dict[str, dict[str, Any]]
    preflight_failures: list[str]
    draft: dict[str, Any] | None
    llm_calls: list[dict[str, Any]]
    rationale_text: str | None
    rationale_metadata: dict[str, Any] | None
    is_llm_fallback: bool
    plan: dict[str, Any] | None
    persist: dict[str, Any] | None
    audit_entries: list[dict[str, Any]]
    warnings: list[str]
    error: str | None


def initial_state(incident_id: str, run_id: str, trigger_id: str | None = None) -> CoordinatorState:
    """Fresh state for one run; every collection starts empty."""
    return {
        "incident_id": incident_id,
        "run_id": run_id,
        "trigger_id": trigger_id,
        "incident_origin": None,
        "state_version": 0,
        "hotspot_ids": [],
        "hotspots": [],
        "clusters": [],
        "weather_by_cluster": {},
        "weather_missing": [],
        "fire_results": [],
        "footprint": None,
        "groups": [],
        "alerts": [],
        "risk_failures": [],
        "candidates": [],
        "excluded_shelters": [],
        "shelter_snapshot": [],
        "specialist_results": {},
        "preflight_failures": [],
        "draft": None,
        "llm_calls": [],
        "rationale_text": None,
        "rationale_metadata": None,
        "is_llm_fallback": False,
        "plan": None,
        "persist": None,
        "audit_entries": [],
        "warnings": [],
        "error": None,
    }

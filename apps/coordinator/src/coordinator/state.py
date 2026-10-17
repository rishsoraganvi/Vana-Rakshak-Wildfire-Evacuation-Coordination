from __future__ import annotations

from typing import Any, TypedDict


class CoordinatorState(TypedDict):
    incident_id: str
    run_id: str
    hotspot_ids: list[str]
    hotspots: list[dict[str, Any]]
    weather_snapshot: dict[str, Any] | None
    clusters: list[dict[str, Any]]
    fire_results: list[dict[str, Any]]
    routes: list[dict[str, Any]]
    rationale: str
    is_llm_fallback: bool
    audit_entries: list[dict[str, Any]]
    warnings: list[str]
    error: str | None

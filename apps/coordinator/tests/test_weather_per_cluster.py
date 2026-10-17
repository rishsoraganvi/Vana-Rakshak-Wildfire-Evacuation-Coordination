"""Per-cluster weather: own lookup per centroid, fail closed when missing (WR-01, D-17, D-21)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from coordinator.runner import run_coordinator
from pipeline_factory import (
    FAR_CENTRE,
    FIRE_CENTRE,
    INCIDENT_ID,
    RecordingRepository,
    add_cluster,
    add_weather,
    make_deps,
    make_settings,
    seeded_repository,
)
from wildfire_core.schemas.plan import IntegratedPlan


def _two_cluster_repo(settings: Any, *, far_weather: bool) -> RecordingRepository:
    repo, _ = seeded_repository(settings, with_weather=False)
    add_cluster(repo, INCIDENT_ID, FAR_CENTRE)
    add_weather(repo, settings, FIRE_CENTRE, wind_speed_ms=4.0)
    if far_weather:
        add_weather(repo, settings, FAR_CENTRE, wind_speed_ms=9.0)
    assert isinstance(repo, RecordingRepository)
    return repo


def _cluster_ids(state: dict[str, Any]) -> tuple[str, str]:
    """(near, far) cluster ids by centroid latitude."""
    ordered = sorted(state["clusters"], key=lambda item: item["centroid_lat"])
    return ordered[0]["cluster_id"], ordered[-1]["cluster_id"]


def test_two_clusters_get_their_own_weather_lookup_and_fire_run() -> None:
    settings = make_settings()
    repo = _two_cluster_repo(settings, far_weather=True)
    fire_calls: list[dict[str, Any]] = []
    deps = make_deps(repo, settings, fire_calls=fire_calls)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    assert len(repo.weather_queries) == 2
    (lat_a, lon_a), (lat_b, lon_b) = sorted(repo.weather_queries)
    assert abs(lat_b - lat_a) > 0.4  # about 60 km apart: two distinct centroid queries
    near, far = _cluster_ids(state)
    wind_by_cluster = {call["cluster_id"]: call["wind_speed_ms"] for call in fire_calls}
    assert wind_by_cluster == {near: 4.0, far: 9.0}  # each fire run got its own snapshot
    assert {item["wind_speed_ms"] for item in state["weather_by_cluster"].values()} == {4.0, 9.0}
    assert state["weather_missing"] == []


def test_cluster_without_weather_fails_the_plan_and_names_it() -> None:
    settings = make_settings()
    repo = _two_cluster_repo(settings, far_weather=False)
    fire_calls: list[dict[str, Any]] = []
    deps = make_deps(repo, settings, fire_calls=fire_calls)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    near, far = _cluster_ids(state)
    assert state["weather_missing"] == [f"weather_unavailable:{far}"]
    assert far not in state["weather_by_cluster"]  # no weather was fabricated
    assert [call["cluster_id"] for call in fire_calls] == [near]  # only the covered cluster ran
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "failed"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert any(far in reason for reason in plan.failure_reasons)
    assert any(
        alert.kind == "weather_unavailable" and alert.cluster_id == far for alert in plan.alerts
    )
    # the other cluster's weather is still recorded
    assert set(plan.provenance.weather_valid_times) == {near}
    assert set(plan.weather_by_cluster) == {near}
    assert plan.routes == () and plan.shelter_assignments == ()


def test_stale_weather_still_plans_and_adds_a_freshness_warning() -> None:
    settings = make_settings()
    repo, _ = seeded_repository(settings, with_weather=False)
    add_weather(repo, settings, FIRE_CENTRE, age_min=120)
    deps = make_deps(repo, settings)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "pending_review"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    cluster_id = state["clusters"][0]["cluster_id"]
    assert f"Weather for cluster {cluster_id} is 120 min old (stale)" in plan.warnings
    assert plan.freshness.weather_age_min_by_cluster[cluster_id] == 120
    assert f"weather:{cluster_id}" in plan.freshness.stale_inputs


def test_in_memory_snapshot_carries_age_minutes() -> None:
    settings = make_settings()
    repo, _ = seeded_repository(settings)
    deps = make_deps(repo, settings)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    (snapshot,) = state["weather_by_cluster"].values()
    assert snapshot["age_min"] == 20 and snapshot["is_stale"] is False

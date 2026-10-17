"""Phase 2 coordinator behaviours, re-proven against the Phase 3 pipeline.

The Phase 2 tests faked SQL strings and patched module globals. These run the real ten-node graph
with an in-memory repository and injected dependencies instead. The AOI-exit routing tests were
superseded by ``snap_points`` (plan 03-05) and the V2 validator tests (plan 03-06).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from coordinator.runner import run_coordinator
from pipeline_factory import (
    FAR_CENTRE,
    INCIDENT_ID,
    RecordingRepository,
    add_cluster,
    add_weather,
    make_deps,
    make_settings,
    seeded_repository,
)
from shapely import wkt
from shapely.geometry import Point
from wildfire_core.schemas.plan import IntegratedPlan


def test_hotspots_are_scoped_to_the_incident_triggers() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)
    own_ids = list(repo.triggers[trigger_id]["hotspot_ids"])
    other_incident = str(uuid4())
    repo.add_incident(other_incident)
    add_cluster(repo, other_incident, (11.95, 76.40))  # another incident's trigger
    add_cluster(repo, INCIDENT_ID, (11.90, 76.10), count=4)
    coalesced = list(repo.triggers)[-1]
    repo.triggers[coalesced]["coalesced"] = True  # already merged into another trigger

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=make_deps(repo, settings))

    assert sorted(state["hotspot_ids"]) == sorted(own_ids)
    assert len(state["clusters"]) == 1
    assert state["incident_origin"] == "simulated"


def test_every_cluster_is_simulated_and_the_footprint_unions_all_fires() -> None:
    settings = make_settings()
    repo, _ = seeded_repository(settings)
    add_cluster(repo, INCIDENT_ID, FAR_CENTRE)
    add_weather(repo, settings, FAR_CENTRE, wind_speed_ms=7.0)
    fire_calls: list[dict[str, Any]] = []
    rationale_calls: list[Any] = []
    deps = make_deps(repo, settings, fire_calls=fire_calls, rationale_calls=rationale_calls)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    clusters = state["clusters"]
    assert len(clusters) == 2
    assert {call["cluster_id"] for call in fire_calls} == {item["cluster_id"] for item in clusters}
    assert len(state["fire_results"]) == 2
    current = wkt.loads(state["footprint"]["current_wkt"])
    for cluster in clusters:
        assert current.covers(Point(cluster["centroid_lon"], cluster["centroid_lat"]))

    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert {item.cluster_id for item in plan.fire_results} == {
        item.cluster_id for item in plan.clusters
    }
    assert len(plan.risk) == 2
    assert len(rationale_calls) == 1
    assert len(rationale_calls[0]["cluster_risk"]) == 2


def test_weather_unavailable_fails_the_plan_without_fabrication() -> None:
    settings = make_settings()
    repo, _ = seeded_repository(settings, with_weather=False)
    fire_calls: list[dict[str, Any]] = []
    deps = make_deps(repo, settings, fire_calls=fire_calls)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    cluster_id = state["clusters"][0]["cluster_id"]
    assert state["weather_by_cluster"] == {}
    assert state["fire_results"] == []
    assert fire_calls == []  # no cluster is simulated on made-up weather
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "failed"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert f"weather_unavailable:{cluster_id}" in plan.failure_reasons
    assert plan.weather_by_cluster == {} and plan.routes == ()
    weather_entry = next(e for e in state["audit_entries"] if e["node_name"] == "run_weather")
    outputs = json.loads(weather_entry["outputs_json"])
    assert outputs["weather_by_cluster"] == {}
    assert outputs["weather_missing"] == [f"weather_unavailable:{cluster_id}"]
    assert "valid_time" not in weather_entry["outputs_json"]
    assert isinstance(repo, RecordingRepository)
    centroid = state["clusters"][0]
    assert repo.weather_queries == [(centroid["centroid_lat"], centroid["centroid_lon"])]


def test_generate_rationale_audit_records_metadata_when_the_plan_failed() -> None:
    settings = make_settings(llm_enabled=True, llm_model="test-model")
    repo, _ = seeded_repository(settings, with_weather=False)
    rationale_calls: list[Any] = []
    deps = make_deps(repo, settings, rationale_calls=rationale_calls)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    assert rationale_calls == []  # the LLM is never called for a failed plan
    entry = next(e for e in state["audit_entries"] if e["node_name"] == "generate_rationale")
    metadata = entry["model_metadata"]
    assert metadata["fallback_reason"] == "plan_failed"
    assert metadata["llm_called"] is False
    assert metadata["is_fallback"] is True
    assert metadata["model"] == "test-model"
    flushed = next(e for e in repo.audit_entries if e["node_name"] == "generate_rationale")
    assert flushed["model_metadata"]["fallback_reason"] == "plan_failed"
    assert state["is_llm_fallback"] is True

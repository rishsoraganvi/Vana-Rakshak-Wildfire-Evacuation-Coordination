"""Offline end-to-end Phase 3 pipeline: hotspot incident to a persisted versioned plan."""

from __future__ import annotations

import json
from uuid import uuid4

from agent_fire.ensemble import compute_fire_spread
from coordinator.graph import NODE_ORDER
from coordinator.runner import run_coordinator
from pipeline_factory import (
    INCIDENT_ID,
    make_deps,
    make_settings,
    node_names,
    seeded_repository,
)
from wildfire_core.schemas.plan import IntegratedPlan


def _run(repo, settings, trigger_id, **kwargs):
    rationale_calls: list = []
    deps = make_deps(repo, settings, rationale_calls=rationale_calls, **kwargs)
    state = run_coordinator(INCIDENT_ID, str(uuid4()), trigger_id=trigger_id, deps=deps)
    return state, deps, rationale_calls


def test_incident_flows_through_ten_nodes_to_a_pending_review_plan() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    state, deps, _ = _run(repo, settings, trigger_id)

    assert state["error"] is None
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "pending_review"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert len(plan.groups) >= 1
    assert len(plan.routes) == len(plan.shelter_assignments) >= 1
    assert [item.validator_id for item in plan.validation] == [f"V{i}" for i in range(1, 9)]
    assert all(item.status != "fail" for item in plan.validation)
    assert plan.freshness.weather_age_min_by_cluster
    assert plan.freshness.firms_age_min == 30
    assert plan.provenance.hotspot_ids and plan.provenance.fire_run_ids
    assert plan.provenance.weather_provider == settings.weather_provider
    assert plan.provenance.trigger_id == trigger_id
    assert plan.is_simulated is True
    assert state["persist"]["created"] is True
    assert state["persist"]["version"] == 1
    assert repo.incidents[INCIDENT_ID].state_version == 1
    assert state["run_id"] not in deps.scratch  # run-scoped scratch is released


def test_audit_covers_ten_nodes_and_both_specialist_agents() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    state, _, _ = _run(repo, settings, trigger_id)

    assert set(NODE_ORDER) <= node_names(repo.audit_entries)
    agents = {entry["agent"] for entry in repo.audit_entries}
    assert {"coordinator", "shelter", "traffic_routing"} <= agents
    assert len(repo.audit_entries) == len(state["audit_entries"])
    assert repo.triggers[trigger_id]["handled_entry_id"] is not None
    handled = repo.triggers[trigger_id]["handled_entry_id"]
    assert any(
        entry["entry_id"] == handled and entry["node_name"] == "assemble_plan"
        for entry in repo.audit_entries
    )


def test_langgraph_state_is_json_serializable() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    state, _, _ = _run(repo, settings, trigger_id)

    json.dumps(state)


def test_rerun_without_material_change_creates_no_version() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    first, _, _ = _run(repo, settings, trigger_id)
    second, _, _ = _run(repo, settings, trigger_id)

    assert first["persist"]["created"] is True
    assert second["persist"]["created"] is False
    assert second["persist"]["plan_id"] == first["persist"]["plan_id"]
    assert "replan_no_change" in node_names(second["audit_entries"])
    assert len(repo.plans[INCIDENT_ID]) == 1
    assert repo.incidents[INCIDENT_ID].state_version == 1


def test_capacity_starved_run_persists_a_failed_plan_naming_the_group() -> None:
    settings = make_settings()
    # 3 shelters x floor(10 x 0.5) = 15 places, but the near settlement has 60 people
    repo, trigger_id = seeded_repository(settings, shelter_capacity=10)

    state, _, rationale_calls = _run(repo, settings, trigger_id)

    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "failed"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert plan.routes == () and plan.shelter_assignments == ()
    assert any("set-near" in reason for reason in plan.failure_reasons)
    assert rationale_calls == []  # no LLM call for a failed plan
    rationale = next(e for e in state["audit_entries"] if e["node_name"] == "generate_rationale")
    assert rationale["model_metadata"]["fallback_reason"] == "plan_failed"


def test_critical_specialist_failure_makes_the_plan_failed() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    def broken_loader(_path):
        raise RuntimeError("graph cache unreadable")

    _, _, _ = _run(repo, settings, trigger_id, graph_loader=broken_loader)

    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.status == "failed"
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert any(
        reason.startswith("specialist_unavailable:traffic_routing")
        for reason in plan.failure_reasons
    )
    assert any(alert.kind == "specialist_unavailable" for alert in plan.alerts)


def test_real_ca_on_the_synthetic_graph_produces_a_persisted_plan() -> None:
    settings = make_settings()
    repo, trigger_id = seeded_repository(settings)

    state, _, _ = _run(repo, settings, trigger_id, fire_fn=compute_fire_spread)

    assert state["error"] is None
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None
    assert stored.status in {"pending_review", "failed"}
    plan = IntegratedPlan.model_validate(stored.plan_data)
    assert plan.fire_results and plan.footprint.current_wkt != "POLYGON EMPTY"


def test_no_clusters_produces_no_plan() -> None:
    settings = make_settings()
    repo, _ = seeded_repository(settings)
    repo.triggers.clear()
    deps = make_deps(repo, settings)

    state = run_coordinator(INCIDENT_ID, str(uuid4()), deps=deps)

    assert state["plan"] is None and state["persist"] is None
    assert state["error"] is not None
    assert repo.latest_plan(INCIDENT_ID) is None
    assert "assemble_plan" in node_names(repo.audit_entries)

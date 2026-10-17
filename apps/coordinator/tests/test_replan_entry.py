"""Offline on-demand re-planning: perimeter trigger, debounce and the material-change gate."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from coordinator.replan import ReplanObservation, check_and_replan, replan_incident
from coordinator.runner import run_coordinator
from pipeline_factory import (
    INCIDENT_ID,
    make_deps,
    make_settings,
    node_names,
    seeded_repository,
)
from shapely.geometry import box
from wildfire_core.clock import SimClock
from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot
from wildfire_core.schemas.plan import IntegratedPlan


def wide_fire(cluster: HotspotCluster, weather: WeatherSnapshot, **_kwargs) -> FireSpreadResult:
    """A fire that has spread east: its P50 now covers shelter SH-1 but not SH-2 or SH-3."""
    lon, lat = cluster.centroid_lon, cluster.centroid_lat

    def rect(half_lon: float, half_lat: float) -> str:
        return box(lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat).wkt

    return FireSpreadResult(
        cluster_id=cluster.cluster_id,
        current_perimeter_wkt=rect(0.012, 0.006),
        p50_1h_wkt=rect(0.035, 0.015),
        p50_3h_wkt=rect(0.036, 0.016),
        p50_6h_wkt=rect(0.037, 0.017),
        p90_1h_wkt=rect(0.035, 0.015),
        p90_3h_wkt=rect(0.036, 0.016),
        p90_6h_wkt=rect(0.037, 0.017),
        affected_area_km2=4.0,
        spread_direction_deg=90.0,
        spread_rate_m_per_h=600.0,
        confidence="medium",
    )


def _first_plan(settings):
    repo, trigger_id = seeded_repository(settings)
    deps = make_deps(repo, settings)
    run_coordinator(INCIDENT_ID, str(uuid4()), trigger_id=trigger_id, deps=deps)
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.version == 1
    return repo, deps, IntegratedPlan.model_validate(stored.plan_data)


def _wide_perimeter(deps) -> str:
    cluster = next(iter(deps.repository.incident_hotspots(INCIDENT_ID)))
    return box(
        cluster["lon"] - 0.012,
        cluster["lat"] - 0.006,
        cluster["lon"] + 0.012,
        cluster["lat"] + 0.006,
    ).wkt


def test_perimeter_growth_replans_to_a_parent_linked_version_and_coalesces_repeats() -> None:
    settings = make_settings()
    repo, deps, v1 = _first_plan(settings)
    assert {a.shelter_id for a in v1.shelter_assignments} == {"shelter-sh-1"}
    clock = deps.clock
    assert isinstance(clock, SimClock)

    deps.fire_fn = wide_fire
    observation = ReplanObservation(
        incident_id=INCIDENT_ID, new_perimeter_wkt=_wide_perimeter(deps)
    )
    outcomes = check_and_replan(observation, deps=deps)

    assert [item.status for item in outcomes] == ["new_version"]
    assert outcomes[0].version == 2
    stored = repo.latest_plan(INCIDENT_ID)
    assert stored is not None and stored.version == 2
    v2 = IntegratedPlan.model_validate(stored.plan_data)
    assert v2.parent_plan_id == v1.plan_id
    assert "shelter-sh-1" not in {a.shelter_id for a in v2.shelter_assignments}
    extras = repo.plan_extras[v2.plan_id]
    assert extras.parent_plan_id == v1.plan_id and extras.diff
    assert [p.status for p in repo.plans[INCIDENT_ID]] == ["superseded", v2.status]
    leader = outcomes[0].trigger_id
    assert repo.triggers[leader]["handled_entry_id"] is not None
    assert repo.triggers[leader]["type"] == "perimeter_change"

    # a repeat 120 s later is coalesced into the leader and runs nothing
    audit_count = len(repo.audit_entries)
    clock.advance(timedelta(seconds=120))
    repeat = replan_incident(INCIDENT_ID, "perimeter_change", {"iou": 0.4}, deps=deps)
    assert repeat.status == "coalesced" and repeat.coalesced_into == leader
    assert len(repo.audit_entries) == audit_count
    assert len(repo.plans[INCIDENT_ID]) == 2


def test_replan_after_the_window_with_an_unchanged_fire_creates_no_version() -> None:
    settings = make_settings()
    repo, deps, _ = _first_plan(settings)
    clock = deps.clock
    assert isinstance(clock, SimClock)
    deps.fire_fn = wide_fire
    check_and_replan(
        ReplanObservation(incident_id=INCIDENT_ID, new_perimeter_wkt=_wide_perimeter(deps)),
        deps=deps,
    )
    assert len(repo.plans[INCIDENT_ID]) == 2

    clock.advance(timedelta(seconds=301))
    outcome = replan_incident(INCIDENT_ID, "perimeter_change", {"iou": 0.9}, deps=deps)

    assert outcome.status == "no_change"
    assert outcome.version == 2
    assert len(repo.plans[INCIDENT_ID]) == 2
    assert repo.incidents[INCIDENT_ID].state_version == 2
    assert "replan_no_change" in node_names(repo.audit_entries)
    assert repo.triggers[outcome.trigger_id]["handled_entry_id"] is not None


def test_check_and_replan_below_threshold_does_nothing() -> None:
    settings = make_settings()
    repo, deps, v1 = _first_plan(settings)
    same = ReplanObservation(incident_id=INCIDENT_ID, new_perimeter_wkt=v1.footprint.current_wkt)

    assert check_and_replan(same, deps=deps) == []
    assert len(repo.plans[INCIDENT_ID]) == 1


@pytest.mark.parametrize("trigger_type", ["wind_shift", "scheduled_refresh", "manual"])
def test_deferred_trigger_types_are_rejected(trigger_type: str) -> None:
    settings = make_settings()
    repo, deps, _ = _first_plan(settings)
    triggers_before = len(repo.triggers)

    with pytest.raises(ValueError):
        replan_incident(INCIDENT_ID, trigger_type, {}, deps=deps)
    assert len(repo.triggers) == triggers_before

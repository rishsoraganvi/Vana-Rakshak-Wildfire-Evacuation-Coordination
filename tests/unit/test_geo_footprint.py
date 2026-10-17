from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from shapely import wkt
from shapely.geometry import Point, box
from wildfire_core.geo.footprint import (
    LoadedFootprint,
    buffer_metric,
    build_footprint,
    load_footprint,
)
from wildfire_core.geo.horizons import nearest_horizon_h
from wildfire_core.schemas.phase2 import FireSpreadResult
from wildfire_core.schemas.plan import IntegratedPlan, PlanFreshness, PlanProvenance


@pytest.mark.parametrize(
    ("arrival_min", "expected"),
    [(0, 1), (60, 1), (89, 1), (120, 3), (179, 3), (270, 6), (1000, 6)],
)
def test_nearest_horizon_table(arrival_min: float, expected: int) -> None:
    assert nearest_horizon_h(arrival_min) == expected


@pytest.mark.parametrize("bad", [-1, float("nan")])
def test_nearest_horizon_rejects_invalid(bad: float) -> None:
    with pytest.raises(ValueError):
        nearest_horizon_h(bad)


def _fire(cluster_id: str, west: float, south: float) -> FireSpreadResult:
    square = box(west, south, west + 0.01, south + 0.01).wkt
    return FireSpreadResult(
        cluster_id=cluster_id,
        current_perimeter_wkt=square,
        p50_1h_wkt=square,
        p50_3h_wkt=square,
        p50_6h_wkt=square,
        p90_1h_wkt=square,
        p90_3h_wkt=square,
        p90_6h_wkt=square,
        affected_area_km2=1.0,
        spread_direction_deg=None,
        spread_rate_m_per_h=100.0,
        confidence="medium",
    )


def test_build_footprint_unions_disjoint_squares() -> None:
    fp = build_footprint([_fire("b", 76.7, 11.8), _fire("a", 76.5, 11.6)])
    current = wkt.loads(fp.current_wkt)
    assert current.geom_type == "MultiPolygon"
    assert current.area == pytest.approx(2 * 0.01 * 0.01)
    assert fp.cluster_ids == ("a", "b")
    assert list(fp.fire_run_ids) == sorted(fp.fire_run_ids)
    assert len(fp.fire_run_ids) == 2


def test_build_footprint_empty_input() -> None:
    fp = build_footprint([])
    assert fp.current_wkt == "POLYGON EMPTY"
    assert fp.p90_6h_wkt == "POLYGON EMPTY"
    assert fp.fire_run_ids == ()


def test_load_footprint_is_prepared_and_handles_empty() -> None:
    loaded = load_footprint(build_footprint([_fire("a", 76.5, 11.6)]))
    assert isinstance(loaded, LoadedFootprint)
    assert loaded.current.contains(Point(76.505, 11.605))
    assert set(loaded.p50) == {1, 3, 6}
    assert set(loaded.p90) == {1, 3, 6}
    assert load_footprint(build_footprint([])).current.is_empty


def test_buffer_metric_1000_m_is_about_0_009_degrees_of_latitude() -> None:
    buffered = buffer_metric(Point(76.64, 11.72), 1000.0)
    _west, south, _east, north = buffered.bounds
    radius_deg = (north - south) / 2
    assert radius_deg == pytest.approx(0.009, rel=0.02)


def test_integrated_plan_round_trips_json() -> None:
    now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    fire = _fire("a", 76.5, 11.6)
    footprint = build_footprint([fire])
    plan = IntegratedPlan(
        incident_id="inc-1",
        run_id="run-1",
        status="failed",
        valid_until=now + timedelta(minutes=60),
        created_at=now,
        freshness=PlanFreshness(computed_at=now),
        provenance=PlanProvenance(
            run_id="run-1",
            state_version=1,
            weather_provider="open-meteo",
            graph_source="synthetic",
            graph_node_count=36,
            graph_edge_count=120,
        ),
        fire_results=(fire,),
        footprint=footprint,
        failure_reasons=("no shelter",),
    )
    restored = IntegratedPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert restored.plan_schema_version == "3.0"

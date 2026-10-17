"""Re-plan trigger detectors and the per-incident debounce (D-14, D-15, TechSpec 9)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from ingest_worker.triggers import (
    detect_perimeter_change,
    detect_road_blocked,
    detect_shelter_capacity_change,
    record_trigger,
)
from shapely.geometry import box
from wildfire_core.clock import SimClock
from wildfire_core.schemas.plan import ShelterSnapshot

T0 = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
LON, LAT = 76.62, 11.70


def square(side: float, *, shift: float = 0.0) -> str:
    half = side / 2
    return box(LON - half + shift, LAT - half, LON + half + shift, LAT + half).wkt


def perimeter(new_wkt: str, **overrides: float):
    options = {"iou_threshold": 0.8, "growth_threshold": 0.25} | overrides
    return detect_perimeter_change(square(0.01), new_wkt, **options)


# ---- perimeter ---------------------------------------------------------------------------------


def test_identical_polygons_do_not_cross() -> None:
    decision = perimeter(square(0.01))
    assert not decision.crossed
    assert decision.reason == "perimeter_change_below_threshold"
    assert decision.details["iou"] == pytest.approx(1.0)
    assert decision.details["growth"] == pytest.approx(0.0)


def test_thirty_percent_growth_crosses_on_growth_alone() -> None:
    larger = square(0.01 * 1.3**0.5)
    # IoU is 1/1.3 = 0.77, so relax it to isolate the growth rule
    decision = perimeter(larger, iou_threshold=0.5)
    assert decision.crossed and decision.reason == "perimeter_change_crossed"
    assert decision.details["growth"] == pytest.approx(0.3, abs=0.01)
    assert not perimeter(square(0.01 * 1.2**0.5), iou_threshold=0.5).crossed


def test_shifted_polygon_with_low_iou_crosses() -> None:
    decision = perimeter(square(0.01, shift=0.01 * 0.176))
    assert decision.crossed
    assert decision.details["iou"] == pytest.approx(0.7, abs=0.02)
    assert decision.details["growth"] == pytest.approx(0.0, abs=0.01)


def test_thresholds_come_from_parameters() -> None:
    shifted = square(0.01, shift=0.001)  # IoU about 0.82
    assert not perimeter(shifted).crossed
    assert perimeter(shifted, iou_threshold=0.9).crossed


def test_empty_previous_perimeter_is_infinite_growth() -> None:
    decision = detect_perimeter_change(
        "POLYGON EMPTY", square(0.01), iou_threshold=0.8, growth_threshold=0.25
    )
    assert decision.crossed
    both_empty = detect_perimeter_change(
        "POLYGON EMPTY", "POLYGON EMPTY", iou_threshold=0.8, growth_threshold=0.25
    )
    assert not both_empty.crossed and both_empty.details["iou"] == 1.0


# ---- road blocked ------------------------------------------------------------------------------


def test_road_blocked_crosses_only_for_route_edges() -> None:
    route = {(1, 2, 0), (2, 3, 0)}
    assert detect_road_blocked(route, {(2, 3, 0): "blocked"}).crossed
    assert detect_road_blocked(route, {(1, 2, 0): "unsafe"}).crossed
    assert not detect_road_blocked(route, {(1, 2, 0): "congested", (2, 3, 0): "open"}).crossed
    assert not detect_road_blocked(route, {(9, 9, 0): "blocked"}).crossed
    assert not detect_road_blocked(set(), {(1, 2, 0): "blocked"}).crossed


def test_road_blocked_details_list_the_affected_edges() -> None:
    decision = detect_road_blocked(
        {(1, 2, 0), (2, 3, 0), (3, 4, 0)},
        {(3, 4, 0): "unsafe", (1, 2, 0): "blocked", (7, 8, 0): "blocked"},
    )
    assert decision.details["edges"] == [[1, 2, 0, "blocked"], [3, 4, 0, "unsafe"]]


# ---- shelter capacity --------------------------------------------------------------------------


def snap(shelter_id: str, *, occupancy: int = 0, usable: int = 100, active: bool = True):
    return ShelterSnapshot(
        shelter_id=shelter_id,
        occupancy=occupancy,
        usable_capacity=usable,
        is_active=active,
        capacity_source="synthetic",
    )


def shelter_change(previous, current, tolerance: float = 0.10):
    return detect_shelter_capacity_change(previous, current, tolerance_fraction=tolerance)


def test_shelter_becoming_inactive_crosses() -> None:
    decision = shelter_change([snap("a")], [snap("a", active=False)])
    assert decision.crossed and decision.details["shelter_ids"] == ["a"]


def test_missing_shelter_counts_as_inactive_but_unknown_extras_are_ignored() -> None:
    assert shelter_change([snap("a"), snap("b")], [snap("b")]).crossed
    assert not shelter_change([snap("a")], [snap("a"), snap("new")]).crossed


def test_already_inactive_shelter_does_not_cross_again() -> None:
    assert not shelter_change([snap("a", active=False)], [snap("a", active=False)]).crossed


def test_occupancy_change_crosses_at_the_tolerance() -> None:
    assert not shelter_change([snap("a", occupancy=10)], [snap("a", occupancy=19)]).crossed
    assert shelter_change([snap("a", occupancy=10)], [snap("a", occupancy=20)]).crossed
    assert shelter_change([snap("a", occupancy=30)], [snap("a", occupancy=20)]).crossed
    assert not shelter_change([snap("a", occupancy=5)], [snap("a", occupancy=5)]).crossed
    # no delta, no cross, even with zero usable capacity
    assert not shelter_change([snap("a", usable=0)], [snap("a", usable=0)]).crossed


# ---- record_trigger ----------------------------------------------------------------------------


class FakeEngine:
    """Postgres stand-in for the trigger table; records the statement order."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.rows: list[dict[str, Any]] = []

    @contextmanager
    def begin(self) -> Iterator[FakeConnection]:
        yield FakeConnection(self)


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def execute(self, statement: Any, parameters: dict[str, Any]) -> Any:
        sql = str(statement)
        self.engine.statements.append(sql)
        if "pg_advisory_xact_lock" in sql:
            return None
        if sql.lstrip().startswith("SELECT id FROM triggers"):
            leaders = sorted(
                (
                    row
                    for row in self.engine.rows
                    if row["incident_id"] == parameters["incident_id"]
                    and row["type"] == parameters["type"]
                    and row["coalesced_into"] is None
                    and row["detected_at"] > parameters["cutoff"]
                ),
                key=lambda row: row["detected_at"],
            )
            first = (leaders[0]["id"],) if leaders else None
            return type("Result", (), {"first": lambda self: first})()
        assert sql.lstrip().startswith("INSERT INTO triggers")
        self.engine.rows.append(dict(parameters))
        return None


def record(engine: FakeEngine, clock: SimClock, incident_id, trigger_type="perimeter_change"):
    return record_trigger(
        engine,  # type: ignore[arg-type]
        incident_id=str(incident_id),
        trigger_type=trigger_type,
        details={"iou": 0.5},
        clock=clock,
        debounce_s=300,
    )


def test_record_trigger_sql_order_and_parameters() -> None:
    engine, clock, incident = FakeEngine(), SimClock(T0), uuid4()

    result = record(engine, clock, incident)

    assert result.coalesced_into is None
    lock, leader, insert = engine.statements
    assert "pg_advisory_xact_lock" in lock and "hashtext" in lock
    assert "coalesced_into IS NULL" in leader and "ORDER BY detected_at" in leader
    assert "incident_id = :incident_id" in leader and "CAST(:type AS trigger_type)" in leader
    assert "CAST(:type AS trigger_type)" in insert and "CAST(:details AS jsonb)" in insert
    row = engine.rows[0]
    assert row["detected_at"] == T0  # injected clock, not the database clock
    assert json.loads(row["details"]) == {"iou": 0.5}


def test_debounce_boundary_299_coalesces_and_301_starts_a_new_leader() -> None:
    engine, clock, incident = FakeEngine(), SimClock(T0), uuid4()
    leader = record(engine, clock, incident)

    clock.advance(timedelta(seconds=299))
    inside = record(engine, clock, incident)
    assert inside.coalesced_into == leader.trigger_id

    clock.advance(timedelta(seconds=2))  # 301 s after the leader
    outside = record(engine, clock, incident)
    assert outside.coalesced_into is None
    assert outside.trigger_id != leader.trigger_id


def test_window_is_anchored_on_the_first_trigger_and_scoped_per_incident_and_type() -> None:
    engine, clock, incident = FakeEngine(), SimClock(T0), uuid4()
    leader = record(engine, clock, incident)
    clock.advance(timedelta(seconds=200))
    assert record(engine, clock, incident).coalesced_into == leader.trigger_id
    clock.advance(timedelta(seconds=150))  # 350 s after the leader, 150 s after the last one
    assert record(engine, clock, incident).coalesced_into is None

    other_type = record(engine, clock, incident, "road_blocked")
    other_incident = record(engine, clock, uuid4())
    assert other_type.coalesced_into is None
    assert other_incident.coalesced_into is None


@pytest.mark.parametrize("trigger_type", ["wind_shift", "manual", "scheduled_refresh", "bogus"])
def test_record_trigger_rejects_other_types_before_any_sql(trigger_type: str) -> None:
    engine = FakeEngine()
    with pytest.raises(ValueError):
        record(engine, SimClock(T0), uuid4(), trigger_type)
    assert engine.statements == []

"""Offline tests for the planning repository: fake connection for SQL order, dicts for semantics."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from coordinator.planning.finalize import finalize_plan
from coordinator.repository import (
    CapacityRecheckFailed,
    InMemoryPlanningRepository,
    SqlPlanningRepository,
    StateVersionConflict,
    shared_state_for,
)
from plan_factory import NOW, failed_draft, failing, freshness, provenance, valid_draft, valid_until
from wildfire_core.schemas.plan import IntegratedPlan, SettlementRecord, ShelterRecord

INCIDENT = str(uuid4())
NAMES = ["Mudumalai", "Kargudi", "Gudalur School", "Masinagudi Hall"]


def make_plan(*, failed: bool = False, incident_id: str = INCIDENT) -> IntegratedPlan:
    draft = (
        failed_draft(reasons=["V5 group_unassigned"], results=[failing("V5", "x", "y")])
        if failed
        else valid_draft()
    )
    plan = finalize_plan(
        draft,
        rationale=None,
        registry_names=NAMES,
        freshness=freshness(),
        provenance=provenance(hotspot_ids=("h1",), fire_run_ids=("fr1",)),
        created_at=NOW,
        valid_until=valid_until(),
        is_simulated=True,
    )
    return plan.model_copy(update={"incident_id": incident_id})


class FakeResult:
    def __init__(self, *, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.scalar

    def scalar_one_or_none(self) -> Any:
        return self.scalar


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def execute(self, statement: Any, parameters: Any = None) -> FakeResult:
        sql = " ".join(str(statement).split())
        self.engine.log.append((sql, parameters))
        if "pg_advisory_xact_lock" in sql:
            return FakeResult()
        if "SELECT state_version FROM incidents" in sql:
            return FakeResult(scalar=self.engine.state_version)
        if "FROM shelters" in sql:
            return FakeResult(rows=self.engine.shelter_rows)
        if "SELECT COALESCE(MAX(version)" in sql:
            return FakeResult(scalar=self.engine.next_version)
        if "INSERT INTO plan_versions" in sql:
            return FakeResult()
        if "UPDATE plan_versions SET status" in sql:
            return FakeResult(rows=[(item,) for item in self.engine.superseded])
        if "UPDATE incidents" in sql:
            return FakeResult(scalar=self.engine.state_version + 1)
        if "INSERT INTO shared_state_snapshots" in sql:
            return FakeResult()
        raise AssertionError(f"Unexpected SQL: {sql}")

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class FakeEngine:
    def __init__(self, *, state_version: int = 0, occupancy: tuple[int, int] = (0, 0)) -> None:
        self.state_version = state_version
        self.next_version = 2
        self.superseded: list[str] = [str(uuid4())]
        self.log: list[tuple[str, Any]] = []
        # valid_draft assigns 120 persons to s0 and 80 to s1; usable capacity is persons + 50
        self.shelter_rows = [
            {
                "id": "s0",
                "capacity": 400,
                "usable_factor": 0.5,
                "occupancy": occupancy[0],
                "is_active": True,
            },
            {
                "id": "s1",
                "capacity": 400,
                "usable_factor": 0.5,
                "occupancy": occupancy[1],
                "is_active": True,
            },
        ]

    @contextmanager
    def begin(self) -> Any:
        yield FakeConnection(self)

    @contextmanager
    def connect(self) -> Any:
        yield FakeConnection(self)

    def statements(self) -> list[str]:
        return [sql for sql, _ in self.log]

    def params_for(self, fragment: str) -> dict[str, Any]:
        return next(params for sql, params in self.log if fragment in sql)


def repo_for(engine: FakeEngine) -> SqlPlanningRepository:
    return SqlPlanningRepository(engine, default_factor=0.6)  # type: ignore[arg-type]


def test_persist_takes_advisory_lock_before_reading_max_version_and_writes_all_columns() -> None:
    engine = FakeEngine()
    parent = str(uuid4())
    trigger = str(uuid4())
    plan = make_plan()

    result = repo_for(engine).persist_plan(
        plan,
        expected_state_version=0,
        parent_plan_id=parent,
        trigger_id=trigger,
        diff={"is_material": True},
    )

    statements = engine.statements()
    lock = next(i for i, sql in enumerate(statements) if "pg_advisory_xact_lock" in sql)
    state = next(i for i, sql in enumerate(statements) if "FOR UPDATE" in sql)
    capacity = next(i for i, sql in enumerate(statements) if "FOR SHARE" in sql)
    maximum = next(i for i, sql in enumerate(statements) if "MAX(version)" in sql)
    insert = next(i for i, sql in enumerate(statements) if "INSERT INTO plan_versions" in sql)
    supersede = next(i for i, sql in enumerate(statements) if "SET status = 'superseded'" in sql)
    bump = next(i for i, sql in enumerate(statements) if "SET state_version" in sql)
    snapshot = next(i for i, sql in enumerate(statements) if "shared_state_snapshots" in sql)
    assert lock < state < capacity < maximum < insert < supersede < bump < snapshot

    params = engine.params_for("INSERT INTO plan_versions")
    assert str(params["parent_plan_id"]) == parent
    assert str(params["trigger_id"]) == trigger
    assert params["status"] == "pending_review"
    assert params["version"] == 2
    assert params["plan_schema_version"] == "3.0"
    assert params["state_version"] == 0
    assert len(json.loads(params["validation"])) == 8
    assert json.loads(params["freshness"]) and json.loads(params["provenance"])
    assert json.loads(params["diff"]) == {"is_material": True}
    assert params["valid_until"] == plan.valid_until
    stored = json.loads(params["plan_data"])
    assert stored["version"] == 2 and stored["parent_plan_id"] == parent

    assert result.version == 2 and result.parent_plan_id == parent
    assert result.state_version == 1
    assert result.superseded_plan_ids == tuple(engine.superseded)
    snapshot_state = json.loads(engine.params_for("shared_state_snapshots")["state"])
    assert snapshot_state["version"] == 1


def test_stale_state_version_raises_before_any_write() -> None:
    engine = FakeEngine(state_version=5)

    with pytest.raises(StateVersionConflict) as caught:
        repo_for(engine).persist_plan(
            make_plan(), expected_state_version=4, parent_plan_id=None, trigger_id=None, diff=None
        )

    assert (caught.value.expected, caught.value.actual) == (4, 5)
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql in engine.statements())


def test_capacity_overflow_raises_before_insert() -> None:
    # s0 usable = floor(400 x 0.5) = 200, occupancy 100 leaves 100 < 120 assigned
    engine = FakeEngine(occupancy=(100, 0))

    with pytest.raises(CapacityRecheckFailed) as caught:
        repo_for(engine).persist_plan(
            make_plan(), expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
        )

    assert any("s0" in item and "120" in item for item in caught.value.violations)
    assert not any("INSERT" in sql for sql in engine.statements())


def test_inactive_shelter_fails_recheck_and_failed_plan_skips_it() -> None:
    engine = FakeEngine()
    engine.shelter_rows[1]["is_active"] = False
    with pytest.raises(CapacityRecheckFailed, match="inactive"):
        repo_for(engine).persist_plan(
            make_plan(), expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
        )

    # a failed plan has no assignments, so no shelter lock query and persists as planning
    engine = FakeEngine()
    repo_for(engine).persist_plan(
        make_plan(failed=True),
        expected_state_version=0,
        parent_plan_id=None,
        trigger_id=None,
        diff=None,
    )
    assert not any("FOR SHARE" in sql for sql in engine.statements())
    assert engine.params_for("UPDATE incidents")["incident_status"] == "planning"
    assert engine.params_for("INSERT INTO plan_versions")["status"] == "failed"


# ---- in-memory semantics -----------------------------------------------------------------


def seeded_memory() -> InMemoryPlanningRepository:
    repo = InMemoryPlanningRepository(default_factor=0.5)
    repo.add_incident(INCIDENT)
    for shelter_id, name in (("s0", "Gudalur School"), ("s1", "Masinagudi Hall")):
        repo.add_shelter(
            ShelterRecord(
                shelter_id=shelter_id,
                external_ref=f"ref-{shelter_id}",
                name=name,
                kind="school",
                lat=11.7,
                lon=76.6,
                capacity=400,
                occupancy=0,
                capacity_source="synthetic",
            )
        )
    return repo


def test_in_memory_versions_parent_supersede_and_state_version() -> None:
    repo = seeded_memory()

    first = repo.persist_plan(
        make_plan(), expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
    )
    second = repo.persist_plan(
        make_plan(),
        expected_state_version=1,
        parent_plan_id=first.plan_id,
        trigger_id=None,
        diff={"is_material": True},
    )

    assert (first.version, second.version) == (1, 2)
    assert (first.state_version, second.state_version) == (1, 2)
    assert second.superseded_plan_ids == (first.plan_id,)
    stored = {item.plan_id: item for item in repo.plans[INCIDENT]}
    assert stored[first.plan_id].status == "superseded"
    assert stored[second.plan_id].plan_data["parent_plan_id"] == first.plan_id
    latest = repo.latest_plan(INCIDENT)
    assert latest is not None and latest.plan_id == second.plan_id
    assert [snap.version for snap in repo.snapshots[INCIDENT]] == [1, 2]
    assert repo.incident_context(INCIDENT).status == "awaiting_review"


def test_in_memory_rejects_stale_state_and_overbooking() -> None:
    repo = seeded_memory()
    repo.persist_plan(
        make_plan(), expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
    )
    with pytest.raises(StateVersionConflict):
        repo.persist_plan(
            make_plan(), expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
        )

    repo.update_occupancy("s0", 100)  # usable 200, only 100 free < 120 assigned
    with pytest.raises(CapacityRecheckFailed):
        repo.persist_plan(
            make_plan(), expected_state_version=1, parent_plan_id=None, trigger_id=None, diff=None
        )
    assert len(repo.plans[INCIDENT]) == 1 and repo.incident_context(INCIDENT).state_version == 1


def test_in_memory_failed_plan_sets_planning_and_is_latest() -> None:
    repo = seeded_memory()
    result = repo.persist_plan(
        make_plan(failed=True),
        expected_state_version=0,
        parent_plan_id=None,
        trigger_id=None,
        diff=None,
    )
    latest = repo.latest_plan(INCIDENT)
    assert latest is not None and latest.status == "failed" and latest.version == result.version
    assert repo.incident_context(INCIDENT).status == "planning"


def test_in_memory_hotspots_union_weather_and_trigger_handling() -> None:
    repo = seeded_memory()
    t0 = NOW - timedelta(minutes=30)
    first = repo.add_hotspots(
        INCIDENT, [{"id": "h1", "lat": 11.72, "lon": 76.64, "frp": 10.0, "acq_datetime": t0}]
    )
    repo.add_hotspots(
        INCIDENT,
        [{"id": "h2", "lat": 11.73, "lon": 76.65, "acq_datetime": t0 - timedelta(hours=1)}],
    )
    repo.add_hotspots(
        INCIDENT, [{"id": "h3", "lat": 0, "lon": 0, "acq_datetime": t0}], coalesced=True
    )

    rows = repo.incident_hotspots(INCIDENT)
    assert [row["id"] for row in rows] == ["h2", "h1"]  # union of triggers, ordered, no coalesced
    assert repo.latest_hotspot_time(["h1", "h2"]) == t0
    assert repo.latest_hotspot_time([]) is None

    repo.add_weather_point(11.72, 76.64, valid_time=NOW - timedelta(minutes=10), wind_speed_ms=5.0)
    repo.add_weather_point(11.72, 76.64, valid_time=NOW + timedelta(hours=1))  # future: ignored
    snapshot = repo.weather_for(11.72, 76.64, origin="simulated", provider="open_meteo", now=NOW)
    assert snapshot.wind_speed_ms == 5.0 and not snapshot.is_stale
    with pytest.raises(LookupError):
        repo.weather_for(11.72, 76.64, origin="live", provider="open_meteo", now=NOW)

    entry = {"entry_id": str(uuid4()), "incident_id": INCIDENT}
    with pytest.raises(LookupError):
        repo.mark_trigger_handled(first, entry["entry_id"])  # audit row not flushed yet
    repo.flush_audit([entry])
    repo.flush_audit([entry])  # idempotent
    repo.mark_trigger_handled(first, entry["entry_id"])
    assert len(repo.audit_entries) == 1


def test_in_memory_registry_reads_are_sorted() -> None:
    repo = seeded_memory()
    repo.add_settlement(
        SettlementRecord(
            settlement_id="b", external_ref="B", name="B", lat=11.7, lon=76.6, buffer_m=500
        )
    )
    repo.add_settlement(
        SettlementRecord(
            settlement_id="a", external_ref="A", name="A", lat=11.7, lon=76.6, buffer_m=500
        )
    )
    repo.set_edge_status(1, 2, 0, "blocked")

    assert [item.settlement_id for item in repo.settlements()] == ["a", "b"]
    assert [item.shelter_id for item in repo.shelters()] == ["s0", "s1"]
    assert repo.edge_statuses(datetime.now(UTC)) == {(1, 2, 0): "blocked"}


def test_shared_state_for_references_inputs() -> None:
    state = shared_state_for(make_plan(), 3)
    assert state.version == 3
    assert {(item.kind, item.identifier) for item in state.references} == {
        ("hotspot", "h1"),
        ("fire_run", "fr1"),
    }

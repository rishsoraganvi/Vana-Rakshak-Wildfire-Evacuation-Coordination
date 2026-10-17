"""Planning persistence behind one interface (PLAN-08, RESEARCH Pitfall 9).

Every coordinator database access goes through ``PlanningRepository``. ``SqlPlanningRepository``
is the only place coordinator SQL lives; ``InMemoryPlanningRepository`` implements the same
semantics with dicts so offline tests and replays fake functions, not SQL strings.

``persist_plan`` is the single writer of ``plan_versions``. It runs in one transaction, serialised
per incident by ``pg_advisory_xact_lock``, checks the optimistic ``incidents.state_version``,
re-checks shelter capacity (Rules 6), assigns ``MAX(version) + 1``, supersedes earlier
non-terminal versions
with a status-only update (the immutability trigger allows nothing else) and writes a shared-state
snapshot.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from agent_shelter.registry import fetch_shelters, usable_capacity
from agent_weather.agent import _STALE_AFTER_MIN, DEFAULT_MAX_DISTANCE_KM, get_weather_snapshot
from sqlalchemy import Engine, bindparam, text
from wildfire_core.db.repositories import current_edge_statuses
from wildfire_core.schemas.phase2 import WeatherSnapshot
from wildfire_core.schemas.plan import IntegratedPlan, SettlementRecord, ShelterRecord
from wildfire_core.schemas.state import SharedState, StateReference

from coordinator.audit import flush_audit_entries

_NON_TERMINAL = ("draft", "pending_review", "failed")
_KM_PER_DEGREE = 111.32


@dataclass(frozen=True)
class IncidentContext:
    origin: str
    state_version: int
    status: str


@dataclass(frozen=True)
class StoredPlan:
    plan_id: str
    version: int
    status: str
    plan_data: dict[str, Any]


@dataclass(frozen=True)
class PersistResult:
    plan_id: str
    version: int
    parent_plan_id: str | None
    superseded_plan_ids: tuple[str, ...]
    state_version: int


class StateVersionConflict(Exception):
    """The incident's shared state moved since the plan was built (optimistic check)."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"incident state_version is {actual}, plan was built on {expected}")
        self.expected = expected
        self.actual = actual


class CapacityRecheckFailed(Exception):
    """Shelter occupancy changed so that the plan's assignments no longer fit."""

    def __init__(self, violations: Sequence[str]) -> None:
        self.violations = tuple(violations)
        super().__init__("capacity re-check failed: " + "; ".join(self.violations))


class PlanningRepository(Protocol):
    def incident_context(self, incident_id: str) -> IncidentContext: ...

    def incident_hotspots(self, incident_id: str) -> list[dict[str, Any]]: ...

    def latest_hotspot_time(self, hotspot_ids: Sequence[str]) -> datetime | None: ...

    def weather_for(
        self,
        lat: float,
        lon: float,
        *,
        origin: str | None,
        provider: str | None,
        now: datetime | None = None,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    ) -> WeatherSnapshot: ...

    def settlements(self) -> list[SettlementRecord]: ...

    def shelters(self) -> list[ShelterRecord]: ...

    def edge_statuses(self, now: datetime) -> dict[tuple[int, int, int], str]: ...

    def latest_plan(self, incident_id: str) -> StoredPlan | None: ...

    def persist_plan(
        self,
        plan: IntegratedPlan,
        *,
        expected_state_version: int,
        parent_plan_id: str | None,
        trigger_id: str | None,
        diff: dict[str, Any] | None,
    ) -> PersistResult: ...

    def flush_audit(self, entries: Sequence[dict[str, Any]]) -> None: ...

    def mark_trigger_handled(self, trigger_id: str, handled_entry_id: str) -> None: ...


# --------------------------------------------------------------------------------------------
# Shared pure helpers
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ShelterState:
    """Locked shelter facts used by the in-transaction capacity re-check."""

    capacity: int
    usable_factor: float | Decimal | None
    occupancy: int
    is_active: bool


def capacity_violations(
    plan: IntegratedPlan,
    states: Mapping[str, ShelterState],
    default_factor: float,
) -> tuple[str, ...]:
    """Readable reasons why the plan's assignments no longer fit (empty when they still do)."""
    if plan.status != "pending_review":
        return ()
    assigned: dict[str, int] = defaultdict(int)
    for assignment in plan.shelter_assignments:
        assigned[assignment.shelter_id] += assignment.persons
    violations: list[str] = []
    for shelter_id in sorted(assigned):
        state = states.get(shelter_id)
        if state is None:
            violations.append(f"shelter {shelter_id} no longer exists")
            continue
        if not state.is_active:
            violations.append(f"shelter {shelter_id} is inactive")
            continue
        usable = usable_capacity(state.capacity, state.usable_factor, default_factor)
        available = max(0, usable - state.occupancy)
        if assigned[shelter_id] > available:
            violations.append(
                f"shelter {shelter_id}: {assigned[shelter_id]} persons assigned but only "
                f"{available} available (usable {usable}, occupancy {state.occupancy})"
            )
    return tuple(violations)


def shared_state_for(plan: IntegratedPlan, state_version: int) -> SharedState:
    """Shared state by reference (Rules 2.7): ids of the inputs the plan was built on."""
    references: list[StateReference] = [
        StateReference(kind="hotspot", identifier=hotspot_id)
        for hotspot_id in plan.provenance.hotspot_ids
    ]
    references.extend(
        StateReference(kind="fire_run", identifier=run_id)
        for run_id in plan.provenance.fire_run_ids
    )
    return SharedState(
        incident_id=plan.incident_id,
        version=state_version,
        references=tuple(references),
    )


def _plan_json(final: IntegratedPlan) -> str:
    return json.dumps(final.model_dump(mode="json"), sort_keys=True)


def _incident_status_for(plan: IntegratedPlan) -> str:
    return "awaiting_review" if plan.status == "pending_review" else "planning"


def _loads(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


# --------------------------------------------------------------------------------------------
# SQL implementation
# --------------------------------------------------------------------------------------------

_INCIDENT_CONTEXT_SQL = """
    SELECT origin::text AS origin, state_version, status::text AS status
    FROM incidents WHERE id = :incident_id
"""

_INCIDENT_HOTSPOTS_SQL = """
    SELECT h.id::text AS id, h.lat, h.lon, h.frp, h.acq_datetime
    FROM hotspots h
    WHERE h.id IN (
        SELECT CAST(jsonb_array_elements_text(t.details -> 'hotspot_ids') AS uuid)
        FROM triggers t
        WHERE t.incident_id = :incident_id
          AND t.type = 'new_hotspot'
          AND t.coalesced_into IS NULL
    )
    ORDER BY h.acq_datetime, h.id
"""

_SETTLEMENTS_SQL = """
    SELECT id::text AS settlement_id, external_ref, name, kind,
           ST_Y(geom) AS lat, ST_X(geom) AS lon, population, pop_source, buffer_m, is_simulated
    FROM settlements
    ORDER BY external_ref, id
"""

_LATEST_PLAN_SQL = """
    SELECT id::text AS plan_id, version, status::text AS status, plan_data
    FROM plan_versions
    WHERE incident_id = :incident_id AND status IN ('draft', 'pending_review', 'failed')
    ORDER BY version DESC
    LIMIT 1
"""

_LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext(CAST(:incident_id AS text)))"

_STATE_VERSION_SQL = "SELECT state_version FROM incidents WHERE id = :incident_id FOR UPDATE"

_LOCK_SHELTERS_SQL = """
    SELECT CAST(id AS text) AS id, capacity, usable_factor, occupancy, is_active
    FROM shelters
    WHERE CAST(id AS text) IN :ids
    FOR SHARE
"""

_NEXT_VERSION_SQL = (
    "SELECT COALESCE(MAX(version), 0) + 1 FROM plan_versions WHERE incident_id = :incident_id"
)

_INSERT_PLAN_SQL = """
    INSERT INTO plan_versions
        (id, incident_id, version, status, rationale_md, is_llm_fallback, is_simulated,
         warnings, plan_data, parent_plan_id, trigger_id, state_version, plan_schema_version,
         validation, freshness, provenance, diff, used_fallback, valid_until)
    VALUES
        (:plan_id, :incident_id, :version, CAST(:status AS plan_status), :rationale,
         :is_fallback, :is_simulated, CAST(:warnings AS jsonb), CAST(:plan_data AS jsonb),
         :parent_plan_id, :trigger_id, :state_version, :plan_schema_version,
         CAST(:validation AS jsonb), CAST(:freshness AS jsonb), CAST(:provenance AS jsonb),
         CAST(:diff AS jsonb), :used_fallback, :valid_until)
"""

_SUPERSEDE_SQL = """
    UPDATE plan_versions SET status = 'superseded'
    WHERE incident_id = :incident_id
      AND id <> :new_id
      AND status IN ('draft', 'pending_review', 'failed')
    RETURNING id
"""

_BUMP_STATE_SQL = """
    UPDATE incidents
    SET state_version = state_version + 1,
        status = CAST(:incident_status AS incident_status)
    WHERE id = :incident_id
    RETURNING state_version
"""

_INSERT_SNAPSHOT_SQL = """
    INSERT INTO shared_state_snapshots (incident_id, version, state)
    VALUES (:incident_id, :version, CAST(:state AS jsonb))
"""

_MARK_TRIGGER_SQL = "UPDATE triggers SET handled_run_id = :entry_id WHERE id = :trigger_id"


class SqlPlanningRepository:
    """Postgres implementation. All parameters are bound; ids are typed as UUID (T-03-08-06)."""

    def __init__(self, engine: Engine, *, default_factor: float | None = None) -> None:
        self._engine = engine
        self._default_factor = default_factor

    def _factor(self) -> float:
        if self._default_factor is None:
            from wildfire_core.config import load_settings

            self._default_factor = load_settings().shelter_usable_factor
        return self._default_factor

    def incident_context(self, incident_id: str) -> IncidentContext:
        with self._engine.connect() as connection:
            row = (
                connection.execute(text(_INCIDENT_CONTEXT_SQL), {"incident_id": UUID(incident_id)})
                .mappings()
                .first()
            )
        if row is None:
            raise LookupError(f"incident {incident_id} not found")
        return IncidentContext(
            origin=str(row["origin"]),
            state_version=int(row["state_version"]),
            status=str(row["status"]),
        )

    def incident_hotspots(self, incident_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(text(_INCIDENT_HOTSPOTS_SQL), {"incident_id": UUID(incident_id)})
                .mappings()
                .all()
            )
        return [
            {
                "id": str(row["id"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "frp": float(row["frp"]) if row["frp"] is not None else None,
                "acq_datetime": row["acq_datetime"],
            }
            for row in rows
        ]

    def latest_hotspot_time(self, hotspot_ids: Sequence[str]) -> datetime | None:
        if not hotspot_ids:
            return None
        statement = text(
            "SELECT max(acq_datetime) FROM hotspots WHERE CAST(id AS text) IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        with self._engine.connect() as connection:
            result = connection.execute(statement, {"ids": [str(item) for item in hotspot_ids]})
            value = result.scalar_one_or_none()
        return value if isinstance(value, datetime) else None

    def weather_for(
        self,
        lat: float,
        lon: float,
        *,
        origin: str | None,
        provider: str | None,
        now: datetime | None = None,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    ) -> WeatherSnapshot:
        return get_weather_snapshot(
            lat,
            lon,
            self._engine,
            origin=origin,
            provider=provider,
            max_distance_km=max_distance_km,
            now=now,
        )

    def settlements(self) -> list[SettlementRecord]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_SETTLEMENTS_SQL)).mappings().all()
        return [
            SettlementRecord(
                settlement_id=str(row["settlement_id"]),
                external_ref=row["external_ref"],
                name=row["name"],
                kind=row["kind"],
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                population=None if row["population"] is None else int(row["population"]),
                pop_source=row["pop_source"],
                buffer_m=int(row["buffer_m"]),
                is_simulated=bool(row["is_simulated"]),
            )
            for row in rows
        ]

    def shelters(self) -> list[ShelterRecord]:
        return fetch_shelters(self._engine)

    def edge_statuses(self, now: datetime) -> dict[tuple[int, int, int], str]:
        return current_edge_statuses(self._engine, now)

    def latest_plan(self, incident_id: str) -> StoredPlan | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(text(_LATEST_PLAN_SQL), {"incident_id": UUID(incident_id)})
                .mappings()
                .first()
            )
        if row is None:
            return None
        return StoredPlan(
            plan_id=str(row["plan_id"]),
            version=int(row["version"]),
            status=str(row["status"]),
            plan_data=dict(_loads(row["plan_data"])),
        )

    def persist_plan(
        self,
        plan: IntegratedPlan,
        *,
        expected_state_version: int,
        parent_plan_id: str | None,
        trigger_id: str | None,
        diff: dict[str, Any] | None,
    ) -> PersistResult:
        incident_uuid = UUID(plan.incident_id)
        plan_uuid = UUID(plan.plan_id)
        parent_uuid = UUID(parent_plan_id) if parent_plan_id is not None else None
        trigger_uuid = UUID(trigger_id) if trigger_id is not None else None

        with self._engine.begin() as connection:
            # (1) serialise every persist for this incident
            connection.execute(text(_LOCK_SQL), {"incident_id": str(incident_uuid)})

            # (2) optimistic shared-state check, before any write
            actual = connection.execute(
                text(_STATE_VERSION_SQL), {"incident_id": incident_uuid}
            ).scalar_one_or_none()
            if actual is None:
                raise LookupError(f"incident {plan.incident_id} not found")
            if int(actual) != expected_state_version:
                raise StateVersionConflict(expected_state_version, int(actual))

            # (3) in-transaction capacity re-check (Rules 6)
            if plan.status == "pending_review" and plan.shelter_assignments:
                shelter_ids = sorted({item.shelter_id for item in plan.shelter_assignments})
                statement = text(_LOCK_SHELTERS_SQL).bindparams(bindparam("ids", expanding=True))
                rows = connection.execute(statement, {"ids": shelter_ids}).mappings().all()
                states = {
                    str(row["id"]): ShelterState(
                        capacity=int(row["capacity"]),
                        usable_factor=row["usable_factor"],
                        occupancy=int(row["occupancy"]),
                        is_active=bool(row["is_active"]),
                    )
                    for row in rows
                }
                violations = capacity_violations(plan, states, self._factor())
                if violations:
                    raise CapacityRecheckFailed(violations)

            # (4) next version, safe under the advisory lock
            version = int(
                connection.execute(
                    text(_NEXT_VERSION_SQL), {"incident_id": incident_uuid}
                ).scalar_one()
            )

            # (5) immutable row
            final = plan.model_copy(update={"version": version, "parent_plan_id": parent_plan_id})
            connection.execute(
                text(_INSERT_PLAN_SQL),
                {
                    "plan_id": plan_uuid,
                    "incident_id": incident_uuid,
                    "version": version,
                    "status": final.status,
                    "rationale": final.rationale_md,
                    "is_fallback": final.is_llm_fallback,
                    "is_simulated": final.is_simulated,
                    "warnings": json.dumps(list(final.warnings)),
                    "plan_data": _plan_json(final),
                    "parent_plan_id": parent_uuid,
                    "trigger_id": trigger_uuid,
                    "state_version": expected_state_version,
                    "plan_schema_version": final.plan_schema_version,
                    "validation": json.dumps(
                        [item.model_dump(mode="json") for item in final.validation],
                        sort_keys=True,
                    ),
                    "freshness": json.dumps(
                        final.freshness.model_dump(mode="json"), sort_keys=True
                    ),
                    "provenance": json.dumps(
                        final.provenance.model_dump(mode="json"), sort_keys=True
                    ),
                    "diff": json.dumps(diff, sort_keys=True) if diff is not None else None,
                    "used_fallback": final.used_fallback,
                    "valid_until": final.valid_until,
                },
            )

            # (6) supersede earlier non-terminal versions: a status-only update
            superseded = tuple(
                str(row[0])
                for row in connection.execute(
                    text(_SUPERSEDE_SQL), {"incident_id": incident_uuid, "new_id": plan_uuid}
                ).all()
            )

            # (7) bump the shared state version and incident status
            new_state_version = int(
                connection.execute(
                    text(_BUMP_STATE_SQL),
                    {
                        "incident_id": incident_uuid,
                        "incident_status": _incident_status_for(final),
                    },
                ).scalar_one()
            )

            # (8) shared-state snapshot for the new version
            connection.execute(
                text(_INSERT_SNAPSHOT_SQL),
                {
                    "incident_id": incident_uuid,
                    "version": new_state_version,
                    "state": shared_state_for(final, new_state_version).model_dump_json(),
                },
            )

        return PersistResult(
            plan_id=str(plan_uuid),
            version=version,
            parent_plan_id=parent_plan_id,
            superseded_plan_ids=superseded,
            state_version=new_state_version,
        )

    def flush_audit(self, entries: Sequence[dict[str, Any]]) -> None:
        if not entries:
            return
        with self._engine.begin() as connection:
            flush_audit_entries(entries, connection)

    def mark_trigger_handled(self, trigger_id: str, handled_entry_id: str) -> None:
        """Link a trigger to the audit row (agent_runs.id) that handled it; flush audit first."""
        with self._engine.begin() as connection:
            connection.execute(
                text(_MARK_TRIGGER_SQL),
                {"trigger_id": UUID(trigger_id), "entry_id": UUID(handled_entry_id)},
            )


# --------------------------------------------------------------------------------------------
# In-memory implementation
# --------------------------------------------------------------------------------------------


@dataclass
class _Incident:
    origin: str
    state_version: int
    status: str


@dataclass
class _WeatherPoint:
    lat: float
    lon: float
    origin: str
    provider: str
    valid_time: datetime
    wind_speed_ms: float
    wind_dir_deg: float
    rh_pct: float
    temperature_c: float


@dataclass
class _PlanExtras:
    parent_plan_id: str | None
    trigger_id: str | None
    state_version: int
    diff: dict[str, Any] | None


@dataclass
class InMemoryPlanningRepository:
    """Dict-backed repository with the same semantics as ``SqlPlanningRepository``.

    Production code (replays, offline demos, graph tests), not a test double hidden in tests/.
    """

    default_factor: float = 0.6
    incidents: dict[str, _Incident] = field(default_factory=dict)
    hotspot_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    triggers: dict[str, dict[str, Any]] = field(default_factory=dict)
    weather_points: list[_WeatherPoint] = field(default_factory=list)
    settlement_rows: dict[str, SettlementRecord] = field(default_factory=dict)
    shelter_rows: dict[str, ShelterRecord] = field(default_factory=dict)
    edge_status_rows: dict[tuple[int, int, int], str] = field(default_factory=dict)
    plans: dict[str, list[StoredPlan]] = field(default_factory=dict)
    plan_extras: dict[str, _PlanExtras] = field(default_factory=dict)
    snapshots: dict[str, list[SharedState]] = field(default_factory=dict)
    audit_entries: list[dict[str, Any]] = field(default_factory=list)

    # ---- seeding helpers -------------------------------------------------------------------

    def add_incident(
        self,
        incident_id: str,
        *,
        origin: str = "simulated",
        state_version: int = 0,
        status: str = "open",
    ) -> None:
        self.incidents[incident_id] = _Incident(origin, state_version, status)
        self.plans.setdefault(incident_id, [])
        self.snapshots.setdefault(incident_id, [])

    def add_hotspots(
        self,
        incident_id: str,
        rows: Iterable[Mapping[str, Any]],
        *,
        trigger_id: str | None = None,
        coalesced: bool = False,
    ) -> str:
        """Store hotspot rows and a ``new_hotspot`` trigger listing them; returns the trigger id."""
        ids: list[str] = []
        for row in rows:
            stored = dict(row)
            stored["id"] = str(stored["id"])
            stored.setdefault("frp", None)
            self.hotspot_rows[stored["id"]] = stored
            ids.append(stored["id"])
        trigger = trigger_id or str(uuid.uuid4())
        self.triggers[trigger] = {
            "incident_id": incident_id,
            "hotspot_ids": ids,
            "coalesced": coalesced,
            "handled_entry_id": None,
        }
        return trigger

    def add_weather_point(
        self,
        lat: float,
        lon: float,
        *,
        origin: str = "simulated",
        provider: str = "open_meteo",
        valid_time: datetime,
        wind_speed_ms: float = 4.0,
        wind_dir_deg: float = 270.0,
        rh_pct: float = 40.0,
        temperature_c: float = 30.0,
    ) -> None:
        self.weather_points.append(
            _WeatherPoint(
                lat,
                lon,
                origin,
                provider,
                valid_time,
                wind_speed_ms,
                wind_dir_deg,
                rh_pct,
                temperature_c,
            )
        )

    def add_settlement(self, record: SettlementRecord) -> None:
        self.settlement_rows[record.settlement_id] = record

    def add_shelter(self, record: ShelterRecord) -> None:
        self.shelter_rows[record.shelter_id] = record

    def set_edge_status(self, u: int, v: int, key: int, status: str) -> None:
        self.edge_status_rows[(u, v, key)] = status

    def update_occupancy(self, shelter_id: str, occupancy: int) -> None:
        self.shelter_rows[shelter_id] = self.shelter_rows[shelter_id].model_copy(
            update={"occupancy": occupancy}
        )

    # ---- PlanningRepository ----------------------------------------------------------------

    def incident_context(self, incident_id: str) -> IncidentContext:
        incident = self._incident(incident_id)
        return IncidentContext(incident.origin, incident.state_version, incident.status)

    def incident_hotspots(self, incident_id: str) -> list[dict[str, Any]]:
        wanted: set[str] = set()
        for trigger in self.triggers.values():
            if trigger["incident_id"] == incident_id and not trigger["coalesced"]:
                wanted.update(trigger["hotspot_ids"])
        rows = [self.hotspot_rows[item] for item in wanted if item in self.hotspot_rows]
        rows.sort(key=lambda row: (row["acq_datetime"], row["id"]))
        return [dict(row) for row in rows]

    def latest_hotspot_time(self, hotspot_ids: Sequence[str]) -> datetime | None:
        times = [
            self.hotspot_rows[str(item)]["acq_datetime"]
            for item in hotspot_ids
            if str(item) in self.hotspot_rows
        ]
        return max(times) if times else None

    def weather_for(
        self,
        lat: float,
        lon: float,
        *,
        origin: str | None,
        provider: str | None,
        now: datetime | None = None,
        max_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    ) -> WeatherSnapshot:
        now_utc = now if now is not None else datetime.now(UTC)
        candidates: list[tuple[float, float, _WeatherPoint]] = []
        for point in self.weather_points:
            if point.valid_time > now_utc:
                continue
            if provider is not None and point.provider != provider:
                continue
            if origin is not None and point.origin != origin:
                continue
            distance_km = math.hypot(
                (point.lat - lat) * _KM_PER_DEGREE,
                (point.lon - lon) * _KM_PER_DEGREE * math.cos(math.radians(point.lat)),
            )
            if distance_km > max_distance_km:
                continue
            candidates.append((distance_km, -point.valid_time.timestamp(), point))
        if not candidates:
            raise LookupError(
                f"No complete weather observation within {max_distance_km} km of "
                f"({lat:.4f}, {lon:.4f}) for origin={origin!r}, provider={provider!r}"
            )
        point = min(candidates, key=lambda item: (item[0], item[1]))[2]
        age_min = (now_utc - point.valid_time).total_seconds() / 60.0
        is_stale = age_min > _STALE_AFTER_MIN
        return WeatherSnapshot(
            valid_time=point.valid_time,
            wind_speed_ms=point.wind_speed_ms,
            wind_dir_deg=point.wind_dir_deg,
            rh_pct=point.rh_pct,
            temperature_c=point.temperature_c,
            is_stale=is_stale,
            stale_age_min=int(age_min) if is_stale else None,
        )

    def settlements(self) -> list[SettlementRecord]:
        return sorted(
            self.settlement_rows.values(),
            key=lambda item: (item.external_ref or "", item.settlement_id),
        )

    def shelters(self) -> list[ShelterRecord]:
        return sorted(
            self.shelter_rows.values(), key=lambda item: (item.external_ref or "", item.shelter_id)
        )

    def edge_statuses(self, now: datetime) -> dict[tuple[int, int, int], str]:
        return dict(self.edge_status_rows)

    def latest_plan(self, incident_id: str) -> StoredPlan | None:
        live = [item for item in self.plans.get(incident_id, []) if item.status in _NON_TERMINAL]
        return max(live, key=lambda item: item.version) if live else None

    def persist_plan(
        self,
        plan: IntegratedPlan,
        *,
        expected_state_version: int,
        parent_plan_id: str | None,
        trigger_id: str | None,
        diff: dict[str, Any] | None,
    ) -> PersistResult:
        incident = self._incident(plan.incident_id)
        if incident.state_version != expected_state_version:
            raise StateVersionConflict(expected_state_version, incident.state_version)

        if plan.status == "pending_review" and plan.shelter_assignments:
            states = {
                shelter_id: ShelterState(
                    capacity=record.capacity,
                    usable_factor=record.usable_factor,
                    occupancy=record.occupancy,
                    is_active=record.is_active,
                )
                for shelter_id, record in self.shelter_rows.items()
            }
            violations = capacity_violations(plan, states, self.default_factor)
            if violations:
                raise CapacityRecheckFailed(violations)

        existing = self.plans.setdefault(plan.incident_id, [])
        version = max((item.version for item in existing), default=0) + 1
        final = plan.model_copy(update={"version": version, "parent_plan_id": parent_plan_id})

        superseded: list[str] = []
        for index, item in enumerate(existing):
            if item.status in _NON_TERMINAL:
                existing[index] = replace(item, status="superseded")
                superseded.append(item.plan_id)
        existing.append(
            StoredPlan(
                plan_id=final.plan_id,
                version=version,
                status=final.status,
                plan_data=json.loads(_plan_json(final)),
            )
        )
        self.plan_extras[final.plan_id] = _PlanExtras(
            parent_plan_id, trigger_id, expected_state_version, diff
        )

        incident.state_version += 1
        incident.status = _incident_status_for(final)
        self.snapshots.setdefault(plan.incident_id, []).append(
            shared_state_for(final, incident.state_version)
        )
        return PersistResult(
            plan_id=final.plan_id,
            version=version,
            parent_plan_id=parent_plan_id,
            superseded_plan_ids=tuple(superseded),
            state_version=incident.state_version,
        )

    def flush_audit(self, entries: Sequence[dict[str, Any]]) -> None:
        known = {entry["entry_id"] for entry in self.audit_entries}
        for entry in entries:
            if entry["entry_id"] not in known:  # ON CONFLICT (id) DO NOTHING
                self.audit_entries.append(dict(entry))
                known.add(entry["entry_id"])

    def mark_trigger_handled(self, trigger_id: str, handled_entry_id: str) -> None:
        if trigger_id not in self.triggers:
            raise LookupError(f"trigger {trigger_id} not found")
        if handled_entry_id not in {entry["entry_id"] for entry in self.audit_entries}:
            # mirrors the triggers.handled_run_id -> agent_runs(id) foreign key
            raise LookupError(f"audit entry {handled_entry_id} not flushed")
        self.triggers[trigger_id]["handled_entry_id"] = handled_entry_id

    def _incident(self, incident_id: str) -> _Incident:
        try:
            return self.incidents[incident_id]
        except KeyError:
            raise LookupError(f"incident {incident_id} not found") from None

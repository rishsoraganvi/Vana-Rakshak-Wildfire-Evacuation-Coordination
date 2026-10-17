"""Live proof of D-14/D-15 against Postgres: debounced triggers, version linking, handled audit.

Requires the Compose database at migration head (0006). The test creates its own incident and
removes every row it created in ``finally`` (versions, triggers, audit rows, snapshots, incident).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from coordinator.planning.diff import is_material_change, plan_diff
from coordinator.repository import SqlPlanningRepository
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from wildfire_core.clock import SimClock
from wildfire_core.schemas.phase2 import AuditEntry
from wildfire_core.schemas.plan import (
    ForecastFootprint,
    IntegratedPlan,
    PlanFreshness,
    PlanProvenance,
    ValidationResult,
)

load_dotenv()

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EMPTY = "POLYGON EMPTY"
DEBOUNCE_S = 300


def _engine():  # type: ignore[no-untyped-def]
    url = make_url(os.environ["DATABASE_URL"])
    if url.host == "localhost":  # IPv6 fallback adds ~200 s per connection on loopback binding
        url = url.set(host="127.0.0.1")
    return create_engine(url)


def _plan(incident_id: str, *, failed: bool, trigger_id: str | None = None) -> IntegratedPlan:
    common = {
        "incident_id": incident_id,
        "run_id": str(uuid4()),
        "valid_until": NOW + timedelta(hours=1),
        "freshness": PlanFreshness(computed_at=NOW, firms_age_min=10),
        "provenance": PlanProvenance(
            run_id="r",
            trigger_id=trigger_id,
            state_version=0,
            weather_provider="open_meteo",
            graph_source="osm",
            graph_node_count=1,
            graph_edge_count=1,
        ),
        "footprint": ForecastFootprint(
            current_wkt=EMPTY,
            p50_1h_wkt=EMPTY,
            p50_3h_wkt=EMPTY,
            p50_6h_wkt=EMPTY,
            p90_1h_wkt=EMPTY,
            p90_3h_wkt=EMPTY,
            p90_6h_wkt=EMPTY,
        ),
        "created_at": NOW,
        "rationale_md": "[DETERMINISTIC TEMPLATE] live re-plan test",
        "is_simulated": True,
    }
    if failed:
        return IntegratedPlan(
            status="failed",
            failure_reasons=("V5 group_unassigned: live test",),
            **common,  # type: ignore[arg-type]
        )
    return IntegratedPlan(
        status="pending_review",
        validation=tuple(
            ValidationResult(validator_id=f"V{i}", status="pass")  # type: ignore[arg-type]
            for i in range(1, 9)
        ),
        **common,  # type: ignore[arg-type]
    )


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_trigger_coalescing_version_link_and_handled_audit_live() -> None:
    engine = _engine()
    repo = SqlPlanningRepository(engine, default_factor=0.6)
    clock = SimClock(NOW)
    incident_id: str | None = None
    try:
        with engine.begin() as connection:
            incident_id = str(
                connection.execute(
                    text(
                        "INSERT INTO incidents (code, origin) "
                        "VALUES (:code, 'simulated') RETURNING id"
                    ),
                    {"code": f"TEST-RP-{uuid4().hex[:10]}"},
                ).scalar_one()
            )

        # two perimeter triggers 60 s apart coalesce; another type is its own leader
        leader = repo.record_trigger(
            incident_id, "perimeter_change", {"iou": 0.5}, clock.now_utc(), debounce_s=DEBOUNCE_S
        )
        clock.advance(timedelta(seconds=60))
        repeat = repo.record_trigger(
            incident_id, "perimeter_change", {"iou": 0.4}, clock.now_utc(), debounce_s=DEBOUNCE_S
        )
        other = repo.record_trigger(
            incident_id,
            "road_blocked",
            {"edges": [[1, 2, 0, "blocked"]]},
            clock.now_utc(),
            debounce_s=DEBOUNCE_S,
        )
        assert leader.coalesced_into is None
        assert repeat.coalesced_into == leader.trigger_id
        assert other.coalesced_into is None
        clock.advance(timedelta(seconds=241))  # 301 s after the leader: a new window
        fresh = repo.record_trigger(
            incident_id, "perimeter_change", {"iou": 0.3}, clock.now_utc(), debounce_s=DEBOUNCE_S
        )
        assert fresh.coalesced_into is None
        with pytest.raises(ValueError):
            repo.record_trigger(
                incident_id, "wind_shift", {}, clock.now_utc(), debounce_s=DEBOUNCE_S
            )

        with engine.connect() as connection:
            rows = {
                str(row["id"]): row
                for row in connection.execute(
                    text(
                        "SELECT id, type::text AS type, coalesced_into, detected_at, details "
                        "FROM triggers WHERE incident_id = :i"
                    ),
                    {"i": incident_id},
                ).mappings()
            }
        assert len(rows) == 4
        assert str(rows[repeat.trigger_id]["coalesced_into"]) == leader.trigger_id
        assert rows[leader.trigger_id]["detected_at"] == NOW
        assert rows[other.trigger_id]["type"] == "road_blocked"
        assert rows[other.trigger_id]["details"] == {"edges": [[1, 2, 0, "blocked"]]}

        # v1, then a materially different v2 linked to its parent and the leader trigger
        v1 = _plan(incident_id, failed=True)
        first = repo.persist_plan(
            v1, expected_state_version=0, parent_plan_id=None, trigger_id=None, diff=None
        )
        stored = repo.latest_plan(incident_id)
        assert stored is not None
        v2 = _plan(incident_id, failed=False, trigger_id=leader.trigger_id)
        assert is_material_change(stored.plan_data, v2)
        second = repo.persist_plan(
            v2,
            expected_state_version=1,
            parent_plan_id=first.plan_id,
            trigger_id=leader.trigger_id,
            diff=plan_diff(stored.plan_data, v2).model_dump(mode="json"),
        )
        assert (first.version, second.version) == (1, 2)
        with engine.connect() as connection:
            linked = (
                connection.execute(
                    text(
                        "SELECT status::text AS status, parent_plan_id, trigger_id, diff "
                        "FROM plan_versions WHERE id = :id"
                    ),
                    {"id": second.plan_id},
                )
                .mappings()
                .one()
            )
            first_status = connection.execute(
                text("SELECT status::text FROM plan_versions WHERE id = :id"),
                {"id": first.plan_id},
            ).scalar_one()
        assert str(linked["parent_plan_id"]) == first.plan_id
        assert str(linked["trigger_id"]) == leader.trigger_id
        assert linked["diff"]
        assert first_status == "superseded"

        # handled_run_id points at the flushed audit row
        run_id = str(uuid4())
        entry = AuditEntry(
            incident_id=incident_id,
            run_id=run_id,
            node_name="assemble_plan",
            inputs_json="{}",
            outputs_json="{}",
            latency_ms=1,
        ).model_dump(mode="json")
        repo.flush_audit([entry])
        repo.mark_trigger_handled(leader.trigger_id, entry["entry_id"])
        with engine.connect() as connection:
            handled = connection.execute(
                text("SELECT handled_run_id FROM triggers WHERE id = :id"),
                {"id": leader.trigger_id},
            ).scalar_one()
        assert str(handled) == entry["entry_id"]
    finally:
        if incident_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM shared_state_snapshots WHERE incident_id = :i"),
                    {"i": incident_id},
                )
                versions = (
                    connection.execute(
                        text(
                            "SELECT id FROM plan_versions WHERE incident_id = :i "
                            "ORDER BY version DESC"
                        ),
                        {"i": incident_id},
                    )
                    .scalars()
                    .all()
                )
                for plan_row in versions:  # children (higher versions) before parents
                    connection.execute(
                        text("DELETE FROM plan_versions WHERE id = :id"), {"id": plan_row}
                    )
                connection.execute(
                    text(
                        "DELETE FROM triggers WHERE incident_id = :i AND coalesced_into IS NOT NULL"
                    ),
                    {"i": incident_id},
                )
                connection.execute(
                    text("DELETE FROM triggers WHERE incident_id = :i"), {"i": incident_id}
                )
                connection.execute(
                    text("DELETE FROM agent_runs WHERE incident_id = :i"), {"i": incident_id}
                )
                connection.execute(text("DELETE FROM incidents WHERE id = :i"), {"i": incident_id})

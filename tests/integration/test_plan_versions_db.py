"""Live proof of PLAN-08: versioning, supersede, immutability, state check and capacity re-check.

Requires the Compose database at migration head (0006). The test creates its own incident and
shelter and removes every row it created in ``finally`` (plan versions children first).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from coordinator.repository import (
    CapacityRecheckFailed,
    SqlPlanningRepository,
    StateVersionConflict,
)
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from wildfire_core.db.repositories import upsert_shelters
from wildfire_core.schemas.plan import (
    ForecastFootprint,
    IntegratedPlan,
    PlanFreshness,
    PlanProvenance,
    ShelterAssignment,
    ValidationResult,
)
from wildfire_core.seed import ShelterSeedRow

load_dotenv()

DEFAULT_FACTOR = 0.6
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
EMPTY = "POLYGON EMPTY"


def _engine():  # type: ignore[no-untyped-def]
    url = make_url(os.environ["DATABASE_URL"])
    if url.host == "localhost":  # IPv6 fallback adds ~200 s per connection on loopback binding
        url = url.set(host="127.0.0.1")
    return create_engine(url)


def _plan(incident_id: str, *, failed: bool, shelter_id: str, persons: int) -> IntegratedPlan:
    footprint = ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )
    common = {
        "incident_id": incident_id,
        "run_id": str(uuid4()),
        "valid_until": NOW + timedelta(hours=1),
        "freshness": PlanFreshness(computed_at=NOW, firms_age_min=10),
        "provenance": PlanProvenance(
            run_id="r",
            state_version=0,
            weather_provider="open_meteo",
            graph_source="osm",
            graph_node_count=1,
            graph_edge_count=1,
        ),
        "footprint": footprint,
        "created_at": NOW,
        "rationale_md": "[DETERMINISTIC TEMPLATE] live test",
        "is_simulated": True,
    }
    if failed:
        return IntegratedPlan(
            status="failed",
            failure_reasons=("V5 group_unassigned: live test",),
            validation=(),
            **common,  # type: ignore[arg-type]
        )
    return IntegratedPlan(
        status="pending_review",
        validation=tuple(
            ValidationResult(validator_id=f"V{i}", status="pass")  # type: ignore[arg-type]
            for i in range(1, 9)
        ),
        shelter_assignments=(
            ShelterAssignment(
                shelter_id=shelter_id,
                shelter_name="TEST Shelter",
                group_id="g0",
                persons=persons,
                usable_capacity=60,
                available_before=60,
            ),
        ),
        **common,  # type: ignore[arg-type]
    )


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_versions_supersede_immutability_state_and_capacity_live() -> None:
    engine = _engine()
    repo = SqlPlanningRepository(engine, default_factor=DEFAULT_FACTOR)
    code = f"TEST-PV-{uuid4().hex[:10]}"
    external_ref = f"TEST-SH-{uuid4().hex[:10]}"
    incident_id: str | None = None
    try:
        with engine.begin() as connection:
            incident_id = str(
                connection.execute(
                    text(
                        "INSERT INTO incidents (code, origin) "
                        "VALUES (:code, 'simulated') RETURNING id"
                    ),
                    {"code": code},
                ).scalar_one()
            )
        upsert_shelters(
            engine,
            [
                ShelterSeedRow(
                    external_ref=external_ref,
                    name="TEST Shelter",
                    kind="school",
                    lat=11.72,
                    lon=76.64,
                    capacity=100,
                    usable_factor=None,
                    capacity_source="synthetic",
                    is_simulated=True,
                    notes="live test row",
                )
            ],
        )
        with engine.connect() as connection:
            shelter_id = str(
                connection.execute(
                    text("SELECT id FROM shelters WHERE external_ref = :ref"),
                    {"ref": external_ref},
                ).scalar_one()
            )

        # two persists: versions 1 and 2, parent link, supersede, state_version bumps
        first = repo.persist_plan(
            _plan(incident_id, failed=False, shelter_id=shelter_id, persons=40),
            expected_state_version=0,
            parent_plan_id=None,
            trigger_id=None,
            diff=None,
        )
        second = repo.persist_plan(
            _plan(incident_id, failed=False, shelter_id=shelter_id, persons=45),
            expected_state_version=1,
            parent_plan_id=first.plan_id,
            trigger_id=None,
            diff={"is_material": True},
        )
        assert (first.version, second.version) == (1, 2)
        assert (first.state_version, second.state_version) == (1, 2)
        assert second.superseded_plan_ids == (first.plan_id,)

        with engine.connect() as connection:
            rows = {
                str(row["id"]): row
                for row in connection.execute(
                    text(
                        "SELECT id, version, status::text AS status, parent_plan_id, "
                        "plan_schema_version, state_version, diff "
                        "FROM plan_versions WHERE incident_id = :i"
                    ),
                    {"i": incident_id},
                ).mappings()
            }
            incident = (
                connection.execute(
                    text(
                        "SELECT state_version, status::text AS status FROM incidents WHERE id = :i"
                    ),
                    {"i": incident_id},
                )
                .mappings()
                .one()
            )
            snapshots = connection.execute(
                text("SELECT count(*) FROM shared_state_snapshots WHERE incident_id = :i"),
                {"i": incident_id},
            ).scalar_one()
        assert rows[first.plan_id]["status"] == "superseded"
        assert rows[second.plan_id]["status"] == "pending_review"
        assert str(rows[second.plan_id]["parent_plan_id"]) == first.plan_id
        assert rows[second.plan_id]["plan_schema_version"] == "3.0"
        assert rows[second.plan_id]["state_version"] == 1
        assert rows[second.plan_id]["diff"] == {"is_material": True}
        assert incident["state_version"] == 2 and incident["status"] == "awaiting_review"
        assert snapshots == 2

        latest = repo.latest_plan(incident_id)
        assert latest is not None and latest.plan_id == second.plan_id and latest.version == 2

        # immutability trigger: plan_data is frozen, status is not
        with pytest.raises(DBAPIError, match="immutable"):  # noqa: SIM117
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE plan_versions SET plan_data = '{}'::jsonb WHERE id = :id"),
                    {"id": second.plan_id},
                )
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE plan_versions SET status = 'rejected' WHERE id = :id"),
                {"id": second.plan_id},
            )

        # optimistic state check and in-transaction capacity re-check leave no row behind
        with pytest.raises(StateVersionConflict):
            repo.persist_plan(
                _plan(incident_id, failed=True, shelter_id=shelter_id, persons=0),
                expected_state_version=1,
                parent_plan_id=None,
                trigger_id=None,
                diff=None,
            )
        with pytest.raises(CapacityRecheckFailed):  # usable = floor(100 x 0.6) = 60 < 70
            repo.persist_plan(
                _plan(incident_id, failed=False, shelter_id=shelter_id, persons=70),
                expected_state_version=2,
                parent_plan_id=second.plan_id,
                trigger_id=None,
                diff=None,
            )

        # a failed plan persists with status 'failed' and puts the incident back to planning
        third = repo.persist_plan(
            _plan(incident_id, failed=True, shelter_id=shelter_id, persons=0),
            expected_state_version=2,
            parent_plan_id=second.plan_id,
            trigger_id=None,
            diff=None,
        )
        assert third.version == 3 and third.state_version == 3
        assert third.superseded_plan_ids == ()  # 'rejected' is terminal, never superseded
        with engine.connect() as connection:
            statuses = dict(
                connection.execute(
                    text("SELECT version, status::text FROM plan_versions WHERE incident_id = :i"),
                    {"i": incident_id},
                ).all()
            )
            incident_status = connection.execute(
                text("SELECT status::text FROM incidents WHERE id = :i"), {"i": incident_id}
            ).scalar_one()
        assert statuses == {1: "superseded", 2: "rejected", 3: "failed"}
        assert incident_status == "planning"
    finally:
        with engine.begin() as connection:
            if incident_id is not None:
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
                connection.execute(text("DELETE FROM incidents WHERE id = :i"), {"i": incident_id})
            connection.execute(
                text("DELETE FROM shelters WHERE external_ref = :ref"), {"ref": external_ref}
            )

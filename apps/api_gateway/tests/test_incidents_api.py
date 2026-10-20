from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from api_gateway.main import create_app
from fastapi.testclient import TestClient


class FakeResult:
    def __init__(self, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._scalar


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).split())
        self.engine.executed_sql.append(sql)
        if "FROM incidents i" in sql:
            return FakeResult(self.engine.incidents)
        if "FROM plan_versions p" in sql:
            return FakeResult(self.engine.plans)
        if "SELECT 1 FROM incidents" in sql:
            return FakeResult(scalar=1 if self.engine.incident_exists else None)
        if "FROM agent_runs" in sql:
            return FakeResult(self.engine.audit_entries)
        if "FROM hotspots" in sql:
            return FakeResult(scalar=self.engine.latest_hotspot)
        raise AssertionError(f"Unexpected SQL: {sql}")


class FakeEngine:
    def __init__(self, *, incidents=(), plans=(), audit_entries=(), incident_exists=False):
        self.incidents = list(incidents)
        self.plans = list(plans)
        self.audit_entries = list(audit_entries)
        self.incident_exists = incident_exists
        self.latest_hotspot = None
        self.executed_sql: list[str] = []

    @contextmanager
    def connect(self):
        yield FakeConnection(self)


def make_client(engine: FakeEngine) -> TestClient:
    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def test_list_incidents_returns_empty_list_for_fresh_database() -> None:
    with make_client(FakeEngine()) as client:
        response = client.get("/api/v1/incidents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_incidents_serializes_summary_fields() -> None:
    incident_id = uuid4()
    now = datetime.now(UTC)
    engine = FakeEngine(
        incidents=[
            {
                "incident_id": incident_id,
                "status": "planning",
                "trigger_type": "new_hotspot",
                "severity": "2",
                "created_at": now,
                "updated_at": now,
                "hotspot_count": 5,
                "is_simulated": True,
            }
        ]
    )

    with make_client(engine) as client:
        response = client.get("/api/v1/incidents?status=planning&limit=10")

    assert response.status_code == 200
    assert response.json()[0]["incident_id"] == str(incident_id)
    assert response.json()[0]["hotspot_count"] == 5
    assert response.json()[0]["is_simulated"] is True


def test_list_incidents_counts_hotspots_only_from_new_hotspot_triggers() -> None:
    # WR-02: re-plan triggers (perimeter_change, road_blocked, ...) carry no hotspot_ids, so the
    # hotspot_count subquery must not read the latest trigger of an arbitrary type.
    engine = FakeEngine()

    with make_client(engine) as client:
        assert client.get("/api/v1/incidents").status_code == 200

    (sql,) = engine.executed_sql
    count_subquery = sql.split("jsonb_array_length((", 1)[1].split(") AS hotspot_count", 1)[0]
    assert "t.details -> 'hotspot_ids'" in count_subquery
    assert "t.type = 'new_hotspot'" in count_subquery


def test_plan_endpoint_returns_404_for_unknown_plan() -> None:
    with make_client(FakeEngine()) as client:
        response = client.get(f"/api/v1/incidents/{uuid4()}/plan")

    assert response.status_code == 404


def test_plan_endpoint_returns_draft_and_freshness() -> None:
    incident_id = uuid4()
    plan_id = uuid4()
    valid_time = datetime.now(UTC).isoformat()
    engine = FakeEngine(
        plans=[
            {
                "plan_id": plan_id,
                "incident_id": incident_id,
                "version": 1,
                "status": "draft",
                "rationale_md": "Grounded rationale",
                "is_llm_fallback": True,
                "is_simulated": True,
                "warnings": ["weather stale"],
                "plan_data": {
                    "weather_snapshot": {"valid_time": valid_time},
                    "clusters": [],
                },
                "created_at": datetime.now(UTC),
            }
        ]
    )

    with make_client(engine) as client:
        response = client.get(f"/api/v1/incidents/{incident_id}/plan")

    assert response.status_code == 200
    assert response.json()["plan_id"] == str(plan_id)
    assert response.json()["status"] == "draft"
    assert response.json()["freshness"] == {"firms_age_min": None, "weather_age_min": 0.0}


def _phase3_row(incident_id, plan_id, status, **overrides):
    row = {
        "plan_id": plan_id,
        "incident_id": incident_id,
        "version": 2,
        "status": status,
        "rationale_md": "Template rationale",
        "is_llm_fallback": True,
        "is_simulated": True,
        "warnings": [],
        "plan_data": {},
        "created_at": datetime.now(UTC),
        "validation": [],
        "freshness": {},
        "parent_plan_id": None,
        "used_fallback": False,
        "plan_schema_version": "3.0",
    }
    row.update(overrides)
    return row


def test_plan_endpoint_serves_a_failed_plan_with_reasons_and_validation() -> None:
    incident_id, plan_id, parent_id = uuid4(), uuid4(), uuid4()
    validation = [{"validator_id": "V1", "status": "fail", "reasons": ["capacity"]}]
    engine = FakeEngine(
        plans=[
            _phase3_row(
                incident_id,
                plan_id,
                "failed",
                validation=validation,
                parent_plan_id=parent_id,
                plan_data={
                    "failure_reasons": ["group set-near: no shelter capacity"],
                    "alerts": [{"kind": "capacity_shortfall", "message": "short by 45"}],
                },
                freshness={"firms_age_min": 30, "weather_age_min_by_cluster": {"c1": 20}},
            )
        ]
    )

    with make_client(engine) as client:
        response = client.get(f"/api/v1/incidents/{incident_id}/plan")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "failed"
    assert body["failure_reasons"] == ["group set-near: no shelter capacity"]
    assert body["validation"] == validation
    assert body["alerts"][0]["kind"] == "capacity_shortfall"
    assert body["parent_plan_id"] == str(parent_id)
    assert body["plan_schema_version"] == "3.0"


def test_plan_endpoint_passes_stored_phase3_freshness_through() -> None:
    incident_id, plan_id = uuid4(), uuid4()
    stored = {
        "computed_at": "2026-10-17T12:00:00Z",
        "firms_age_min": 30,
        "weather_age_min_by_cluster": {"c1": 20},
        "weather_age_min_max": 20,
        "stale_inputs": [],
    }
    engine = FakeEngine(
        plans=[_phase3_row(incident_id, plan_id, "pending_review", freshness=stored)]
    )

    with make_client(engine) as client:
        response = client.get(f"/api/v1/incidents/{incident_id}/plan")

    assert response.status_code == 200
    assert response.json()["status"] == "pending_review"
    assert response.json()["freshness"] == stored
    assert response.json()["failure_reasons"] == []


def test_plan_endpoint_404_names_plans_not_drafts() -> None:
    with make_client(FakeEngine()) as client:
        response = client.get(f"/api/v1/incidents/{uuid4()}/plan")

    assert response.json()["detail"] == "Incident or plan not found"


def test_audit_endpoint_returns_404_for_unknown_incident() -> None:
    with make_client(FakeEngine()) as client:
        response = client.get(f"/api/v1/audit/{uuid4()}")

    assert response.status_code == 404


def test_audit_endpoint_returns_coordinator_rows() -> None:
    incident_id = uuid4()
    run_id = uuid4()
    entry_id = uuid4()
    engine = FakeEngine(
        incident_exists=True,
        audit_entries=[
            {
                "entry_id": entry_id,
                "run_id": run_id,
                "node_name": "ingest_trigger",
                "latency_ms": 4,
                "model_metadata": None,
                "created_at": datetime.now(UTC),
                "has_outputs": True,
            }
        ],
    )

    with make_client(engine) as client:
        response = client.get(f"/api/v1/audit/{incident_id}?limit=10")

    assert response.status_code == 200
    assert response.json()[0]["entry_id"] == str(entry_id)
    assert response.json()[0]["run_id"] == str(run_id)
    assert response.json()[0]["has_outputs"] is True

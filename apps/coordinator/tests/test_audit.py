from datetime import UTC, datetime
from uuid import uuid4

from coordinator.audit import flush_audit_entries


class FakeSession:
    def __init__(self) -> None:
        self.statement = ""
        self.parameters: list[dict[str, object]] = []

    def execute(self, statement, parameters=None):
        self.statement = str(statement)
        self.parameters = parameters


def test_flush_audit_entries_bulk_inserts_idempotently() -> None:
    entry_id = uuid4()
    incident_id = uuid4()
    run_id = uuid4()
    created_at = datetime.now(UTC)
    session = FakeSession()

    flush_audit_entries(
        [
            {
                "entry_id": str(entry_id),
                "incident_id": str(incident_id),
                "run_id": str(run_id),
                "node_name": "ingest_trigger",
                "inputs_json": "{}",
                "outputs_json": '{"count": 2}',
                "latency_ms": 4,
                "model_metadata": None,
                "created_at": created_at.isoformat(),
            }
        ],
        session,
    )

    assert "ON CONFLICT (id) DO NOTHING" in session.statement
    assert len(session.parameters) == 1
    assert session.parameters[0]["id"] == entry_id
    assert session.parameters[0]["incident_id"] == incident_id
    assert session.parameters[0]["created_at"] == created_at


def _entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "entry_id": str(uuid4()),
        "incident_id": str(uuid4()),
        "run_id": str(uuid4()),
        "node_name": "specialist_shelter",
        "inputs_json": "{}",
        "outputs_json": "{}",
        "latency_ms": 1,
        "model_metadata": None,
        "created_at": datetime.now(UTC).isoformat(),
    }
    entry.update(overrides)
    return entry


def test_each_entry_is_written_with_its_own_agent() -> None:
    session = FakeSession()

    flush_audit_entries(
        [
            _entry(agent="shelter"),
            _entry(agent="traffic_routing"),
            _entry(agent="coordinator"),
        ],
        session,
    )

    assert "CAST(:agent AS agent_name)" in session.statement
    assert [row["agent"] for row in session.parameters] == [
        "shelter",
        "traffic_routing",
        "coordinator",
    ]


def test_run_failed_marker_is_stored_as_failed_and_other_rows_as_succeeded() -> None:
    # WR-09: status used to be hard-coded to 'succeeded', hiding crashed runs from status filters.
    session = FakeSession()

    flush_audit_entries(
        [_entry(node_name="specialist_shelter"), _entry(node_name="run_failed")], session
    )

    assert "CAST(:status AS run_status)" in session.statement
    assert [row["status"] for row in session.parameters] == ["succeeded", "failed"]


def test_entry_without_agent_defaults_to_coordinator() -> None:
    session = FakeSession()

    flush_audit_entries([_entry()], session)

    assert session.parameters[0]["agent"] == "coordinator"

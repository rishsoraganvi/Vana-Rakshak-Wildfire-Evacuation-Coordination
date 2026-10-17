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
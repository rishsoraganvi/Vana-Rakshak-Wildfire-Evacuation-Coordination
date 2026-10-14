import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ingest_worker.triggers import evaluate_new_hotspot, record_new_hotspot_trigger


def test_new_hotspot_threshold_crossing_is_explicit() -> None:
    assert evaluate_new_hotspot(3, 3).crossed
    assert not evaluate_new_hotspot(2, 3).crossed


def test_threshold_must_be_positive() -> None:
    with pytest.raises(ValueError):
        evaluate_new_hotspot(1, 0)


def test_new_hotspot_trigger_records_exact_hotspot_ids() -> None:
    incident_id = uuid4()
    statements: list[tuple[str, dict[str, object]]] = []

    class FakeConnection:
        def execute(self, statement, parameters):
            sql = str(statement)
            statements.append((sql, parameters))
            if sql.lstrip().startswith("SELECT id FROM triggers"):
                return type("PreviousTrigger", (), {"first": lambda self: None})()
            if sql.lstrip().startswith("INSERT INTO incidents"):
                return type("CreatedIncident", (), {"scalar_one": lambda self: incident_id})()
            return None

    class FakeEngine:
        @contextmanager
        def begin(self):
            yield FakeConnection()

    hotspot_ids = (uuid4(), uuid4())
    result = record_new_hotspot_trigger(
        FakeEngine(),
        count=2,
        threshold=2,
        detected_at=datetime(2026, 10, 14, tzinfo=UTC),
        hotspot_ids=hotspot_ids,
    )

    trigger_parameters = next(
        parameters
        for sql, parameters in statements
        if sql.lstrip().startswith("INSERT INTO triggers")
    )
    details = json.loads(str(trigger_parameters["details"]))
    assert result.crossed is True
    assert trigger_parameters["incident_id"] == incident_id
    assert details["hotspot_ids"] == [str(hotspot_id) for hotspot_id in hotspot_ids]

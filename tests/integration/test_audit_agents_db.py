"""Live proof that audit rows carry their own agent value (PLAN-01 specialist audit rows).

Requires the Compose database at migration head. The test creates its own incident and removes
every row it created in ``finally`` (audit rows first).
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from coordinator.repository import SqlPlanningRepository
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from wildfire_core.schemas.phase2 import AuditEntry

load_dotenv()


def _engine():  # type: ignore[no-untyped-def]
    url = make_url(os.environ["DATABASE_URL"])
    if url.host == "localhost":  # IPv6 fallback adds ~200 s per connection on loopback binding
        url = url.set(host="127.0.0.1")
    return create_engine(url)


@pytest.mark.compose
@pytest.mark.skipif(os.getenv("COMPOSE_SMOKE") != "1", reason="requires Compose services")
def test_flush_audit_writes_each_entrys_agent_live() -> None:
    engine = _engine()
    repo = SqlPlanningRepository(engine, default_factor=0.6)
    code = f"TEST-AUD-{uuid4().hex[:10]}"
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
        run_id = str(uuid4())
        entries = [
            AuditEntry(
                incident_id=incident_id,
                run_id=run_id,
                node_name=f"specialist_{agent}" if agent != "coordinator" else "ingest_trigger",
                agent=agent,  # type: ignore[arg-type]
                inputs_json="{}",
                outputs_json="{}",
                latency_ms=1,
            ).model_dump(mode="json")
            for agent in ("shelter", "traffic_routing", "coordinator")
        ]
        repo.flush_audit(entries)
        repo.flush_audit(entries)  # idempotent: ON CONFLICT (id) DO NOTHING

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT node_name, agent::text FROM agent_runs "
                    "WHERE incident_id = CAST(:incident_id AS uuid) ORDER BY node_name"
                ),
                {"incident_id": incident_id},
            ).all()
        assert [tuple(row) for row in rows] == [
            ("ingest_trigger", "coordinator"),
            ("specialist_shelter", "shelter"),
            ("specialist_traffic_routing", "traffic_routing"),
        ]
    finally:
        if incident_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM agent_runs WHERE incident_id = CAST(:id AS uuid)"),
                    {"id": incident_id},
                )
                connection.execute(
                    text("DELETE FROM incidents WHERE id = CAST(:id AS uuid)"), {"id": incident_id}
                )
        engine.dispose()

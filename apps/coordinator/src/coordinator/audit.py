from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def flush_audit_entries(entries: Sequence[dict[str, Any]], session: Connection) -> None:
    if not entries:
        return

    rows = [
        {
            "id": UUID(entry["entry_id"]),
            "incident_id": UUID(entry["incident_id"]),
            "run_id": UUID(entry["run_id"]),
            "node_name": entry["node_name"],
            "agent_input": entry["inputs_json"],
            "agent_output": entry["outputs_json"],
            "latency_ms": entry["latency_ms"],
            "model_metadata": json.dumps(entry["model_metadata"], sort_keys=True)
            if entry.get("model_metadata") is not None
            else None,
            "created_at": datetime.fromisoformat(entry["created_at"])
            if isinstance(entry["created_at"], str)
            else entry["created_at"],
        }
        for entry in entries
    ]
    session.execute(
        text(
            """
            INSERT INTO agent_runs
                (id, incident_id, agent, status, input, output, latency_ms,
                 run_id, node_name, model_metadata, created_at)
            VALUES
                (:id, :incident_id, 'coordinator', 'succeeded',
                 CAST(:agent_input AS jsonb), CAST(:agent_output AS jsonb), :latency_ms,
                 :run_id, :node_name, CAST(:model_metadata AS jsonb), :created_at)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        rows,
    )
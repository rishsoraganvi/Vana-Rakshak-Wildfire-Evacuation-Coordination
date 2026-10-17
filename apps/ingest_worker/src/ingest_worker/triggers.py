from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Engine, text


@dataclass(frozen=True)
class TriggerDecision:
    crossed: bool
    reason: str


def evaluate_new_hotspot(count: int, threshold: int) -> TriggerDecision:
    if threshold < 1:
        raise ValueError("threshold must be positive")
    return (
        TriggerDecision(True, "new_hotspot_threshold_crossed")
        if count >= threshold
        else TriggerDecision(False, "below_new_hotspot_threshold")
    )


def record_new_hotspot_trigger(
    engine: Engine,
    *,
    count: int,
    threshold: int,
    detected_at: datetime,
    debounce_seconds: int = 300,
    hotspot_ids: Sequence[str | UUID] = (),
) -> TriggerDecision:
    decision = evaluate_new_hotspot(count, threshold)
    if not decision.crossed:
        return decision
    with engine.begin() as connection:
        previous = connection.execute(
            text(
                """
                SELECT id FROM triggers
                WHERE type = 'new_hotspot'
                  AND detected_at >= :cutoff
                  AND coalesced_into IS NULL
                ORDER BY detected_at DESC LIMIT 1
                """
            ),
            {"cutoff": detected_at - timedelta(seconds=debounce_seconds)},
        ).first()
        incident_id = connection.execute(
            text(
                """
                INSERT INTO incidents (code, status, origin, summary)
                VALUES (:code, 'open', 'replay', :summary)
                RETURNING id
                """
            ),
            {"code": f"INC-{uuid4().hex[:10]}", "summary": decision.reason},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO triggers (incident_id, type, details, detected_at, coalesced_into)
                VALUES (
                    :incident_id, 'new_hotspot', CAST(:details AS jsonb),
                    :detected_at, :coalesced_into
                )
                """
            ),
            {
                "incident_id": incident_id,
                "details": json.dumps(
                    {
                        "count": count,
                        "threshold": threshold,
                        "hotspot_ids": [str(hotspot_id) for hotspot_id in hotspot_ids],
                    }
                ),
                "detected_at": detected_at,
                "coalesced_into": previous[0] if previous else None,
            },
        )
    return decision

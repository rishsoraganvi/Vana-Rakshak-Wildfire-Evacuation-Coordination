from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, get_args
from uuid import UUID, uuid4

import pyproj
from shapely import wkt as shapely_wkt
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from sqlalchemy import Engine, text
from wildfire_core.clock import Clock
from wildfire_core.schemas.metadata import Origin

DATA_ORIGINS = frozenset(get_args(Origin))

# Trigger types a re-plan may be requested for in Phase 3 (D-14). wind_shift, scheduled_refresh
# and manual are deferred; ``record_trigger`` rejects them before any SQL.
PHASE3_TRIGGER_TYPES = frozenset({"perimeter_change", "road_blocked", "shelter_capacity_change"})

_METRIC_CRS = 32643  # UTM 43N: metric CRS for this region (Rules 4)
_TO_METRIC = pyproj.Transformer.from_crs(4326, _METRIC_CRS, always_xy=True).transform


@dataclass(frozen=True)
class TriggerDecision:
    crossed: bool
    reason: str
    details: dict[str, float] = field(default_factory=dict)


def evaluate_new_hotspot(count: int, threshold: int) -> TriggerDecision:
    if threshold < 1:
        raise ValueError("threshold must be positive")
    return (
        TriggerDecision(True, "new_hotspot_threshold_crossed")
        if count >= threshold
        else TriggerDecision(False, "below_new_hotspot_threshold")
    )


def _metric_geometry(geometry_wkt: str) -> BaseGeometry:
    return shapely_transform(_TO_METRIC, shapely_wkt.loads(geometry_wkt))


def detect_perimeter_change(
    previous_wkt: str,
    new_wkt: str,
    *,
    iou_threshold: float,
    growth_threshold: float,
) -> TriggerDecision:
    """Perimeter change crosses when IoU < ``iou_threshold`` or growth > ``growth_threshold``.

    Areas are computed in EPSG:32643. IoU is 1.0 when the union is empty; growth against a
    zero-area previous perimeter is infinite when the new one has area and 0 otherwise.
    """
    previous = _metric_geometry(previous_wkt)
    new = _metric_geometry(new_wkt)
    union_area = previous.union(new).area
    iou = previous.intersection(new).area / union_area if union_area > 0 else 1.0
    if previous.area > 0:
        growth = (new.area - previous.area) / previous.area
    else:
        growth = float("inf") if new.area > 0 else 0.0
    details = {"iou": iou, "growth": growth}
    crossed = iou < iou_threshold or growth > growth_threshold
    reason = "perimeter_change_crossed" if crossed else "perimeter_change_below_threshold"
    return TriggerDecision(crossed, reason, details)


@dataclass(frozen=True)
class RecordedTrigger:
    trigger_id: str
    coalesced_into: str | None


_RECORD_LOCK_SQL = (
    "SELECT pg_advisory_xact_lock(hashtext(CAST(:incident_id AS text) || ':' || :type))"
)

_RECORD_LEADER_SQL = """
    SELECT id FROM triggers
    WHERE incident_id = :incident_id
      AND type = CAST(:type AS trigger_type)
      AND coalesced_into IS NULL
      AND detected_at > :cutoff
    ORDER BY detected_at
    LIMIT 1
"""

_RECORD_INSERT_SQL = """
    INSERT INTO triggers (id, incident_id, type, details, detected_at, coalesced_into)
    VALUES (
        :id, :incident_id, CAST(:type AS trigger_type), CAST(:details AS jsonb),
        :detected_at, :coalesced_into
    )
"""


def record_trigger(
    engine: Engine,
    *,
    incident_id: str,
    trigger_type: str,
    details: dict[str, Any],
    clock: Clock,
    debounce_s: int,
) -> RecordedTrigger:
    """Insert a re-plan trigger, coalescing it into the first uncoalesced one in the window.

    One transaction: advisory lock on (incident, type), the leader lookup (first uncoalesced
    trigger of the same incident and type detected within ``debounce_s``), then the insert.
    Time comes from ``clock``, never from the database or ``datetime.now`` (Rules 2.9).
    """
    if trigger_type not in PHASE3_TRIGGER_TYPES:
        raise ValueError(
            f"trigger_type must be one of {sorted(PHASE3_TRIGGER_TYPES)}, got {trigger_type!r}"
        )
    incident_uuid = UUID(incident_id)
    detected_at = clock.now_utc()
    cutoff = detected_at - timedelta(seconds=debounce_s)
    trigger_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(_RECORD_LOCK_SQL), {"incident_id": str(incident_uuid), "type": trigger_type}
        )
        leader = connection.execute(
            text(_RECORD_LEADER_SQL),
            {"incident_id": incident_uuid, "type": trigger_type, "cutoff": cutoff},
        ).first()
        leader_id = leader[0] if leader else None
        connection.execute(
            text(_RECORD_INSERT_SQL),
            {
                "id": trigger_id,
                "incident_id": incident_uuid,
                "type": trigger_type,
                "details": json.dumps(details, sort_keys=True, default=str),
                "detected_at": detected_at,
                "coalesced_into": leader_id,
            },
        )
    return RecordedTrigger(
        trigger_id=str(trigger_id),
        coalesced_into=str(leader_id) if leader_id is not None else None,
    )


def record_new_hotspot_trigger(
    engine: Engine,
    *,
    origin: str,
    count: int,
    threshold: int,
    detected_at: datetime,
    debounce_seconds: int = 300,
    hotspot_ids: Sequence[str | UUID] = (),
) -> TriggerDecision:
    if origin not in DATA_ORIGINS:
        raise ValueError(f"origin must be one of {sorted(DATA_ORIGINS)}, got {origin!r}")
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
                VALUES (:code, 'open', CAST(:origin AS data_origin), :summary)
                RETURNING id
                """
            ),
            {
                "code": f"INC-{uuid4().hex[:10]}",
                "origin": origin,
                "summary": decision.reason,
            },
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

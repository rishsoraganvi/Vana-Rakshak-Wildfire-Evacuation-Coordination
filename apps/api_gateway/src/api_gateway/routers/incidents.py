"""Local-only read APIs (Phase 2, Phase 3 plans), pending Phase 4 JWT viewer roles."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine


class IncidentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    status: str
    trigger_type: str | None
    severity: str | None
    created_at: datetime
    updated_at: datetime
    hotspot_count: int
    is_simulated: bool


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str
    incident_id: str
    version: int
    status: str
    rationale_md: str
    is_llm_fallback: bool
    is_simulated: bool
    warnings: list[str]
    created_at: datetime
    freshness: dict[str, Any]
    validation: list[dict[str, Any]] = []
    failure_reasons: list[str] = []
    alerts: list[dict[str, Any]] = []
    parent_plan_id: str | None = None
    used_fallback: bool = False
    plan_schema_version: str = "2.0"


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: str
    run_id: str
    node_name: str
    latency_ms: int
    model_metadata: dict[str, Any] | None
    created_at: datetime
    has_outputs: bool


def _engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.engine)


def _plan_data(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else []


def _age_minutes(value: Any) -> float | None:
    if value is None:
        return None
    timestamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return round(max(0.0, (datetime.now(UTC) - timestamp).total_seconds() / 60.0), 2)


def _freshness(
    engine: Engine,
    incident_id: UUID,
    plan_data: dict[str, Any],
) -> dict[str, float | None]:
    weather = plan_data.get("weather_snapshot")
    weather_age = _age_minutes(weather.get("valid_time")) if isinstance(weather, dict) else None
    clusters = plan_data.get("clusters", [])
    hotspot_ids = [
        str(hotspot_id)
        for cluster in clusters
        if isinstance(cluster, dict)
        for hotspot_id in cluster.get("hotspot_ids", [])
    ]

    firms_age: float | None = None
    if hotspot_ids:
        statement = text(
            "SELECT max(acq_datetime) FROM hotspots WHERE id IN :hotspot_ids"
        ).bindparams(bindparam("hotspot_ids", expanding=True))
        with engine.connect() as connection:
            latest_hotspot = connection.execute(
                statement,
                {"hotspot_ids": [UUID(hotspot_id) for hotspot_id in hotspot_ids]},
            ).scalar_one_or_none()
        firms_age = _age_minutes(latest_hotspot)

    return {"firms_age_min": firms_age, "weather_age_min": weather_age}


def create_incidents_router() -> APIRouter:
    router = APIRouter()

    @router.get("/incidents", response_model=list[IncidentSummary])
    def list_incidents(
        request: Request,
        status: str | None = None,
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[IncidentSummary]:
        statement = text(
            """
            SELECT i.id AS incident_id,
                   i.status::text AS status,
                   (SELECT t.type::text FROM triggers t
                    WHERE t.incident_id = i.id
                    ORDER BY t.detected_at DESC LIMIT 1) AS trigger_type,
                   i.severity::text AS severity,
                   i.opened_at AS created_at,
                   GREATEST(i.opened_at, COALESCE(
                       (SELECT max(t.detected_at) FROM triggers t WHERE t.incident_id = i.id),
                       i.opened_at
                   )) AS updated_at,
                   COALESCE(jsonb_array_length((
                       SELECT t.details -> 'hotspot_ids' FROM triggers t
                       WHERE t.incident_id = i.id AND t.type = 'new_hotspot'
                       ORDER BY t.detected_at DESC LIMIT 1
                   )), 0) AS hotspot_count,
                       (i.origin::text IN ('replay', 'simulated')) AS is_simulated
            FROM incidents i
            WHERE (CAST(:status AS text) IS NULL OR i.status::text = CAST(:status AS text))
            ORDER BY i.opened_at DESC
            LIMIT :limit OFFSET :offset
            """
        )
        with _engine(request).connect() as connection:
            rows = (
                connection.execute(
                    statement,
                    {"status": status, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
        return [
            IncidentSummary(
                incident_id=str(row["incident_id"]),
                status=row["status"],
                trigger_type=row["trigger_type"],
                severity=str(row["severity"]) if row["severity"] is not None else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                hotspot_count=int(row["hotspot_count"]),
                is_simulated=bool(row["is_simulated"]),
            )
            for row in rows
        ]

    @router.get("/incidents/{incident_id}/plan", response_model=PlanResponse)
    def get_incident_plan(request: Request, incident_id: UUID) -> PlanResponse:
        statement = text(
            """
            SELECT p.id AS plan_id, p.incident_id, p.version, p.status::text AS status,
                   p.rationale_md, p.is_llm_fallback, p.is_simulated, p.warnings,
                   p.plan_data, p.created_at, p.validation, p.freshness, p.parent_plan_id,
                   p.used_fallback, p.plan_schema_version
            FROM plan_versions p
            WHERE p.incident_id = :incident_id
              AND p.status IN ('draft', 'pending_review', 'failed')
            ORDER BY p.version DESC
            LIMIT 1
            """
        )
        engine = _engine(request)
        with engine.connect() as connection:
            row = connection.execute(statement, {"incident_id": incident_id}).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="Incident or plan not found")

        warnings = row["warnings"]
        if isinstance(warnings, str):
            warnings = json.loads(warnings)
        plan_data = _plan_data(row["plan_data"])
        # Phase 3 plans store their freshness; Phase 2 rows (empty column) are computed as before.
        stored_freshness = _plan_data(row.get("freshness"))
        parent_plan_id = row.get("parent_plan_id")
        return PlanResponse(
            plan_id=str(row["plan_id"]),
            incident_id=str(row["incident_id"]),
            version=int(row["version"]),
            status=row["status"],
            rationale_md=row["rationale_md"],
            is_llm_fallback=bool(row["is_llm_fallback"]),
            is_simulated=bool(row["is_simulated"]),
            warnings=warnings or [],
            created_at=row["created_at"],
            freshness=stored_freshness or _freshness(engine, row["incident_id"], plan_data),
            validation=_json_list(row.get("validation")),
            failure_reasons=[str(item) for item in _json_list(plan_data.get("failure_reasons"))],
            alerts=_json_list(plan_data.get("alerts")),
            parent_plan_id=str(parent_plan_id) if parent_plan_id is not None else None,
            used_fallback=bool(row.get("used_fallback") or False),
            plan_schema_version=str(row.get("plan_schema_version") or "2.0"),
        )

    @router.get("/audit/{incident_id}", response_model=list[AuditEntryResponse])
    def get_incident_audit(
        request: Request,
        incident_id: UUID,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[AuditEntryResponse]:
        engine = _engine(request)
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM incidents WHERE id = :incident_id"),
                {"incident_id": incident_id},
            ).scalar_one_or_none()
            if exists is None:
                raise HTTPException(status_code=404, detail="Incident not found")
            rows = (
                connection.execute(
                    text(
                        """
                    SELECT id AS entry_id, run_id, node_name, latency_ms,
                           model_metadata, created_at, (output IS NOT NULL) AS has_outputs
                    FROM agent_runs
                    WHERE incident_id = :incident_id AND node_name IS NOT NULL
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                    ),
                    {"incident_id": incident_id, "limit": limit},
                )
                .mappings()
                .all()
            )
        return [
            AuditEntryResponse(
                entry_id=str(row["entry_id"]),
                run_id=str(row["run_id"]),
                node_name=row["node_name"],
                latency_ms=int(row["latency_ms"] or 0),
                model_metadata=row["model_metadata"],
                created_at=row["created_at"],
                has_outputs=bool(row["has_outputs"]),
            )
            for row in rows
        ]

    return router

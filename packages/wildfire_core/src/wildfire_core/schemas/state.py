from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StateReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "hotspot", "weather", "fire_run", "risk_assessment", "settlement", "plan", "shelter"
    ]
    identifier: str = Field(min_length=1)
    schema_version: str = "1.0"


class FireSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_ids: tuple[str, ...] = ()
    cluster_ids: tuple[str, ...] = ()


class SettlementEta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    eta_min: float = Field(ge=0)


class RiskSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlements_at_risk: tuple[SettlementEta, ...] = ()


class RoadsSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Content hash of the edge statuses the plan was routed on (stable for equal inputs).
    edge_status_version: str | None = None


class SheltersSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Content hash of the shelter occupancy snapshot the plan was matched against.
    occupancy_version: str | None = None


class PlanSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_plan_id: str | None = None
    status: str | None = None
    version: int | None = Field(default=None, ge=1)


class FreshnessSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firms_age_min: int | None = Field(default=None, ge=0)
    weather_age_min: int | None = Field(default=None, ge=0)


class SharedState(BaseModel):
    """Versioned shared state (TechSpec section 5). Sections are optional so Phase 1/2 snapshots
    (incident_id, version, references only) keep validating."""

    model_config = ConfigDict(extra="forbid")

    incident_id: str
    version: int = Field(ge=0)
    references: tuple[StateReference, ...]
    updated_at: datetime | None = None
    fire: FireSection | None = None
    risk: RiskSection | None = None
    roads: RoadsSection | None = None
    shelters: SheltersSection | None = None
    plan: PlanSection | None = None
    freshness: FreshnessSection | None = None

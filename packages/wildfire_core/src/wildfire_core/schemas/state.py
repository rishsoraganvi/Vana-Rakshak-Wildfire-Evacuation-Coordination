from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StateReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["hotspot", "weather", "fire_run", "risk_assessment", "settlement"]
    identifier: str = Field(min_length=1)
    schema_version: str = "1.0"


class SharedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    version: int = Field(ge=0)
    references: tuple[StateReference, ...]

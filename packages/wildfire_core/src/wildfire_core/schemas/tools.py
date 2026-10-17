"""Tool result envelope shared by agent tools (Rules 2.5)."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    retryable: bool


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: str
    ok: bool
    data: Any = None
    error: ToolError | None = None
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def ok_matches_error(self) -> Self:
        if self.ok != (self.error is None):
            raise ValueError("ok must be True exactly when error is None")
        return self

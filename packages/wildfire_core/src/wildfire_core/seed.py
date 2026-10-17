"""Validated seed-row models and CSV loaders for shelters and settlements.

Seed CSV text is data, never instructions (Rules 12.10): every field is validated and no field is
ever evaluated or used to build SQL. Synthetic rows must be labelled (S3, S9, D-18).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_REF_PATTERN = r"^[A-Za-z0-9_.-]{1,64}$"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
SYNTHETIC = "synthetic"


def _no_control_chars(value: str) -> str:
    if _CONTROL_CHARS.search(value):
        raise ValueError("control characters are not allowed")
    return value


def _empty_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class ShelterSeedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_ref: str = Field(pattern=_REF_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["school", "community_hall", "other"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    capacity: int = Field(ge=1, le=100000)
    usable_factor: float | None = Field(default=None, gt=0, le=1)
    capacity_source: str = Field(min_length=1, max_length=120)
    is_simulated: bool = False
    notes: str = Field(default="", max_length=500)

    @field_validator("usable_factor", mode="before")
    @classmethod
    def blank_factor_is_none(cls, value: object) -> object:
        return _empty_to_none(value)

    @field_validator("name", "capacity_source", "notes")
    @classmethod
    def text_has_no_control_chars(cls, value: str) -> str:
        return _no_control_chars(value)

    @model_validator(mode="after")
    def synthetic_must_be_simulated(self) -> Self:
        if self.capacity_source == SYNTHETIC and not self.is_simulated:
            raise ValueError("capacity_source 'synthetic' requires is_simulated true")
        return self


class SettlementSeedRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_ref: str = Field(pattern=_REF_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["village", "hamlet", "town", "other"]
    population: int = Field(ge=1, le=10_000_000)
    pop_source: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    buffer_m: int = Field(ge=100, le=20000)
    is_simulated: bool = False

    @field_validator("name", "pop_source")
    @classmethod
    def text_has_no_control_chars(cls, value: str) -> str:
        return _no_control_chars(value)

    @model_validator(mode="after")
    def synthetic_must_be_simulated(self) -> Self:
        if self.pop_source == SYNTHETIC and not self.is_simulated:
            raise ValueError("pop_source 'synthetic' requires is_simulated true")
        return self


def _read_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _check_unique(refs: list[str]) -> None:
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            raise ValueError(f"duplicate external_ref: {ref}")
        seen.add(ref)


def load_shelter_rows(path: Path) -> list[ShelterSeedRow]:
    rows = [ShelterSeedRow.model_validate(raw) for raw in _read_rows(path)]
    _check_unique([row.external_ref for row in rows])
    return rows


def load_settlement_rows(path: Path) -> list[SettlementSeedRow]:
    rows = [SettlementSeedRow.model_validate(raw) for raw in _read_rows(path)]
    _check_unique([row.external_ref for row in rows])
    return rows

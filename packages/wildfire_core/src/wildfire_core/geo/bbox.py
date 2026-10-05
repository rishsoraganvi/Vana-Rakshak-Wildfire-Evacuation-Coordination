from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def ordered(self) -> BBox:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("bbox bounds must be ordered")
        return self

    @classmethod
    def from_value(cls, value: Any) -> BBox:
        if isinstance(value, str):
            values = [float(part.strip()) for part in value.split(",")]
        else:
            values = list(value)
        if len(values) != 4:
            raise ValueError("bbox requires west,south,east,north")
        return cls(west=values[0], south=values[1], east=values[2], north=values[3])

    def contains(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north

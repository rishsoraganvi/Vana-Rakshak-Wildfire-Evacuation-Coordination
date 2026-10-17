"""Shelter registry: conservative usable capacity and candidate construction (D-03, D-04)."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Any

from sqlalchemy import Engine, text
from wildfire_core.schemas.plan import ShelterCandidate, ShelterRecord

_FETCH_SHELTERS_SQL = """
    SELECT id::text AS shelter_id, external_ref, name, kind,
           ST_Y(geom) AS lat, ST_X(geom) AS lon, capacity,
           usable_factor, occupancy, capacity_source, is_active, is_simulated
    FROM shelters
    ORDER BY external_ref
"""


def usable_capacity(
    capacity: int, usable_factor: float | Decimal | None, default_factor: float
) -> int:
    """floor(capacity x factor) computed exactly in decimal, so 100 x 0.29 is 29 (D-03)."""
    factor = default_factor if usable_factor is None else usable_factor
    exact = Decimal(capacity) * Decimal(str(factor))
    return int(exact.to_integral_value(rounding=ROUND_FLOOR))


def _record_from_row(row: Any) -> ShelterRecord:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    factor = mapping["usable_factor"]
    return ShelterRecord(
        shelter_id=str(mapping["shelter_id"]),
        external_ref=mapping["external_ref"],
        name=mapping["name"],
        kind=mapping["kind"],
        lat=float(mapping["lat"]),
        lon=float(mapping["lon"]),
        capacity=int(mapping["capacity"]),
        usable_factor=None if factor is None else float(factor),
        occupancy=int(mapping["occupancy"]),
        capacity_source=mapping["capacity_source"],
        is_active=bool(mapping["is_active"]),
        is_simulated=bool(mapping["is_simulated"]),
    )


def fetch_shelters(engine: Engine) -> list[ShelterRecord]:
    with engine.connect() as connection:
        rows = connection.execute(text(_FETCH_SHELTERS_SQL)).all()
    return [_record_from_row(row) for row in rows]


def to_candidate(record: ShelterRecord, default_factor: float) -> ShelterCandidate:
    usable = usable_capacity(record.capacity, record.usable_factor, default_factor)
    return ShelterCandidate(
        shelter_id=record.shelter_id,
        name=record.name,
        kind=record.kind,
        lat=record.lat,
        lon=record.lon,
        usable_capacity=usable,
        occupancy=record.occupancy,
        available=max(0, usable - record.occupancy),
        capacity_source=record.capacity_source,
        is_simulated=record.is_simulated,
    )

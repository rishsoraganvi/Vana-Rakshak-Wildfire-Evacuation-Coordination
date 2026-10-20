"""Shelter registry: conservative usable capacity and candidate construction (D-03, D-04)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from typing import Any
from uuid import UUID

import shapely
from shapely import wkt
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from sqlalchemy import Engine, text
from wildfire_core.geo.footprint import buffer_metric
from wildfire_core.schemas.plan import (
    ExcludedShelter,
    ForecastFootprint,
    ShelterCandidate,
    ShelterRecord,
)

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


def exclusion_zone(footprint: ForecastFootprint, buffer_m: float) -> BaseGeometry:
    """Current perimeter union P90-6h, buffered by ``buffer_m`` metres in EPSG:32643 (D-21)."""
    parts = [wkt.loads(footprint.current_wkt), wkt.loads(footprint.p90_6h_wkt)]
    non_empty = [geometry for geometry in parts if not geometry.is_empty]
    if not non_empty:
        return wkt.loads("POLYGON EMPTY")
    return buffer_metric(unary_union(non_empty), buffer_m)


@dataclass(frozen=True)
class CandidateList:
    candidates: tuple[ShelterCandidate, ...]
    excluded: tuple[ExcludedShelter, ...]


def list_candidate_shelters(
    shelters: Sequence[ShelterRecord],
    footprint: ForecastFootprint,
    *,
    buffer_m: float,
    default_factor: float,
) -> CandidateList:
    """Split shelters into planning candidates and excluded entries with reasons (D-04, D-21).

    Pure and deterministic: both tuples are sorted by shelter_id.
    """
    zone = exclusion_zone(footprint, buffer_m)
    if not zone.is_empty:
        shapely.prepare(zone)
    candidates: list[ShelterCandidate] = []
    excluded: list[ExcludedShelter] = []
    for record in sorted(shelters, key=lambda item: item.shelter_id):
        if not record.is_active:
            excluded.append(ExcludedShelter(shelter_id=record.shelter_id, reason="inactive"))
            continue
        if not zone.is_empty and zone.intersects(Point(record.lon, record.lat)):
            excluded.append(
                ExcludedShelter(shelter_id=record.shelter_id, reason="inside_exclusion_zone")
            )
            continue
        candidate = to_candidate(record, default_factor)
        if candidate.available <= 0:
            excluded.append(ExcludedShelter(shelter_id=record.shelter_id, reason="no_capacity"))
            continue
        candidates.append(candidate)
    return CandidateList(candidates=tuple(candidates), excluded=tuple(excluded))


class CapacityExceeded(Exception):
    """The requested occupancy change would exceed usable capacity or go below zero."""

    def __init__(self, shelter_id: str, delta: int) -> None:
        super().__init__(f"occupancy change {delta:+d} refused for shelter {shelter_id}")
        self.shelter_id = shelter_id
        self.delta = delta


_UPDATE_OCCUPANCY_SQL = """
    UPDATE shelters
    SET occupancy = occupancy + CAST(:delta AS integer), updated_at = now()
    WHERE id = CAST(:shelter_id AS uuid)
      AND occupancy + CAST(:delta AS integer) >= 0
      AND (
          CAST(:delta AS integer) < 0
          OR (
              is_active
              AND occupancy + CAST(:delta AS integer)
                  <= floor(capacity * COALESCE(usable_factor, CAST(:default_factor AS numeric)))
          )
      )
    RETURNING occupancy
"""

_INSERT_OCCUPANCY_HISTORY_SQL = """
    INSERT INTO shelter_occupancy (shelter_id, incident_id, occupancy, delta, source)
    VALUES (
        CAST(:shelter_id AS uuid), CAST(:incident_id AS uuid), :occupancy, :delta, :source
    )
"""


def update_occupancy(
    engine: Engine,
    *,
    shelter_id: str,
    delta: int,
    incident_id: str | UUID | None,
    default_factor: float,
    source: str = "plan",
) -> int:
    """Atomically change occupancy; the only sanctioned writer of shelters.occupancy (D-03).

    One UPDATE carries the capacity bound in its WHERE clause, so concurrent writers cannot
    double-book. Capacity is therefore re-checked inside the transaction (Rules 6). A history row
    is written in the same transaction only after the UPDATE succeeded.

    The active and usable-capacity bounds apply to increases only. A release (negative delta) is
    always allowed down to zero, so evacuees can leave a shelter that has gone inactive or whose
    usable factor was lowered below its current occupancy.
    """
    if delta == 0:
        raise ValueError("delta must be non-zero")
    with engine.begin() as connection:
        new_occupancy = connection.execute(
            text(_UPDATE_OCCUPANCY_SQL),
            {
                "shelter_id": str(shelter_id),
                "delta": delta,
                "default_factor": Decimal(str(default_factor)),
            },
        ).scalar_one_or_none()
        if new_occupancy is None:
            raise CapacityExceeded(str(shelter_id), delta)
        connection.execute(
            text(_INSERT_OCCUPANCY_HISTORY_SQL),
            {
                "shelter_id": str(shelter_id),
                "incident_id": None if incident_id is None else str(incident_id),
                "occupancy": int(new_occupancy),
                "delta": delta,
                "source": source,
            },
        )
    return int(new_occupancy)

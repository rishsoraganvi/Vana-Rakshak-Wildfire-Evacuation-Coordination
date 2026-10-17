from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from agent_shelter.registry import fetch_shelters, to_candidate, usable_capacity
from wildfire_core.db.repositories import upsert_shelters
from wildfire_core.seed import load_shelter_rows

ROOT = Path(__file__).resolve().parents[4]
SHELTERS_CSV = ROOT / "config" / "seed" / "shelters_bandipur.csv"


@pytest.mark.parametrize(
    ("capacity", "factor", "default", "expected"),
    [(100, None, 0.6, 60), (100, 0.29, 0.6, 29), (7, 0.6, 0.6, 4), (100, Decimal("0.50"), 0.6, 50)],
)
def test_usable_capacity_is_exact_floor(
    capacity: int, factor: float | Decimal | None, default: float, expected: int
) -> None:
    assert usable_capacity(capacity, factor, default) == expected


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class FakeConnection:
    def __init__(self, log: list[tuple[str, Any]], rows: list[dict[str, Any]]) -> None:
        self._log = log
        self._rows = rows

    def execute(self, statement: Any, parameters: Any = None) -> FakeResult:
        self._log.append((str(statement), parameters))
        return FakeResult(self._rows)


class FakeEngine:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.log: list[tuple[str, Any]] = []
        self._rows = rows or []

    @contextmanager
    def connect(self) -> Iterator[FakeConnection]:
        yield FakeConnection(self.log, self._rows)

    @contextmanager
    def begin(self) -> Iterator[FakeConnection]:
        yield FakeConnection(self.log, self._rows)


def _db_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "shelter_id": "11111111-1111-1111-1111-111111111111",
        "external_ref": "SYN-SH-01",
        "name": "SYN Shelter 01",
        "kind": "school",
        "lat": 11.72,
        "lon": 76.64,
        "capacity": 100,
        "usable_factor": Decimal("0.50"),
        "occupancy": 20,
        "capacity_source": "synthetic",
        "is_active": True,
        "is_simulated": True,
    }
    row.update(overrides)
    return row


def test_fetch_shelters_maps_rows_to_records() -> None:
    engine = FakeEngine([_db_row(), _db_row(external_ref="SYN-SH-02", usable_factor=None)])
    records = fetch_shelters(engine)  # type: ignore[arg-type]
    assert [r.external_ref for r in records] == ["SYN-SH-01", "SYN-SH-02"]
    assert records[0].usable_factor == 0.5
    assert records[1].usable_factor is None
    assert "FROM shelters" in engine.log[0][0]


def test_seed_row_flows_through_upsert_and_registry_candidate() -> None:
    row = load_shelter_rows(SHELTERS_CSV)[0]
    engine = FakeEngine()
    assert upsert_shelters(engine, [row]) == 1  # type: ignore[arg-type]
    sql, params = engine.log[0]
    assert "ON CONFLICT (external_ref)" in sql
    update_set = sql.split("DO UPDATE SET", 1)[1]
    assert "occupancy" not in update_set
    assert params["external_ref"] == row.external_ref
    assert params["capacity_source"] == "synthetic"

    record = fetch_shelters(
        FakeEngine(  # type: ignore[arg-type]
            [
                _db_row(
                    external_ref=row.external_ref,
                    capacity=row.capacity,
                    usable_factor=None,
                    occupancy=10,
                )
            ]
        )
    )[0]
    candidate = to_candidate(record, 0.6)
    assert candidate.usable_capacity == int(row.capacity * 0.6)
    assert candidate.available == candidate.usable_capacity - 10
    assert candidate.is_simulated

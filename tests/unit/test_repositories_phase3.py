from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wildfire_core.db.repositories import (
    current_edge_statuses,
    set_edge_status,
    upsert_settlements,
)
from wildfire_core.seed import load_settlement_rows

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Connection:
    def __init__(self, log: list[tuple[str, Any]], rows: list[tuple[Any, ...]]) -> None:
        self._log = log
        self._rows = rows

    def execute(self, statement: Any, parameters: Any = None) -> _Result:
        self._log.append((str(statement), parameters))
        return _Result(self._rows)


class _Engine:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.log: list[tuple[str, Any]] = []
        self._rows = rows or []

    @contextmanager
    def begin(self) -> Iterator[_Connection]:
        yield _Connection(self.log, self._rows)

    @contextmanager
    def connect(self) -> Iterator[_Connection]:
        yield _Connection(self.log, self._rows)


def test_upsert_settlements_is_keyed_on_external_ref() -> None:
    rows = load_settlement_rows(ROOT / "config" / "seed" / "settlements_bandipur.csv")
    engine = _Engine()
    assert upsert_settlements(engine, rows) == 10  # type: ignore[arg-type]
    assert len(engine.log) == 10
    sql, params = engine.log[0]
    assert "ON CONFLICT (external_ref) DO UPDATE" in sql
    assert params["pop_source"] == "synthetic"
    assert params["is_simulated"] is True


def test_set_edge_status_binds_parameters() -> None:
    engine = _Engine()
    set_edge_status(
        engine,  # type: ignore[arg-type]
        osm_u=1,
        osm_v=2,
        osm_key=0,
        status="blocked",
        source="scenario",
        incident_id=None,
        valid_from=NOW,
    )
    sql, params = engine.log[0]
    assert "INSERT INTO road_edge_status" in sql
    assert params["status"] == "blocked"
    assert params["incident_id"] is None


def test_current_edge_statuses_uses_distinct_on_latest_valid_row() -> None:
    engine = _Engine([(1, 2, 0, "blocked"), (3, 4, 1, "congested")])
    result = current_edge_statuses(engine, NOW)  # type: ignore[arg-type]
    assert result == {(1, 2, 0): "blocked", (3, 4, 1): "congested"}
    sql, params = engine.log[0]
    assert "DISTINCT ON (osm_u, osm_v, osm_key)" in sql
    assert "ORDER BY osm_u, osm_v, osm_key, valid_from DESC" in sql
    assert "valid_to IS NULL OR valid_to > :now" in sql
    assert params == {"now": NOW}

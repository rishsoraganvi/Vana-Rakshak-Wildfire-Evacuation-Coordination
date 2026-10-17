from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from wildfire_core.seed import (
    SettlementSeedRow,
    ShelterSeedRow,
    load_settlement_rows,
    load_shelter_rows,
)

ROOT = Path(__file__).resolve().parents[2]
SHELTERS_CSV = ROOT / "config" / "seed" / "shelters_bandipur.csv"
SETTLEMENTS_CSV = ROOT / "config" / "seed" / "settlements_bandipur.csv"
CENTER_LAT = 11.72
CENTER_LON = 76.64


def _distance_km(lat: float, lon: float) -> float:
    """Equirectangular distance from the pilot centre."""
    dy = (lat - CENTER_LAT) * 111.2
    dx = (lon - CENTER_LON) * 111.2 * math.cos(math.radians(CENTER_LAT))
    return math.hypot(dx, dy)


def _shelter(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "external_ref": "SYN-SH-99",
        "name": "SYN Shelter 99",
        "kind": "school",
        "lat": 11.72,
        "lon": 76.64,
        "capacity": 100,
        "usable_factor": "",
        "capacity_source": "synthetic",
        "is_simulated": "true",
        "notes": "x",
    }
    base.update(overrides)
    return base


def test_committed_shelter_csv_loads_and_is_labelled() -> None:
    rows = load_shelter_rows(SHELTERS_CSV)
    assert len(rows) == 20
    assert len({row.external_ref for row in rows}) == 20
    for row in rows:
        assert row.capacity_source
        if row.capacity_source == "synthetic":
            assert row.is_simulated
        assert _distance_km(row.lat, row.lon) <= 10.0
        assert 80 <= row.capacity <= 600
    assert sum(1 for row in rows if _distance_km(row.lat, row.lon) >= 5.0) >= 6
    assert sum(1 for row in rows if row.usable_factor == 0.5) == 2


def test_blank_usable_factor_is_none() -> None:
    assert ShelterSeedRow.model_validate(_shelter()).usable_factor is None


def test_shelter_row_rejects_control_character_in_name() -> None:
    with pytest.raises(ValidationError):
        ShelterSeedRow.model_validate(_shelter(name="bad\x07name"))


def test_shelter_row_rejects_zero_capacity() -> None:
    with pytest.raises(ValidationError):
        ShelterSeedRow.model_validate(_shelter(capacity=0))


def test_shelter_row_rejects_synthetic_not_simulated() -> None:
    with pytest.raises(ValidationError):
        ShelterSeedRow.model_validate(_shelter(is_simulated="false"))


def test_shelter_row_rejects_bad_ref_and_unknown_column() -> None:
    with pytest.raises(ValidationError):
        ShelterSeedRow.model_validate(_shelter(external_ref="x; DROP TABLE shelters"))
    with pytest.raises(ValidationError):
        ShelterSeedRow.model_validate(_shelter(extra_col="1"))


def test_loader_rejects_duplicate_external_ref(tmp_path: Path) -> None:
    header = SHELTERS_CSV.read_text(encoding="utf-8").splitlines()
    path = tmp_path / "dup.csv"
    path.write_text("\n".join([header[0], header[1], header[1]]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_shelter_rows(path)


def _settlement(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "external_ref": "SYN-ST-99",
        "name": "SYN Village 99",
        "kind": "village",
        "population": 100,
        "pop_source": "synthetic",
        "lat": 11.72,
        "lon": 76.64,
        "buffer_m": 2000,
        "is_simulated": "true",
    }
    base.update(overrides)
    return base


def test_committed_settlement_csv_loads_and_is_labelled() -> None:
    rows = load_settlement_rows(SETTLEMENTS_CSV)
    assert len(rows) == 10
    assert len({row.external_ref for row in rows}) == 10
    for row in rows:
        assert row.pop_source
        if row.pop_source == "synthetic":
            assert row.is_simulated
        assert _distance_km(row.lat, row.lon) <= 10.0
        assert 50 <= row.population <= 900
        assert row.buffer_m == 2000


@pytest.mark.parametrize(
    "override",
    [
        {"population": 0},
        {"pop_source": ""},
        {"buffer_m": 99},
        {"buffer_m": 20001},
        {"is_simulated": "false"},
        {"name": "bad\nname"},
    ],
)
def test_settlement_row_rejections(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SettlementSeedRow.model_validate(_settlement(**override))


def test_settlement_non_synthetic_source_may_be_real() -> None:
    row = SettlementSeedRow.model_validate(
        _settlement(pop_source="census-2011", is_simulated="false")
    )
    assert not row.is_simulated

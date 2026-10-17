from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError
from wildfire_core.config import Settings, load_settings

DEFAULTS = Path("config/defaults.yaml")


def _raw() -> dict[str, Any]:
    values: dict[str, Any] = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
    values.setdefault("database_url", "postgresql+psycopg://u@localhost/db")
    values.setdefault("redis_url", "redis://localhost:6379/0")
    return values


def test_phase3_defaults_load_with_exact_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = load_settings(DEFAULTS)
    assert s.shelter_usable_factor == 0.6
    assert s.shelter_exclusion_buffer_m == 1000
    assert s.route_p50_mult == 10.0
    assert s.route_p90_mult == 3.0
    assert (s.k_paths, s.k_paths_max_leg_s, s.max_snap_distance_m) == (3, 5.0, 2000)
    assert (s.bpr_alpha, s.bpr_beta) == (0.15, 4.0)
    assert (s.persons_per_vehicle, s.evac_window_h, s.congestion_passes) == (4.0, 2.0, 3)
    assert s.lane_capacity_vph == {
        "motorway": 1800,
        "trunk": 1600,
        "primary": 1400,
        "secondary": 1100,
        "tertiary": 900,
        "default": 600,
    }
    assert s.link_capacity_factor == 0.8
    assert s.conflict_max_loops == 3
    assert s.fix_menu_order == ("next_path", "rematch", "split")
    assert s.trigger_debounce_s == 300
    assert (s.perimeter_iou_threshold, s.perimeter_growth_threshold) == (0.8, 0.25)
    assert s.shelter_capacity_change_fraction == 0.10
    assert (s.pilot_center_lat, s.pilot_center_lon, s.pilot_buffer_m) == (11.72, 76.64, 10000)
    assert (s.plan_valid_for_min, s.specialist_timeout_s) == (60, 60)
    assert (s.stale_firms_min, s.weather_max_distance_km) == (180, 50.0)
    assert (s.llm_control_max_tokens, s.llm_control_temperature) == (256, 0.0)
    assert s.shelters_seed_path == Path("config/seed/shelters_bandipur.csv")
    assert s.settlements_seed_path == Path("config/seed/settlements_bandipur.csv")
    assert s.route_fire_penalty_near == 5.0


def test_raw_defaults_validate() -> None:
    assert Settings.model_validate(_raw()).fix_menu_order == ("next_path", "rematch", "split")


@pytest.mark.parametrize(
    "override",
    [
        {"shelter_usable_factor": 1.5},
        {"shelter_usable_factor": 0.0},
        {"congestion_passes": 5},
        {"congestion_passes": 1},
        {"conflict_max_loops": 4},
        {"conflict_max_loops": 0},
        {"fix_menu_order": ["next_path", "rematch", "split", "unassign"]},
        {"fix_menu_order": ["next_path", "rematch"]},
        {"route_p90_mult": 12.0},
        {"route_p90_mult": 0.5, "route_p50_mult": 0.4},
        {"llm_control_temperature": 0.5},
        {"k_paths": 6},
        {"lane_capacity_vph": {"primary": 1400}},
        {"trigger_debounce_s": -1},
        {"perimeter_iou_threshold": 0.0},
        {"persons_per_vehicle": 0},
        {"evac_window_h": 0},
    ],
)
def test_invalid_phase3_values_are_rejected(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({**_raw(), **override})


def test_fix_menu_list_in_yaml_becomes_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = tmp_path / "c.yaml"
    raw = _raw()
    raw["fix_menu_order"] = ["split", "rematch", "next_path"]
    config.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_settings(config).fix_menu_order == ("split", "rematch", "next_path")

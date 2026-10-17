from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from agent_fire.ca_model import (
    _moisture_factor,
    _spread_metrics,
    _wind_factor,
    run_ensemble,
)
from agent_fire.ensemble import compute_fire_spread
from pydantic import ValidationError
from shapely import wkt as shapely_wkt
from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot


def test_wind_factor_uses_meteorological_from_direction():
    # Wind FROM 270 (westerly) pushes fire toward 90 (east).
    east = _wind_factor(wind_speed_ms=10.0, wind_from_deg=270.0, spread_dir_deg=90.0)
    west = _wind_factor(wind_speed_ms=10.0, wind_from_deg=270.0, spread_dir_deg=270.0)
    north = _wind_factor(wind_speed_ms=10.0, wind_from_deg=270.0, spread_dir_deg=0.0)
    south = _wind_factor(wind_speed_ms=10.0, wind_from_deg=270.0, spread_dir_deg=180.0)

    assert east == 1.0
    assert west < north
    assert west < south
    assert abs(north - south) < 1e-12
    assert north < east


def test_moisture_factor_high_rh():
    factor_low_rh = _moisture_factor(rh_pct=25.0, temperature_c=35.0)
    factor_high_rh = _moisture_factor(rh_pct=85.0, temperature_c=35.0)

    assert factor_high_rh < factor_low_rh
    assert factor_high_rh >= 0.05


def test_ensemble_returns_all_perimeters():
    res = run_ensemble(
        centroid_lat=11.72,
        centroid_lon=76.64,
        bbox_west=76.55,
        bbox_south=11.65,
        bbox_east=76.75,
        bbox_north=11.80,
        wind_speed_ms=6.0,
        wind_from_deg=45.0,
        rh_pct=30.0,
        temperature_c=33.0,
        resolution_m=500,
        seeds=(42, 43, 44),
        horizons_min=(60, 180, 360),
    )

    required_keys = [
        "current_perimeter_wkt",
        "p50_1h_wkt",
        "p50_3h_wkt",
        "p50_6h_wkt",
        "p90_1h_wkt",
        "p90_3h_wkt",
        "p90_6h_wkt",
    ]
    for key in required_keys:
        assert key in res
        assert isinstance(res[key], str)
        assert len(res[key]) > 0

    assert res["affected_area_km2"] >= 0
    assert res["confidence"] in ("low", "medium", "high")
    assert res["spread_direction_deg"] is None or 0.0 <= res["spread_direction_deg"] <= 360.0
    assert res["spread_rate_m_per_h"] >= 0.0


def test_ensemble_deterministic():
    kwargs: dict[str, Any] = dict(
        centroid_lat=11.72,
        centroid_lon=76.64,
        bbox_west=76.58,
        bbox_south=11.68,
        bbox_east=76.70,
        bbox_north=11.78,
        wind_speed_ms=5.0,
        wind_from_deg=90.0,
        rh_pct=35.0,
        temperature_c=30.0,
        resolution_m=500,
        seeds=(42, 43, 44),
        horizons_min=(60, 180, 360),
    )
    run1 = run_ensemble(**kwargs)
    run2 = run_ensemble(**kwargs)

    assert run1["p50_3h_wkt"] == run2["p50_3h_wkt"]
    assert run1["p90_3h_wkt"] == run2["p90_3h_wkt"]
    assert run1["affected_area_km2"] == run2["affected_area_km2"]
    assert run1["spread_direction_deg"] == run2["spread_direction_deg"]
    assert run1["spread_rate_m_per_h"] == run2["spread_rate_m_per_h"]
    assert run1["confidence"] == run2["confidence"]


def _wind_kwargs(wind_from_deg: float) -> dict[str, Any]:
    return dict(
        centroid_lat=11.72,
        centroid_lon=76.64,
        bbox_west=76.55,
        bbox_south=11.65,
        bbox_east=76.75,
        bbox_north=11.80,
        wind_speed_ms=8.0,
        wind_from_deg=wind_from_deg,
        rh_pct=30.0,
        temperature_c=33.0,
        resolution_m=500,
        seeds=(42, 43, 44),
    )


def test_ensemble_spreads_downwind_for_westerly_wind():
    res = run_ensemble(**_wind_kwargs(270.0))

    assert res["spread_direction_deg"] is not None
    assert 45.0 < res["spread_direction_deg"] < 135.0
    assert shapely_wkt.loads(res["p50_3h_wkt"]).centroid.x > 76.64


def test_ensemble_spreads_south_for_northerly_wind():
    res = run_ensemble(**_wind_kwargs(0.0))

    assert res["spread_direction_deg"] is not None
    assert 135.0 < res["spread_direction_deg"] < 225.0


def test_compute_fire_spread_passes_from_direction():
    cluster = HotspotCluster(
        centroid_lat=11.72,
        centroid_lon=76.64,
        point_count=3,
        bbox_west=76.63,
        bbox_south=11.71,
        bbox_east=76.65,
        bbox_north=11.73,
    )
    weather = WeatherSnapshot(
        valid_time=datetime.now(UTC),
        wind_speed_ms=8.0,
        wind_dir_deg=270.0,
        rh_pct=30.0,
        temperature_c=33.0,
    )
    result = compute_fire_spread(
        cluster, weather, bbox=(76.55, 11.65, 76.75, 11.80), resolution_m=500
    )

    assert result.spread_direction_deg is not None
    assert 45.0 < result.spread_direction_deg < 135.0


CELL_DEG_250 = 250 / 111_320.0


def _blocks(p50_cols: range, p50_rows: range = range(9, 12)) -> tuple[np.ndarray, np.ndarray]:
    ignition = np.zeros((21, 21), dtype=int)
    ignition[9:12, 9:12] = 1
    p50 = ignition.copy()
    for r in p50_rows:
        for c in p50_cols:
            p50[r, c] = 1
    return ignition, p50


def _metrics(ignition: np.ndarray, p50: np.ndarray, horizon_min: int) -> tuple[float | None, float]:
    return _spread_metrics(
        ignition,
        p50,
        bbox_north=11.80,
        bbox_west=76.55,
        cell_deg=CELL_DEG_250,
        resolution_m=250,
        horizon_min=horizon_min,
    )


def test_spread_metrics_east_only_advance():
    ignition, p50 = _blocks(range(12, 16))
    direction, rate = _metrics(ignition, p50, 60)

    assert direction is not None
    assert 80.0 < direction < 100.0
    assert 800.0 < rate < 1000.0

    _, rate_2h = _metrics(ignition, p50, 120)
    assert rate_2h == pytest.approx(rate / 2.0, rel=1e-9)


def test_spread_metrics_symmetric_growth_has_no_direction():
    ignition = np.zeros((21, 21), dtype=int)
    ignition[9:12, 9:12] = 1
    p50 = np.zeros((21, 21), dtype=int)
    p50[7:14, 7:14] = 1
    direction, rate = _metrics(ignition, p50, 60)

    assert direction is None
    assert rate > 0.0


def test_spread_metrics_empty_p50():
    ignition = np.zeros((21, 21), dtype=int)
    ignition[9:12, 9:12] = 1
    assert _metrics(ignition, np.zeros((21, 21), dtype=int), 60) == (None, 0.0)


def test_spread_metrics_ignore_raw_centroid_snapping():
    kwargs = _wind_kwargs(0.0)
    kwargs["wind_speed_ms"] = 0.0
    cell_deg = 500 / 111_320.0
    lat_a, lat_b = 11.72, 11.719
    assert round((11.80 - lat_a) / cell_deg) == round((11.80 - lat_b) / cell_deg)

    res_a = run_ensemble(**{**kwargs, "centroid_lat": lat_a})
    res_b = run_ensemble(**{**kwargs, "centroid_lat": lat_b})

    assert res_a["spread_direction_deg"] == res_b["spread_direction_deg"]
    assert res_a["spread_rate_m_per_h"] == res_b["spread_rate_m_per_h"]


def test_spread_metrics_use_actual_horizon():
    res = run_ensemble(**_wind_kwargs(270.0), horizons_min=(60, 120))

    assert res["p50_3h_wkt"] == "POLYGON EMPTY"
    assert res["spread_rate_m_per_h"] > 0.0
    # Front advance over 120 min, not 180 min: rate stays physically plausible
    # (cannot exceed the CA ceiling of one cell per 6-minute step = 500 m / 0.1 h).
    assert res["spread_rate_m_per_h"] <= 5000.0


def test_fire_spread_result_accepts_null_direction():
    base: dict[str, Any] = dict(
        cluster_id="c1",
        current_perimeter_wkt="POLYGON EMPTY",
        p50_1h_wkt="POLYGON EMPTY",
        p50_3h_wkt="POLYGON EMPTY",
        p50_6h_wkt="POLYGON EMPTY",
        p90_1h_wkt="POLYGON EMPTY",
        p90_3h_wkt="POLYGON EMPTY",
        p90_6h_wkt="POLYGON EMPTY",
        affected_area_km2=0.0,
        spread_rate_m_per_h=0.0,
        confidence="low",
    )
    assert FireSpreadResult(spread_direction_deg=None, **base).spread_direction_deg is None
    with pytest.raises(ValidationError):
        FireSpreadResult(spread_direction_deg=361.0, **base)
    with pytest.raises(ValidationError):
        FireSpreadResult(**base)

from datetime import UTC, datetime
from typing import Any

from agent_fire.ca_model import (
    _moisture_factor,
    _wind_factor,
    run_ensemble,
)
from agent_fire.ensemble import compute_fire_spread
from shapely import wkt as shapely_wkt
from wildfire_core.schemas.phase2 import HotspotCluster, WeatherSnapshot


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

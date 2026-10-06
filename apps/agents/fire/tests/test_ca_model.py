from agent_fire.ca_model import (
    _moisture_factor,
    _wind_factor,
    run_ensemble,
)


def test_wind_factor_downwind():
    # Wind speed 10 m/s blowing at 90 deg (East)
    downwind = _wind_factor(wind_speed_ms=10.0, wind_dir_deg=90.0, spread_dir_deg=90.0)
    upwind = _wind_factor(wind_speed_ms=10.0, wind_dir_deg=90.0, spread_dir_deg=270.0)
    crosswind = _wind_factor(wind_speed_ms=10.0, wind_dir_deg=90.0, spread_dir_deg=0.0)

    assert downwind == 1.0
    assert upwind < downwind
    assert crosswind < downwind
    assert upwind < crosswind


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
        wind_dir_deg=45.0,
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
    assert 0.0 <= res["spread_direction_deg"] <= 360.0
    assert res["spread_rate_m_per_h"] >= 0.0


def test_ensemble_deterministic():
    kwargs = dict(
        centroid_lat=11.72,
        centroid_lon=76.64,
        bbox_west=76.58,
        bbox_south=11.68,
        bbox_east=76.70,
        bbox_north=11.78,
        wind_speed_ms=5.0,
        wind_dir_deg=90.0,
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

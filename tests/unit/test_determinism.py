from wildfire_core.schemas.fire import FireRunInput


def test_same_fire_inputs_and_seed_are_equal() -> None:
    values = {
        "aoi_reference": "aoi-1",
        "hotspot_references": ("hotspot-1",),
        "weather_references": ("weather-1",),
        "parameters": {"spread_factor": 0.25},
        "seed": 7,
    }
    assert FireRunInput(**values) == FireRunInput(**values)

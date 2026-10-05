import pytest
from pydantic import ValidationError
from wildfire_core.schemas.fire import FirePerimeter, FireRunInput, FireRunOutput, SettlementRisk
from wildfire_core.schemas.metadata import Freshness


def _input(seed: int = 42) -> FireRunInput:
    return FireRunInput(
        aoi_reference="aoi-1",
        hotspot_references=("hotspot-1",),
        weather_references=("weather-1",),
        parameters={"wind_factor": 0.4},
        seed=seed,
    )


def test_fire_input_is_seeded_and_has_required_horizons() -> None:
    assert _input().model_dump() == _input().model_dump()
    assert _input().horizons_min == (60, 180, 360)


def test_fire_input_rejects_other_horizons() -> None:
    with pytest.raises(ValidationError):
        FireRunInput(
            aoi_reference="aoi-1",
            hotspot_references=("hotspot-1",),
            weather_references=("weather-1",),
            horizons_min=(60,),
            parameters={"wind_factor": 0.4},
            seed=42,
        )


def test_fire_output_contains_perimeters_and_settlement_risk() -> None:
    output = FireRunOutput(
        seed=42,
        perimeters=(
            FirePerimeter(
                kind="current",
                horizon_min=0,
                geometry_wkt="MULTIPOLYGON EMPTY",
                area_ha=1.2,
                freshness=Freshness(status="fresh", age_seconds=10),
            ),
        ),
        confidence_label="medium",
        settlement_risks=(
            SettlementRisk(settlement_id="settlement-1", exposure="inside_p90", eta_minutes=90),
        ),
    )
    assert output.settlement_risks[0].eta_minutes == 90

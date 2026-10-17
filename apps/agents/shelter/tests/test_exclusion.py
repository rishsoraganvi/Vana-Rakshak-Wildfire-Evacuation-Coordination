from __future__ import annotations

import math

from agent_shelter.registry import (
    CandidateList,
    exclusion_zone,
    list_candidate_shelters,
)
from shapely.geometry import Point
from wildfire_core.schemas.plan import ForecastFootprint, ShelterRecord

LAT = 11.72
LON = 76.64
EMPTY = "POLYGON EMPTY"
M_PER_DEG_LON = 111_195.0 * math.cos(math.radians(LAT))


def _box(west: float, south: float, east: float, north: float) -> str:
    return (
        f"POLYGON(({west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}))"
    )


# Roughly a 2 km x 2.2 km perimeter around the pilot centre.
P90_6H = _box(LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
CURRENT = _box(LON - 0.002, LAT - 0.002, LON + 0.002, LAT + 0.002)
EAST_EDGE = LON + 0.01


def _footprint(current: str = CURRENT, p90_6h: str = P90_6H) -> ForecastFootprint:
    return ForecastFootprint(
        current_wkt=current,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=p90_6h,
    )


def _empty_footprint() -> ForecastFootprint:
    return ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )


def _shelter(
    shelter_id: str,
    *,
    east_of_edge_m: float = 0.0,
    capacity: int = 100,
    occupancy: int = 0,
    is_active: bool = True,
    usable_factor: float | None = None,
) -> ShelterRecord:
    return ShelterRecord(
        shelter_id=shelter_id,
        external_ref=shelter_id,
        name=f"SYN {shelter_id}",
        kind="school",
        lat=LAT,
        lon=EAST_EDGE + east_of_edge_m / M_PER_DEG_LON,
        capacity=capacity,
        usable_factor=usable_factor,
        occupancy=occupancy,
        capacity_source="synthetic",
        is_active=is_active,
        is_simulated=True,
    )


def test_exclusion_zone_covers_perimeters_plus_buffer() -> None:
    zone = exclusion_zone(_footprint(), 1000)
    assert zone.contains(Point(LON, LAT))
    assert zone.contains(Point(EAST_EDGE + 900 / M_PER_DEG_LON, LAT))
    assert not zone.contains(Point(EAST_EDGE + 1500 / M_PER_DEG_LON, LAT))


def test_shelter_900m_outside_p90_6h_is_excluded_and_1500m_is_candidate() -> None:
    near = _shelter("a-near", east_of_edge_m=900)
    far = _shelter("b-far", east_of_edge_m=1500)
    result = list_candidate_shelters([near, far], _footprint(), buffer_m=1000, default_factor=0.6)
    assert [c.shelter_id for c in result.candidates] == ["b-far"]
    assert [(e.shelter_id, e.reason) for e in result.excluded] == [
        ("a-near", "inside_exclusion_zone")
    ]


def test_current_perimeter_alone_also_excludes() -> None:
    footprint = _footprint(current=CURRENT, p90_6h=EMPTY)
    inside = _shelter("inside").model_copy(update={"lon": LON})
    outside = _shelter("outside").model_copy(update={"lon": LON + 0.002 + 1500 / M_PER_DEG_LON})
    result = list_candidate_shelters(
        [inside, outside], footprint, buffer_m=1000, default_factor=0.6
    )
    assert [e.shelter_id for e in result.excluded] == ["inside"]
    assert [c.shelter_id for c in result.candidates] == ["outside"]


def test_inactive_and_no_capacity_reasons() -> None:
    shelters = [
        _shelter("c-inactive", east_of_edge_m=3000, is_active=False),
        _shelter("d-full", east_of_edge_m=3000, capacity=100, occupancy=60),
        _shelter("e-zero-usable", east_of_edge_m=3000, capacity=1, usable_factor=0.5),
        _shelter("f-ok", east_of_edge_m=3000, capacity=100, occupancy=10),
    ]
    result = list_candidate_shelters(shelters, _footprint(), buffer_m=1000, default_factor=0.6)
    reasons = {e.shelter_id: e.reason for e in result.excluded}
    assert reasons == {
        "c-inactive": "inactive",
        "d-full": "no_capacity",
        "e-zero-usable": "no_capacity",
    }
    assert [c.shelter_id for c in result.candidates] == ["f-ok"]
    assert result.candidates[0].available == 50


def test_empty_footprint_excludes_nothing_for_perimeter_reasons() -> None:
    shelters = [_shelter("a", east_of_edge_m=-500), _shelter("b")]
    result = list_candidate_shelters(
        shelters, _empty_footprint(), buffer_m=1000, default_factor=0.6
    )
    assert [c.shelter_id for c in result.candidates] == ["a", "b"]
    assert result.excluded == ()


def test_output_is_sorted_and_deterministic() -> None:
    shelters = [_shelter(x, east_of_edge_m=3000) for x in ("z", "m", "a")]
    first = list_candidate_shelters(shelters, _footprint(), buffer_m=1000, default_factor=0.6)
    second = list_candidate_shelters(
        list(reversed(shelters)), _footprint(), buffer_m=1000, default_factor=0.6
    )
    assert isinstance(first, CandidateList)
    assert first == second
    assert [c.shelter_id for c in first.candidates] == ["a", "m", "z"]

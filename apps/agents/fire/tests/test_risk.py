"""Behaviour tests for assess_risk (D-02, D-20, D-21, TechSpec 7.1)."""

from __future__ import annotations

import pytest
from agent_fire.risk import assess_risk
from shapely.geometry import MultiPolygon, Point, box
from shapely.geometry.base import BaseGeometry
from wildfire_core.geo.footprint import from_metric, to_metric
from wildfire_core.schemas.plan import ForecastFootprint, SettlementRecord

EMPTY = "POLYGON EMPTY"
LON, LAT = 76.64, 11.72
RATE = 1000.0


def settlement(
    settlement_id: str = "s1",
    *,
    lon: float = LON,
    lat: float = LAT,
    population: int | None = 120,
    buffer_m: int = 200,
) -> SettlementRecord:
    return SettlementRecord(
        settlement_id=settlement_id,
        name=f"Village {settlement_id}",
        lat=lat,
        lon=lon,
        population=population,
        pop_source="census",
        buffer_m=buffer_m,
        is_simulated=True,
    )


def metric_box(
    dx0: float, dy0: float, dx1: float, dy1: float, *, lon: float = LON, lat: float = LAT
) -> BaseGeometry:
    """Box with corners offset in metres from the point (lon, lat), returned in EPSG:4326."""
    origin = to_metric(Point(lon, lat))
    x, y = origin.x, origin.y
    return from_metric(box(x + dx0, y + dy0, x + dx1, y + dy1))


def around(half_m: float = 400.0, **kwargs: float) -> str:
    return metric_box(-half_m, -half_m, half_m, half_m, **kwargs).wkt


def footprint(**overrides: str) -> ForecastFootprint:
    base = {
        "current_wkt": EMPTY,
        "p50_1h_wkt": EMPTY,
        "p50_3h_wkt": EMPTY,
        "p50_6h_wkt": EMPTY,
        "p90_1h_wkt": EMPTY,
        "p90_3h_wkt": EMPTY,
        "p90_6h_wkt": EMPTY,
    }
    base.update(overrides)
    return ForecastFootprint(**base)


def far_box() -> str:
    """A square roughly 20 km north of the settlement, so it never touches the buffer."""
    return metric_box(-300, 20_000, 300, 20_600).wkt


def test_point_inside_current_is_rescue_and_others_still_assessed() -> None:
    inside = settlement("a_inside", lon=LON, lat=LAT)
    other = settlement("b_other", lon=LON + 0.05, lat=LAT)
    fp = footprint(
        current_wkt=around(300),
        p50_1h_wkt=metric_box(-300, -300, 300, 300, lon=LON + 0.05).wkt,
    )
    result = assess_risk([other, inside], fp, spread_rate_m_per_h=RATE)
    assert [item.settlement_id for item in result.rescue_alerts] == ["a_inside"]
    assert result.rescue_alerts[0].kind == "needs_rescue_response"
    assert "needs rescue response" in result.rescue_alerts[0].message
    assert [item.group_id for item in result.groups] == ["b_other"]


def test_buffer_touching_current_with_point_outside_is_priority_one_eta_zero() -> None:
    # Perimeter starts 100 m east of the point; the 200 m buffer reaches it.
    fp = footprint(current_wkt=metric_box(100, -300, 700, 300).wkt)
    result = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE)
    assert not result.rescue_alerts
    (group,) = result.groups
    assert group.exposure == "buffer_in_current"
    assert group.priority == 1
    assert group.eta_min == 0


def test_first_p50_hit_at_1h_is_priority_one_eta_within_first_hour() -> None:
    fp = footprint(p50_1h_wkt=around(), p50_3h_wkt=around(800), p50_6h_wkt=around(1200))
    (group,) = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE).groups
    assert group.exposure == "inside_p50_1h"
    assert group.priority == 1
    assert 0 <= group.eta_min <= 60


def test_first_p50_hit_at_3h_is_priority_two_eta_in_second_bracket() -> None:
    fp = footprint(p50_1h_wkt=far_box(), p50_3h_wkt=around(), p50_6h_wkt=around(1200))
    (group,) = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE).groups
    assert group.exposure == "inside_p50_3h"
    assert group.priority == 2
    assert 60 <= group.eta_min <= 180


def test_first_p50_hit_at_6h_is_priority_three_eta_in_third_bracket() -> None:
    fp = footprint(p50_1h_wkt=far_box(), p50_3h_wkt=far_box(), p50_6h_wkt=around())
    (group,) = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE).groups
    assert group.exposure == "inside_p50_6h"
    assert group.priority == 3
    assert 180 <= group.eta_min <= 360


def test_eta_is_interpolated_from_distance_and_spread_rate() -> None:
    # Buffer (200 m) is 500 m from P50_1h, which sits north of the point; P50_3h covers it.
    previous = metric_box(-300, 700, 300, 1300).wkt
    fp = footprint(p50_1h_wkt=previous, p50_3h_wkt=around(), p50_6h_wkt=around(1200))
    settlements = [settlement()]
    (group,) = assess_risk(settlements, fp, spread_rate_m_per_h=1000.0).groups
    assert group.eta_min in (89, 90)  # 60 + 500 m / 1000 m/h * 60 = 90 minutes
    (stalled,) = assess_risk(settlements, fp, spread_rate_m_per_h=0.0).groups
    assert stalled.eta_min == 60
    (slow,) = assess_risk(settlements, fp, spread_rate_m_per_h=1.0).groups
    assert slow.eta_min == 180  # distance beyond the bracket clamps to t_B


def test_empty_previous_perimeter_uses_the_horizon_time() -> None:
    fp = footprint(p50_3h_wkt=around(), p50_6h_wkt=around(1200))
    (group,) = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE).groups
    assert group.eta_min == 180


def test_p90_only_exposure_warns_without_a_group() -> None:
    fp = footprint(p90_3h_wkt=around(), p90_6h_wkt=around(1200))
    result = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE)
    assert not result.groups
    (alert,) = result.p90_only_alerts
    assert alert.kind == "p90_only_exposure"
    assert alert.settlement_id == "s1"
    assert "3h" in alert.message


def test_p50_exposure_wins_over_p90() -> None:
    fp = footprint(p50_6h_wkt=around(), p90_1h_wkt=around())
    result = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE)
    assert [item.exposure for item in result.groups] == ["inside_p50_6h"]
    assert not result.p90_only_alerts


def test_no_intersection_yields_nothing() -> None:
    fp = footprint(current_wkt=far_box(), p50_3h_wkt=far_box(), p90_6h_wkt=far_box())
    result = assess_risk([settlement()], fp, spread_rate_m_per_h=RATE)
    assert result.groups == ()
    assert result.rescue_alerts == ()
    assert result.p90_only_alerts == ()
    assert result.unknown_population == ()


@pytest.mark.parametrize("population", [None, 0])
def test_unknown_population_is_reported_not_guessed(population: int | None) -> None:
    fp = footprint(p50_1h_wkt=around())
    result = assess_risk([settlement(population=population)], fp, spread_rate_m_per_h=RATE)
    assert result.groups == ()
    assert result.unknown_population == ("s1",)


def test_unknown_population_outside_the_forecast_is_not_reported() -> None:
    fp = footprint(p50_1h_wkt=far_box())
    result = assess_risk([settlement(population=None)], fp, spread_rate_m_per_h=RATE)
    assert result.unknown_population == ()


def test_results_are_sorted_deterministic_and_keyed_on_settlement() -> None:
    fp = footprint(p50_1h_wkt=around(), p50_3h_wkt=around(800))
    shuffled = [settlement("c"), settlement("a"), settlement("b")]
    first = assess_risk(shuffled, fp, spread_rate_m_per_h=RATE)
    second = assess_risk(list(reversed(shuffled)), fp, spread_rate_m_per_h=RATE)
    assert first == second
    assert [item.group_id for item in first.groups] == ["a", "b", "c"]
    assert all(item.group_id == item.settlement_id for item in first.groups)
    assert all(item.persons == 120 and item.origin_node is None for item in first.groups)
    assert all(item.is_simulated and item.pop_source == "census" for item in first.groups)


def test_multi_cluster_union_assesses_settlements_near_either_cluster() -> None:
    east = metric_box(-300, -300, 300, 300, lon=LON + 0.1)
    west = metric_box(-300, -300, 300, 300)
    union = MultiPolygon([east, west])
    fp = footprint(p50_1h_wkt=union.wkt)
    near_west = settlement("west")
    near_east = settlement("east", lon=LON + 0.1)
    result = assess_risk([near_west, near_east], fp, spread_rate_m_per_h=RATE)
    assert [item.group_id for item in result.groups] == ["east", "west"]

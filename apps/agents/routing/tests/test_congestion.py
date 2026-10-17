from __future__ import annotations

import pytest
from agent_routing import apply_horizon_costs
from agent_routing.congestion import (
    apply_congestion,
    bpr_time,
    edge_capacity_vph,
    edge_flows_vph,
    msa_blend,
    parse_tag,
)
from hypothesis import given
from hypothesis import strategies as st
from wildfire_core.schemas.plan import ForecastFootprint

from tests.fixtures.graphs import build_synthetic_graph

LANE_CAPACITY = {
    "motorway": 1800,
    "trunk": 1600,
    "primary": 1400,
    "secondary": 1100,
    "tertiary": 900,
    "default": 600,
}
LINK_FACTOR = 0.8
EMPTY = "POLYGON EMPTY"


def _capacity(data: dict[str, object]) -> float:
    return edge_capacity_vph(data, lane_capacity=LANE_CAPACITY, link_factor=LINK_FACTOR)


def test_bpr_time_zero_flow_is_free_flow() -> None:
    assert bpr_time(60.0, 0.0, 1400.0, alpha=0.15, beta=4.0) == 60.0


def test_bpr_time_at_capacity_adds_alpha_share() -> None:
    assert bpr_time(60.0, 1400.0, 1400.0, alpha=0.15, beta=4.0) == pytest.approx(69.0)


def test_bpr_time_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        bpr_time(60.0, 10.0, 0.0, alpha=0.15, beta=4.0)


@given(
    t0=st.floats(min_value=0.0, max_value=1e5),
    flow_a=st.floats(min_value=0.0, max_value=1e4),
    flow_b=st.floats(min_value=0.0, max_value=1e4),
    capacity=st.floats(min_value=1.0, max_value=1e4),
)
def test_bpr_time_is_monotone_in_flow_and_never_below_free_flow(
    t0: float, flow_a: float, flow_b: float, capacity: float
) -> None:
    low, high = sorted((flow_a, flow_b))
    time_low = bpr_time(t0, low, capacity, alpha=0.15, beta=4.0)
    time_high = bpr_time(t0, high, capacity, alpha=0.15, beta=4.0)

    assert time_low >= t0
    assert time_high >= time_low


def test_parse_tag_handles_list_strings_scalars_and_none() -> None:
    assert parse_tag("['1', '2']") == ["1", "2"]
    assert parse_tag("2") == ["2"]
    assert parse_tag(None) == []
    assert parse_tag(["a", "b"]) == ["a", "b"]
    assert parse_tag(2) == ["2"]


@pytest.mark.parametrize("value", ["[unterminated", "['1', ", "[__import__('os').getcwd()]"])
def test_parse_tag_malformed_or_hostile_list_string_never_raises(value: str) -> None:
    assert parse_tag(value) == [value]


def test_capacity_two_way_primary_two_lanes_is_one_lane_per_direction() -> None:
    assert _capacity({"highway": "primary", "lanes": "2"}) == 1400


def test_capacity_one_way_uses_all_lanes() -> None:
    assert _capacity({"highway": "primary", "lanes": "2", "oneway": True}) == 2800
    assert _capacity({"highway": "primary", "lanes": "2", "oneway": "True"}) == 2800


def test_capacity_missing_lanes_is_one_lane() -> None:
    assert _capacity({"highway": "primary"}) == 1400
    assert _capacity({"highway": "primary", "oneway": True}) == 1400


def test_capacity_link_class_applies_link_factor() -> None:
    assert _capacity({"highway": "primary_link", "lanes": "1"}) == pytest.approx(1400 * 0.8)


def test_capacity_list_highway_uses_lowest_capacity_class() -> None:
    assert _capacity({"highway": "['primary', 'tertiary']", "lanes": "2"}) == 900
    assert _capacity({"highway": ["primary", "secondary"], "lanes": "2"}) == 1100


def test_capacity_list_lanes_is_conservative_and_unknown_class_uses_default() -> None:
    assert _capacity({"highway": "secondary", "lanes": "['1', '2']", "oneway": True}) == 1100
    assert _capacity({"highway": "bridleway", "lanes": "2", "oneway": True}) == 1200
    assert _capacity({"highway": "primary", "lanes": "many"}) == 1400


def test_edge_flows_convert_persons_to_vehicles_per_hour_and_add_across_legs() -> None:
    edges = [(1, 2, 0), (2, 3, 0)]

    flows = edge_flows_vph(
        [(edges, 400), ([(2, 3, 0)], 200)], persons_per_vehicle=4, evac_window_h=2
    )

    assert flows[(1, 2, 0)] == pytest.approx(50.0)
    assert flows[(2, 3, 0)] == pytest.approx(75.0)


def test_msa_blend_first_iteration_takes_new_and_second_averages_union() -> None:
    previous = {(1, 2, 0): 100.0, (2, 3, 0): 40.0}
    new = {(1, 2, 0): 200.0, (3, 4, 0): 60.0}

    assert msa_blend(previous, new, 1) == new
    assert msa_blend(previous, new, 2) == {
        (1, 2, 0): 150.0,
        (2, 3, 0): 20.0,
        (3, 4, 0): 30.0,
    }


def test_msa_blend_rejects_iteration_below_one() -> None:
    with pytest.raises(ValueError, match="iteration"):
        msa_blend({}, {}, 0)


def _horizon_graph():
    footprint = ForecastFootprint(
        current_wkt=EMPTY,
        p50_1h_wkt=EMPTY,
        p50_3h_wkt=EMPTY,
        p50_6h_wkt=EMPTY,
        p90_1h_wkt=EMPTY,
        p90_3h_wkt=EMPTY,
        p90_6h_wkt=EMPTY,
    )
    return apply_horizon_costs(build_synthetic_graph(), footprint, p50_mult=10.0, p90_mult=3.0)


def test_apply_congestion_slows_loaded_edges_and_refreshes_horizon_costs() -> None:
    graph = _horizon_graph()
    base = graph[1][2][0]["travel_time"]
    flows = {(1, 2, 0): 1400.0}  # primary, lanes 2, two-way: capacity 1400

    max_vc = apply_congestion(
        graph,
        flows,
        alpha=0.15,
        beta=4.0,
        lane_capacity=LANE_CAPACITY,
        link_factor=LINK_FACTOR,
    )

    loaded = graph[1][2][0]
    assert max_vc == pytest.approx(1.0)
    assert loaded["vc_ratio"] == pytest.approx(1.0)
    assert loaded["congested_time"] == pytest.approx(base * 1.15)
    assert loaded["cost_h1"] == pytest.approx(base * 1.15)
    assert loaded["cost_h6"] == pytest.approx(base * 1.15)


def test_apply_congestion_leaves_unloaded_edges_at_free_flow() -> None:
    graph = _horizon_graph()

    max_vc = apply_congestion(
        graph,
        {(1, 2, 0): 700.0},
        alpha=0.15,
        beta=4.0,
        lane_capacity=LANE_CAPACITY,
        link_factor=LINK_FACTOR,
    )

    other = graph[2][3][0]
    assert other["congested_time"] == other["travel_time"]
    assert other["vc_ratio"] == 0.0
    assert other["cost_h3"] == other["travel_time"]
    assert max_vc == pytest.approx(0.5)


def test_apply_congestion_keeps_blocked_edges_blocked_and_handles_no_flow() -> None:
    graph = _horizon_graph()
    graph[1][2][0]["fire_mult_h1"] = float("inf")

    max_vc = apply_congestion(
        graph, {}, alpha=0.15, beta=4.0, lane_capacity=LANE_CAPACITY, link_factor=LINK_FACTOR
    )

    assert max_vc == 0.0
    assert graph[1][2][0]["cost_h1"] == float("inf")

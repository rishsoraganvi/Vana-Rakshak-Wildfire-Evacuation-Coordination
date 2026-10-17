from __future__ import annotations

from math import inf

import networkx as nx
import pytest
from agent_routing import (
    apply_horizon_costs,
    build_route_edges,
    evaluate_path,
    refresh_horizon_costs,
    route_cost_matrix,
    snap_points,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from wildfire_core.schemas.plan import ForecastFootprint

from tests.fixtures.graphs import CORNER_NE, CORNER_SW, DEAD_END, build_synthetic_graph

EMPTY = "POLYGON EMPTY"
P50_MULT = 10.0
P90_MULT = 3.0

# Synthetic lattice: lon 76.60..76.65, lat 11.68..11.73 (node 1 is the SW corner).
GRID_SQUARE = (76.59, 11.67, 76.67, 11.75)


def _square(x0: float, y0: float, x1: float, y1: float) -> str:
    return f"POLYGON (({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"


def _footprint(**fields: str) -> ForecastFootprint:
    values = {
        "current_wkt": EMPTY,
        "p50_1h_wkt": EMPTY,
        "p50_3h_wkt": EMPTY,
        "p50_6h_wkt": EMPTY,
        "p90_1h_wkt": EMPTY,
        "p90_3h_wkt": EMPTY,
        "p90_6h_wkt": EMPTY,
    }
    values.update(fields)
    return ForecastFootprint(**values)


def _costs(graph: nx.MultiDiGraph, footprint: ForecastFootprint, **kwargs) -> nx.MultiDiGraph:
    return apply_horizon_costs(graph, footprint, p50_mult=P50_MULT, p90_mult=P90_MULT, **kwargs)


# A box straddling the chord between nodes 1 (76.60, 11.68) and 2 (76.61, 11.68) only.
EDGE_1_2_BOX = _square(76.604, 11.679, 76.606, 11.681)
# A box straddling the chord between nodes 2 (76.61, 11.68) and 3 (76.62, 11.68) only.
EDGE_2_3_BOX = _square(76.614, 11.679, 76.616, 11.681)


def test_current_perimeter_blocks_covered_edges_on_all_horizons() -> None:
    graph = build_synthetic_graph()

    result = _costs(graph, _footprint(current_wkt=EDGE_1_2_BOX))

    for u, v in ((1, 2), (2, 1)):
        data = result[u][v][0]
        assert data["blocked"] is True
        assert data["cost_h1"] == data["cost_h3"] == data["cost_h6"] == inf
        assert data["zone_h1"] == data["zone_h3"] == data["zone_h6"] == "blocked"
    assert result[2][3][0]["blocked"] is False
    assert "blocked" not in graph[1][2][0]  # input graph is never mutated


def test_p50_3h_only_penalises_cost_h3() -> None:
    result = _costs(build_synthetic_graph(), _footprint(p50_3h_wkt=EDGE_2_3_BOX))

    data = result[2][3][0]
    assert data["cost_h1"] == pytest.approx(data["travel_time"])
    assert data["cost_h3"] == pytest.approx(10 * data["travel_time"])
    assert data["cost_h6"] == pytest.approx(data["travel_time"])
    assert (data["zone_h1"], data["zone_h3"], data["zone_h6"]) == ("safe", "p50", "safe")
    assert data["blocked"] is False


def test_p90_1h_triples_cost_h1() -> None:
    result = _costs(build_synthetic_graph(), _footprint(p90_1h_wkt=EDGE_2_3_BOX))

    data = result[2][3][0]
    assert data["cost_h1"] == pytest.approx(3 * data["travel_time"])
    assert data["zone_h1"] == "p90"
    assert data["fire_mult_h1"] == P90_MULT
    assert data["cost_h3"] == pytest.approx(data["travel_time"])


def test_p50_takes_precedence_over_p90_on_same_horizon() -> None:
    footprint = _footprint(p50_1h_wkt=EDGE_2_3_BOX, p90_1h_wkt=EDGE_2_3_BOX)

    data = _costs(build_synthetic_graph(), footprint)[2][3][0]

    assert data["zone_h1"] == "p50"
    assert data["cost_h1"] == pytest.approx(10 * data["travel_time"])


@pytest.mark.parametrize("status", ["blocked", "unsafe"])
def test_blocking_edge_status_blocks_only_that_edge(status: str) -> None:
    result = _costs(build_synthetic_graph(), _footprint(), edge_status={(1, 2, 0): status})

    assert result[1][2][0]["blocked"] is True
    assert result[1][2][0]["cost_h3"] == inf
    assert result[1][2][0]["edge_status"] == status
    assert result[2][1][0]["blocked"] is False


def test_congested_status_changes_nothing() -> None:
    graph = build_synthetic_graph()

    result = _costs(graph, _footprint(), edge_status={(1, 2, 0): "congested"})

    data = result[1][2][0]
    assert data["blocked"] is False
    assert data["edge_status"] == "congested"
    assert data["cost_h1"] == data["cost_h3"] == data["cost_h6"] == pytest.approx(
        graph[1][2][0]["travel_time"]
    )


def test_refresh_horizon_costs_follows_congested_time() -> None:
    result = _costs(build_synthetic_graph(), _footprint(p90_1h_wkt=EDGE_2_3_BOX))
    data = result[2][3][0]
    data["congested_time"] = 2 * data["travel_time"]

    refresh_horizon_costs(result)

    assert data["cost_h1"] == pytest.approx(6 * data["travel_time"])
    assert data["cost_h3"] == pytest.approx(2 * data["travel_time"])


_BASE_GRAPH = build_synthetic_graph()
_COORD = st.floats(min_value=76.60, max_value=76.65, allow_nan=False)
_LAT = st.floats(min_value=11.68, max_value=11.73, allow_nan=False)
_RADIUS = st.floats(min_value=0.001, max_value=0.02, allow_nan=False)


def _nested_boxes(cx: float, cy: float, radii: list[float]) -> list[str]:
    return [_square(cx - r, cy - r, cx + r, cy + r) for r in sorted(radii)]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cx=_COORD,
    cy=_LAT,
    p50_radii=st.lists(_RADIUS, min_size=3, max_size=3),
    p90_radii=st.lists(_RADIUS, min_size=3, max_size=3),
)
def test_nested_perimeters_give_non_decreasing_horizon_costs(
    cx: float, cy: float, p50_radii: list[float], p90_radii: list[float]
) -> None:
    p50 = _nested_boxes(cx, cy, p50_radii)
    p90 = _nested_boxes(cx, cy, p90_radii)
    footprint = _footprint(
        p50_1h_wkt=p50[0],
        p50_3h_wkt=p50[1],
        p50_6h_wkt=p50[2],
        p90_1h_wkt=p90[0],
        p90_3h_wkt=p90[1],
        p90_6h_wkt=p90[2],
    )

    result = _costs(_BASE_GRAPH, footprint)

    for _u, _v, data in result.edges(data=True):
        assert data["cost_h1"] <= data["cost_h3"] <= data["cost_h6"]


def _scaled_graph(total_minutes: float) -> nx.MultiDiGraph:
    """Synthetic graph whose CORNER_SW to CORNER_NE free-flow time is ``total_minutes``."""
    graph = build_synthetic_graph()
    base = nx.single_source_dijkstra_path_length(graph, CORNER_SW, weight="travel_time")[CORNER_NE]
    factor = total_minutes * 60.0 / base
    for _u, _v, data in graph.edges(data=True):
        data["travel_time"] *= factor
    return graph


def test_cost_matrix_uses_horizon_nearest_free_flow_time() -> None:
    footprint = _footprint(p90_3h_wkt=_square(*GRID_SQUARE))
    origins = {"s": CORNER_SW}
    targets = {"sh": CORNER_NE}

    short = route_cost_matrix(_costs(_scaled_graph(50), footprint), origins, targets)[("s", "sh")]
    long = route_cost_matrix(_costs(_scaled_graph(125), footprint), origins, targets)[("s", "sh")]

    assert short is not None and long is not None
    assert short.horizon_h == 1
    assert short.free_flow_s == pytest.approx(50 * 60)
    assert short.cost_s == pytest.approx(short.free_flow_s)  # h1 has no p90 penalty
    assert long.horizon_h == 3
    assert long.free_flow_s == pytest.approx(125 * 60)
    assert long.cost_s == pytest.approx(3 * long.free_flow_s)  # whole grid is p90 at h3


def test_cost_matrix_same_node_is_free_and_sorted_deterministic() -> None:
    graph = _costs(build_synthetic_graph(), _footprint())

    matrix = route_cost_matrix(graph, {"b": CORNER_SW, "a": 2}, {"x": CORNER_SW})

    assert matrix[("b", "x")] is not None
    assert (matrix[("b", "x")].cost_s, matrix[("b", "x")].horizon_h) == (0.0, 1)  # type: ignore[union-attr]
    assert list(matrix) == [("a", "x"), ("b", "x")]


def test_cost_matrix_unreachable_target_is_none() -> None:
    status = {(CORNER_NE, DEAD_END, 0): "blocked", (DEAD_END, CORNER_NE, 0): "blocked"}
    graph = _costs(build_synthetic_graph(), _footprint(), edge_status=status)

    matrix = route_cost_matrix(graph, {"s": CORNER_SW}, {"dead": DEAD_END, "ne": CORNER_NE})

    assert matrix[("s", "dead")] is None
    assert matrix[("s", "ne")] is not None


def test_cost_matrix_routes_around_blocked_edges() -> None:
    open_graph = _costs(build_synthetic_graph(), _footprint())
    blocked_graph = _costs(build_synthetic_graph(), _footprint(current_wkt=EDGE_1_2_BOX))

    open_leg = route_cost_matrix(open_graph, {"s": CORNER_SW}, {"t": CORNER_NE})[("s", "t")]
    blocked_leg = route_cost_matrix(blocked_graph, {"s": CORNER_SW}, {"t": CORNER_NE})[("s", "t")]

    assert open_leg is not None and blocked_leg is not None
    assert blocked_leg.cost_s >= open_leg.cost_s


def test_snap_points_returns_none_when_farther_than_max_snap() -> None:
    graph = build_synthetic_graph()
    far_south = (11.68 - 0.027, 76.60)  # about 3 km below the SW corner

    snapped = snap_points(
        graph, {"far": far_south, "near": (11.68, 76.60)}, perimeter_wkt=EMPTY, max_snap_m=2000
    )

    assert snapped == {"far": None, "near": CORNER_SW}


def test_snap_points_skips_nodes_inside_current_perimeter() -> None:
    graph = build_synthetic_graph()
    perimeter = _square(76.595, 11.675, 76.605, 11.685)  # covers node 1 only

    snapped = snap_points(graph, {"p": (11.68, 76.60)}, perimeter_wkt=perimeter, max_snap_m=2000)

    assert snapped == {"p": 2}


def _flat_graph(edge_seconds: float) -> nx.MultiDiGraph:
    graph = build_synthetic_graph()
    for _u, _v, data in graph.edges(data=True):
        data["travel_time"] = edge_seconds
    return graph


def test_evaluate_path_flags_p50_edge_reached_at_minute_30() -> None:
    graph = _costs(_flat_graph(900.0), _footprint(p50_1h_wkt=EDGE_2_3_BOX))
    node_path = [1, 2, 3]
    keys = build_route_edges(graph, node_path, "cost_h1")

    evaluation = evaluate_path(graph, node_path, keys)

    assert keys == (0, 0)
    assert evaluation.arrival_end_s == (900.0, 1800.0)
    assert evaluation.horizons == (1, 1)
    assert evaluation.zones == ("safe", "p50")
    assert evaluation.p50_idx == (1,)
    assert evaluation.blocked_idx == ()
    assert evaluation.safe is False
    assert evaluation.total_time_s == 1800.0
    assert evaluation.risk_score == pytest.approx(0.5)


def test_evaluate_path_uses_later_horizon_zone_for_late_arrival() -> None:
    graph = _costs(_flat_graph(3600.0), _footprint(p50_3h_wkt=EDGE_2_3_BOX))
    keys = build_route_edges(graph, [1, 2, 3], "cost_h1")

    evaluation = evaluate_path(graph, [1, 2, 3], keys)

    # Edge 1 ends at 120 min, a tie that goes to horizon 3 where the edge is p50.
    assert evaluation.horizons == (1, 3)
    assert evaluation.p50_idx == (1,)
    assert evaluation.safe is False


def test_evaluate_path_safe_path_and_p90_exposure() -> None:
    graph = _costs(_flat_graph(600.0), _footprint(p90_1h_wkt=EDGE_2_3_BOX))
    keys = build_route_edges(graph, [1, 2, 3], "cost_h1")

    evaluation = evaluate_path(graph, [1, 2, 3], keys)

    assert evaluation.p90_idx == (1,)
    assert evaluation.safe is True
    assert 0 < evaluation.risk_score <= 1


def test_build_route_edges_prefers_cheaper_parallel_edge_and_skips_blocked() -> None:
    graph = _costs(build_synthetic_graph(), _footprint())
    assert build_route_edges(graph, [2, 3], "cost_h1") == (0,)  # key 0 is cheaper than key 1

    blocked = _costs(build_synthetic_graph(), _footprint(), edge_status={(2, 3, 0): "blocked"})
    assert build_route_edges(blocked, [2, 3], "cost_h1") == (1,)


def test_evaluate_path_rejects_mismatched_key_count() -> None:
    graph = _costs(build_synthetic_graph(), _footprint())

    with pytest.raises(ValueError, match="one key per hop"):
        evaluate_path(graph, [1, 2, 3], (0,))

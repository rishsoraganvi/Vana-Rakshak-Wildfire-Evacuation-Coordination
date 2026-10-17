"""Shared builders for validator tests: footprints, routes, groups, candidates, contexts."""

from __future__ import annotations

from collections.abc import Sequence

from coordinator.validators.runner import ValidationContext
from shapely.geometry import box
from wildfire_core.geo.footprint import load_footprint
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ForecastFootprint,
    PlanRoute,
    ShelterAssignment,
    ShelterCandidate,
)

from tests.fixtures.graphs import build_synthetic_graph

EMPTY = "POLYGON EMPTY"
NODE_1 = (76.60, 11.68)
NODE_8 = (76.61, 11.69)
NODE_36 = (76.65, 11.73)
SAFE_PATH = (1, 2, 3, 9, 15)
FIRE_PATH = (1, 7, 8, 9, 15)


def square(center: tuple[float, float], half_deg: float) -> str:
    lon, lat = center
    return box(lon - half_deg, lat - half_deg, lon + half_deg, lat + half_deg).wkt


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


def make_route(
    path: Sequence[int],
    keys: Sequence[int] | None = None,
    *,
    group_id: str = "g1",
    shelter_id: str = "s1",
    persons: int = 40,
    origin: int | None = None,
    destination: int | None = None,
) -> PlanRoute:
    return PlanRoute(
        group_id=group_id,
        shelter_id=shelter_id,
        persons=persons,
        origin_node=path[0] if origin is None else origin,
        destination_node=path[-1] if destination is None else destination,
        osm_node_path=tuple(path),
        osm_edge_keys=tuple(keys) if keys is not None else (0,) * (len(path) - 1),
        total_distance_m=1000.0,
        free_flow_time_s=100.0,
        congested_time_s=100.0,
        eta_min=2.0,
        horizon_h=1,
        path_rank=1,
        risk_score=0.0,
        safety_classification="safe",
    )


def make_group(group_id: str = "g1", persons: int = 40, origin: int | None = 1) -> EvacueeGroup:
    return EvacueeGroup(
        group_id=group_id,
        settlement_id=group_id,
        settlement_name=f"Settlement {group_id}",
        persons=persons,
        priority=1,
        eta_min=30.0,
        exposure="inside_p50_1h",
        origin_node=origin,
    )


def make_candidate(
    shelter_id: str = "s1", node: int | None = 15, available: int = 100
) -> ShelterCandidate:
    return ShelterCandidate(
        shelter_id=shelter_id,
        name=f"Shelter {shelter_id}",
        kind="school",
        lat=11.70,
        lon=76.62,
        usable_capacity=available,
        occupancy=0,
        available=available,
        capacity_source="test",
        node=node,
    )


def make_assignment(
    group_id: str = "g1",
    shelter_id: str = "s1",
    persons: int = 40,
    *,
    available: int = 100,
) -> ShelterAssignment:
    return ShelterAssignment(
        shelter_id=shelter_id,
        shelter_name=f"Shelter {shelter_id}",
        group_id=group_id,
        persons=persons,
        usable_capacity=available,
        available_before=available,
    )


def make_ctx(
    fp: ForecastFootprint,
    *,
    edge_status: dict[tuple[int, int, int], str] | None = None,
    groups: Sequence[EvacueeGroup] | None = None,
    candidates: Sequence[ShelterCandidate] | None = None,
    clusters: frozenset[str] = frozenset({"c1"}),
) -> ValidationContext:
    group_list = [make_group()] if groups is None else list(groups)
    candidate_list = [make_candidate()] if candidates is None else list(candidates)
    return ValidationContext(
        graph=build_synthetic_graph(),
        footprint=load_footprint(fp),
        edge_status=edge_status or {},
        groups={item.group_id: item for item in group_list},
        candidates={item.shelter_id: item for item in candidate_list},
        known_settlement_ids=frozenset(item.group_id for item in group_list),
        known_shelter_ids=frozenset(item.shelter_id for item in candidate_list),
        fire_cluster_ids=clusters,
    )

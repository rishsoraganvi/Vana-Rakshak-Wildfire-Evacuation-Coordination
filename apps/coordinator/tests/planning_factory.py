"""Shared builders for the planning core tests: params, routing context, inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent_routing.costs import apply_horizon_costs
from coordinator.planning.params import PlanningParams
from coordinator.planning.plan_core import PlanInputs, RoutingContext
from validator_factory import footprint, make_candidate, make_group
from wildfire_core.config import load_settings
from wildfire_core.geo.footprint import load_footprint
from wildfire_core.schemas.plan import EvacueeGroup, ForecastFootprint, ShelterCandidate

from tests.fixtures.graphs import build_synthetic_graph


def make_params(**overrides: Any) -> PlanningParams:
    params = PlanningParams.from_settings(load_settings())
    return params.model_copy(update=overrides) if overrides else params


def make_routing_ctx(
    fp: ForecastFootprint | None = None,
    *,
    edge_status: Mapping[tuple[int, int, int], str] | None = None,
    params: PlanningParams | None = None,
) -> RoutingContext:
    fp = fp or footprint()
    params = params or make_params()
    status = dict(edge_status or {})
    graph = apply_horizon_costs(
        build_synthetic_graph(),
        fp,
        p50_mult=params.p50_mult,
        p90_mult=params.p90_mult,
        edge_status=status,
    )
    return RoutingContext(
        graph=graph,
        footprint=fp,
        loaded=load_footprint(fp),
        edge_status=status,
        graph_source="synthetic",
        graph_mtime=None,
    )


def group(group_id: str, persons: int, node: int | None, priority: int = 1) -> EvacueeGroup:
    return make_group(group_id, persons, node).model_copy(update={"priority": priority})


def shelter(shelter_id: str, node: int | None, available: int) -> ShelterCandidate:
    return make_candidate(shelter_id, node, available)


def make_inputs(
    groups: Sequence[EvacueeGroup],
    candidates: Sequence[ShelterCandidate],
    **overrides: Any,
) -> PlanInputs:
    return PlanInputs(
        incident_id=overrides.pop("incident_id", "inc-1"),
        run_id=overrides.pop("run_id", "run-1"),
        groups=tuple(groups),
        candidates=tuple(candidates),
        **overrides,
    )

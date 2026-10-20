"""Settlement risk assessment: forecast footprint to evacuee groups (TechSpec 7.1, D-02/D-20/D-21).

Units: ``eta_min`` is minutes from now, ``buffer_m`` and distances are metres (EPSG:32643),
``spread_rate_m_per_h`` is metres per hour. Coordinates are (lon, lat) in EPSG:4326.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from wildfire_core.geo.footprint import LoadedFootprint, buffer_metric, load_footprint, to_metric
from wildfire_core.geo.horizons import HORIZONS_H
from wildfire_core.schemas.plan import (
    EvacueeGroup,
    ForecastFootprint,
    PlanAlert,
    SettlementRecord,
)

_PRIORITY_BY_HORIZON = {1: 1, 3: 2, 6: 3}  # A7: earlier inclusion means higher priority
_EXPOSURE_BY_HORIZON: dict[int, Literal["inside_p50_1h", "inside_p50_3h", "inside_p50_6h"]] = {
    1: "inside_p50_1h",
    3: "inside_p50_3h",
    6: "inside_p50_6h",
}


@dataclass(frozen=True)
class RiskAssessment:
    """Outcome of ``assess_risk``; every collection is sorted by settlement_id."""

    groups: tuple[EvacueeGroup, ...]
    rescue_alerts: tuple[PlanAlert, ...]
    p90_only_alerts: tuple[PlanAlert, ...]
    unknown_population: tuple[str, ...]


def _previous_perimeter(footprint: LoadedFootprint, horizon_h: int) -> BaseGeometry:
    """Perimeter the fire had already reached before ``horizon_h`` (current, P50 1h, P50 3h)."""
    if horizon_h == 1:
        return footprint.current
    return footprint.p50[1 if horizon_h == 3 else 3]


def _interpolated_eta_min(
    buffer: BaseGeometry,
    footprint: LoadedFootprint,
    horizon_h: int,
    spread_rate_m_per_h: float,
) -> int:
    """ETA in minutes, interpolated between the previous perimeter and the P50 horizon.

    ``eta = clamp(t_A + d_A / rate * 60, t_A, t_B)`` rounded down, where ``d_A`` is the metric
    distance from the settlement buffer to the previous perimeter. An empty previous perimeter
    gives ``t_B``; a non-positive spread rate gives ``t_A`` (the most conservative value).
    """
    t_b = horizon_h * 60
    t_a = {1: 0, 3: 60, 6: 180}[horizon_h]
    previous = _previous_perimeter(footprint, horizon_h)
    if previous.is_empty:
        return t_b
    if spread_rate_m_per_h <= 0:
        return t_a
    distance_m = float(to_metric(buffer).distance(to_metric(previous)))
    eta = t_a + distance_m / spread_rate_m_per_h * 60.0
    return math.floor(min(max(eta, t_a), t_b))


def _first_hit(zones: dict[int, BaseGeometry], buffer: BaseGeometry) -> int | None:
    for horizon in HORIZONS_H:
        zone = zones[horizon]
        if not zone.is_empty and zone.intersects(buffer):
            return horizon
    return None


def assess_risk(
    settlements: Sequence[SettlementRecord],
    footprint: ForecastFootprint,
    *,
    spread_rate_m_per_h: float,
) -> RiskAssessment:
    """Turn a forecast footprint into evacuee groups, rescue alerts and P90-only warnings.

    ``spread_rate_m_per_h`` should be the maximum across the fire results (earliest ETA, the
    conservative choice). Settlements are visited sorted by settlement_id.
    """
    loaded = load_footprint(footprint)
    groups: list[EvacueeGroup] = []
    rescue: list[PlanAlert] = []
    p90_only: list[PlanAlert] = []
    unknown_population: list[str] = []

    for settlement in sorted(settlements, key=lambda item: item.settlement_id):
        point = Point(settlement.lon, settlement.lat)
        if not loaded.current.is_empty and loaded.current.covers(point):
            rescue.append(
                PlanAlert(
                    kind="needs_rescue_response",
                    message=(
                        f"{settlement.name} is inside the active fire perimeter: "
                        "needs rescue response (exempt from evacuation matching)"
                    ),
                    settlement_id=settlement.settlement_id,
                    settlement_name=settlement.name,
                )
            )
            continue

        buffer = buffer_metric(point, float(settlement.buffer_m))
        if not loaded.current.is_empty and loaded.current.intersects(buffer):
            exposure: Literal[
                "buffer_in_current", "inside_p50_1h", "inside_p50_3h", "inside_p50_6h"
            ] = "buffer_in_current"
            priority, eta_min = 1, 0
        else:
            horizon = _first_hit(loaded.p50, buffer)
            if horizon is None:
                p90_horizon = _first_hit(loaded.p90, buffer)
                if p90_horizon is not None:
                    p90_only.append(
                        PlanAlert(
                            kind="p90_only_exposure",
                            message=(
                                f"{settlement.name} is reached only by the P90 forecast "
                                f"(first at {p90_horizon}h): monitor, no evacuation group"
                            ),
                            settlement_id=settlement.settlement_id,
                            settlement_name=settlement.name,
                        )
                    )
                continue
            exposure = _EXPOSURE_BY_HORIZON[horizon]
            priority = _PRIORITY_BY_HORIZON[horizon]
            eta_min = _interpolated_eta_min(buffer, loaded, horizon, spread_rate_m_per_h)

        if settlement.population is None or settlement.population < 1:
            unknown_population.append(settlement.settlement_id)
            continue
        groups.append(
            EvacueeGroup(
                group_id=settlement.settlement_id,
                settlement_id=settlement.settlement_id,
                settlement_name=settlement.name,
                persons=settlement.population,
                priority=priority,
                eta_min=float(eta_min),
                exposure=exposure,
                origin_node=None,
                is_simulated=settlement.is_simulated,
                pop_source=settlement.pop_source,
            )
        )

    return RiskAssessment(
        groups=tuple(groups),
        rescue_alerts=tuple(rescue),
        p90_only_alerts=tuple(p90_only),
        unknown_population=tuple(unknown_population),
    )

"""Forecast footprint unions, prepared geometries and metric buffering (EPSG:32643).

Coordinates are always (lon, lat) in EPSG:4326 at the boundaries of this module (Rules section 4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

import pyproj
import shapely
from shapely import wkt
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform, unary_union

from wildfire_core.schemas.phase2 import FireSpreadResult
from wildfire_core.schemas.plan import ForecastFootprint

_EMPTY_WKT = "POLYGON EMPTY"

_TO_METRIC = pyproj.Transformer.from_crs(4326, 32643, always_xy=True)
_FROM_METRIC = pyproj.Transformer.from_crs(32643, 4326, always_xy=True)


def _union_wkts(wkts: Sequence[str]) -> str:
    geometries = [geometry for item in wkts if not (geometry := wkt.loads(item)).is_empty]
    if not geometries:
        return _EMPTY_WKT
    return cast(str, unary_union(geometries).wkt)


def build_footprint(fire_results: Sequence[FireSpreadResult]) -> ForecastFootprint:
    """Union the current, P50 and P90 perimeters of every cluster into one footprint."""
    return ForecastFootprint(
        current_wkt=_union_wkts([r.current_perimeter_wkt for r in fire_results]),
        p50_1h_wkt=_union_wkts([r.p50_1h_wkt for r in fire_results]),
        p50_3h_wkt=_union_wkts([r.p50_3h_wkt for r in fire_results]),
        p50_6h_wkt=_union_wkts([r.p50_6h_wkt for r in fire_results]),
        p90_1h_wkt=_union_wkts([r.p90_1h_wkt for r in fire_results]),
        p90_3h_wkt=_union_wkts([r.p90_3h_wkt for r in fire_results]),
        p90_6h_wkt=_union_wkts([r.p90_6h_wkt for r in fire_results]),
        fire_run_ids=tuple(sorted(r.run_id for r in fire_results)),
        cluster_ids=tuple(sorted({r.cluster_id for r in fire_results})),
    )


@dataclass(frozen=True)
class LoadedFootprint:
    """Parsed footprint geometries, prepared for fast repeated predicate checks."""

    current: BaseGeometry
    p50: dict[int, BaseGeometry]
    p90: dict[int, BaseGeometry]


def _load(wkt_text: str) -> BaseGeometry:
    geometry = cast(BaseGeometry, wkt.loads(wkt_text))
    if not geometry.is_empty:
        shapely.prepare(geometry)
    return geometry


def load_footprint(footprint: ForecastFootprint) -> LoadedFootprint:
    return LoadedFootprint(
        current=_load(footprint.current_wkt),
        p50={
            1: _load(footprint.p50_1h_wkt),
            3: _load(footprint.p50_3h_wkt),
            6: _load(footprint.p50_6h_wkt),
        },
        p90={
            1: _load(footprint.p90_1h_wkt),
            3: _load(footprint.p90_3h_wkt),
            6: _load(footprint.p90_6h_wkt),
        },
    )


def to_metric(geom: BaseGeometry) -> BaseGeometry:
    """Reproject an EPSG:4326 (lon, lat) geometry to EPSG:32643 metres."""
    return cast(BaseGeometry, transform(_TO_METRIC.transform, geom))


def from_metric(geom: BaseGeometry) -> BaseGeometry:
    """Reproject an EPSG:32643 geometry back to EPSG:4326 (lon, lat)."""
    return cast(BaseGeometry, transform(_FROM_METRIC.transform, geom))


def buffer_metric(geom: BaseGeometry, distance_m: float) -> BaseGeometry:
    """Buffer by a distance in metres (computed in EPSG:32643); returns EPSG:4326."""
    buffered: Any = to_metric(geom).buffer(distance_m)
    return from_metric(cast(BaseGeometry, buffered))

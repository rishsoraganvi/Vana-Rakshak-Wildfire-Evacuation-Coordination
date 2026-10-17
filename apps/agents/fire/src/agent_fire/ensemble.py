from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot

from .ca_model import run_ensemble


def compute_fire_spread(
    cluster: HotspotCluster,
    weather: WeatherSnapshot,
    bbox: Any = None,
    resolution_m: int = 250,
    seeds: Sequence[int] = (42, 43, 44),
) -> FireSpreadResult:
    """Run the CA ensemble for one cluster.

    ``WeatherSnapshot.wind_dir_deg`` carries the meteorological FROM direction
    (Open-Meteo ``wind_direction_10m``) and is passed to the CA as ``wind_from_deg``.
    """
    if bbox is None:
        buffer_deg = 0.1
        b_west = cluster.bbox_west - buffer_deg
        b_south = cluster.bbox_south - buffer_deg
        b_east = cluster.bbox_east + buffer_deg
        b_north = cluster.bbox_north + buffer_deg
    elif hasattr(bbox, "west"):
        b_west = float(bbox.west)
        b_south = float(bbox.south)
        b_east = float(bbox.east)
        b_north = float(bbox.north)
    elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        b_west = float(bbox[0])
        b_south = float(bbox[1])
        b_east = float(bbox[2])
        b_north = float(bbox[3])
    else:
        buffer_deg = 0.1
        b_west = cluster.bbox_west - buffer_deg
        b_south = cluster.bbox_south - buffer_deg
        b_east = cluster.bbox_east + buffer_deg
        b_north = cluster.bbox_north + buffer_deg

    res = run_ensemble(
        centroid_lat=cluster.centroid_lat,
        centroid_lon=cluster.centroid_lon,
        bbox_west=b_west,
        bbox_south=b_south,
        bbox_east=b_east,
        bbox_north=b_north,
        wind_speed_ms=weather.wind_speed_ms,
        wind_from_deg=weather.wind_dir_deg,
        rh_pct=weather.rh_pct,
        temperature_c=weather.temperature_c,
        resolution_m=resolution_m,
        seeds=seeds,
    )

    return FireSpreadResult(
        cluster_id=cluster.cluster_id,
        seeds_used=tuple(seeds),
        current_perimeter_wkt=res["current_perimeter_wkt"],
        p50_1h_wkt=res["p50_1h_wkt"],
        p50_3h_wkt=res["p50_3h_wkt"],
        p50_6h_wkt=res["p50_6h_wkt"],
        p90_1h_wkt=res["p90_1h_wkt"],
        p90_3h_wkt=res["p90_3h_wkt"],
        p90_6h_wkt=res["p90_6h_wkt"],
        affected_area_km2=res["affected_area_km2"],
        spread_direction_deg=res["spread_direction_deg"],
        spread_rate_m_per_h=res["spread_rate_m_per_h"],
        confidence=res["confidence"],
        settlements_at_risk=(),
    )

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import pyproj
from scipy.signal import convolve2d
from shapely.geometry import box
from shapely.ops import unary_union

WIND_COEFF = 0.12
MOISTURE_COEFF = 0.04
P_BASE = 0.35
STEP_DURATION_MIN = 6


def _wind_factor(wind_speed_ms: float, wind_from_deg: float, spread_dir_deg: float) -> float:
    """Relative spread weight toward ``spread_dir_deg`` (max 1.0 when straight downwind).

    ``wind_from_deg`` is the meteorological FROM direction (Open-Meteo
    ``wind_direction_10m``, degrees clockwise from north). Wind pushes fire toward
    the reciprocal bearing (FROM + 180 mod 360).
    """
    downwind_deg = (wind_from_deg + 180.0) % 360.0
    theta = math.radians(spread_dir_deg - downwind_deg)
    return float(math.exp(WIND_COEFF * wind_speed_ms * (math.cos(theta) - 1.0)))


def _moisture_factor(rh_pct: float, temperature_c: float) -> float:
    return float(max(0.05, 1.0 - MOISTURE_COEFF * (rh_pct - 20.0)))


def _build_kernel(wind_speed_ms: float, wind_from_deg: float) -> np.ndarray:
    kernel = np.zeros((3, 3), dtype=float)
    # Row 0 = North, Row 2 = South; Col 0 = West, Col 2 = East
    for r in range(3):
        for c in range(3):
            dr = r - 1
            dc = c - 1
            if dr == 0 and dc == 0:
                kernel[r, c] = 0.0
                continue
            d_lat = -dr
            d_lon = dc
            spread_dir = math.degrees(math.atan2(d_lon, d_lat)) % 360.0
            kernel[r, c] = _wind_factor(wind_speed_ms, wind_from_deg, spread_dir)

    total = np.sum(kernel)
    if total > 0:
        kernel = kernel / total
    return kernel


def _run_single(
    ignition_grid: np.ndarray,
    wind_speed_ms: float,
    wind_from_deg: float,
    rh_pct: float,
    temperature_c: float,
    steps: int,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    kernel = _build_kernel(wind_speed_ms, wind_from_deg)
    moisture = _moisture_factor(rh_pct, temperature_c)
    grid = ignition_grid.copy().astype(float)

    for _ in range(steps):
        neighbor_density = convolve2d(grid, kernel, mode="same", boundary="fill", fillvalue=0)
        spread_prob = np.clip(neighbor_density * P_BASE * moisture, 0.0, 1.0)
        new_ignitions = (rng.random(grid.shape) < spread_prob).astype(float)
        grid = np.clip(grid + new_ignitions, 0.0, 1.0)

    return grid.astype(int)


def run_ensemble(
    centroid_lat: float,
    centroid_lon: float,
    bbox_west: float,
    bbox_south: float,
    bbox_east: float,
    bbox_north: float,
    wind_speed_ms: float,
    wind_from_deg: float,
    rh_pct: float,
    temperature_c: float,
    resolution_m: int = 250,
    seeds: Sequence[int] = (42, 43, 44),
    horizons_min: Sequence[int] = (60, 180, 360),
) -> dict[str, Any]:
    """Run the CA ensemble.

    ``wind_from_deg`` is the meteorological FROM direction (Open-Meteo
    ``wind_direction_10m``, degrees clockwise from north); fire is pushed toward
    the reciprocal bearing (FROM + 180 mod 360).
    """
    cell_deg = resolution_m / 111_320.0
    n_rows = max(5, int(np.ceil((bbox_north - bbox_south) / cell_deg)))
    n_cols = max(5, int(np.ceil((bbox_east - bbox_west) / cell_deg)))

    c_row = int(np.clip(round((bbox_north - centroid_lat) / cell_deg), 1, n_rows - 2))
    c_col = int(np.clip(round((centroid_lon - bbox_west) / cell_deg), 1, n_cols - 2))

    ignition = np.zeros((n_rows, n_cols), dtype=int)
    ignition[c_row - 1 : c_row + 2, c_col - 1 : c_col + 2] = 1

    sorted_horizons = sorted(horizons_min)
    seed_grids: dict[int, dict[int, np.ndarray]] = {h: {} for h in sorted_horizons}

    for s in seeds:
        curr = ignition.copy()
        prev_h = 0
        for h in sorted_horizons:
            steps = max(1, (h - prev_h) // STEP_DURATION_MIN)
            curr = _run_single(curr, wind_speed_ms, wind_from_deg, rh_pct, temperature_c, steps, s)
            seed_grids[h][s] = curr.copy()
            prev_h = h

    def grid_to_wkt(mask: np.ndarray) -> str:
        rows, cols = np.where(mask > 0)
        if len(rows) == 0:
            return "POLYGON EMPTY"
        boxes = []
        for r, c in zip(rows, cols, strict=True):
            lat_top = bbox_north - r * cell_deg
            lat_bot = lat_top - cell_deg
            lon_left = bbox_west + c * cell_deg
            lon_right = lon_left + cell_deg
            boxes.append(box(lon_left, lat_bot, lon_right, lat_top))
        poly = unary_union(boxes)
        return poly.wkt if not poly.is_empty else "POLYGON EMPTY"

    current_wkt = grid_to_wkt(ignition)

    p50_masks: dict[int, np.ndarray] = {}
    p90_masks: dict[int, np.ndarray] = {}
    p50_wkts: dict[int, str] = {}
    p90_wkts: dict[int, str] = {}

    for h in sorted_horizons:
        stack = np.stack([seed_grids[h][s] for s in seeds], axis=0)
        freq = np.mean(stack, axis=0)
        p50_m = (freq >= 0.5).astype(int)
        p90_m = (freq >= 0.1).astype(int)
        p50_masks[h] = p50_m
        p90_masks[h] = p90_m
        p50_wkts[h] = grid_to_wkt(p50_m)
        p90_wkts[h] = grid_to_wkt(p90_m)

    cell_area_km2 = (resolution_m / 1000.0) ** 2
    h3_p50 = p50_masks.get(180, p50_masks[sorted_horizons[-1]])
    affected_area_km2 = float(np.sum(h3_p50) * cell_area_km2)

    p50_rows, p50_cols = np.where(h3_p50 > 0)
    if len(p50_rows) > 0:
        mean_r = float(np.mean(p50_rows))
        mean_c = float(np.mean(p50_cols))
        end_lat = bbox_north - (mean_r + 0.5) * cell_deg
        end_lon = bbox_west + (mean_c + 0.5) * cell_deg
        geod = pyproj.Geod(ellps="WGS84")
        az12, _, dist_m = geod.inv(centroid_lon, centroid_lat, end_lon, end_lat)
        spread_direction_deg = float((az12 + 360.0) % 360.0)
        spread_rate_m_per_h = float(dist_m / 3.0)
    else:
        spread_direction_deg = float(wind_from_deg % 360.0)
        spread_rate_m_per_h = 0.0

    target_grid = seed_grids.get(180, seed_grids[sorted_horizons[-1]])
    burn_counts = [float(np.sum(target_grid[s])) for s in seeds]
    mean_count = float(np.mean(burn_counts))
    std_count = float(np.std(burn_counts))
    cv = (std_count / mean_count) if mean_count > 0 else 0.0
    if cv < 0.1:
        confidence = "high"
    elif cv < 0.3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "current_perimeter_wkt": current_wkt,
        "p50_1h_wkt": p50_wkts.get(60, "POLYGON EMPTY"),
        "p50_3h_wkt": p50_wkts.get(180, "POLYGON EMPTY"),
        "p50_6h_wkt": p50_wkts.get(360, "POLYGON EMPTY"),
        "p90_1h_wkt": p90_wkts.get(60, "POLYGON EMPTY"),
        "p90_3h_wkt": p90_wkts.get(180, "POLYGON EMPTY"),
        "p90_6h_wkt": p90_wkts.get(360, "POLYGON EMPTY"),
        "affected_area_km2": round(affected_area_km2, 4),
        "spread_direction_deg": round(spread_direction_deg, 2),
        "spread_rate_m_per_h": round(spread_rate_m_per_h, 2),
        "confidence": confidence,
        "seeds_used": tuple(seeds),
    }

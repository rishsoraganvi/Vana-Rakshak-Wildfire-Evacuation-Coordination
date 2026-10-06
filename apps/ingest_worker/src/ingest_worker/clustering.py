from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.cluster import DBSCAN
from wildfire_core.schemas.phase2 import HotspotCluster


def _extract_point(obs: Any) -> tuple[float, float, float | None, str]:
    if isinstance(obs, dict):
        lat = float(obs["lat"])
        lon = float(obs["lon"])
        frp = float(obs["frp"]) if obs.get("frp") is not None else None
        obs_id = str(obs.get("id") or obs.get("hotspot_id") or "")
    else:
        lat = float(obs.lat)
        lon = float(obs.lon)
        frp = float(obs.frp) if getattr(obs, "frp", None) is not None else None
        obs_id = str(getattr(obs, "id", "") or getattr(obs, "hotspot_id", ""))
    return lat, lon, frp, obs_id


def cluster_hotspots(
    observations: Sequence[Any],
    eps_deg: float = 0.01,
    min_samples: int = 3,
) -> list[HotspotCluster]:
    if not observations or len(observations) < min_samples:
        return []

    extracted = [_extract_point(obs) for obs in observations]
    coords = np.array([[item[0], item[1]] for item in extracted], dtype=float)

    clustering = DBSCAN(eps=eps_deg, min_samples=min_samples, metric="euclidean").fit(coords)
    labels = clustering.labels_

    clusters: list[HotspotCluster] = []
    unique_labels = sorted(set(labels))
    for label in unique_labels:
        if label == -1:
            continue
        indices = np.where(labels == label)[0]
        cluster_lats = coords[indices, 0]
        cluster_lons = coords[indices, 1]

        frp_values = [extracted[i][2] for i in indices if extracted[i][2] is not None]
        mean_frp = float(np.mean(frp_values)) if frp_values else None
        hotspot_ids = tuple(extracted[i][3] for i in indices if extracted[i][3])

        clusters.append(
            HotspotCluster(
                centroid_lat=float(np.mean(cluster_lats)),
                centroid_lon=float(np.mean(cluster_lons)),
                point_count=len(indices),
                mean_frp=mean_frp,
                bbox_west=float(np.min(cluster_lons)),
                bbox_south=float(np.min(cluster_lats)),
                bbox_east=float(np.max(cluster_lons)),
                bbox_north=float(np.max(cluster_lats)),
                hotspot_ids=hotspot_ids,
            )
        )

    return clusters

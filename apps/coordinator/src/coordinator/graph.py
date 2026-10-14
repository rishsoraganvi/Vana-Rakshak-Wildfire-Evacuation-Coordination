from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import networkx as nx
from agent_fire.ensemble import compute_fire_spread
from agent_routing import apply_fire_penalties, compute_route, load_or_download_graph, nearest_node
from agent_weather.agent import get_weather_snapshot
from ingest_worker.clustering import cluster_hotspots
from shapely import wkt
from shapely.geometry import Point
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from wildfire_core.config import Settings, load_settings
from wildfire_core.db.models import hotspots
from wildfire_core.db.session import create_db_engine
from wildfire_core.schemas.phase2 import (
    AuditEntry,
    CoordinatorPlan,
    FireSpreadResult,
    HotspotCluster,
    RouteResult,
    WeatherSnapshot,
)

from coordinator.llm.groq_adapter import generate_rationale
from coordinator.state import CoordinatorState


@lru_cache(maxsize=1)
def _engine_for(database_url: str) -> Engine:
    return create_db_engine(database_url)


def _settings() -> Settings:
    return load_settings()


def _aoi_boundary_exit_nodes(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    bbox: tuple[float, float, float, float],
    current_perimeter: Any,
) -> list[int]:
    west, south, east, north = bbox
    safe_nodes: list[tuple[int, float, float]] = []
    for node_id, node_data in graph.nodes(data=True):
        x = float(node_data["x"])
        y = float(node_data["y"])
        point = Point(x, y)
        if not current_perimeter.is_empty and current_perimeter.contains(point):
            continue
        safe_nodes.append((node_id, x, y))

    if not safe_nodes:
        return []

    edge_distance = (
        lambda item: abs(item[1] - west),
        lambda item: abs(east - item[1]),
        lambda item: abs(item[2] - south),
        lambda item: abs(north - item[2]),
    )
    exits: list[int] = []
    for distance_to_edge in edge_distance:
        node_id, _x, _y = min(safe_nodes, key=distance_to_edge)
        if node_id not in exits:
            exits.append(node_id)
    return exits


def _audit(
    state: CoordinatorState,
    node_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    started_ms: int,
) -> None:
    entry = AuditEntry(
        incident_id=state["incident_id"],
        run_id=state["run_id"],
        node_name=node_name,
        inputs_json=json.dumps(inputs, sort_keys=True, default=str),
        outputs_json=json.dumps(outputs, sort_keys=True, default=str),
        latency_ms=max(0, time.monotonic_ns() // 1_000_000 - started_ms),
    )
    state["audit_entries"].append(entry.model_dump(mode="json"))


def ingest_trigger(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    settings = _settings()
    engine = _engine_for(settings.database_url.get_secret_value())
    incident_uuid = UUID(state["incident_id"])

    with engine.connect() as connection:
        trigger = (
            connection.execute(
                text(
                    """
                SELECT details FROM triggers
                WHERE incident_id = :incident_id
                  AND type = 'new_hotspot'
                  AND coalesced_into IS NULL
                ORDER BY detected_at DESC
                LIMIT 1
                """
                ),
                {"incident_id": incident_uuid},
            )
            .mappings()
            .first()
        )

        details = trigger["details"] if trigger is not None else {}
        if isinstance(details, str):
            details = json.loads(details)
        raw_ids = details.get("hotspot_ids", []) if isinstance(details, dict) else []
        hotspot_uuids = [UUID(str(hotspot_id)) for hotspot_id in raw_ids]
        rows = (
            connection.execute(
                select(hotspots.c.id, hotspots.c.lat, hotspots.c.lon, hotspots.c.frp)
                .where(hotspots.c.id.in_(hotspot_uuids))
                .order_by(hotspots.c.acq_datetime)
            )
            .mappings()
            .all()
            if hotspot_uuids
            else []
        )

    state["hotspot_ids"] = [str(row["id"]) for row in rows]
    state["hotspots"] = [
        {
            "id": str(row["id"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "frp": float(row["frp"]) if row["frp"] is not None else None,
        }
        for row in rows
    ]
    if not rows:
        error_message = "No hotspot observations are linked to this incident trigger"
        state["error"] = error_message
        state["warnings"].append(error_message)

    _audit(
        state,
        "ingest_trigger",
        {"incident_id": state["incident_id"]},
        {"hotspot_ids": state["hotspot_ids"], "count": len(rows)},
        started_ms,
    )
    return state


def run_weather(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    settings = _settings()
    latitude = (settings.aoi_bbox.south + settings.aoi_bbox.north) / 2
    longitude = (settings.aoi_bbox.west + settings.aoi_bbox.east) / 2

    try:
        weather = get_weather_snapshot(
            latitude,
            longitude,
            _engine_for(settings.database_url.get_secret_value()),
        )
    except Exception as error:
        weather = WeatherSnapshot(
            valid_time=datetime.now(UTC),
            wind_speed_ms=0.0,
            wind_dir_deg=0.0,
            rh_pct=0.0,
            temperature_c=0.0,
            is_stale=True,
        )
        state["warnings"].append(f"Weather snapshot unavailable: {type(error).__name__}")

    weather_data = weather.model_dump(mode="json")
    state["weather_snapshot"] = weather_data
    _audit(
        state,
        "run_weather",
        {"latitude": latitude, "longitude": longitude},
        weather_data,
        started_ms,
    )
    return state


def cluster_hotspots_node(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    settings = _settings()
    clusters = cluster_hotspots(
        state["hotspots"],
        eps_deg=settings.dbscan_eps_deg,
        min_samples=settings.dbscan_min_samples,
    )
    state["clusters"] = [cluster.model_dump(mode="json") for cluster in clusters]
    if not clusters:
        state["warnings"].append("No hotspot clusters met the configured DBSCAN threshold")
    _audit(
        state,
        "cluster_hotspots",
        {"hotspot_count": len(state["hotspots"])},
        {"clusters": state["clusters"]},
        started_ms,
    )
    return state


def run_fire_ca(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    if not state["clusters"] or state["weather_snapshot"] is None:
        state["fire_result"] = None
        state["warnings"].append("Fire spread skipped because clusters or weather are unavailable")
    else:
        settings = _settings()
        clusters = [HotspotCluster.model_validate(item) for item in state["clusters"]]
        cluster = max(clusters, key=lambda item: item.point_count)
        weather = WeatherSnapshot.model_validate(state["weather_snapshot"])
        fire_result = compute_fire_spread(
            cluster,
            weather,
            bbox=settings.aoi_bbox,
            resolution_m=settings.fire_grid_resolution_m,
            seeds=settings.fire_ensemble_seeds,
        )
        state["fire_result"] = fire_result.model_dump(mode="json")
        if weather.is_stale:
            state["warnings"].append("Fire spread used a stale weather snapshot")

    _audit(
        state,
        "run_fire_ca",
        {"cluster_count": len(state["clusters"])},
        {"fire_result": state["fire_result"]},
        started_ms,
    )
    return state


def compute_route_node(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    state["routes"] = []
    if state["fire_result"] is None:
        state["warnings"].append("Routing skipped because the fire spread result is unavailable")
        _audit(state, "compute_route", {}, {"routes": []}, started_ms)
        return state

    try:
        settings = _settings()
        bbox = settings.aoi_bbox
        graph = load_or_download_graph(
            settings.osm_cache_path,
            (bbox.north, bbox.south, bbox.east, bbox.west),
        )
        fire_result = FireSpreadResult.model_validate(state["fire_result"])
        weighted_graph = apply_fire_penalties(
            graph,
            fire_result.current_perimeter_wkt,
            fire_result.p50_1h_wkt,
            penalty_near=settings.route_fire_penalty_near,
        )
        current_perimeter = wkt.loads(fire_result.current_perimeter_wkt)
        exit_nodes = _aoi_boundary_exit_nodes(
            graph,
            (bbox.west, bbox.south, bbox.east, bbox.north),
            current_perimeter,
        )
        for raw_cluster in state["clusters"]:
            cluster = HotspotCluster.model_validate(raw_cluster)
            origin_node = nearest_node(graph, cluster.centroid_lat, cluster.centroid_lon)
            origin_data = graph.nodes[origin_node]
            candidates: list[tuple[int, float]] = []
            for node_id in exit_nodes:
                if node_id == origin_node:
                    continue
                node_data = weighted_graph.nodes[node_id]
                distance = (float(node_data["x"]) - float(origin_data["x"])) ** 2 + (
                    float(node_data["y"]) - float(origin_data["y"])
                ) ** 2
                candidates.append((node_id, distance))

            candidates.sort(key=lambda item: item[1])
            route: RouteResult | None = None
            blocked_route: RouteResult | None = None
            for destination_node, _distance in candidates:
                candidate_route = compute_route(
                    weighted_graph,
                    origin_node,
                    destination_node,
                    group_id=cluster.cluster_id,
                    origin_cluster_id=cluster.cluster_id,
                )
                if candidate_route is None:
                    continue
                if candidate_route.safety_classification != "blocked":
                    route = candidate_route
                    break
                if blocked_route is None:
                    blocked_route = candidate_route

            route = route or blocked_route
            if route is not None:
                state["routes"].append(route.model_dump(mode="json"))
                if route.safety_classification == "blocked":
                    state["warnings"].append(
                        f"No safe route found for fire cluster {cluster.cluster_id}"
                    )
            else:
                state["warnings"].append(
                    f"No graph route found for fire cluster {cluster.cluster_id}"
                )
    except Exception as error:
        state["warnings"].append(f"Route computation unavailable: {type(error).__name__}")

    _audit(state, "compute_route", {}, {"routes": state["routes"]}, started_ms)
    return state


def generate_rationale_node(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    if state["fire_result"] is None or state["weather_snapshot"] is None:
        state["rationale"] = (
            "[DETERMINISTIC FALLBACK] Fire or weather data unavailable. Human review required."
        )
        state["is_llm_fallback"] = True
    else:
        rationale, is_fallback = generate_rationale(
            FireSpreadResult.model_validate(state["fire_result"]),
            WeatherSnapshot.model_validate(state["weather_snapshot"]),
            [RouteResult.model_validate(item) for item in state["routes"]],
            _settings(),
        )
        state["rationale"] = rationale
        state["is_llm_fallback"] = is_fallback

    _audit(
        state,
        "generate_rationale",
        {"fire_available": state["fire_result"] is not None, "route_count": len(state["routes"])},
        {"rationale": state["rationale"], "is_llm_fallback": state["is_llm_fallback"]},
        started_ms,
    )
    return state


def assemble_plan(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    if state["fire_result"] is None or state["weather_snapshot"] is None:
        state["error"] = state["error"] or "Cannot persist a draft without fire and weather results"
        _audit(state, "assemble_plan", {}, {"error": state["error"]}, started_ms)
        return state

    plan = CoordinatorPlan(
        incident_id=state["incident_id"],
        run_id=state["run_id"],
        fire_result=FireSpreadResult.model_validate(state["fire_result"]),
        weather_snapshot=WeatherSnapshot.model_validate(state["weather_snapshot"]),
        clusters=tuple(HotspotCluster.model_validate(item) for item in state["clusters"]),
        routes=tuple(RouteResult.model_validate(item) for item in state["routes"]),
        rationale_md=state["rationale"],
        is_llm_fallback=state["is_llm_fallback"],
        warnings=tuple(state["warnings"]),
    )
    settings = _settings()
    plan_json = json.dumps(plan.model_dump(mode="json"), sort_keys=True)
    with _engine_for(settings.database_url.get_secret_value()).begin() as connection:
        version = connection.execute(
            text(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM plan_versions "
                "WHERE incident_id = :incident_id"
            ),
            {"incident_id": UUID(state["incident_id"])},
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO plan_versions
                    (incident_id, version, status, rationale_md, is_llm_fallback,
                     is_simulated, warnings, plan_data)
                VALUES
                    (:incident_id, :version, 'draft', :rationale, :is_fallback,
                     false, CAST(:warnings AS jsonb), CAST(:plan_data AS jsonb))
                """
            ),
            {
                "incident_id": UUID(state["incident_id"]),
                "version": version,
                "rationale": plan.rationale_md,
                "is_fallback": plan.is_llm_fallback,
                "warnings": json.dumps(list(plan.warnings)),
                "plan_data": plan_json,
            },
        )
        connection.execute(
            text("UPDATE incidents SET status = 'planning' WHERE id = :incident_id"),
            {"incident_id": UUID(state["incident_id"])},
        )

    _audit(
        state,
        "assemble_plan",
        {"incident_id": state["incident_id"]},
        {"version": version, "plan_id": plan.plan_id},
        started_ms,
    )
    return state


def write_audit(state: CoordinatorState) -> CoordinatorState:
    started_ms = time.monotonic_ns() // 1_000_000
    pending_count = len(state["audit_entries"])
    _audit(
        state,
        "write_audit",
        {"pending_entries": pending_count},
        {"persisted_entries": pending_count + 1},
        started_ms,
    )
    if state["audit_entries"]:
        rows = [
            {
                "id": UUID(entry["entry_id"]),
                "incident_id": UUID(entry["incident_id"]),
                "run_id": UUID(entry["run_id"]),
                "node_name": entry["node_name"],
                "agent_input": entry["inputs_json"],
                "agent_output": entry["outputs_json"],
                "latency_ms": entry["latency_ms"],
                "model_metadata": json.dumps(entry["model_metadata"])
                if entry.get("model_metadata") is not None
                else None,
                "created_at": entry["created_at"],
            }
            for entry in state["audit_entries"]
        ]
        settings = _settings()
        with _engine_for(settings.database_url.get_secret_value()).begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO agent_runs
                        (id, incident_id, agent, status, input, output, latency_ms,
                         run_id, node_name, model_metadata, created_at)
                    VALUES
                        (:id, :incident_id, 'coordinator', 'succeeded',
                         CAST(:agent_input AS jsonb), CAST(:agent_output AS jsonb), :latency_ms,
                         :run_id, :node_name, CAST(:model_metadata AS jsonb), :created_at)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                rows,
            )
    return state

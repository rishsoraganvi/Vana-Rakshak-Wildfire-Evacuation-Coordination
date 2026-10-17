"""Phase 3 coordinator nodes (PLAN-01, PLAN-07, PLAN-08, TechSpec 6.2).

``make_nodes(deps)`` returns the ten graph nodes as closures over ``CoordinatorDeps``::

    ingest_trigger -> cluster_hotspots -> run_weather -> run_fire_ca -> assess_risk
      -> dispatch_specialists -> plan_evacuation -> generate_rationale -> assemble_plan
      -> write_audit

Nodes hold no SQL: every database access goes through ``deps.repository`` (RESEARCH Pitfall 9).
The LangGraph state stays JSON-serializable; the routed road graph lives in ``deps.scratch``
keyed by ``run_id``. Numbers are deterministic; the optional LLM only writes grounded text and
picks a repair strategy from a fixed menu.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import networkx as nx
from agent_fire.risk import assess_risk
from agent_routing import apply_horizon_costs, snap_points
from agent_shelter.registry import CandidateList, list_candidate_shelters, usable_capacity
from ingest_worker.clustering import cluster_hotspots
from shapely import wkt
from shapely.geometry import Point
from wildfire_core.geo.footprint import build_footprint, load_footprint
from wildfire_core.schemas.phase2 import (
    AuditEntry,
    FireSpreadResult,
    HotspotCluster,
    WeatherSnapshot,
)
from wildfire_core.schemas.plan import (
    ClusterRisk,
    EvacueeGroup,
    ExcludedShelter,
    ForecastFootprint,
    PlanAlert,
    PlanDraft,
    ShelterCandidate,
    ShelterRecord,
    ShelterSnapshot,
)
from wildfire_core.schemas.tools import ToolResult

from coordinator.deps import CoordinatorDeps
from coordinator.dispatch import run_specialists
from coordinator.llm.groq_adapter import RationaleResult, base_model_metadata
from coordinator.planning.diff import is_material_change, plan_diff
from coordinator.planning.finalize import (
    as_failed,
    build_freshness,
    build_provenance,
    finalize_plan,
)
from coordinator.planning.params import PlanningParams
from coordinator.planning.plan_core import PlanInputs, RoutingContext, plan_draft
from coordinator.planning.rationale_template import compact_plan_summary
from coordinator.repository import (
    CapacityRecheckFailed,
    PersistResult,
    StateVersionConflict,
)
from coordinator.state import CoordinatorState

Node = Callable[[CoordinatorState], CoordinatorState]

NODE_ORDER = (
    "ingest_trigger",
    "cluster_hotspots",
    "run_weather",
    "run_fire_ca",
    "assess_risk",
    "dispatch_specialists",
    "plan_evacuation",
    "generate_rationale",
    "assemble_plan",
    "write_audit",
)

_SIMULATED_ORIGINS = frozenset({"replay", "simulated"})
_EARTH_RADIUS_M = 6_371_000.0


def _now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def _audit(
    state: CoordinatorState,
    node_name: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    started_ms: int,
    model_metadata: dict[str, Any] | None = None,
    agent: str = "coordinator",
) -> None:
    entry = AuditEntry(
        incident_id=state["incident_id"],
        run_id=state["run_id"],
        node_name=node_name,
        agent=agent,  # type: ignore[arg-type]
        inputs_json=json.dumps(inputs, sort_keys=True, default=str),
        outputs_json=json.dumps(outputs, sort_keys=True, default=str),
        latency_ms=max(0, _now_ms() - started_ms),
        model_metadata=model_metadata,
    )
    state["audit_entries"].append(entry.model_dump(mode="json"))


def _alert(
    kind: str,
    message: str,
    *,
    settlement_id: str | None = None,
    cluster_id: str | None = None,
) -> dict[str, Any]:
    alert = PlanAlert(
        kind=kind,  # type: ignore[arg-type]
        message=message,
        settlement_id=settlement_id,
        cluster_id=cluster_id,
    )
    return alert.model_dump(mode="json")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return float(2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a)))


def _nearest_free_node(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    lat: float,
    lon: float,
    *,
    perimeter_wkt: str,
    avoid: frozenset[int],
    max_snap_m: float,
) -> int | None:
    """Nearest node outside the perimeter that is not in ``avoid``, within ``max_snap_m``."""
    perimeter = wkt.loads(perimeter_wkt)
    best: tuple[float, int] | None = None
    for node, data in graph.nodes(data=True):
        if int(node) in avoid:
            continue
        x, y = float(data["x"]), float(data["y"])
        if not perimeter.is_empty and perimeter.covers(Point(x, y)):
            continue
        distance = _haversine_m(lat, lon, y, x)
        if distance > max_snap_m:
            continue
        candidate = (distance, int(node))
        if best is None or candidate < best:
            best = candidate
    return None if best is None else best[1]


def snap_shelters(
    graph: nx.MultiDiGraph[int, dict[str, Any], dict[str, Any]],
    candidates: list[ShelterCandidate],
    *,
    perimeter_wkt: str,
    max_snap_m: float,
    group_origin_nodes: frozenset[int],
) -> dict[str, int | None]:
    """Snap shelters outside the perimeter and away from the groups' origin nodes.

    A leg whose origin and destination share a node cannot be a ``PlanRoute`` (it needs two
    nodes), so a shelter that snapped onto a settlement's node moves to the nearest free node
    within the snap limit; if none exists it keeps its node (only that pair becomes unreachable).
    """
    snapped: dict[str, int | None] = dict(
        snap_points(
            graph,
            {item.shelter_id: (item.lat, item.lon) for item in candidates},
            perimeter_wkt=perimeter_wkt,
            max_snap_m=max_snap_m,
        )
    )
    by_id = {item.shelter_id: item for item in candidates}
    for shelter_id in sorted(snapped):
        node = snapped[shelter_id]
        if node is None or node not in group_origin_nodes:
            continue
        item = by_id[shelter_id]
        alternative = _nearest_free_node(
            graph,
            item.lat,
            item.lon,
            perimeter_wkt=perimeter_wkt,
            avoid=group_origin_nodes,
            max_snap_m=max_snap_m,
        )
        if alternative is not None:
            snapped[shelter_id] = alternative
    return snapped


def _tool_summary(result: ToolResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "error": None if result.error is None else result.error.model_dump(mode="json"),
        "latency_ms": result.latency_ms,
    }


def _empty_routing_context(footprint: ForecastFootprint) -> RoutingContext:
    """Placeholder when routing is unavailable; the draft fails closed on the preflight reason."""
    return RoutingContext(
        graph=nx.MultiDiGraph(),
        footprint=footprint,
        loaded=load_footprint(footprint),
        edge_status={},
        graph_source="unavailable",
    )


def _footprint_of(state: CoordinatorState) -> ForecastFootprint:
    if state["footprint"] is not None:
        return ForecastFootprint.model_validate(state["footprint"])
    return build_footprint([])


def make_nodes(deps: CoordinatorDeps) -> dict[str, Node]:
    """Build the ten Phase 3 nodes as closures over ``deps``."""
    settings = deps.settings
    repository = deps.repository

    def ingest_trigger(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        context = repository.incident_context(state["incident_id"])
        rows = repository.incident_hotspots(state["incident_id"])
        state["incident_origin"] = context.origin
        state["state_version"] = context.state_version
        state["hotspots"] = [
            {
                "id": str(row["id"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "frp": float(row["frp"]) if row.get("frp") is not None else None,
            }
            for row in rows
        ]
        state["hotspot_ids"] = [item["id"] for item in state["hotspots"]]
        if not rows:
            message = "No hotspot observations are linked to this incident trigger"
            state["error"] = message
            state["warnings"].append(message)
        _audit(
            state,
            "ingest_trigger",
            {"incident_id": state["incident_id"], "trigger_id": state["trigger_id"]},
            {
                "hotspot_ids": state["hotspot_ids"],
                "count": len(rows),
                "origin": context.origin,
                "state_version": context.state_version,
            },
            started_ms,
        )
        return state

    def cluster_hotspots_node(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
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

    def run_weather(state: CoordinatorState) -> CoordinatorState:
        """Per-cluster weather at each centroid; a missing reading fails the plan closed."""
        started_ms = _now_ms()
        now = deps.clock.now_utc()
        clusters = sorted(
            (HotspotCluster.model_validate(item) for item in state["clusters"]),
            key=lambda item: (-item.point_count, item.cluster_id),
        )
        queries: list[dict[str, Any]] = []
        for cluster in clusters:
            queries.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "lat": cluster.centroid_lat,
                    "lon": cluster.centroid_lon,
                }
            )
            try:
                snapshot = repository.weather_for(
                    cluster.centroid_lat,
                    cluster.centroid_lon,
                    origin=state["incident_origin"],
                    provider=settings.weather_provider,
                    now=now,
                    max_distance_km=settings.weather_max_distance_km,
                )
            except Exception as error:
                state["weather_missing"].append(f"weather_unavailable:{cluster.cluster_id}")
                state["alerts"].append(
                    _alert(
                        "weather_unavailable",
                        f"No weather observation is available for cluster {cluster.cluster_id} "
                        f"({type(error).__name__}); no weather was fabricated",
                        cluster_id=cluster.cluster_id,
                    )
                )
                continue
            state["weather_by_cluster"][cluster.cluster_id] = snapshot.model_dump(mode="json")
        _audit(
            state,
            "run_weather",
            {
                "queries": queries,
                "origin": state["incident_origin"],
                "provider": settings.weather_provider,
            },
            {
                "weather_by_cluster": state["weather_by_cluster"],
                "weather_missing": state["weather_missing"],
            },
            started_ms,
        )
        return state

    def run_fire_ca(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        clusters = sorted(
            (HotspotCluster.model_validate(item) for item in state["clusters"]),
            key=lambda item: (-item.point_count, item.cluster_id),
        )
        results: list[dict[str, Any]] = []
        for cluster in clusters:
            raw_weather = state["weather_by_cluster"].get(cluster.cluster_id)
            if raw_weather is None:
                continue
            try:
                result = deps.fire_fn(
                    cluster,
                    WeatherSnapshot.model_validate(raw_weather),
                    bbox=settings.aoi_bbox,
                    resolution_m=settings.fire_grid_resolution_m,
                    seeds=settings.fire_ensemble_seeds,
                )
            except Exception as error:
                state["risk_failures"].append(f"fire_unavailable:{cluster.cluster_id}")
                state["warnings"].append(
                    f"Fire spread failed for cluster {cluster.cluster_id} ({type(error).__name__})"
                )
                continue
            results.append(result.model_dump(mode="json"))
        state["fire_results"] = results
        _audit(
            state,
            "run_fire_ca",
            {
                "cluster_count": len(clusters),
                "simulated_cluster_ids": [item["cluster_id"] for item in results],
            },
            {"fire_run_ids": [item["run_id"] for item in results]},
            started_ms,
        )
        return state

    def assess_risk_node(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        fire_results = [FireSpreadResult.model_validate(item) for item in state["fire_results"]]
        footprint = build_footprint(fire_results)
        state["footprint"] = footprint.model_dump(mode="json")
        assessment = assess_risk(
            repository.settlements(),
            footprint,
            spread_rate_m_per_h=max(
                (item.spread_rate_m_per_h for item in fire_results), default=0.0
            ),
        )
        state["groups"] = [group.model_dump(mode="json") for group in assessment.groups]
        for alert in (*assessment.rescue_alerts, *assessment.p90_only_alerts):
            state["alerts"].append(alert.model_dump(mode="json"))
        for settlement_id in assessment.unknown_population:
            state["risk_failures"].append(f"population_unknown:{settlement_id}")
            state["alerts"].append(
                _alert(
                    "population_unknown",
                    f"Population of settlement {settlement_id} is unknown, so it cannot be "
                    "planned for",
                    settlement_id=settlement_id,
                )
            )
        _audit(
            state,
            "assess_risk",
            {"fire_run_ids": list(footprint.fire_run_ids)},
            {
                "group_ids": [item["group_id"] for item in state["groups"]],
                "rescue_alerts": len(assessment.rescue_alerts),
                "p90_only_alerts": len(assessment.p90_only_alerts),
                "unknown_population": list(assessment.unknown_population),
            },
            started_ms,
        )
        return state

    def dispatch_specialists(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        if not state["clusters"]:
            _audit(state, "dispatch_specialists", {}, {"skipped": "no_clusters"}, started_ms)
            return state

        footprint = _footprint_of(state)
        groups = [EvacueeGroup.model_validate(item) for item in state["groups"]]
        settlements = {item.settlement_id: item for item in repository.settlements()}
        now = deps.clock.now_utc()

        def shelter_candidates() -> tuple[CandidateList, list[ShelterRecord]]:
            records = repository.shelters()
            listed = list_candidate_shelters(
                records,
                footprint,
                buffer_m=settings.shelter_exclusion_buffer_m,
                default_factor=settings.shelter_usable_factor,
            )
            return listed, records

        def prepare_routing() -> tuple[RoutingContext, dict[str, int | None]]:
            graph = deps.graph_loader(settings.osm_cache_path)
            statuses = repository.edge_statuses(now)
            weighted = apply_horizon_costs(
                graph,
                footprint,
                p50_mult=settings.route_p50_mult,
                p90_mult=settings.route_p90_mult,
                edge_status=statuses,
            )
            origins = snap_points(
                weighted,
                {
                    item.group_id: (
                        settlements[item.settlement_id].lat,
                        settlements[item.settlement_id].lon,
                    )
                    for item in groups
                    if item.settlement_id in settlements
                },
                perimeter_wkt=footprint.current_wkt,
                max_snap_m=settings.max_snap_distance_m,
            )
            path = settings.osm_cache_path
            mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC) if path.is_file() else None
            context = RoutingContext(
                graph=weighted,
                footprint=footprint,
                loaded=load_footprint(footprint),
                edge_status=statuses,
                graph_source=path.name,
                graph_mtime=mtime,
            )
            return context, origins

        outcomes = run_specialists(
            {"shelter": shelter_candidates, "traffic_routing": prepare_routing},
            timeout_s=float(settings.specialist_timeout_s),
        )
        failures: list[str] = []
        for name, result in outcomes.items():
            state["specialist_results"][name] = _tool_summary(result)
            if not result.ok and result.error is not None:
                failures.append(f"specialist_unavailable:{name}:{result.error.code}")
                state["alerts"].append(
                    _alert(
                        "specialist_unavailable",
                        f"The {name} specialist is unavailable ({result.error.code}); "
                        "no plan can be approved",
                    )
                )

        routing = outcomes["traffic_routing"]
        shelter = outcomes["shelter"]
        context: RoutingContext | None = None
        origins: dict[str, int | None] = {}
        if routing.ok:
            context, origins = routing.data
            deps.scratch.setdefault(state["run_id"], {})["ctx"] = context
            for index, item in enumerate(groups):
                node = origins.get(item.group_id)
                groups[index] = item.model_copy(update={"origin_node": node})
                if node is None:
                    failures.append(f"unroutable_group:{item.settlement_id}")
                    state["alerts"].append(
                        _alert(
                            "unroutable_group",
                            f"{item.settlement_name} has no road node within "
                            f"{settings.max_snap_distance_m} m outside the fire perimeter",
                            settlement_id=item.settlement_id,
                        )
                    )
        state["groups"] = [item.model_dump(mode="json") for item in groups]

        candidates: list[ShelterCandidate] = []
        excluded: list[ExcludedShelter] = []
        if shelter.ok:
            listed, records = shelter.data
            excluded = list(listed.excluded)
            candidates = list(listed.candidates)
            state["shelter_snapshot"] = [
                ShelterSnapshot(
                    shelter_id=record.shelter_id,
                    occupancy=record.occupancy,
                    usable_capacity=usable_capacity(
                        record.capacity, record.usable_factor, settings.shelter_usable_factor
                    ),
                    is_active=record.is_active,
                    capacity_source=record.capacity_source,
                ).model_dump(mode="json")
                for record in sorted(records, key=lambda item: item.shelter_id)
            ]
            if context is not None:
                snapped = snap_shelters(
                    context.graph,
                    candidates,
                    perimeter_wkt=footprint.current_wkt,
                    max_snap_m=float(settings.max_snap_distance_m),
                    group_origin_nodes=frozenset(
                        item.origin_node for item in groups if item.origin_node is not None
                    ),
                )
                kept: list[ShelterCandidate] = []
                for candidate in candidates:
                    node = snapped.get(candidate.shelter_id)
                    if node is None:
                        excluded.append(
                            ExcludedShelter(shelter_id=candidate.shelter_id, reason="off_network")
                        )
                    else:
                        kept.append(candidate.model_copy(update={"node": node}))
                candidates = kept
        state["candidates"] = [item.model_dump(mode="json") for item in candidates]
        state["excluded_shelters"] = [
            item.model_dump(mode="json") for item in sorted(excluded, key=lambda e: e.shelter_id)
        ]
        state["preflight_failures"] = failures
        _audit(
            state,
            "dispatch_specialists",
            {"specialists": sorted(outcomes), "timeout_s": settings.specialist_timeout_s},
            {
                "results": {name: _tool_summary(result) for name, result in outcomes.items()},
                "candidate_ids": [item.shelter_id for item in candidates],
                "excluded": state["excluded_shelters"],
                "preflight_failures": failures,
            },
            started_ms,
        )
        # One audit row per specialist, written on the coordinator thread after the gather.
        for name, result in outcomes.items():
            _audit(
                state,
                f"specialist_{name}",
                {"specialist": name},
                _tool_summary(result),
                started_ms,
                agent=name,
            )
        return state

    def plan_evacuation(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        if not state["clusters"]:
            state["draft"] = None
            state["warnings"].append("No hotspot cluster to plan for; no evacuation plan produced")
            _audit(state, "plan_evacuation", {}, {"skipped": "no_clusters"}, started_ms)
            return state

        footprint = _footprint_of(state)
        context = deps.scratch.get(state["run_id"], {}).get("ctx") or _empty_routing_context(
            footprint
        )
        fire_results = tuple(
            FireSpreadResult.model_validate(item) for item in state["fire_results"]
        )
        inputs = PlanInputs(
            incident_id=state["incident_id"],
            run_id=state["run_id"],
            groups=tuple(EvacueeGroup.model_validate(item) for item in state["groups"]),
            candidates=tuple(ShelterCandidate.model_validate(item) for item in state["candidates"]),
            excluded=tuple(
                ExcludedShelter.model_validate(item) for item in state["excluded_shelters"]
            ),
            alerts=tuple(PlanAlert.model_validate(item) for item in state["alerts"]),
            warnings=tuple(state["warnings"]),
            preflight_failures=tuple(
                [*state["weather_missing"], *state["risk_failures"], *state["preflight_failures"]]
            ),
            clusters=tuple(HotspotCluster.model_validate(item) for item in state["clusters"]),
            fire_results=fire_results,
            weather_by_cluster={
                cluster_id: WeatherSnapshot.model_validate(item)
                for cluster_id, item in state["weather_by_cluster"].items()
            },
            cluster_risk=tuple(
                ClusterRisk(
                    cluster_id=item.cluster_id,
                    affected_area_ha=item.affected_area_km2 * 100.0,
                    spread_dir_deg=item.spread_direction_deg,
                    spread_rate_m_per_h=item.spread_rate_m_per_h,
                    confidence=item.confidence,
                )
                for item in fire_results
            ),
            known_settlement_ids=frozenset(item.settlement_id for item in repository.settlements()),
            known_shelter_ids=frozenset(item["shelter_id"] for item in state["shelter_snapshot"])
            or None,
        )
        outcome = plan_draft(
            inputs,
            context,
            PlanningParams.from_settings(settings),
            chooser=deps.chooser_factory(settings, settings.fix_menu_order),
        )
        state["draft"] = outcome.draft.model_dump(mode="json")
        state["llm_calls"] = [dict(item) for item in outcome.llm_calls]
        for index, metadata in enumerate(outcome.llm_calls, start=1):
            _audit(
                state,
                "choose_fix_strategy",
                {"call": index},
                {
                    "llm_called": metadata.get("llm_called"),
                    "fallback_reason": metadata.get("fallback_reason"),
                },
                started_ms,
                model_metadata=dict(metadata),
            )
        draft = outcome.draft
        _audit(
            state,
            "plan_evacuation",
            {
                "group_ids": [item.group_id for item in inputs.groups],
                "candidate_ids": [item.shelter_id for item in inputs.candidates],
                "preflight_failures": list(inputs.preflight_failures),
            },
            {
                "outcome": draft.outcome,
                "used_fallback": draft.used_fallback,
                "assignments": [
                    [item.group_id, item.shelter_id, item.persons]
                    for item in draft.shelter_assignments
                ],
                "failure_reasons": list(draft.failure_reasons),
                "resolver_steps": [item.model_dump(mode="json") for item in draft.resolver_steps],
            },
            started_ms,
        )
        return state

    def generate_rationale(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        metadata: dict[str, Any]
        if state["draft"] is None:
            reason = "no_plan"
        else:
            draft = PlanDraft.model_validate(state["draft"])
            failed = draft.outcome == "failed" or any(
                item.status == "fail" for item in draft.validation
            )
            reason = "plan_failed" if failed else ""
        if reason:
            state["rationale_text"] = (
                "[DETERMINISTIC FALLBACK] No approvable plan was produced; no LLM rationale "
                "was requested. Human review required."
            )
            state["is_llm_fallback"] = True
            metadata = {
                **base_model_metadata(settings),
                "llm_called": False,
                "is_fallback": True,
                "fallback_reason": reason,
                "finish_reason": None,
                "usage": None,
                "response_model": None,
            }
        else:
            result = deps.rationale_fn(compact_plan_summary(draft), settings)
            state["rationale_text"] = result.text
            state["is_llm_fallback"] = result.is_fallback
            metadata = result.model_metadata
        state["rationale_metadata"] = metadata
        _audit(
            state,
            "generate_rationale",
            {"draft_available": state["draft"] is not None, "reason": reason or None},
            {
                "rationale": state["rationale_text"],
                "is_llm_fallback": state["is_llm_fallback"],
            },
            started_ms,
            model_metadata=metadata,
        )
        return state

    def assemble_plan(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        if state["draft"] is None:
            state["error"] = state["error"] or "no_plan"
            _audit(state, "assemble_plan", {}, {"error": state["error"]}, started_ms)
            return state

        draft = PlanDraft.model_validate(state["draft"])
        now = deps.clock.now_utc()
        context: RoutingContext | None = deps.scratch.get(state["run_id"], {}).get("ctx")
        weather = {
            cluster_id: WeatherSnapshot.model_validate(item)
            for cluster_id, item in state["weather_by_cluster"].items()
        }
        settlements = repository.settlements()
        freshness = build_freshness(
            computed_at=now,
            latest_hotspot_at=repository.latest_hotspot_time(state["hotspot_ids"]),
            weather_by_cluster=weather,
            graph_built_at=None if context is None else context.graph_mtime,
            stale_firms_min=settings.stale_firms_min,
        )
        shelter_snapshot = tuple(
            ShelterSnapshot.model_validate(item) for item in state["shelter_snapshot"]
        )
        provenance = build_provenance(
            run_id=state["run_id"],
            state_version=state["state_version"],
            weather_provider=settings.weather_provider,
            graph_source="unavailable" if context is None else context.graph_source,
            graph_node_count=0 if context is None else context.graph.number_of_nodes(),
            graph_edge_count=0 if context is None else context.graph.number_of_edges(),
            trigger_id=state["trigger_id"],
            hotspot_ids=state["hotspot_ids"],
            cluster_ids=sorted(item["cluster_id"] for item in state["clusters"]),
            fire_run_ids=sorted(item["run_id"] for item in state["fire_results"]),
            fire_seeds=sorted(
                {seed for item in state["fire_results"] for seed in item["seeds_used"]}
            ),
            weather_valid_times={
                cluster_id: item.valid_time for cluster_id, item in weather.items()
            },
            graph_mtime=None if context is None else context.graph_mtime,
            shelter_snapshot=shelter_snapshot,
            settlement_sources={
                item.settlement_id: item.pop_source or "unknown" for item in settlements
            },
            params=PlanningParams.from_settings(settings).snapshot(),
        )
        rationale = RationaleResult(
            text=state["rationale_text"] or "",
            is_fallback=state["is_llm_fallback"],
            model_metadata=dict(state["rationale_metadata"] or {}),
        )
        registry_names = [
            *(item.name for item in settlements),
            *(item.name for item in repository.shelters()),
        ]
        is_simulated = (
            state["incident_origin"] in _SIMULATED_ORIGINS
            or any(item.is_simulated for item in draft.groups)
            or any(item["is_simulated"] for item in state["candidates"])
        )
        plan = finalize_plan(
            draft,
            rationale=rationale,
            registry_names=registry_names,
            freshness=freshness,
            provenance=provenance,
            created_at=now,
            valid_until=now + timedelta(minutes=settings.plan_valid_for_min),
            is_simulated=is_simulated,
        )
        state["plan"] = plan.model_dump(mode="json")

        latest = repository.latest_plan(state["incident_id"])
        if latest is not None and not is_material_change(latest.plan_data, plan):
            state["persist"] = {
                "created": False,
                "plan_id": latest.plan_id,
                "version": latest.version,
                "status": latest.status,
            }
            _audit(
                state,
                "assemble_plan",
                {"incident_id": state["incident_id"]},
                {"persisted": False, "plan_id": latest.plan_id, "version": latest.version},
                started_ms,
            )
            _audit(
                state,
                "replan_no_change",
                {"incident_id": state["incident_id"], "latest_plan_id": latest.plan_id},
                {"created": False, "version": latest.version},
                started_ms,
            )
            return state

        parent = None if latest is None else latest.plan_id
        previous = None if latest is None else latest.plan_data

        def persist(candidate: Any) -> PersistResult:
            return repository.persist_plan(
                candidate,
                expected_state_version=state["state_version"],
                parent_plan_id=parent,
                trigger_id=state["trigger_id"],
                diff=plan_diff(previous, candidate).model_dump(mode="json"),
            )

        persisted: PersistResult | None = None
        try:
            try:
                persisted = persist(plan)
            except CapacityRecheckFailed as error:
                plan = as_failed(plan, error.violations)
                state["plan"] = plan.model_dump(mode="json")
                state["warnings"].append(
                    "Shelter capacity changed during planning; plan recorded as failed"
                )
                persisted = persist(plan)
        except StateVersionConflict as conflict:
            state["error"] = "state_version_conflict"
            state["warnings"].append(
                f"Shared state moved during planning ({conflict}); no plan version was written"
            )

        if persisted is None:
            state["persist"] = None
            _audit(state, "assemble_plan", {}, {"error": state["error"]}, started_ms)
            return state
        state["persist"] = {
            "created": True,
            "plan_id": persisted.plan_id,
            "version": persisted.version,
            "status": plan.status,
            "state_version": persisted.state_version,
            "superseded_plan_ids": list(persisted.superseded_plan_ids),
        }
        _audit(
            state,
            "assemble_plan",
            {"incident_id": state["incident_id"]},
            {
                "persisted": True,
                "plan_id": persisted.plan_id,
                "version": persisted.version,
                "status": plan.status,
            },
            started_ms,
        )
        return state

    def write_audit(state: CoordinatorState) -> CoordinatorState:
        started_ms = _now_ms()
        pending_count = len(state["audit_entries"])
        _audit(
            state,
            "write_audit",
            {"pending_entries": pending_count},
            {"persisted_entries": pending_count + 1},
            started_ms,
        )
        repository.flush_audit(state["audit_entries"])
        if state["trigger_id"] is not None:
            # triggers.handled_run_id references agent_runs, so this must follow the flush.
            handled = next(
                (
                    entry
                    for entry in reversed(state["audit_entries"])
                    if entry["node_name"] in {"replan_no_change", "assemble_plan"}
                ),
                None,
            )
            if handled is not None and state["error"] is None:
                repository.mark_trigger_handled(state["trigger_id"], handled["entry_id"])
        return state

    return {
        "ingest_trigger": ingest_trigger,
        "cluster_hotspots": cluster_hotspots_node,
        "run_weather": run_weather,
        "run_fire_ca": run_fire_ca,
        "assess_risk": assess_risk_node,
        "dispatch_specialists": dispatch_specialists,
        "plan_evacuation": plan_evacuation,
        "generate_rationale": generate_rationale,
        "assemble_plan": assemble_plan,
        "write_audit": write_audit,
    }


__all__ = ["NODE_ORDER", "Node", "make_nodes", "snap_shelters"]

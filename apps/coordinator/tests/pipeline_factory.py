"""Shared builders for the offline Phase 3 pipeline tests (in-memory repo, synthetic graph)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from coordinator.deps import CoordinatorDeps
from coordinator.llm.groq_adapter import RationaleResult, base_model_metadata
from coordinator.repository import InMemoryPlanningRepository
from shapely.geometry import box
from wildfire_core.clock import SimClock
from wildfire_core.config import Settings, load_settings
from wildfire_core.schemas.phase2 import FireSpreadResult, HotspotCluster, WeatherSnapshot
from wildfire_core.schemas.plan import SettlementRecord, ShelterRecord

from tests.fixtures.graphs import build_synthetic_graph

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
INCIDENT_ID = "11111111-1111-4111-8111-111111111111"
FIRE_CENTRE = (11.70, 76.62)  # (lat, lon) of synthetic node 15
FAR_CENTRE = (12.24, 76.62)  # about 60 km north of the first fire
EMPTY = "POLYGON EMPTY"


def make_settings(**overrides: Any) -> Settings:
    """Settings with the LLM off and a short specialist timeout, whatever the local env says."""
    values: dict[str, Any] = {"llm_enabled": False, "specialist_timeout_s": 30}
    values.update(overrides)
    return load_settings().model_copy(update=values)


@dataclass
class RecordingRepository(InMemoryPlanningRepository):
    """In-memory repository that remembers every weather lookup."""

    weather_queries: list[tuple[float, float]] = field(default_factory=list)

    def weather_for(self, lat: float, lon: float, **kwargs: Any) -> WeatherSnapshot:
        self.weather_queries.append((lat, lon))
        return super().weather_for(lat, lon, **kwargs)


def square_fire_fn(calls: list[dict[str, Any]] | None = None) -> Callable[..., FireSpreadResult]:
    """Fire simulator stub: nested squares around the cluster centroid (deterministic)."""

    def fire(cluster: HotspotCluster, weather: WeatherSnapshot, **_kwargs: Any) -> FireSpreadResult:
        if calls is not None:
            calls.append({"cluster_id": cluster.cluster_id, "wind_speed_ms": weather.wind_speed_ms})
        lon, lat = cluster.centroid_lon, cluster.centroid_lat

        def square(half: float) -> str:
            return box(lon - half, lat - half, lon + half, lat + half).wkt

        return FireSpreadResult(
            cluster_id=cluster.cluster_id,
            current_perimeter_wkt=square(0.004),
            p50_1h_wkt=square(0.012),
            p50_3h_wkt=square(0.014),
            p50_6h_wkt=square(0.015),
            p90_1h_wkt=square(0.012),
            p90_3h_wkt=square(0.014),
            p90_6h_wkt=square(0.015),
            affected_area_km2=1.0,
            spread_direction_deg=45.0,
            spread_rate_m_per_h=300.0,
            confidence="medium",
        )

    return fire


def fallback_rationale(settings: Settings, calls: list[Any] | None = None) -> Any:
    def rationale(summary: Any, _settings: Settings) -> RationaleResult:
        if calls is not None:
            calls.append(summary)
        return RationaleResult(
            text="[DETERMINISTIC FALLBACK] LLM rationale unavailable (llm_disabled).",
            is_fallback=True,
            model_metadata={
                **base_model_metadata(settings),
                "llm_called": False,
                "is_fallback": True,
                "fallback_reason": "llm_disabled",
            },
        )

    return rationale


def add_cluster(
    repo: InMemoryPlanningRepository,
    incident_id: str,
    centre: tuple[float, float],
    *,
    count: int = 5,
    trigger_id: str | None = None,
) -> str:
    """Add ``count`` hotspots around ``centre`` plus a new_hotspot trigger; returns its id."""
    rows = [
        {
            "id": str(uuid4()),
            "lat": centre[0] + index * 0.0002,
            "lon": centre[1] + index * 0.0002,
            "frp": 20.0 + index,
            "acq_datetime": NOW - timedelta(minutes=30),
        }
        for index in range(count)
    ]
    return repo.add_hotspots(incident_id, rows, trigger_id=trigger_id)


def add_weather(
    repo: InMemoryPlanningRepository,
    settings: Settings,
    centre: tuple[float, float],
    *,
    wind_speed_ms: float = 4.0,
    age_min: int = 20,
    origin: str = "simulated",
) -> None:
    repo.add_weather_point(
        centre[0],
        centre[1],
        origin=origin,
        provider=settings.weather_provider,
        valid_time=NOW - timedelta(minutes=age_min),
        wind_speed_ms=wind_speed_ms,
    )


def add_settlements(repo: InMemoryPlanningRepository, *, near_population: int | None = 60) -> None:
    """One settlement whose buffer meets the 1h P50 (node 17) and one far away (node 36)."""
    repo.add_settlement(
        SettlementRecord(
            settlement_id="set-near",
            external_ref="S-NEAR",
            name="Nearville",
            lat=11.70,
            lon=76.64,
            population=near_population,
            pop_source="synthetic",
            buffer_m=1500,
            is_simulated=True,
        )
    )
    repo.add_settlement(
        SettlementRecord(
            settlement_id="set-far",
            external_ref="S-FAR",
            name="Farville",
            lat=11.73,
            lon=76.65,
            population=40,
            pop_source="synthetic",
            buffer_m=500,
            is_simulated=True,
        )
    )


def add_shelters(
    repo: InMemoryPlanningRepository, *, capacity: int = 200, usable_factor: float = 0.5
) -> None:
    """Three shelters on synthetic nodes 24, 30 and 35 (outside the exclusion zone)."""
    for ref, name, lat, lon in (
        ("SH-1", "Hall One", 11.71, 76.65),
        ("SH-2", "School Two", 11.72, 76.65),
        ("SH-3", "Hall Three", 11.73, 76.64),
    ):
        repo.add_shelter(
            ShelterRecord(
                shelter_id=f"shelter-{ref.lower()}",
                external_ref=ref,
                name=name,
                kind="school",
                lat=lat,
                lon=lon,
                capacity=capacity,
                usable_factor=usable_factor,
                occupancy=0,
                capacity_source="synthetic",
                is_simulated=True,
            )
        )


def seeded_repository(
    settings: Settings,
    *,
    shelter_capacity: int = 200,
    near_population: int | None = 60,
    with_weather: bool = True,
    repo: InMemoryPlanningRepository | None = None,
) -> tuple[InMemoryPlanningRepository, str]:
    """Simulated incident with one fire cluster, two settlements, three shelters and weather."""
    repo = repo if repo is not None else RecordingRepository()
    repo.add_incident(INCIDENT_ID, origin="simulated")
    trigger_id = add_cluster(repo, INCIDENT_ID, FIRE_CENTRE)
    if with_weather:
        add_weather(repo, settings, FIRE_CENTRE)
    add_settlements(repo, near_population=near_population)
    add_shelters(repo, capacity=shelter_capacity)
    return repo, trigger_id


def make_deps(
    repo: InMemoryPlanningRepository,
    settings: Settings,
    *,
    fire_calls: list[dict[str, Any]] | None = None,
    rationale_calls: list[Any] | None = None,
    **overrides: Any,
) -> CoordinatorDeps:
    values: dict[str, Any] = {
        "settings": settings,
        "repository": repo,
        "graph_loader": lambda _path: build_synthetic_graph(),
        "fire_fn": square_fire_fn(fire_calls),
        "clock": SimClock(NOW),
        "rationale_fn": fallback_rationale(settings, rationale_calls),
    }
    values.update(overrides)
    return CoordinatorDeps(**values)


def node_names(entries: Sequence[dict[str, Any]]) -> set[str]:
    return {entry["node_name"] for entry in entries}

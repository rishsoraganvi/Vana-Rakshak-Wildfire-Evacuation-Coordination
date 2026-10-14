from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import networkx as nx
from coordinator import graph as coordinator_graph
from coordinator.runner import build_graph
from pydantic import SecretStr
from wildfire_core.config import BBox
from wildfire_core.schemas.phase2 import FireSpreadResult, WeatherSnapshot


class FakeResult:
    def __init__(self, *, rows=(), scalar=None):
        self.rows = list(rows)
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class FakeConnection:
    def __init__(self, engine):
        self.engine = engine

    def execute(self, statement, parameters=None):
        sql = " ".join(str(statement).split())
        if "SELECT details FROM triggers" in sql:
            return FakeResult(rows=[{"details": self.engine.trigger_details}])
        if "FROM hotspots" in sql:
            return FakeResult(rows=self.engine.hotspots)
        if "SELECT origin::text FROM incidents" in sql:
            return FakeResult(scalar="replay")
        if "SELECT COALESCE(MAX(version)" in sql:
            return FakeResult(scalar=1)
        if "INSERT INTO plan_versions" in sql:
            self.engine.plan_parameters = parameters
            return FakeResult()
        if "INSERT INTO agent_runs" in sql:
            self.engine.audit_parameters = parameters
            return FakeResult()
        if "UPDATE incidents SET status" in sql:
            return FakeResult()
        raise AssertionError(f"Unexpected SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeEngine:
    def __init__(self, hotspot_rows, hotspot_ids):
        self.hotspots = hotspot_rows
        self.trigger_details = {"hotspot_ids": [str(item) for item in hotspot_ids]}
        self.plan_parameters = None
        self.audit_parameters = None

    @contextmanager
    def connect(self):
        yield FakeConnection(self)

    @contextmanager
    def begin(self):
        yield FakeConnection(self)


def test_coordinator_runs_all_nodes_with_incident_scoped_data(monkeypatch) -> None:
    incident_id = str(uuid4())
    run_id = str(uuid4())
    hotspot_ids = [uuid4() for _ in range(5)]
    hotspot_rows = [
        {
            "id": hotspot_id,
            "lat": 11.72 + index * 0.0002,
            "lon": 76.64 + index * 0.0002,
            "frp": 20.0 + index,
        }
        for index, hotspot_id in enumerate(hotspot_ids)
    ]
    engine = FakeEngine(hotspot_rows, hotspot_ids)
    settings = SimpleNamespace(
        database_url=SecretStr("postgresql+psycopg://unused"),
        aoi_bbox=BBox(west=76.0, south=11.5, east=77.3, north=12.4),
        osm_cache_path=Path("tests/fixtures/osm/bandipur_stub.graphml"),
        dbscan_eps_deg=0.01,
        dbscan_min_samples=3,
        fire_grid_resolution_m=250,
        fire_ensemble_seeds=(42, 43, 44),
        route_fire_penalty_near=5.0,
    )
    weather = WeatherSnapshot(
        valid_time=datetime.now(UTC),
        wind_speed_ms=5.0,
        wind_dir_deg=45.0,
        rh_pct=30.0,
        temperature_c=34.0,
    )
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "EPSG:4326"
    graph.add_node(1, x=76.64, y=11.72)
    graph.add_node(2, x=76.0, y=11.72)
    graph.add_node(3, x=77.3, y=11.72)
    graph.add_edge(1, 2, key=0, length=1000.0, travel_time=90.0)
    graph.add_edge(1, 3, key=0, length=1100.0, travel_time=100.0)

    monkeypatch.setattr(coordinator_graph, "_settings", lambda: settings)
    monkeypatch.setattr(coordinator_graph, "_engine_for", lambda _url: engine)
    monkeypatch.setattr(coordinator_graph, "get_weather_snapshot", lambda *_args: weather)
    monkeypatch.setattr(coordinator_graph, "compute_fire_spread", _fire_result)
    monkeypatch.setattr(coordinator_graph, "load_or_download_graph", lambda *_args: graph)
    monkeypatch.setattr(
        coordinator_graph,
        "generate_rationale",
        lambda *_args: ("Grounded replay rationale", False),
    )

    initial_state = {
        "incident_id": incident_id,
        "run_id": run_id,
        "hotspot_ids": [],
        "hotspots": [],
        "weather_snapshot": None,
        "clusters": [],
        "fire_result": None,
        "routes": [],
        "rationale": "",
        "is_llm_fallback": False,
        "audit_entries": [],
        "warnings": [],
        "error": None,
    }

    final_state = build_graph().compile().invoke(initial_state)

    assert final_state["error"] is None
    assert final_state["hotspot_ids"] == [str(item) for item in hotspot_ids]
    assert len(final_state["clusters"]) == 1
    assert final_state["fire_result"] is not None
    assert final_state["routes"]
    assert final_state["rationale"] == "Grounded replay rationale"
    assert len(final_state["audit_entries"]) == 8
    assert engine.plan_parameters["plan_id"] == UUID(
        json.loads(engine.plan_parameters["plan_data"])["plan_id"]
    )
    assert engine.plan_parameters["is_simulated"] is True
    assert len(engine.audit_parameters) == 8


def _fire_result(cluster, _weather, **_kwargs) -> FireSpreadResult:
    return FireSpreadResult(
        cluster_id=cluster.cluster_id,
        current_perimeter_wkt="POLYGON EMPTY",
        p50_1h_wkt="POLYGON EMPTY",
        p50_3h_wkt="POLYGON EMPTY",
        p50_6h_wkt="POLYGON EMPTY",
        p90_1h_wkt="POLYGON EMPTY",
        p90_3h_wkt="POLYGON EMPTY",
        p90_6h_wkt="POLYGON EMPTY",
        affected_area_km2=1.0,
        spread_direction_deg=45.0,
        spread_rate_m_per_h=100.0,
        confidence="medium",
    )
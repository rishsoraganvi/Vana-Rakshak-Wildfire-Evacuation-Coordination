from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import networkx as nx
import pytest
from coordinator import graph as coordinator_graph
from coordinator.llm.groq_adapter import RationaleResult, base_model_metadata
from coordinator.runner import build_graph
from pydantic import SecretStr
from shapely import wkt
from shapely.geometry import Point, box
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
        weather_provider="open-meteo",
        llm_provider="groq",
        llm_model="test-model",
        llm_enabled=True,
        llm_rationale_max_tokens=400,
        llm_request_timeout_s=30,
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
    monkeypatch.setattr(
        coordinator_graph, "get_weather_snapshot", lambda *_args, **_kwargs: weather
    )
    monkeypatch.setattr(coordinator_graph, "compute_fire_spread", _fire_result)
    monkeypatch.setattr(coordinator_graph, "load_or_download_graph", lambda *_args: graph)
    monkeypatch.setattr(
        coordinator_graph,
        "generate_rationale",
        lambda *_args: RationaleResult(
            text="Grounded replay rationale",
            is_fallback=False,
            model_metadata={**base_model_metadata(settings), "llm_called": True},
        ),
    )

    initial_state = {
        "incident_id": incident_id,
        "run_id": run_id,
        "hotspot_ids": [],
        "hotspots": [],
        "weather_snapshot": None,
        "clusters": [],
        "fire_results": [],
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
    assert len(final_state["fire_results"]) == 1
    assert final_state["routes"]
    assert final_state["rationale"] == "Grounded replay rationale"
    assert len(final_state["audit_entries"]) == 8
    assert engine.plan_parameters["plan_id"] == UUID(
        json.loads(engine.plan_parameters["plan_data"])["plan_id"]
    )
    assert engine.plan_parameters["is_simulated"] is True
    assert len(engine.audit_parameters) == 8

    rationale_entries = [
        entry
        for entry in final_state["audit_entries"]
        if entry["node_name"] == "generate_rationale"
    ]
    assert len(rationale_entries) == 1
    assert rationale_entries[0]["model_metadata"]["model"] == "test-model"
    rows_by_node = {row["node_name"]: row for row in engine.audit_parameters}
    metadata_text = rows_by_node["generate_rationale"]["model_metadata"]
    assert isinstance(metadata_text, str)
    assert json.loads(metadata_text)["model"] == "test-model"
    others = [row for name, row in rows_by_node.items() if name != "generate_rationale"]
    assert len(others) == 7
    assert all(row["model_metadata"] is None for row in others)


def test_generate_rationale_audit_records_metadata_when_inputs_unavailable(monkeypatch) -> None:
    settings = SimpleNamespace(
        weather_provider="open-meteo",
        llm_provider="groq",
        llm_model="test-model",
        llm_enabled=True,
        llm_rationale_max_tokens=400,
        llm_request_timeout_s=30,
    )
    monkeypatch.setattr(coordinator_graph, "_settings", lambda: settings)
    state = {
        "incident_id": str(uuid4()),
        "run_id": str(uuid4()),
        "fire_results": [],
        "weather_snapshot": None,
        "routes": [],
        "rationale": "",
        "is_llm_fallback": False,
        "audit_entries": [],
    }

    coordinator_graph.generate_rationale_node(state)

    metadata = state["audit_entries"][0]["model_metadata"]
    assert metadata["fallback_reason"] == "inputs_unavailable"
    assert metadata["llm_called"] is False
    assert metadata["is_fallback"] is True
    assert metadata["model"] == "test-model"


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


# ---------------------------------------------------------------------------
# Plan 02-07: per-cluster CA, union-penalised routing, outside-fire origins
# ---------------------------------------------------------------------------


def _pipeline_settings(**overrides) -> SimpleNamespace:
    values = {
        "database_url": SecretStr("postgresql+psycopg://unused"),
        "aoi_bbox": BBox(west=76.0, south=11.5, east=77.3, north=12.4),
        "osm_cache_path": Path("tests/fixtures/osm/bandipur_stub.graphml"),
        "dbscan_eps_deg": 0.01,
        "dbscan_min_samples": 3,
        "fire_grid_resolution_m": 250,
        "fire_ensemble_seeds": (42, 43, 44),
        "route_fire_penalty_near": 5.0,
        "weather_provider": "open-meteo",
        "llm_provider": "groq",
        "llm_model": "test-model",
        "llm_enabled": True,
        "llm_rationale_max_tokens": 400,
        "llm_request_timeout_s": 30,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _pipeline_weather() -> WeatherSnapshot:
    return WeatherSnapshot(
        valid_time=datetime.now(UTC),
        wind_speed_ms=5.0,
        wind_dir_deg=45.0,
        rh_pct=30.0,
        temperature_c=34.0,
    )


def _empty_state() -> dict:
    return {
        "incident_id": str(uuid4()),
        "run_id": str(uuid4()),
        "hotspot_ids": [],
        "hotspots": [],
        "weather_snapshot": None,
        "clusters": [],
        "fire_results": [],
        "routes": [],
        "rationale": "",
        "is_llm_fallback": False,
        "audit_entries": [],
        "warnings": [],
        "error": None,
    }


def _hotspot_rows(centres, *, counts) -> tuple[list[dict], list]:
    rows: list[dict] = []
    ids: list = []
    for (lat, lon), count in zip(centres, counts, strict=True):
        for index in range(count):
            hotspot_id = uuid4()
            ids.append(hotspot_id)
            rows.append(
                {
                    "id": hotspot_id,
                    "lat": lat + index * 0.0001,
                    "lon": lon + index * 0.0001,
                    "frp": 20.0 + index,
                }
            )
    return rows, ids


def _toy_graph(nodes, edges) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph["crs"] = "EPSG:4326"
    for node_id, (x, y) in nodes.items():
        graph.add_node(node_id, x=x, y=y)
    for u, v, length, travel_time in edges:
        graph.add_edge(u, v, key=0, length=length, travel_time=travel_time)
        graph.add_edge(v, u, key=0, length=length, travel_time=travel_time)
    return graph


def _stub_fire(current_wkt: str, p50_wkt: str, cluster_id: str) -> FireSpreadResult:
    return FireSpreadResult(
        cluster_id=cluster_id,
        current_perimeter_wkt=current_wkt,
        p50_1h_wkt=p50_wkt,
        p50_3h_wkt="POLYGON EMPTY",
        p50_6h_wkt="POLYGON EMPTY",
        p90_1h_wkt="POLYGON EMPTY",
        p90_3h_wkt="POLYGON EMPTY",
        p90_6h_wkt="POLYGON EMPTY",
        affected_area_km2=1.0,
        spread_direction_deg=None,
        spread_rate_m_per_h=100.0,
        confidence="medium",
    )


def _square_fire_fn(current_half: float, p50_half: float | None, calls: list):
    def fire(cluster, _weather, **_kwargs) -> FireSpreadResult:
        calls.append(cluster.cluster_id)
        lon, lat = cluster.centroid_lon, cluster.centroid_lat
        current = box(
            lon - current_half, lat - current_half, lon + current_half, lat + current_half
        )
        p50 = (
            box(lon - p50_half, lat - p50_half, lon + p50_half, lat + p50_half).wkt
            if p50_half is not None
            else "POLYGON EMPTY"
        )
        return _stub_fire(current.wkt, p50, cluster.cluster_id)

    return fire


def _install_pipeline(monkeypatch, *, engine, settings, graph, fire_fn, rationale=None) -> None:
    monkeypatch.setattr(coordinator_graph, "_settings", lambda: settings)
    monkeypatch.setattr(coordinator_graph, "_engine_for", lambda _url: engine)
    monkeypatch.setattr(
        coordinator_graph, "get_weather_snapshot", lambda *_args, **_kwargs: _pipeline_weather()
    )
    monkeypatch.setattr(coordinator_graph, "compute_fire_spread", fire_fn)
    monkeypatch.setattr(coordinator_graph, "load_or_download_graph", lambda *_args: graph)
    monkeypatch.setattr(
        coordinator_graph,
        "generate_rationale",
        rationale
        or (
            lambda *_args: RationaleResult(
                text="Grounded rationale",
                is_fallback=False,
                model_metadata={**base_model_metadata(settings), "llm_called": True},
            )
        ),
    )


def test_every_cluster_is_simulated_and_routing_penalises_union_of_fires(monkeypatch) -> None:
    rows, ids = _hotspot_rows([(11.90, 76.30), (11.90, 76.40)], counts=(4, 3))
    engine = FakeEngine(rows, ids)
    settings = _pipeline_settings()
    graph = _toy_graph(
        {1: (76.0, 11.9), 2: (76.6, 11.9), 3: (77.3, 11.9)},
        [(1, 2, 1000.0, 90.0), (2, 3, 1000.0, 90.0)],
    )
    fire_calls: list[str] = []
    penalty_calls: list[tuple[str, str]] = []
    real_apply = coordinator_graph.apply_fire_penalties

    def recording_apply(graph_arg, current_wkt, p50_wkt, **kwargs):
        penalty_calls.append((current_wkt, p50_wkt))
        return real_apply(graph_arg, current_wkt, p50_wkt, **kwargs)

    rationale_inputs: list = []

    def recording_rationale(fire_results, *_args):
        rationale_inputs.append(list(fire_results))
        return RationaleResult(
            text="Grounded rationale",
            is_fallback=False,
            model_metadata={**base_model_metadata(settings), "llm_called": True},
        )

    _install_pipeline(
        monkeypatch,
        engine=engine,
        settings=settings,
        graph=graph,
        fire_fn=_square_fire_fn(0.01, 0.02, fire_calls),
        rationale=recording_rationale,
    )
    monkeypatch.setattr(coordinator_graph, "apply_fire_penalties", recording_apply)

    final_state = build_graph().compile().invoke(_empty_state())

    assert final_state["error"] is None
    clusters = final_state["clusters"]
    assert len(clusters) == 2
    assert len(fire_calls) == 2
    assert set(fire_calls) == {cluster["cluster_id"] for cluster in clusters}

    assert len(penalty_calls) == 1
    current_union = wkt.loads(penalty_calls[0][0])
    p50_union = wkt.loads(penalty_calls[0][1])
    for cluster in clusters:
        centroid = Point(cluster["centroid_lon"], cluster["centroid_lat"])
        assert current_union.covers(centroid)
        assert p50_union.covers(centroid)

    fire_results = final_state["fire_results"]
    assert len(fire_results) == 2
    assert len({item["cluster_id"] for item in fire_results}) == 2

    plan_data = json.loads(engine.plan_parameters["plan_data"])
    assert len(plan_data["fire_results"]) == len(plan_data["clusters"]) == 2
    assert {item["cluster_id"] for item in plan_data["fire_results"]} == {
        item["cluster_id"] for item in plan_data["clusters"]
    }

    assert len(rationale_inputs) == 1
    assert len(rationale_inputs[0]) == 2


def _fixed_fire_fn(current_wkt: str, p50_wkt: str):
    def fire(cluster, _weather, **_kwargs) -> FireSpreadResult:
        return _stub_fire(current_wkt, p50_wkt, cluster.cluster_id)

    return fire


def test_route_origin_moves_outside_current_perimeter(monkeypatch) -> None:
    rows, ids = _hotspot_rows([(11.72, 76.64)], counts=(4,))
    engine = FakeEngine(rows, ids)
    graph = _toy_graph(
        {1: (76.64, 11.72), 2: (76.66, 11.72), 3: (77.30, 11.72), 4: (76.00, 11.72)},
        [(1, 2, 100.0, 10.0), (2, 3, 1000.0, 100.0), (1, 4, 500.0, 50.0)],
    )
    _install_pipeline(
        monkeypatch,
        engine=engine,
        settings=_pipeline_settings(),
        graph=graph,
        fire_fn=_fixed_fire_fn(box(76.63, 11.71, 76.65, 11.73).wkt, "POLYGON EMPTY"),
    )

    final_state = build_graph().compile().invoke(_empty_state())

    assert final_state["error"] is None
    assert len(final_state["routes"]) == 1
    route = final_state["routes"][0]
    assert tuple(route["osm_node_path"]) == (2, 3)
    assert route["safety_classification"] == "safe"
    assert any(
        "moved to nearest road node outside the current perimeter" in warning
        for warning in final_state["warnings"]
    )


def test_blocked_candidates_choose_least_fire_exposure(monkeypatch) -> None:
    rows, ids = _hotspot_rows([(11.72, 76.66)], counts=(4,))
    engine = FakeEngine(rows, ids)
    graph = _toy_graph(
        {2: (76.66, 11.72), 3: (77.30, 11.72), 4: (76.00, 11.72)},
        [(2, 3, 5000.0, 500.0), (2, 4, 500.0, 50.0)],
    )
    ring = (
        "POLYGON((76.61 11.67, 76.71 11.67, 76.71 11.77, 76.61 11.77, 76.61 11.67), "
        "(76.65 11.71, 76.67 11.71, 76.67 11.73, 76.65 11.73, 76.65 11.71))"
    )
    _install_pipeline(
        monkeypatch,
        engine=engine,
        settings=_pipeline_settings(),
        graph=graph,
        fire_fn=_fixed_fire_fn(ring, "POLYGON EMPTY"),
    )

    final_state = build_graph().compile().invoke(_empty_state())

    assert final_state["error"] is None
    assert len(final_state["routes"]) == 1
    route = final_state["routes"][0]
    assert tuple(route["osm_node_path"]) == (2, 4)
    assert route["safety_classification"] == "blocked"
    assert any("No safe route found for fire cluster" in w for w in final_state["warnings"])


def test_offline_pipeline_with_real_ca_and_routing_on_fixture_graph(monkeypatch) -> None:
    """Real CA ensemble and real routing on the bundled fixture graph (PLAT-06)."""
    fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/osm/bandipur_stub.graphml"
    jitter = [(-0.002, -0.001), (-0.001, 0.001), (0.0, 0.0), (0.001, -0.002), (0.002, 0.001)]
    rows = []
    ids = []
    for index, (lat_delta, lon_delta) in enumerate(jitter):
        hotspot_id = uuid4()
        ids.append(hotspot_id)
        rows.append(
            {
                "id": hotspot_id,
                "lat": 11.72 + lat_delta,
                "lon": 76.64 + lon_delta,
                "frp": 20.0 + index,
            }
        )
    engine = FakeEngine(rows, ids)
    settings = _pipeline_settings(osm_cache_path=fixture, fire_grid_resolution_m=500)

    monkeypatch.setattr(coordinator_graph, "_settings", lambda: settings)
    monkeypatch.setattr(coordinator_graph, "_engine_for", lambda _url: engine)
    monkeypatch.setattr(
        coordinator_graph, "get_weather_snapshot", lambda *_args, **_kwargs: _pipeline_weather()
    )
    monkeypatch.setattr(
        coordinator_graph,
        "generate_rationale",
        lambda *_args: RationaleResult(
            text="Grounded rationale",
            is_fallback=False,
            model_metadata={**base_model_metadata(settings), "llm_called": True},
        ),
    )

    final_state = build_graph().compile().invoke(_empty_state())

    assert final_state["error"] is None
    assert len(final_state["fire_results"]) == 1
    fire = final_state["fire_results"][0]
    for field in (
        "p50_1h_wkt",
        "p50_3h_wkt",
        "p50_6h_wkt",
        "p90_1h_wkt",
        "p90_3h_wkt",
        "p90_6h_wkt",
    ):
        assert fire[field], field
        assert not wkt.loads(fire[field]).is_empty, field
    assert wkt.loads(fire["current_perimeter_wkt"]).covers(Point(76.64, 11.72))
    direction = fire["spread_direction_deg"]
    assert direction is None or 180.0 <= direction <= 270.0

    assert len(final_state["routes"]) == 1
    route = final_state["routes"][0]
    assert route["osm_node_path"][0] == 1000001
    assert route["safety_classification"] == "blocked"

    assert engine.plan_parameters is not None
    assert len(final_state["audit_entries"]) == 8


# ---------------------------------------------------------------------------
# Plan 02-09: incident-scoped weather and no fabricated observation
# ---------------------------------------------------------------------------


def _weather_pipeline(monkeypatch, weather_fn):
    rows, ids = _hotspot_rows([(11.72, 76.64), (11.74, 76.68)], counts=(2, 2))
    engine = FakeEngine(rows, ids)
    graph = _toy_graph(
        {1: (76.64, 11.72), 2: (76.00, 11.72), 3: (77.30, 11.72)},
        [(1, 2, 1000.0, 90.0), (1, 3, 1100.0, 100.0)],
    )
    _install_pipeline(
        monkeypatch,
        engine=engine,
        settings=_pipeline_settings(dbscan_min_samples=2),
        graph=graph,
        fire_fn=_square_fire_fn(0.002, None, []),
    )
    monkeypatch.setattr(coordinator_graph, "get_weather_snapshot", weather_fn)
    return engine, rows


def test_run_weather_queries_incident_origin_and_hotspot_location(monkeypatch) -> None:
    calls: list[tuple[tuple, dict]] = []

    def recording_weather(*args, **kwargs):
        calls.append((args, kwargs))
        return _pipeline_weather()

    _, rows = _weather_pipeline(monkeypatch, recording_weather)

    build_graph().compile().invoke(_empty_state())

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs["origin"] == "replay"
    assert kwargs["provider"] == "open-meteo"
    assert args[0] == pytest.approx(sum(row["lat"] for row in rows) / len(rows))
    assert args[1] == pytest.approx(sum(row["lon"] for row in rows) / len(rows))


def test_weather_unavailable_skips_planning_without_fabrication(monkeypatch) -> None:
    def unavailable(*_args, **_kwargs):
        raise LookupError("No complete weather observation")

    engine, _ = _weather_pipeline(monkeypatch, unavailable)

    final_state = build_graph().compile().invoke(_empty_state())

    assert final_state["weather_snapshot"] is None
    assert final_state["fire_results"] == []
    assert final_state["routes"] == []
    assert final_state["error"] is not None
    assert engine.plan_parameters is None
    assert len(engine.audit_parameters) == 8
    weather_entry = next(
        entry for entry in final_state["audit_entries"] if entry["node_name"] == "run_weather"
    )
    outputs = json.loads(weather_entry["outputs_json"])
    assert outputs["weather_snapshot"] is None
    assert "valid_time" not in weather_entry["outputs_json"]
    assert any(
        "No weather observation was fabricated" in warning for warning in final_state["warnings"]
    )
    rationale_entry = next(
        entry
        for entry in final_state["audit_entries"]
        if entry["node_name"] == "generate_rationale"
    )
    assert rationale_entry["model_metadata"]["fallback_reason"] == "inputs_unavailable"

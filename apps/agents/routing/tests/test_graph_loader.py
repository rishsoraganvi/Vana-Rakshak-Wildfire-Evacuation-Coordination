from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import networkx as nx
import osmnx as ox
import pytest
from agent_routing import GraphNotBuiltError, build_graph_for_area, load_graph
from agent_routing import graph as graph_module

from tests.fixtures.graphs import build_synthetic_graph

REPO_ROOT = Path(__file__).resolve().parents[4]
STUB = REPO_ROOT / "tests" / "fixtures" / "osm" / "bandipur_stub.graphml"
SCRIPT = REPO_ROOT / "scripts" / "build_osm_graph.py"

_DOWNLOAD_FUNCTIONS = (
    "graph_from_bbox",
    "graph_from_polygon",
    "graph_from_point",
    "graph_from_place",
    "graph_from_address",
)


def _forbid_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network download attempted")

    for name in _DOWNLOAD_FUNCTIONS:
        monkeypatch.setattr(ox, name, explode)


def test_load_graph_missing_file_raises_graph_not_built_and_never_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_downloads(monkeypatch)

    with pytest.raises(GraphNotBuiltError) as excinfo:
        load_graph(tmp_path / "missing.graphml")

    assert isinstance(excinfo.value, FileNotFoundError)
    assert "uv run python scripts/build_osm_graph.py" in str(excinfo.value)


def test_load_graph_is_cached_in_process_and_reloads_on_mtime_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file = tmp_path / "road.graphml"
    shutil.copy(STUB, cache_file)
    real_load = ox.load_graphml
    calls: list[Path] = []

    def counting_load(filepath: Path, *args: object, **kwargs: object) -> nx.MultiDiGraph:
        calls.append(Path(filepath))
        return real_load(filepath, *args, **kwargs)

    monkeypatch.setattr(ox, "load_graphml", counting_load)
    _forbid_downloads(monkeypatch)

    first = load_graph(cache_file)
    second = load_graph(cache_file)

    assert second is first
    assert len(calls) == 1

    stat = cache_file.stat()
    os.utime(cache_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    third = load_graph(cache_file)

    assert len(calls) == 2
    assert third is not first


def test_bundled_stub_loads_with_travel_times() -> None:
    graph = load_graph(STUB)

    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 4
    assert all(data["travel_time"] > 0 for _, _, data in graph.edges(data=True))


def test_load_graph_adds_travel_times_only_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_file = tmp_path / "road.graphml"
    cache_file.write_text("cached", encoding="utf-8")
    complete = build_synthetic_graph()
    bare = build_synthetic_graph()
    for _u, _v, data in bare.edges(data=True):
        del data["travel_time"]
    speed_calls: list[str] = []

    def add_speeds(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        speed_calls.append("speeds")
        return graph

    def add_times(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
        speed_calls.append("times")
        for _u, _v, data in graph.edges(data=True):
            data["travel_time"] = 1.0
        return graph

    monkeypatch.setattr(ox, "add_edge_speeds", add_speeds)
    monkeypatch.setattr(ox, "add_edge_travel_times", add_times)

    monkeypatch.setattr(ox, "load_graphml", lambda _path: complete)
    assert load_graph(cache_file) is complete
    assert speed_calls == []

    os.utime(cache_file, ns=(0, 1_000_000_000))
    monkeypatch.setattr(ox, "load_graphml", lambda _path: bare)
    loaded = load_graph(cache_file)

    assert loaded is bare
    assert speed_calls == ["speeds", "times"]


def test_load_or_download_graph_wrapper_never_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _forbid_downloads(monkeypatch)

    with pytest.raises(GraphNotBuiltError):
        graph_module.load_or_download_graph(
            tmp_path / "absent.graphml", (11.74, 11.70, 76.66, 76.62), "drive"
        )

    loaded = graph_module.load_or_download_graph(STUB, (11.74, 11.70, 76.66, 76.62))
    assert loaded.number_of_edges() == 4


def test_build_graph_for_area_writes_file_from_metric_buffer_and_uses_project_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    synthetic = build_synthetic_graph()

    def fake_from_polygon(polygon: object, **kwargs: object) -> nx.MultiDiGraph:
        captured["polygon"] = polygon
        captured["kwargs"] = kwargs
        return synthetic

    monkeypatch.setattr(ox.settings, "cache_folder", "unset")
    monkeypatch.setattr(ox.settings, "use_cache", False)
    monkeypatch.setattr(ox, "graph_from_polygon", fake_from_polygon)
    target = tmp_path / "nested" / "g.graphml"

    graph = build_graph_for_area(11.72, 76.64, 10_000, target)

    min_lon, min_lat, max_lon, max_lat = captured["polygon"].bounds  # type: ignore[attr-defined]
    assert 0.09 <= 11.72 - min_lat <= 0.092
    assert 0.09 <= max_lat - 11.72 <= 0.092
    assert min_lon < 76.64 < max_lon
    assert captured["kwargs"] == {"network_type": "drive", "simplify": True}
    assert str(ox.settings.cache_folder).replace("\\", "/").endswith("data/osm/cache")
    assert ox.settings.use_cache is True
    assert target.is_file()
    assert not list(target.parent.glob("*.tmp"))
    assert graph.number_of_edges() == synthetic.number_of_edges()
    assert all("travel_time" in data for _, _, data in graph.edges(data=True))


def test_build_graph_for_area_failure_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_save(_graph: nx.MultiDiGraph, filepath: Path) -> None:
        Path(filepath).write_text("partial", encoding="utf-8")
        raise OSError("disk full")

    monkeypatch.setattr(ox.settings, "cache_folder", "unset")
    monkeypatch.setattr(ox.settings, "use_cache", False)
    monkeypatch.setattr(ox, "graph_from_polygon", lambda *_a, **_k: build_synthetic_graph())
    monkeypatch.setattr(ox, "save_graphml", failing_save)
    target = tmp_path / "g.graphml"

    with pytest.raises(OSError, match="disk full"):
        build_graph_for_area(11.72, 76.64, 10_000, target)

    assert not target.exists()
    assert list(tmp_path.glob("*")) == []


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_osm_graph_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_check_mode_prints_counts_without_network() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--out", str(STUB)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "nodes=3" in result.stdout
    assert "edges=4" in result.stdout
    assert "OpenStreetMap contributors" in result.stdout


def test_script_check_mode_missing_graph_exits_nonzero(tmp_path: Path) -> None:
    script = _load_script()

    assert script.main(["--check", "--out", str(tmp_path / "none.graphml")]) == 1


def test_script_dry_run_never_builds(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _load_script()
    monkeypatch.setattr(
        script, "build_graph_for_area", lambda *_a, **_k: pytest.fail("build must not run")
    )

    code = script.main(["--dry-run", "--out", str(tmp_path / "g.graphml")])

    out = capsys.readouterr().out
    assert code == 0
    assert "buffer_m=10000" in out
    assert "11.72" in out and "76.64" in out


def test_script_build_uses_pilot_defaults_and_reports_counts(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _load_script()
    calls: list[tuple[object, ...]] = []

    def fake_build(lat: float, lon: float, buffer_m: float, path: Path, **kwargs: object):
        calls.append((lat, lon, buffer_m, path, kwargs))
        return build_synthetic_graph()

    monkeypatch.setattr(script, "build_graph_for_area", fake_build)
    out_path = tmp_path / "g.graphml"

    code = script.main(["--out", str(out_path)])

    assert code == 0
    assert calls[0][:3] == (11.72, 76.64, 10000)
    assert calls[0][3] == out_path
    assert "nodes=" in capsys.readouterr().out


def test_script_network_error_exits_two_with_clear_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = _load_script()

    def failing_build(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("Overpass unreachable")

    monkeypatch.setattr(script, "build_graph_for_area", failing_build)

    code = script.main(["--out", str(tmp_path / "g.graphml")])

    assert code == 2
    assert "Overpass unreachable" in capsys.readouterr().err
    assert not (tmp_path / "g.graphml").exists()
